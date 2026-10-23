#!/usr/bin/env python3
"""Inactive known hidden passive children still cast in pinned TC loading."""
import copy
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'lib'))
from spells import reconstruct,Unsupported
spec=importlib.util.spec_from_file_location('inactive_fixture',ROOT/'tests/spell-state-tests.py')
fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)


class InactivePassiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):fixture.SpellTests.setUpClass()
    @classmethod
    def tearDownClass(cls):fixture.SpellTests.tearDownClass()

    def convert(self,rule,rank,active,groups=2,same=False,flags=(0,0),tc=None,ac=None):
        owner=rule['owners'][rank]
        talents={owner:3 if same else 1<<active}
        if not same and groups==2 and rank!=len(rule['owners'])-1:
            talents[rule['owners'][-1]]=1<<(1-active)
        stored={owner:(1,0),**{s:flags for s in rule['children'][rank]}}
        skills={134:(400,400)} if rule['class']==11 else {770:(400,400)}
        original=copy.deepcopy((stored,talents,skills))
        out=reconstruct((1,rule['class'],active,groups),stored,talents,skills,
                        tc or fixture.SpellTests.tc,ac or fixture.SpellTests.ac,'tc-to-ac')
        self.assertEqual((stored,talents,skills),original)
        return out,stored,talents,skills

    def test_all_reviewed_families_ranks_and_both_active_specs_keep_exact_children(self):
        for rule in fixture.SpellTests.tc.native_passive_ranks.values():
            for rank in range(len(rule['owners'])):
                for active in (0,1):
                    with self.subTest(owner=rule['owners'][rank],active=active):
                        out,_,_,_=self.convert(rule,rank,active)
                        for child in rule['children'][rank]:
                            row=out[child]
                            self.assertEqual(row['mask'],1<<active)
                            self.assertEqual(row['disposition'],'RUNTIME')
                            self.assertEqual(row['original'],[0,0])
                            self.assertTrue(row['authorization']['native_passive_rank']['inactive_source_passive_cast'])
                            self.assertFalse(row['authorization']['native_passive_rank']['target_predecessors_persisted'])

    def test_same_owner_in_both_specs_merges_without_grants_or_ownership_changes(self):
        for rule in fixture.SpellTests.tc.native_passive_ranks.values():
            out,_,_,_=self.convert(rule,0,0,same=True)
            for child in rule['children'][0]:self.assertEqual(out[child]['mask'],3)

    def test_reverse_and_relogin_canonical_state_keeps_active_auras(self):
        for rule in fixture.SpellTests.tc.native_passive_ranks.values():
            for active in (0,1):
                out,_,talents,skills=self.convert(rule,0,active)
                persisted={s:(r['mask'],0)for s,r in out.items()if r['disposition']=='PERSISTENT'}
                reverse=reconstruct((1,rule['class'],active,2),persisted,talents,skills,
                    fixture.SpellTests.tc,fixture.SpellTests.ac,'ac-to-tc')
                again=reconstruct((1,rule['class'],active,2),{s:(r['active'],r['disabled'])for s,r in reverse.items()},
                    talents,skills,fixture.SpellTests.tc,fixture.SpellTests.ac,'tc-to-ac')
                for child in rule['children'][0]:
                    self.assertEqual((again[child]['mask'],again[child]['disposition']),
                                     (out[child]['mask'],out[child]['disposition']))

    def test_unselected_disabled_and_ordinary_inactivity_still_block(self):
        rule=fixture.SpellTests.tc.native_passive_ranks['2034']
        for flags in ((0,1),(1,1),(2,0)):
            with self.assertRaises(Unsupported):self.convert(rule,0,0,flags=flags)
        with self.assertRaises(Unsupported) as error:
            reconstruct((1,6,0,2),{50096:(0,0)}, {},{770:(400,400)},fixture.SpellTests.tc,fixture.SpellTests.ac,'tc-to-ac')
        self.assertEqual(error.exception.reason,'UNAUTHORIZED_TALENT_SPELL')
        for spell in (48782,643):
            with self.assertRaises(Unsupported) as error:fixture.SpellTests().convert({spell:(0,0)})
            self.assertEqual(error.exception.reason,'UNREPRESENTABLE_INACTIVE_SPELL')

    def test_matching_changed_visibility_effects_and_dependency_contracts_still_block(self):
        for field,value in ((4,0),(71,44),(116,6603)):
            tc,ac=copy.deepcopy(fixture.SpellTests.tc),copy.deepcopy(fixture.SpellTests.ac)
            for meta in (tc,ac):meta.spells[50096][field]=value
            with self.subTest(field=field),self.assertRaises(Unsupported):
                self.convert(tc.native_passive_ranks['2034'],0,0,tc=tc,ac=ac)
        for field in (86,95):
            tc=copy.deepcopy(fixture.SpellTests.tc)
            tc.spells[50096][field]^=1
            with self.subTest(field=field),self.assertRaises(Unsupported):
                self.convert(tc.native_passive_ranks['2034'],0,0,tc=tc)


if __name__=='__main__':unittest.main()
