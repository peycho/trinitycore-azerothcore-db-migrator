#!/usr/bin/env python3
"""Selected passive repairs require BOTH ownership and known lower-rank evidence."""
import copy
import importlib.util
import os
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'lib'))
from cleanup_console import CleanupError, parser
from cleanup_ownership import select, REKEY_POLICY
from spells import reconstruct, Unsupported

spec = importlib.util.spec_from_file_location('rekey_fixture',ROOT/'tests/spell-state-tests.py')
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


class RekeyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.SpellTests.setUpClass()
        cls.source = Path(os.environ.get('TRINITYCORE_DIR',ROOT.parent/'TrinityCore'))

    @classmethod
    def tearDownClass(cls):
        fixture.SpellTests.tearDownClass()

    def setUp(self):
        self.meta = copy.deepcopy(fixture.SpellTests.tc)
        self.meta.history_default_spells = set()
        self.rule = self.meta.native_passive_ranks['801']
        self.state = self.build(self.rule)

    def build(self,rule,active=0,inactive=False):
        lower,higher = rule['owners'][0],rule['owners'][-1]
        return {'characters':[[1,1,rule['class'],80,active,2,0,32]],
                'character_talent':[[1,lower,active]]+([[1,higher,1-active]] if inactive else []),
                'character_spell':[[1,lower,1,0]]+[[1,s,1,0] for s in rule['children'][-1]]+[[1,6603,1,0]],
                'character_skills':[[1,171,375,450]]}

    def review(self,**kw):
        return select(self.state,self.meta,preview=True,source_dir=self.source,native_passive_rekey=True,**kw)

    def test_all_four_contracts_both_specs_and_native_migration(self):
        for rule in self.meta.native_passive_ranks.values():
            for active in (0,1):
                for inactive in (False,True):
                    with self.subTest(rule=rule['owners'],active=active,inactive=inactive):
                        self.state=self.build(rule,active,inactive)
                        original=copy.deepcopy(self.state)
                        before={s:(a,d) for _,s,a,d in self.state['character_spell']}
                        talents={s:1<<k for _,s,k in self.state['character_talent']}
                        skills={134:(400,400)} if rule['class']==11 else {770:(400,400)}
                        self.assertEqual(select(self.state,self.meta,preview=True,source_dir=self.source)[0],[])
                        with self.assertRaises(Unsupported):
                            reconstruct((1,rule['class'],active,2),before,talents,skills,self.meta,fixture.SpellTests.ac,'tc-to-ac')
                        result=self.review()
                        self.assertEqual(result,self.review())
                        self.assertEqual(len(result[0]),len(rule['chains']))
                        self.assertEqual(result[1],[])
                        after=before.copy()
                        for _,old,new in result[3]['rekeys']:
                            self.assertIn(new,self.meta.predecessors(old))
                            self.assertNotIn(new,before)
                            after[new]=after.pop(old)
                        output=reconstruct((1,rule['class'],active,2),after,talents,skills,self.meta,fixture.SpellTests.ac,'tc-to-ac')
                        for child in rule['children'][0]:
                            self.assertEqual(output[child]['mask'],1<<active)
                        self.assertEqual(self.state,original)
                        self.assertEqual(set(after)&set(rule['children'][-1]),set())
                        self.assertEqual(len(before),len(after))

    def test_no_missing_anchor_or_higher_grant(self):
        self.state['character_talent']=[[1,37117,0]]
        self.state['character_spell']=[[1,37117,1,0],[1,16952,1,0],[1,16958,1,0]]
        self.assertEqual(self.review()[0],[])
        self.state=self.build(self.rule)
        self.state['character_spell']=[r for r in self.state['character_spell'] if r[1]!=16961]
        self.assertEqual(self.review()[0],[])
        self.assertTrue(any(r[2]=='DEFER_NATIVE_REKEY_ANCHOR_COUNT' for r in self.review()[1]))

    def test_same_selection_in_both_specs_merges_and_correct_sibling_anchor_stays(self):
        self.state['character_talent'].append([1,37116,1])
        # The second chain already has its correct active child; it stays intact.
        self.state['character_spell']=[r for r in self.state['character_spell'] if r[1]!=16961]
        self.state['character_spell'].append([1,16958,1,0])
        result=self.review()
        self.assertEqual(result[3]['rekeys'],[(1,16954,16952)])
        masks=dict(result[3]['native_owner_proofs'][0]['native_authorization_masks'])
        self.assertEqual(masks[16952],3)
        self.assertEqual(masks[16958],3)

    def test_middle_selected_passive_ranks_are_known_without_promoting_talents(self):
        rule=self.meta.native_passive_ranks['2034']
        for index in (1,2,3):
            self.state=self.build(rule)
            self.state['character_talent'][0][1]=rule['owners'][index]
            self.state['character_spell'][0][1]=rule['owners'][index]
            result=self.review()
            self.assertEqual({new for _,_,new in result[3]['rekeys']},set(rule['children'][index]))
            for _,old,new in result[3]['rekeys']:
                self.assertIn(new,self.meta.predecessors(old))

    def test_target_collision_multiple_anchors_and_disabled_or_inactive_anchor_defer(self):
        for flags in ((1,1),(0,0),(0,1)):
            self.state=self.build(self.rule)
            self.state['character_spell'][1][2:]=flags
            self.assertEqual(self.review()[0],[])
        for row in ([1,16952,1,0],[1,16952,1,1]):
            self.state=self.build(self.rule)
            self.state['character_spell'].append(row)
            self.assertEqual(self.review()[0],[])

    def test_missing_selected_parent_unselected_family_and_direct_talent_rank_defer(self):
        self.state['character_spell']=[r for r in self.state['character_spell'] if r[1]!=37116]
        self.assertEqual(self.review()[0],[])
        self.state=self.build(self.rule)
        self.state['character_talent']=[]
        self.assertEqual(self.review()[0],[])
        self.state=self.build(self.rule)
        self.state['character_spell'].append([1,37117,1,0])
        self.assertEqual(self.review()[0],[])
        self.state={'characters':[[1,1,1,80,0,2,0,0]],'character_talent':[[1,12676,0]],
                    'character_spell':[[1,12677,1,0]],'character_skills':[]}
        self.assertEqual(self.review()[0],[])

    def test_reset_online_foreign_invalid_builds_and_script_drift_defer(self):
        for index,value in ((7,4),(6,1),(2,1),(4,2)):
            self.state=self.build(self.rule)
            self.state['characters'][0][index]=value
            self.assertEqual(self.review()[0],[])
        self.state=self.build(self.rule)
        self.state['character_talent'].append([1,37117,0])
        self.assertEqual(self.review()[0],[])
        self.state=self.build(self.rule)
        self.meta.scripts[16954].add('unreviewed')
        self.assertEqual(self.review()[0],[])

    def test_default_skill_independent_routes_and_contract_drift_block(self):
        for mutate in (
            lambda m:m.history_default_spells.add(16954),
            lambda m:m.requires[16954].add(6603),
            lambda m:m.learns[6603].append((16954,1,False)),
            lambda m:m.spells[16954].__setitem__(71,44),
            lambda m:m.spells[16954].__setitem__(116,6603)):
            self.meta=copy.deepcopy(fixture.SpellTests.tc)
            self.meta.history_default_spells=set()
            mutate(self.meta)
            self.assertEqual(self.review()[0],[])

    def test_selection_count_bound_and_mutually_exclusive_cli(self):
        with self.assertRaises(CleanupError):
            select(self.state,self.meta,2,native_passive_rekey=True,native_passive_prefixes=True)
        with self.assertRaises(CleanupError):
            select(self.state,self.meta,3,native_passive_rekey=True,source_dir=self.source)
        with mock.patch('cleanup_ownership.MAX_ROWS',1):
            with self.assertRaises(CleanupError):self.review()
        args=parser().parse_args(['plan','talent-ownership','--migration-inspection','latest','--native-passive-rekey','--expect-rows','2'])
        self.assertTrue(args.native_passive_rekey)
        self.assertIn('v5',REKEY_POLICY)
        with self.assertRaises(SystemExit):
            parser().parse_args(['plan','talent-ownership','--migration-inspection','latest','--native-passive-rekey','--reviewed-aura-aliases','--preview'])


if __name__=='__main__':unittest.main()
