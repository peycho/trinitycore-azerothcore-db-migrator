#!/usr/bin/env python3
"""Correct racial state, bounded stock rewards, and unchanged pending resets."""
import copy,importlib.util,json,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'lib'))
from cleanup_console import CleanupError
from cleanup_racial_skills import select,contract
from spells import Metadata,reconstruct,Unsupported

def module(name,file):
    spec=importlib.util.spec_from_file_location(name,ROOT/'tests'/file);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
assets=module('racial_skill_assets','racial-skill-fixtures.py')
fixture=module('racial_skill_base','spell-fixtures.py')
semantic=module('racial_skill_world','spell-state-tests.py')
class World(semantic.World):
    def table(self,world,table,columns):
        rows=super().table(world,table,columns)
        if world=='tc':
            if table=='spell_learn_spell':rows+=[['58984','21009','1']]
            if table=='spell_script_names':rows+=[['59752','spell_pvp_trinket_shared_cd']]
        return rows

class RacialSkillTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();p=Path(cls.tmp.name)
        profile=json.loads((ROOT/'compatibility/tc335-acwotlk-v2/spell-metadata.json').read_text());original=fixture.stores
        fixture.stores=lambda p:assets.extend(original(p),p);fixture.write_assets(p,profile)
        cls.tc=Metadata('tc',p/'tc-dbc','tc',profile,World());cls.ac=Metadata('ac',p/'ac-dbc','ac',profile,World())
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def setUp(self):
        self.tc,self.ac=copy.deepcopy(type(self).tc),copy.deepcopy(type(self).ac)
        self.state={'characters':[[1,1,1,14,0,1,0,20]],'character_spell':[[1,20597,1,0],[1,6603,1,0]],
                    'character_skills':[[1,171,75,75]],'character_talent':[]}
    def review(self):return select(self.state,self.tc,self.ac)
    def test_four_fixed_native_catalogs_and_explicit_stock_rewards(self):
        for m in(self.tc,self.ac):
            for sk in(101,125,126,754):self.assertTrue(contract(m,sk,assets.RULES),(m.core,sk))
        original=copy.deepcopy(self.state);rows,excluded,proof=self.review()
        self.assertEqual(rows,[(1,754,70,70)]);self.assertFalse(excluded);self.assertEqual(self.state,original)
        self.assertTrue(proof[0]['pending_native_reset_preserved']);self.assertFalse(proof[0]['reset_executed'])
        self.assertIn(59752,proof[0]['missing_native_reward_spells']);self.assertEqual(proof[0]['sql_spell_rows_inserted'],0)
    def test_source_blocker_resolves_without_foreign_grant_or_sql_spell_change(self):
        with self.assertRaises(Unsupported)as error:reconstruct((1,1,0,1),{20597:(1,0),6603:(1,0)},{},{},self.tc,self.ac,'tc-to-ac',level=14)
        self.assertEqual(error.exception.reason,'SPELL_WOULD_ADD_SKILL')
        out=reconstruct((1,1,0,1),{20597:(1,0),6603:(1,0)},{},{754:(70,70)},self.tc,self.ac,'tc-to-ac',level=14)
        self.assertIn(20597,out)
    def test_race_class_level_and_offline_guards(self):
        for field,value in((1,2),(2,10),(3,0),(3,81),(4,1),(5,0),(6,1)):
            old=self.state['characters'][0][field];self.state['characters'][0][field]=value
            self.assertFalse(self.review()[0]);self.state['characters'][0][field]=old
        self.state['characters'][0][1:4]=[2,7,14];self.state['character_spell'][0][1]=20572
        self.assertFalse(self.review()[0])  # Warrior/rogue/hunter Blood Fury variant is not the shaman variant.
    def test_each_fixed_racial_native_max_and_existing_rows_untouched(self):
        for skill,spell,race in((101,2481,3),(125,20572,2),(126,20582,4),(754,20597,1)):
            self.state['characters'][0][1]=race;self.state['character_spell'][0][1]=spell
            self.assertEqual(self.review()[0],[(1,skill,70,70)])
            self.state['character_skills'].append([1,skill,1,1]);self.assertFalse(self.review()[0]);self.state['character_skills'].pop()
    def test_disabled_anchors_or_stored_inactive_rewards_defer(self):
        for flags in((0,0),(1,1),(0,1)):
            self.state['character_spell'][0][2:]=flags;self.assertFalse(self.review()[0])
        self.state['character_spell'][0][2:]=[1,0];self.state['character_spell'].append([1,59752,1,1]);self.assertFalse(self.review()[0])
    def test_unknown_reward_extra_dependency_matching_custom_metadata_and_skill_tier_defer(self):
        for kind in('reward','dependency','matching','tier','script'):
            self.tc,self.ac=copy.deepcopy(type(self).tc),copy.deepcopy(type(self).ac)
            for m in(self.tc,self.ac):
                if kind=='reward':r=m.abilities[20597][0].copy();r[2]=6603;m.stores['SkillLineAbility'][999999]=r
                elif kind=='dependency':m.learns[20597].append((6603,True,False))
                elif kind=='matching':m.spells[20597][71]=36
                elif kind=='tier':m.stores['SkillRaceClassInfo'][862][6]=99
                else:m.scripts[20597].add('custom')
            self.assertFalse(self.review()[0],kind)
    def test_slot_bound_and_no_mutations_to_other_skills_or_talent_groups(self):
        self.state['character_talent']=[[1,12282,0]];self.state['character_skills']=[[1,1000+i,1,1]for i in range(127)]
        original=copy.deepcopy(self.state);self.assertFalse(self.review()[0]);self.assertEqual(self.state,original)

if __name__=='__main__':unittest.main()
