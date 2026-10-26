#!/usr/bin/env python3
"""Explicit native parent restoration preserves the retained choice and recipes."""
import copy,importlib.util,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'lib'))
from cleanup_console import CleanupError,parser
from cleanup_specialization_parent import select
from cleanup_specializations import select as retirement
from spells import reconstruct,Unsupported
spec=importlib.util.spec_from_file_location('specialty_parent_base',ROOT/'tests/specialization-tests.py');base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)

class ParentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):base.SpecializationTests.setUpClass()
    @classmethod
    def tearDownClass(cls):base.SpecializationTests.tearDownClass()
    def setUp(self):
        self.tc=copy.deepcopy(base.SpecializationTests.tc);self.ac=copy.deepcopy(base.SpecializationTests.ac)
        self.state={'characters':[[1,1,1,80,0,2,0,32]],'character_talent':[],
            'character_spell':[[1,9788,0,0],[1,17039,0,0],[1,17040,0,0],[1,17041,1,0],[1,51300,1,0],[1,6603,1,0],[1,3275,1,0]],
            'character_skills':[[1,164,441,450]]}
        self.equipment=[[1,15,101,101,10001,10001,17041,10001,17041]]
    def review(self):return select(self.state,self.tc,self.ac,preview=True,equipment=self.equipment)
    def test_explicit_policy_and_semantic_roundtrip(self):
        original=copy.deepcopy(self.state)
        self.assertFalse(retirement(self.state,self.tc,self.ac,preview=True,equipment=self.equipment)[0])
        rows,excluded,_,summary,_=self.review()
        self.assertEqual(rows,[(1,9788,0,0),(1,17039,0,0),(1,17040,0,0)]);self.assertFalse(excluded)
        self.assertEqual(summary['spell_rows_inserted'],1);self.assertEqual(summary['skill_rows_changed'],0)
        self.assertEqual(self.state,original)
        after={s:(a,d)for _,s,a,d in self.state['character_spell']if s not in (9788,17039,17040)};after[9787]=(1,0)
        out=reconstruct((1,1,0,2),after,{},{164:(441,450)},self.tc,self.ac,'tc-to-ac',level=80)
        self.assertTrue({9787,17041,3275}<=out.keys())
        reverse=reconstruct((1,1,0,2),{s:(r['mask'],)for s,r in out.items()if r['disposition']=='PERSISTENT'},{},{164:(441,450)},self.ac,self.tc,'ac-to-tc',level=80)
        self.assertTrue({9787,17041,3275}<=reverse.keys());self.assertNotIn(17040,reverse)
        self.assertEqual(select(self.state,self.tc,self.ac,3,equipment=self.equipment)[0],rows)
        with self.assertRaises(CleanupError):select(self.state,self.tc,self.ac,1,equipment=self.equipment)
    def test_native_invalid_equipment_requires_explicit_parent_policy_and_checks_live_items(self):
        self.equipment=[[1,15,101,101,0,None,None,None,None]]
        self.assertFalse(self.review()[0])
        rows,_,_,summary,_=select(self.state,self.tc,self.ac,preview=True,equipment=self.equipment,native_invalid_items=True,zero_template_counts={'tc':0,'ac':0})
        self.assertEqual(len(rows),3);self.assertEqual(summary['spell_rows_inserted'],1)
        self.assertEqual(summary['native_invalid_item_rows_retained'],1)
        self.equipment.append([1,16,102,102,10002,10002,9788,10002,0])
        self.assertFalse(select(self.state,self.tc,self.ac,preview=True,equipment=self.equipment,native_invalid_items=True,zero_template_counts={'tc':0,'ac':0})[0])

    def test_existing_parent_or_different_choice_or_flags_cannot_be_inferred(self):
        self.state['character_spell'].append([1,9787,0,0]);self.assertFalse(self.review()[0]);self.state['character_spell'].pop()
        for spell in (17039,17040,17041):
            for flags in ((1,1),(0,1),(1,0)if spell!=17041 else (0,0)):
                original=copy.deepcopy(self.state)
                for r in self.state['character_spell']:
                    if r[1]==spell:r[2:]=flags
                self.assertFalse(self.review()[0]);self.state=original
    def test_skills_levels_reset_ownership_and_ordinary_anchor_guards(self):
        original=copy.deepcopy(self.state)
        for field,value in ((3,49),(3,200),(4,2),(5,3),(6,1),(7,4)):
            self.state=copy.deepcopy(original);self.state['characters'][0][field]=value;self.assertFalse(self.review()[0])
        self.state=copy.deepcopy(original);self.state['character_skills'][0][2]=1;self.assertFalse(self.review()[0])
        self.state=copy.deepcopy(original);self.state['character_talent']=[[1,123456,0]];self.assertFalse(self.review()[0])
        self.state=copy.deepcopy(original);self.state['character_spell']=[r for r in self.state['character_spell']if r[1]!=51300];self.assertFalse(self.review()[0])
    def test_equipment_requires_every_retired_competitor_in_both_worlds(self):
        for index in (6,8):
            for spell in (9788,17039,17040):
                original=copy.deepcopy(self.equipment);self.equipment[0][index]=spell;self.assertFalse(self.review()[0]);self.equipment=original
        for index in (3,4,5,7,8):
            original=copy.deepcopy(self.equipment);self.equipment[0][index]=None;self.assertFalse(self.review()[0]);self.equipment=original
        self.equipment[0][1]=20;self.equipment[0][6]=9788;self.assertFalse(self.review()[0])
    def test_known_teachers_recipe_dependencies_and_modified_contracts_defer(self):
        for teacher in (9789,9790,39097,39098,39099):
            self.state['character_spell'].append([1,teacher,1,1]);self.assertFalse(self.review()[0]);self.state['character_spell'].pop()
        for core in ('tc','ac'):
            tc,ac=copy.deepcopy(self.tc),copy.deepcopy(self.ac);m=tc if core=='tc'else ac;m.spells[9787][71]=36
            self.assertFalse(select(self.state,tc,ac,preview=True,equipment=self.equipment)[0])
        self.tc.prerequisite_users[17039].add(3275);self.assertFalse(self.review()[0])
    def test_parser_is_separate_policy(self):
        args=parser().parse_args(['plan','specialization-parent','--migration-inspection','latest','--preview'])
        self.assertTrue(args.parent_specialization);self.assertTrue(args.specialization_retirement)

if __name__=='__main__':unittest.main()
