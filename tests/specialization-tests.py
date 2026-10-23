#!/usr/bin/env python3
"""Retain verified chosen specialties; never infer choices or ignore equipment."""
import copy,importlib.util,json,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'lib'))
from cleanup_specializations import select,contract,FAMILIES
from cleanup_console import CleanupError,parser
from spells import Metadata,reconstruct,Unsupported
spec=importlib.util.spec_from_file_location('specialty_assets',ROOT/'tests/specialization-fixtures.py');assets=importlib.util.module_from_spec(spec);spec.loader.exec_module(assets)
spec=importlib.util.spec_from_file_location('specialty_world',ROOT/'tests/spell-state-tests.py');semantic=importlib.util.module_from_spec(spec);spec.loader.exec_module(semantic)


class SpecializationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();p=Path(cls.temp.name);profile=json.loads((ROOT/'compatibility/tc335-acwotlk-v2/spell-metadata.json').read_text())
        assets.base.write_assets(p,profile)
        cls.tc=Metadata('tc',p/'tc-dbc','tc',profile,assets.world(semantic.World));cls.ac=Metadata('ac',p/'ac-dbc','ac',profile,assets.world(semantic.World))
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()
    def setUp(self):
        self.tc=copy.deepcopy(type(self).tc);self.ac=copy.deepcopy(type(self).ac)
        self.state={'characters':[[1,1,1,80,0,2,0,32]],'character_talent':[],
            'character_spell':[[1,17039,0,0],[1,17040,0,0],[1,17041,1,0],[1,9787,1,0],[1,51300,1,0],[1,6603,1,0],[1,3275,1,0]],
            'character_skills':[[1,164,441,450]]}
        self.equipment=[[1,15,101,101,10001,10001,0,10001,0]]
    def review(self):return select(self.state,self.tc,self.ac,preview=True,equipment=self.equipment)
    def test_all_frozen_contracts_and_source_unchanged(self):
        for m in (self.tc,self.ac):
            for family in FAMILIES:self.assertTrue(contract(m,family),(m.core,family))
        original=copy.deepcopy(self.state);rows,excluded,_,summary,_=self.review()
        self.assertEqual(rows,[(1,17039,0,0),(1,17040,0,0)]);self.assertFalse(excluded);self.assertEqual(self.state,original)
        self.assertEqual(summary['skill_rows_changed'],0);self.assertEqual(summary['spell_rows_inserted'],0)
    def test_inactive_guard_and_explicit_retirement_semantic_round_trip(self):
        book={s:(a,d)for _,s,a,d in self.state['character_spell']};skills={164:(441,450)}
        with self.assertRaises(Unsupported)as e:reconstruct((1,1,0,2),book,{},skills,self.tc,self.ac,'tc-to-ac',level=80)
        self.assertEqual(e.exception.reason,'UNREPRESENTABLE_INACTIVE_SPELL')
        del book[17039];del book[17040]
        out=reconstruct((1,1,0,2),book,{},skills,self.tc,self.ac,'tc-to-ac',level=80)
        self.assertTrue({17041,9787,51300,3275}<=out.keys());self.assertNotIn(17039,out)
        reverse=reconstruct((1,1,0,2),{s:(r['mask'],)for s,r in out.items()if r['disposition']=='PERSISTENT'}, {},skills,self.ac,self.tc,'ac-to-tc',level=80)
        self.assertTrue({17041,9787,3275}<=reverse.keys());self.assertNotIn(17040,reverse)
    def test_each_other_group_uses_existing_active_choice_and_ordinary_prefix(self):
        for stale,choice,rank,skill,minimum in ((9788,9787,51300,164,225),(10656,10660,51302,165,250),(20219,20222,51306,202,200),(26797,26798,51309,197,350)):
            self.state['character_spell']=[[1,stale,0,0],[1,choice,1,0],[1,rank,1,0],[1,6603,1,0]]
            self.state['character_skills']=[[1,skill,minimum,450]]
            self.assertEqual(self.review()[0],[(1,stale,0,0)],(stale,self.review()[1]))
    def test_no_choice_or_multiple_active_choices_or_disabled_siblings(self):
        base=copy.deepcopy(self.state)
        for change in ('absent','multiple','disabled'):
            self.state=copy.deepcopy(base)
            if change=='absent':self.state['character_spell']=[r for r in self.state['character_spell']if r[1]!=17041]
            elif change=='multiple':self.state['character_spell'][0][2]=1
            else:self.state['character_spell'][1][3]=1
            self.assertFalse(self.review()[0])
    def test_never_infer_weaponsmith_from_active_axe(self):
        self.state['character_spell']=[r for r in self.state['character_spell']if r[1]!=9787]
        self.assertFalse(self.review()[0]);self.assertEqual(self.review()[1][0][2],'DEFER_SPECIALIZATION_PARENT')
    def test_no_missing_ordinary_rank_or_skill_inference(self):
        base=copy.deepcopy(self.state)
        for change in ('missing','inactive','lowcap','lowvalue'):
            self.state=copy.deepcopy(base)
            if change=='missing':self.state['character_spell']=[r for r in self.state['character_spell']if r[1]!=51300]
            elif change=='inactive':next(r for r in self.state['character_spell']if r[1]==51300)[2]=0
            elif change=='lowcap':self.state['character_skills']=[[1,164,250,300]]
            else:self.state['character_skills']=[[1,164,1,450]]
            self.assertFalse(self.review()[0])
    def test_item_requirements_in_either_world_and_unknown_templates_defer(self):
        baseline=copy.deepcopy(self.equipment)
        for field,val in ((6,17039),(8,17040),(3,None),(5,None),(7,None),(6,None),(4,0)):
            self.equipment=copy.deepcopy(baseline);self.equipment[0][field]=val;self.assertFalse(self.review()[0])
        self.equipment=copy.deepcopy(baseline);self.equipment[0][6]=17041;self.assertEqual(len(self.review()[0]),2)
        self.equipment[0][1]=67;self.equipment[0][6]=17039;self.assertFalse(self.review()[0])
        self.equipment=[];self.assertEqual(len(self.review()[0]),2)
    def test_teacher_and_dependent_routes_defer(self):
        self.state['character_spell'].append([1,39097,1,0]);self.assertFalse(self.review()[0])
        self.state['character_spell']=[[1,9787,0,0],[1,9788,1,0],[1,51300,1,0],[1,17039,1,0]]
        self.assertFalse(self.review()[0])
    def test_metadata_matching_custom_modifications_never_authorize(self):
        for field in (4,71,76,116):
            self.tc=copy.deepcopy(type(self).tc);self.ac=copy.deepcopy(type(self).ac)
            for m in (self.tc,self.ac):m.spells[17039][field]^=1
            self.assertFalse(self.review()[0])
        self.tc=copy.deepcopy(type(self).tc);self.ac=copy.deepcopy(type(self).ac);self.ac.scripts[9787].add('custom')
        self.assertFalse(self.review()[0])
    def test_malformed_equipment_or_duplicate_slot_is_not_silently_ignored(self):
        row=self.equipment[0].copy();row[2:4]=[102,102];self.equipment.append(row)
        self.assertFalse(self.review()[0])
        self.equipment=[[1,23,101,101,10001,10001,0,10001,0]]
        with self.assertRaises(CleanupError):self.review()
        self.equipment=[[2,15,101,101,10001,10001,0,10001,0]]
        with self.assertRaises(CleanupError):self.review()
    def test_recipe_skill_and_choice_flags_are_never_rewritten(self):
        original=copy.deepcopy(self.state);rows=self.review()[0]
        after=copy.deepcopy(self.state);pairs={r[:2]for r in rows}
        after['character_spell']=[r for r in after['character_spell']if tuple(r[:2])not in pairs]
        for table in ('characters','character_talent','character_skills'):self.assertEqual(after[table],original[table])
        self.assertIn([1,17041,1,0],after['character_spell']);self.assertIn([1,3275,1,0],after['character_spell'])
    def test_character_pending_reset_and_count_guards(self):
        base=copy.deepcopy(self.state)
        for field,val in ((1,9),(2,10),(3,49),(3,81),(4,2),(5,3),(6,1),(7,4)):
            self.state=copy.deepcopy(base);self.state['characters'][0][field]=val;self.assertFalse(self.review()[0])
        self.state=copy.deepcopy(base);self.state['character_talent']=[[1,123456,0]];self.assertFalse(self.review()[0])
        self.state=base
        with self.assertRaises(CleanupError):select(self.state,self.tc,self.ac,1,equipment=self.equipment)
        args=parser().parse_args(['plan','specialization-retirement','--migration-inspection','latest','--preview']);self.assertTrue(args.specialization_retirement)


if __name__=='__main__':unittest.main()
