#!/usr/bin/env python3
"""Eligibility retirement must not become a general enabled-spell deletion policy."""
import copy
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'lib'))
from cleanup_console import CleanupError, parser
from cleanup_eligibility import select, configuration_contract
from cleanup_ordinary_history import select as old_select
from spells import Unsupported, reconstruct
from cleanup_active_reset import exact_hex, row_hash

spec = importlib.util.spec_from_file_location('semantic', ROOT/'tests/spell-state-tests.py')
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


class EligibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.SpellTests.setUpClass()

    @classmethod
    def tearDownClass(cls):
        fixture.SpellTests.tearDownClass()

    def setUp(self):
        self.tc, self.ac = copy.deepcopy(fixture.SpellTests.tc), copy.deepcopy(fixture.SpellTests.ac)
        self.tc.history_default_spells = set()
        self.state = {'characters': [[1,1,1,80,0,2,0,32]],
                      'character_spell': [[1,465,0,0], [1,48942,1,0], [1,6603,1,0]],
                      'character_talent': [[1,12282,0], [1,12664,1]],
                      'character_skills': [[1,171,375,450]]}

    def review(self):
        return select(self.state, self.tc, self.ac, preview=True)

    def test_regression_foreign_enabled_chain_becomes_migratable_only_after_explicit_retirement(self):
        before = copy.deepcopy(self.state)
        with self.assertRaises(Unsupported) as error:
            reconstruct((1,1,0,2), {48942:(1,0),6603:(1,0)}, {}, {}, self.tc, self.ac, 'tc-to-ac')
        self.assertEqual(error.exception.reason, 'AC_WOULD_DELETE_SPELL')
        self.assertFalse(old_select(self.state, self.tc, None, preview=True)[0])
        rows, excluded, proof, summary, _ = self.review()
        self.assertEqual(rows, [(1,465,0,0), (1,48942,1,0)])
        self.assertFalse(excluded)
        self.assertEqual(summary['enabled_rows_removed'], 2)
        self.assertEqual(summary['skill_rows_changed'], 0)
        self.assertEqual(summary['spell_rows_inserted'], 0)
        self.assertIn((1,465,10290,'INELIGIBLE_ORDINARY_RANK','ABSENT_NO_GRANT','',''), proof)
        self.assertEqual(set(reconstruct((1,1,0,2), {6603:(1,0)}, {}, {}, self.tc, self.ac, 'tc-to-ac')), {6603})
        self.assertEqual(self.state, before)
        self.assertEqual(self.review(), (rows, excluded, proof, summary, self.review()[4]))
        self.assertEqual(select(self.state,self.tc,self.ac,2)[0], rows)
        with self.assertRaises(CleanupError) as error:
            select(self.state,self.tc,self.ac,1)
        self.assertEqual(error.exception.code, 'ELIGIBILITY_SELECTION_MISMATCH')

    def test_eligible_class_both_specs_and_source_target_disagreement_are_preserved(self):
        self.state['character_talent'] = []
        self.state['characters'][0][2] = 2
        for active in (0,1):
            self.state['characters'][0][4] = active
            self.assertFalse(self.review()[0])
        self.state['characters'][0][2] = 1
        for row in self.tc.stores['SkillRaceClassInfo'].values():
            if row[1] == 267:
                row[3] |= 1
        self.assertFalse(self.review()[0])
        self.assertEqual({r[2] for r in self.review()[1]}, {'DEFER_ELIGIBLE_OR_DISAGREEING_RANK'})

    def test_skill_rows_and_profession_riding_state_are_never_changed(self):
        self.state['character_skills'].append([1,267,1,400])
        self.assertFalse(self.review()[0])
        self.assertEqual({r[2] for r in self.review()[1]}, {'DEFER_EXISTING_ASSOCIATED_SKILL'})
        self.state['character_skills'].pop()
        self.tc.stores['SkillLine'][267][1] = 9
        self.assertFalse(self.review()[0])
        self.assertEqual({r[2] for r in self.review()[1]}, {'DEFER_PROFESSION_RIDING_OR_NONPLAYER_SKILL'})

    def test_weapon_proficiency_requires_absent_skill_and_known_native_restrictions(self):
        for m in (self.tc,self.ac):
            m.stores['SkillLine'][267][1]=6
            for spell in m.chain(465):
                m.spells[spell][71:74]=[25,60,0]
        self.assertEqual(len(self.review()[0]),2)
        self.state['character_skills'].append([1,267,1,400])
        self.assertFalse(self.review()[0])
        self.state['character_skills'].pop()
        for m in (self.tc,self.ac):
            m.stores['SkillRaceClassInfo']={k:r for k,r in m.stores['SkillRaceClassInfo'].items() if r[1]!=267}
        self.assertFalse(self.review()[0])
        self.assertEqual({r[2] for r in self.review()[1]}, {'DEFER_MISSING_NATIVE_SKILL_INFO'})

    def test_any_dependency_talent_or_script_defers_entire_family(self):
        for mutation in (
                lambda m: m.requires[465].add(6603),
                lambda m: m.requires[6603].add(465),
                lambda m: m.learns[465].append((6603,1,False)),
                lambda m: m.effect_learns[6603].append((465,1,True)),
                lambda m: m.talent_learn_owners[465].add(12282),
                lambda m: m.aura_owners.__setitem__(465,12282),
                lambda m: m.scripts[465].add('spell_already_reviewed'),
                lambda m: m.spells[465].__setitem__(71,118),
                lambda m: m.spells[465].__setitem__(95,30)):
            for core in ('tc', 'ac'):
                tc, ac = copy.deepcopy(self.tc), copy.deepcopy(self.ac)
                mutation(tc if core == 'tc' else ac)
                rows, excluded, *_ = select(self.state,tc,ac,preview=True)
                self.assertFalse(rows)
                self.assertEqual({r[1] for r in excluded}, {465,48942})

    def test_whole_family_and_metadata_agreement(self):
        # A changed target rank relation must not yield a partial family removal.
        self.ac.chains[465] = (465,10290)
        with self.assertRaises(CleanupError) as error:
            self.review()
        self.assertEqual(error.exception.code,'HISTORY_RELATION_METADATA')
        self.ac = copy.deepcopy(fixture.SpellTests.ac)
        self.ac.abilities[465][0][7] += 1
        self.assertFalse(self.review()[0])
        self.assertEqual({r[2] for r in self.review()[1]}, {'DEFER_INCOMPATIBLE_ELIGIBILITY_METADATA'})

    def test_pending_online_invalid_and_selected_ownership_states_defer(self):
        for index, value in ((7,4),(6,1),(3,81),(4,2),(5,0),(1,32)):
            state = copy.deepcopy(self.state)
            self.state['characters'][0][index] = value
            self.assertFalse(self.review()[0], (index,value))
            self.state = state
        for talents in ([[1,130,0]], [[1,12282,3]], [[1,12282,0],[1,12664,0]]):
            self.state['character_talent'] = talents
            self.assertFalse(self.review()[0])

    def test_configuration_is_separate_from_source_session_and_never_inferred(self):
        values = {('target','world'):'ac_world', ('source','player_start_all_spells'):'0',
                  ('target','player_start_custom_spells'):'0'}
        settings = SimpleNamespace(get=lambda a,b:values.get((a,b),''),
                                   schemas={'characters':'chars','auth':'auth','world':'tc_world'},
                                   paths={'ac_dbc':Path('/tmp/dbc'), 'ac_source':Path('/tmp/ac')})
        self.assertEqual(configuration_contract(settings)['target_world'], 'ac_world')
        for key in values:
            original = values[key]
            values[key] = ''
            with self.assertRaises(CleanupError):
                configuration_contract(settings)
            values[key] = original
        values['target','world'] = 'chars'
        with self.assertRaises(CleanupError) as error:
            configuration_contract(settings)
        self.assertEqual(error.exception.code,'ELIGIBILITY_TARGET_OVERLAP')
        for mode in ('--preview','--expect-rows'):
            argv=['plan','spell-eligibility','--migration-inspection','latest',mode]
            args=parser().parse_args(argv+(['2'] if mode=='--expect-rows' else []))
            self.assertTrue(args.spell_eligibility)

    def test_exact_numeric_hashing_keeps_decimal_precision_and_binary_bytes(self):
        self.assertEqual(exact_hex('c','float'), 'HEX(CAST(CAST(c AS DOUBLE) AS CHAR))')
        self.assertEqual(exact_hex('c','double unsigned'), 'HEX(CAST(CAST(c AS DOUBLE) AS CHAR))')
        self.assertEqual(exact_hex('c','decimal(65,30)'), 'HEX(CAST(c AS CHAR))')
        for kind in ('varbinary(20)','blob','varchar(50)','int unsigned','timestamp'):
            self.assertEqual(exact_hex('c',kind),'HEX(c)')
        meta={'columns':[['t','fraction','float'],['t','bytes','blob']]}
        legacy=row_hash(meta,'t')
        self.assertIn('HEX(s.`fraction`)',legacy)
        self.assertNotIn('CAST',legacy)  # Never reinterpret previously generated archives.
        exact=row_hash(meta,'t',exact_numeric=True)
        self.assertIn('CAST(CAST(s.`fraction` AS DOUBLE) AS CHAR)',exact)
        self.assertIn('HEX(s.`bytes`)',exact)


if __name__ == '__main__':
    unittest.main()
