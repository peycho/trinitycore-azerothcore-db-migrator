#!/usr/bin/env python3
"""Coupled retirement requires unselected ownership, native skill and empty slot."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'lib'))
from cleanup_console import CleanupError, parser
from cleanup_shaman_dual_wield import contract, select
from spells import Metadata, reconstruct, Unsupported
spec=importlib.util.spec_from_file_location('shaman_assets',ROOT/'tests/shaman-dual-wield-fixtures.py')
assets=importlib.util.module_from_spec(spec);spec.loader.exec_module(assets)


class ShamanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.path=Path(cls.temp.name)
        cls.profile=json.loads((ROOT/'compatibility/tc335-acwotlk-v2/spell-metadata.json').read_text())
        assets.base.write_assets(cls.path,cls.profile)
        fixture_spec=importlib.util.spec_from_file_location('shaman_spell_tests',ROOT/'tests/spell-state-tests.py')
        fixture=importlib.util.module_from_spec(fixture_spec);fixture_spec.loader.exec_module(fixture)
        cls.tc=Metadata('tc',cls.path/'tc-dbc','tc_world',cls.profile,fixture.World())
        cls.ac=Metadata('ac',cls.path/'ac-dbc','ac_world',cls.profile,fixture.World())
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()
    def setUp(self):
        self.tc=copy.deepcopy(type(self).tc);self.ac=copy.deepcopy(type(self).ac)
        self.state={'characters':[[1,11,7,55,0,2,0,32]],'character_talent':[],
                    'character_spell':[[1,674,1,0],[1,6603,1,0]],'character_skills':[[1,118,1,275],[1,171,375,450]]}
    def review(self,**kw):return select(self.state,self.tc,self.ac,preview=True,offhand=set(),default_skills={},**kw)
    def test_pair_and_preserved_state(self):
        original=copy.deepcopy(self.state)
        self.assertTrue(contract(self.tc));self.assertTrue(contract(self.ac))
        rows,excluded,_,summary,_=self.review()
        self.assertEqual(rows,[(1,674,1,0)]);self.assertFalse(excluded)
        self.assertEqual(summary['skill_rows_removed'],1);self.assertEqual(self.state,original)
        with self.assertRaises(Unsupported):
            reconstruct((11,7,0,2),{674:(1,0),6603:(1,0)},{},{118:(1,275)},self.tc,self.ac,'tc-to-ac',level=55)
        forward=reconstruct((11,7,0,2),{6603:(1,0)},{},{},self.tc,self.ac,'tc-to-ac',level=55)
        self.assertNotIn(674,forward)
        reverse=reconstruct((11,7,0,2),{6603:(3,)},{},{},self.ac,self.tc,'ac-to-tc',level=55)
        self.assertNotIn(674,reverse)
        self.ac.trainer_taught.add(674);self.assertEqual(self.review()[0],rows)
    def test_occupied_slot_and_expectation(self):
        self.assertEqual(select(self.state,self.tc,self.ac,preview=True,offhand={1},default_skills={})[1],[(1,674,'DEFER_OCCUPIED_OFFHAND')])
        with self.assertRaises(CleanupError):select(self.state,self.tc,self.ac,3,offhand=set(),default_skills={})
    def test_selected_in_either_spec_and_stored_parent(self):
        for group in (0,1):
            self.state['character_talent']=[[1,30798,group]]
            self.assertFalse(self.review()[0])
        self.state['character_talent']=[];self.state['character_spell'].append([1,30798,1,1])
        self.assertFalse(self.review()[0])
    def test_character_skill_flags_and_wrong_class(self):
        for field,value in ((1,1),(2,1),(3,0),(4,2),(5,3),(6,1),(7,4)):
            old=self.state['characters'][0][field];self.state['characters'][0][field]=value
            self.assertFalse(self.review()[0]);self.state['characters'][0][field]=old
        for flags in ((0,0),(1,1),(0,1)):
            self.state['character_spell'][0][2:]=flags;self.assertFalse(self.review()[0])
        self.state['character_spell'][0][2:]=[1,0]
        self.state['character_skills'][0][2]=2;self.assertFalse(self.review()[0])
    def test_script_route_masks_and_default_skill_drift(self):
        self.tc.scripts[674].add('unreviewed');self.assertFalse(self.review()[0]);self.tc.scripts[674].clear()
        self.ac.abilities[674][0][4]=45;self.assertFalse(self.review()[0]);self.ac.abilities[674][0][4]=109
        defaults={'tc':{'layout':{'columns':[['playercreateinfo_skills',f]for f in ('raceMask','classMask','skill','rank')]},'rows':{'playercreateinfo_skills':[[0,64,118,0]]}}}
        self.assertFalse(select(self.state,self.tc,self.ac,preview=True,offhand=set(),default_skills=defaults)[0])
    def test_alternate_anchor_and_talent_identity_defer(self):
        self.tc.spells[6603][71]=40
        self.assertFalse(self.review()[0])
        self.tc.spells[6603][71]=3
        self.state['character_talent']=[[1,30798,2]]
        self.assertFalse(self.review()[0])

    def test_cli_exclusive_and_optional(self):
        args=parser().parse_args(['plan','talent-ownership','--migration-inspection','latest','--unselected-shaman-dual-wield','--preview'])
        self.assertTrue(args.unselected_shaman_dual_wield)


if __name__=='__main__':unittest.main()
