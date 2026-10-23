#!/usr/bin/env python3
"""Redundant wrappers may retire only with known children and unchanged skills."""
import copy,importlib.util,json,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'lib'))
from cleanup_skill_teaching import select,contract,RULES
from cleanup_console import CleanupError,parser
from spells import Metadata,reconstruct,Unsupported
spec=importlib.util.spec_from_file_location('teaching_assets',ROOT/'tests/skill-teaching-fixtures.py');assets=importlib.util.module_from_spec(spec);spec.loader.exec_module(assets)
spec=importlib.util.spec_from_file_location('teaching_world',ROOT/'tests/spell-state-tests.py');semantic=importlib.util.module_from_spec(spec);spec.loader.exec_module(semantic)


class TeachingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();p=Path(cls.temp.name);profile=json.loads((ROOT/'compatibility/tc335-acwotlk-v2/spell-metadata.json').read_text())
        assets.base.write_assets(p,profile)
        cls.tc=Metadata('tc',p/'tc-dbc','tc',profile,assets.world(semantic.World));cls.ac=Metadata('ac',p/'ac-dbc','ac',profile,assets.world(semantic.World))
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()
    def setUp(self):
        self.tc=copy.deepcopy(type(self).tc);self.ac=copy.deepcopy(type(self).ac)
        self.state={'characters':[[1,1,9,80,0,2,0,32]],'character_talent':[],
            'character_spell':[[1,5785,1,0],[1,5784,1,0],[1,34091,1,0],[1,6603,1,0]],
            'character_skills':[[1,762,300,300],[1,171,375,450]]}
    def review(self):return select(self.state,self.tc,self.ac,preview=True)
    def test_all_contracts_and_old_blocker_then_semantic_round_trip(self):
        for m in (self.tc,self.ac):
            for s in (19902,1710,5785,65286):self.assertTrue(contract(m,s),(m.core,s))
        before=copy.deepcopy(self.state);rows,excluded,_,summary,_=self.review()
        self.assertEqual(rows,[(1,5785,1,0)]);self.assertFalse(excluded);self.assertEqual(summary['skill_rows_changed'],0)
        book={s:(a,d)for _,s,a,d in self.state['character_spell']};skills={s:(v,c)for _,s,v,c in self.state['character_skills']}
        with self.assertRaises(Unsupported)as e:reconstruct((1,9,0,2),book,{},skills,self.tc,self.ac,'tc-to-ac',level=80)
        self.assertEqual(e.exception.reason,'UNSUPPORTED_SKILL_STEP_SPELL')
        del book[5785];out=reconstruct((1,9,0,2),book,{},skills,self.tc,self.ac,'tc-to-ac',level=80)
        self.assertNotIn(5785,out);self.assertTrue({5784,33388,33391,34090,34091}<=out.keys())
        reverse=reconstruct((1,9,0,2),{s:(r['mask'],)for s,r in out.items()if r['disposition']=='PERSISTENT'}, {},skills,self.ac,self.tc,'ac-to-tc',level=80)
        self.assertNotIn(5785,reverse);self.assertEqual(self.state,before)
    def test_first_aid_and_jewelcrafting_keep_existing_caps_and_spells(self):
        for s,child,skill in ((19902,45542,129),(65286,51311,755)):
            self.state['characters'][0][2]=5;self.state['character_spell']=[[1,s,1,0],[1,child,1,0],[1,6603,1,0]]
            self.state['character_skills']=[[1,skill,450,450]];before=copy.deepcopy(self.state)
            self.assertEqual(self.review()[0],[(1,s,1,0)]);self.assertEqual(self.state,before)
    def test_every_child_requires_an_enabled_retained_anchor(self):
        for s in (5784,34091):
            original=copy.deepcopy(self.state)
            self.state['character_spell']=[r for r in original['character_spell']if r[1]!=s]
            self.assertFalse(self.review()[0]);self.state=original
        self.state['character_spell'][1][3]=1;self.assertFalse(self.review()[0])
    def test_character_flags_ownership_and_skill_tier_guards(self):
        base=copy.deepcopy(self.state)
        for field,v in ((2,8),(3,200),(4,3),(5,3),(6,1),(7,4)):
            self.state=copy.deepcopy(base);self.state['characters'][0][field]=v;self.assertFalse(self.review()[0])
        self.state=copy.deepcopy(base);self.state['character_talent']=[[1,123456,0]];self.assertFalse(self.review()[0])
        for flags in ((0,0),(1,1),(0,1)):
            self.state=copy.deepcopy(base);self.state['character_spell'][0][2:]=flags;self.assertFalse(self.review()[0])
        self.state=copy.deepcopy(base);self.state['character_skills'][0][3]=225;self.assertFalse(self.review()[0])
    def test_matching_mechanic_and_relationship_mutations_do_not_authorize(self):
        for field in (4,71,72,76,112,116):
            self.tc=copy.deepcopy(type(self).tc);self.ac=copy.deepcopy(type(self).ac)
            for m in (self.tc,self.ac):m.spells[5785][field]^=1
            self.assertFalse(self.review()[0])
        self.tc=copy.deepcopy(type(self).tc);self.ac=copy.deepcopy(type(self).ac);self.ac.requires[5785].add(6603)
        self.assertFalse(self.review()[0])
    def test_expected_count_and_parser(self):
        with self.assertRaises(CleanupError):select(self.state,self.tc,self.ac,2)
        args=parser().parse_args(['plan','skill-teaching','--migration-inspection','latest','--preview']);self.assertTrue(args.skill_teaching)


if __name__=='__main__':unittest.main()
