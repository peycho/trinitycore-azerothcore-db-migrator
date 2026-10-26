#!/usr/bin/env python3
"""Narrow selection and source-path boundaries for disabled talent history."""
from collections import defaultdict
import copy
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'lib'))
from cleanup_console import CleanupError
import cleanup_disabled_history as history


class DisabledHistoryTests(unittest.TestCase):
    def setUp(self):
        self.rows=[[1,12296,1,1,1,1,0,2,0,'REVIEW_DISABLED_NO_SELECTED_FAMILY',137,1,'[]'],
                   [2,12300,0,1,1,1,1,2,0,'REVIEW_DISABLED_NO_SELECTED_FAMILY',2,1,'[]'],
                   [3,12282,1,1,1,1,0,2,0,'REVIEW_DISABLED_OTHER_SELECTED_RANK',1,1,'[[12664,1,3]]'],
                   [4,12296,1,0,1,1,0,1,0,'REVIEW_ENABLED_NO_SELECTED_FAMILY',137,1,'[]'],
                   [5,12296,1,1,1,1,0,1,4,'DEFER_PENDING_NATIVE_RESET',137,1,'[]']]
        self.state={'spells':[[r[0],r[1],r[2],r[3]] for r in self.rows],'talents':[[3,12664,1]]}
        self.meta=SimpleNamespace(talents={12296:(137,1),12300:(2,1),12301:(2,2)},
            invalid_talents=set(),learns=defaultdict(list),effect_learns=defaultdict(list),
            abilities=defaultdict(list),scripts=defaultdict(set),chain=lambda spell:(spell,),check_script=lambda spell,name:None)
        self.meta.script_policy={}

    def call(self, expected=2):
        return history.select(self.rows,self.state,self.meta,expected)

    def test_only_disabled_unselected_families_selected_without_mutation(self):
        original=copy.deepcopy((self.rows,self.state))
        self.assertEqual(self.call(),([(1,12296,1,1),(2,12300,0,1)],[]))
        self.assertEqual((self.rows,self.state),original)

    def test_enabled_same_family_rank_excluded_even_without_selected_ownership(self):
        self.state['spells'].append([2,12301,1,0])
        selected,excluded=self.call()
        self.assertEqual(selected,[(1,12296,1,1)])
        self.assertEqual(excluded,[(2,12300,'DEFER_ENABLED_FAMILY_SPELL')])

    def test_incoming_learn_and_skill_routes_excluded(self):
        self.meta.effect_learns[900001]=[(12300,1,True)]
        self.assertEqual(self.call()[1],[(2,12300,'DEFER_INDEPENDENT_LEARN_ROUTE')])
        self.meta.effect_learns.clear()
        ability=[0]*14;ability[9]=2
        self.meta.abilities[12300]=[ability]
        self.assertEqual(self.call()[1],[(2,12300,'DEFER_SKILL_REWARD_ROUTE')])

    def test_effective_rank_identity_and_mixed_chain_excluded(self):
        self.meta.invalid_talents.add(12300)
        self.assertEqual(self.call()[1],[(2,12300,'DEFER_EFFECTIVE_TALENT_IDENTITY')])
        self.meta.invalid_talents.clear()
        self.meta.chain=lambda spell:(12300,900001) if spell==12300 else (spell,)
        self.assertEqual(self.call()[1],[(2,12300,'DEFER_MIXED_RANK_CHAIN')])

    def test_family_sibling_routes_dependencies_scripts_and_skills_excluded(self):
        self.meta.history_default_spells={12301}
        self.assertEqual(self.call()[1],[(2,12300,'DEFER_CUSTOM_DEFAULT_ROUTE')])
        self.meta.history_default_spells.clear()
        self.meta.requires={900001:{12301}}
        self.assertEqual(self.call()[1],[(2,12300,'DEFER_TALENT_DEPENDENCIES')])
        self.meta.requires.clear()
        self.meta.learns[12301]=[(900001,1,True)]
        self.assertEqual(self.call()[1],[(2,12300,'DEFER_TALENT_DEPENDENCIES')])
        self.meta.learns.clear()
        self.meta.scripts[12301].add('combat_script')
        self.assertEqual(self.call()[1],[(2,12300,'DEFER_SCRIPTED_TALENT_FAMILY')])
        self.meta.scripts.clear()
        self.meta.spells={spell:[0]*234 for spell in self.meta.talents}
        self.meta.spells[12301][71]=118
        self.assertEqual(self.call()[1],[(2,12300,'DEFER_TALENT_SKILL_EFFECT')])

    def test_expected_count_and_empty_selection_refused(self):
        for count in (0,1,500001):
            with self.assertRaises(CleanupError) as caught:self.call(count)
            self.assertEqual(caught.exception.code,'HISTORY_SELECTION_MISMATCH')
        self.meta.invalid_talents={12296,12300}
        with self.assertRaises(CleanupError) as caught:self.call()
        self.assertEqual(caught.exception.code,'HISTORY_NO_ELIGIBLE_ROWS')

    def test_retained_talent_parent_scripts_are_checked(self):
        from spells import Unsupported
        self.meta.scripts[12664].add('unreviewed_learning')
        def reject(spell,name):raise Unsupported('UNSUPPORTED_LEARNING_SCRIPT',name)
        self.meta.check_script=reject
        with self.assertRaises(CleanupError) as caught:self.call()
        self.assertEqual(caught.exception.code,'UNSUPPORTED_LEARNING_SCRIPT')

    def test_reviewed_scripts_require_explicit_v2_and_every_family_binding(self):
        self.meta.scripts[12301].add('combat_script')
        self.meta.script_policy['combat_script']='NO_SPELLBOOK_MUTATION'
        self.assertEqual(self.call()[1],[(2,12300,'DEFER_SCRIPTED_TALENT_FAMILY')])
        selected,excluded=history.select(self.rows,self.state,self.meta,2,True)
        self.assertEqual(selected,[(1,12296,1,1),(2,12300,0,1)])
        self.assertEqual(excluded,[])
        self.assertEqual(history.script_bindings(self.meta),[(2,12301,'combat_script','')])
        self.meta.scripts[12300].add('unknown_script')
        self.assertEqual(history.select(self.rows,self.state,self.meta,2,True)[1],
                         [(2,12300,'DEFER_SCRIPTED_TALENT_FAMILY')])

    def test_runtime_aura_contract_does_not_authorize_history_cleanup(self):
        self.meta.scripts[12301].add('runtime_aura_script')
        # The reconstruction checker accepts special aura rules, but the
        # cleanup must still reject them without NO_SPELLBOOK_MUTATION.
        self.assertEqual(history.select(self.rows,self.state,self.meta,2,True)[1],
                         [(2,12300,'DEFER_SCRIPTED_TALENT_FAMILY')])
        self.assertEqual(history.script_bindings(self.meta)[0][-1],'UNREVIEWED_HISTORY_SCRIPT')

    def test_failed_review_contract_is_deferred_and_reported(self):
        from spells import Unsupported
        self.meta.scripts[12301].add('combat_script')
        self.meta.script_policy['combat_script']='NO_SPELLBOOK_MUTATION'
        def reject(spell,name):raise Unsupported('UNSUPPORTED_LEARNING_SCRIPT','changed binding')
        self.meta.check_script=reject
        self.assertEqual(history.select(self.rows,self.state,self.meta,2,True)[1],
                         [(2,12300,'DEFER_SCRIPTED_TALENT_FAMILY')])
        self.assertEqual(history.script_bindings(self.meta)[0][-1],'UNSUPPORTED_LEARNING_SCRIPT')

    def test_reviewed_script_does_not_bypass_other_family_exclusions(self):
        self.meta.scripts[12301].add('combat_script')
        self.meta.script_policy['combat_script']='NO_SPELLBOOK_MUTATION'
        cases=[('DEFER_INDEPENDENT_LEARN_ROUTE',lambda:self.meta.learns[900001].append((12301,1,True))),
               ('DEFER_TALENT_DEPENDENCIES',lambda:self.meta.learns[12301].append((900001,1,True))),
               ('DEFER_ENABLED_FAMILY_SPELL',lambda:self.state['spells'].append([2,12301,1,0]))]
        for reason,mutate in cases:
            with self.subTest(reason=reason):
                saved=copy.deepcopy((self.meta,self.state));mutate()
                self.assertEqual(history.select(self.rows,self.state,self.meta,2,True)[1],[(2,12300,reason)])
                self.meta,self.state=saved
        self.meta.spells={spell:[0]*234 for spell in self.meta.talents}
        self.meta.spells[12301][71]=118
        self.assertEqual(history.select(self.rows,self.state,self.meta,2,True)[1],[(2,12300,'DEFER_TALENT_SKILL_EFFECT')])

    def test_protected_operator_script_examples_have_nonmutating_contracts(self):
        import json
        profile=json.loads((history.PROFILE/'spell-metadata.json').read_text())
        for name in ('spell_dk_mark_of_blood','spell_dk_dancing_rune_weapon',
                     'spell_dk_hysteria','spell_dk_improved_blood_presence','spell_pal_eye_for_an_eye'):
            with self.subTest(script=name):
                self.assertEqual(profile['scripts']['tc'].get(name),'NO_SPELLBOOK_MUTATION')

    def test_native_core_disabled_path_stops_before_learning_and_skill_effects(self):
        core=Path(os.environ.get('TRINITYCORE_DIR',ROOT.parent/'TrinityCore'))
        source=(core/'src/server/game/Entities/Player/Player.cpp').read_text()
        start=source.index('bool Player::AddSpell(')
        end=source.index('bool Player::HandlePassiveSpellLearn(',start)
        body=source[start:end]
        stop=body.index('if (newspell.disabled)\n            return false;')
        self.assertLess(body.index('GetTalentSpellPos(spellId)'),stop)
        self.assertIn('RemoveSpell(rankSpellId, false, false)',body[:stop])
        for expression in ('CastSpell(this, spellId, true)','SetUsedTalentCount(',
                           'SetFreePrimaryProfessions(','SetSkill('):
            self.assertGreater(body.index(expression,body.index('if (!disabled_case)')),stop)
        # Existing runtime entries have an earlier active-state branch which
        # can cast: incoming/skill/script routes cannot be ignored by policy.
        self.assertLess(body.index('CastSpell(this, spellId, true)'),stop)
        known=source[source.index('bool Player::HasSpell('):source.index('bool Player::HasTalent(')]
        self.assertIn('!itr->second.disabled',known)


    def test_retirement_projection_accepts_only_distinct_exact_native_keys(self):
        join=history.retirement_join([(1,12296,1,1),(2,12296,0,1)])
        self.assertIn('retired.guid=s.guid AND retired.spell=s.spell',join)
        self.assertIn('SELECT DISTINCT',join)
        self.assertNotIn(' OR ',join)
        for rows in ([],[(1,12296,1,1),(1,12296,0,1)],[(0,12296)],[(1,0)],[(1,True)],[(1,4294967296)],[(1,"12296;DELETE")]):
            with self.subTest(rows=rows),self.assertRaises(CleanupError):history.retirement_join(rows)


if __name__=='__main__':unittest.main()
