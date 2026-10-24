#!/usr/bin/env python3
"""A forbidden legacy pair must never authorize a riding grant or item loss."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/'lib'))
from cleanup_console import CleanupError, parser
from cleanup_obsolete_riding import contract, select, native_invalid_item
from spells import Metadata, reconstruct, Unsupported

def module(name,path):
    spec = importlib.util.spec_from_file_location(name,path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

assets = module('riding_assets',ROOT/'tests/obsolete-riding-fixtures.py')
semantic = module('riding_semantics',ROOT/'tests/spell-state-tests.py')


class RidingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(); p = Path(cls.temp.name)
        profile = json.loads((ROOT/'compatibility/tc335-acwotlk-v2/spell-metadata.json').read_text())
        assets.base.write_assets(p,profile)
        cls.tc = Metadata('tc',p/'tc-dbc','tc',profile,assets.world(semantic.World))
        cls.ac = Metadata('ac',p/'ac-dbc','ac',profile,assets.world(semantic.World))
    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()
    def setUp(self):
        self.tc = copy.deepcopy(type(self).tc); self.ac = copy.deepcopy(type(self).ac)
        self.state = {'characters':[[1,10,5,80,1,2,0,32]],'character_talent':[],
            'character_spell':[[1,825,1,0],[1,34091,1,0],[1,6603,1,0]],
            'character_skills':[[1,149,1,75],[1,762,300,300],[1,171,375,450]]}
        self.items = [[1,10,10,1,1234,1234,762,300,0,1234,762,300,0]]
    def review(self,**kwargs):
        return select(self.state,self.tc,self.ac,preview=True,items=self.items,default_skills={},**kwargs)
    def test_fixed_contracts_and_no_source_mutation(self):
        before = copy.deepcopy(self.state)
        self.assertTrue(contract(self.tc)); self.assertTrue(contract(self.ac))
        selected,excluded,_,summary,_ = self.review()
        self.assertEqual(selected,[(1,825,1,0)]); self.assertFalse(excluded)
        self.assertEqual(summary['skill_rows_removed'],1); self.assertEqual(self.state,before)
    def test_expert_riding_and_mismatched_higher_rank(self):
        self.state['character_spell'][1][1] = 34090
        self.state['character_skills'][1][2:] = [225,225]
        self.assertTrue(self.review()[0])
        self.state['character_spell'][1][1] = 34091
        self.assertFalse(self.review()[0])
    def test_pending_online_level_and_pair_flags(self):
        for field,value in ((7,4),(6,1),(3,200),(4,2)):
            with self.subTest(field=field):
                original = self.state['characters'][0][field]
                self.state['characters'][0][field] = value
                self.assertFalse(self.review()[0]); self.state['characters'][0][field] = original
        self.state['character_spell'][0][2] = 0; self.assertFalse(self.review()[0])
    def test_eligible_race_or_missing_old_skill_defer(self):
        self.state['characters'][0][1] = 2
        self.assertEqual(self.review()[1][0][2],'DEFER_LEGACY_RIDING_ELIGIBLE')
        self.state['characters'][0][1] = 10
        self.state['character_skills'].pop(0); self.assertFalse(self.review()[0])
    def test_every_owned_inventory_mail_item_requirement(self):
        for index,value in ((6,149),(8,825),(10,149),(12,825),(5,None),(9,None),(2,None)):
            with self.subTest(index=index):
                original = self.items[0][index]; self.items[0][index] = value
                self.assertFalse(self.review()[0]); self.items[0][index] = original
    def test_duplicate_or_malformed_item_evidence_rejects(self):
        self.items.append(self.items[0][:])
        with self.assertRaises(CleanupError): self.review()
    def test_known_legacy_teacher_and_alternate_metadata(self):
        self.state['character_spell'].append([1,6746,1,0]); self.assertFalse(self.review()[0])
        self.state['character_spell'].pop()
        self.ac.learns[6746] = [(825,0,False)]; self.assertFalse(self.review()[0])
    def test_custom_default_route_defer(self):
        defaults = {'tc':{'layout':{'columns':[['playercreateinfo_skills',f] for f in ('raceMask','classMask','skill','rank')]},
            'rows':{'playercreateinfo_skills':[[0,0,149,0]]}}}
        self.assertFalse(select(self.state,self.tc,self.ac,preview=True,items=self.items,default_skills=defaults)[0])
    def test_skill_caps_disabled_anchor_talents_scripts(self):
        self.state['character_skills'][1][2] = 299; self.assertFalse(self.review()[0])
        self.state['character_skills'][1][2] = 300
        self.state['character_spell'][1][3] = 1; self.assertFalse(self.review()[0])
        self.state['character_spell'][1][3] = 0
        self.state['character_talent'].append([1,999999,0]); self.assertFalse(self.review()[0])
        self.state['character_talent'].clear()
        self.tc.scripts[825].add('unreviewed'); self.assertFalse(self.review()[0])
    def test_known_higher_rank_and_changed_skill_tier_defer(self):
        self.state['character_skills'][1][2:] = [225,225]
        self.state['character_spell'][1] = [1,34090,1,0]
        self.state['character_spell'].append([1,34091,0,0]); self.assertFalse(self.review()[0])
        self.state['character_spell'].pop(); self.assertTrue(self.review()[0])
        self.ac.stores['SkillTiers'][223][1] += 1; self.assertFalse(self.review()[0])
    def test_duplicate_skill_and_out_of_scope_state_rejected(self):
        self.state['character_skills'].append(self.state['character_skills'][0][:])
        with self.assertRaises(CleanupError): self.review()
        self.state['character_skills'].pop()
        self.state['character_spell'].append([99,6603,1,0])
        with self.assertRaises(CleanupError): self.review()
    def test_only_exact_nonempty_expected_pairs_generate_package(self):
        for expected in (None,0,2):
            with self.assertRaises(CleanupError):
                select(self.state,self.tc,self.ac,expected,items=self.items,default_skills={})
        self.assertEqual(select(self.state,self.tc,self.ac,1,items=self.items,default_skills={})[0],[(1,825,1,0)])
    def test_parser_uses_pair_count(self):
        args = parser().parse_args(['plan','obsolete-riding','--migration-inspection','latest','--expect-rows','6'])
        self.assertTrue(args.obsolete_riding); self.assertEqual(args.expect_review_rows,6)
    def test_native_invalid_items_are_explicit_and_retained(self):
        self.items += [[1,11,*([None]*11)], [1,12,12,1,0,*([None]*8)]]
        before = copy.deepcopy((self.state,self.items))
        self.assertFalse(self.review()[0])
        result = self.review(native_invalid_items=True,zero_template_counts={'tc':0,'ac':0})
        self.assertEqual(result[0],[(1,825,1,0)])
        self.assertEqual(result[3]['native_invalid_item_rows_retained'],2)
        self.assertEqual(result[3]['native_invalid_item_reasons'],
            {'MISSING_INSTANCE_REFERENCE':1,'ZERO_ENTRY_INSTANCE_WITHOUT_TEMPLATE':1})
        self.assertEqual((self.state,self.items),before)
    def test_unknown_nonzero_template_still_defers_under_v2(self):
        for index in (5,9):
            original = self.items[0][index]; self.items[0][index] = None
            self.assertFalse(self.review(native_invalid_items=True,zero_template_counts={'tc':0,'ac':0})[0])
            self.items[0][index] = original
    def test_zero_template_absence_must_be_explicit_both_worlds(self):
        for counts in (None,{}, {'tc':0}, {'tc':1,'ac':0}, {'tc':0,'ac':1}):
            with self.subTest(counts=counts), self.assertRaises(CleanupError):
                self.review(native_invalid_items=True,zero_template_counts=counts)
    def test_partial_zero_and_zero_guid_are_not_native_invalid_evidence(self):
        rows = [[1,0,*([None]*11)], [1,12,12,None,0,*([None]*8)],
                [1,12,12,1,7,*([None]*8)], [1,12,13,1,0,*([None]*8)],
                [1,12,12,1,0,0,0,0,0,None,None,None,None]]
        for row in rows:
            self.assertIsNone(native_invalid_item(row))
            self.items = [row]
            self.assertFalse(self.review(native_invalid_items=True,zero_template_counts={'tc':0,'ac':0})[0])
    def test_v2_preserves_real_legacy_item_requirement_exclusion(self):
        self.items += [[1,11,*([None]*11)]]
        self.items[0][8] = 825
        self.assertEqual(self.review(native_invalid_items=True,zero_template_counts={'tc':0,'ac':0})[1][0][2],
                         'DEFER_ITEM_REQUIRES_LEGACY_RIDING')


if __name__ == '__main__': unittest.main()
