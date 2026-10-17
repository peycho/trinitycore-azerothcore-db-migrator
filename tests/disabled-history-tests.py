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


if __name__=='__main__':unittest.main()
