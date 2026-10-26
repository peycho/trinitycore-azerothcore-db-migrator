#!/usr/bin/env python3
"""No accidental second-spec purchase or button/Generic grant during retirement."""
import copy,importlib.util,json,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'lib'))
from cleanup_dual_spec_teacher import contract,select
from cleanup_console import CleanupError,parser
from spells import Metadata,reconstruct,Unsupported
spec=importlib.util.spec_from_file_location('spell_tests',ROOT/'tests/spell-state-tests.py');fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
class TeacherTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.temp=tempfile.TemporaryDirectory();p=Path(cls.temp.name);profile=json.loads((ROOT/'compatibility/tc335-acwotlk-v2/spell-metadata.json').read_text());fixture.fixtures.write_assets(p,profile)
  cls.tc=Metadata('tc',p/'tc-dbc','tc',profile,fixture.World());cls.ac=Metadata('ac',p/'ac-dbc','ac',profile,fixture.World())
 @classmethod
 def tearDownClass(cls):cls.temp.cleanup()
 def setUp(self):
  self.tc=copy.deepcopy(type(self).tc);self.ac=copy.deepcopy(type(self).ac)
  self.state={'characters':[[1,7,8,80,0,1,0,4]],'character_talent':[],'character_spell':[[1,63680,1,0],[1,6603,1,0]],'character_skills':[]}
 def review(self):return select(self.state,self.tc,self.ac,preview=True)
 def test_fixed_teacher_retirement_and_reconstruction(self):
  self.assertTrue(contract(self.tc,self.ac));before=copy.deepcopy(self.state);r=self.review();self.assertEqual(r[0],[(1,63680,1,0)])
  self.assertEqual(r[3]['spell_rows_inserted'],0);self.assertEqual(r[3]['skill_rows_changed'],0);self.assertEqual(before,self.state)
  with self.assertRaises(Unsupported)as e:reconstruct((7,8,0,1),{63680:(1,0),6603:(1,0)},{},{},self.tc,self.ac,'tc-to-ac',level=80)
  self.assertEqual(e.exception.reason,'UNREPRESENTABLE_TEACHER_STATE')
  out=reconstruct((7,8,0,1),{6603:(1,0)},{},{},self.tc,self.ac,'tc-to-ac',level=80)
  self.assertFalse({63680,63644,63645}&out.keys())
 def test_character_flags_and_configured_spec_guards(self):
  for index,value in((1,0),(2,10),(3,39),(4,1),(5,2),(6,1),(7,0)):
   old=self.state['characters'][0][index];self.state['characters'][0][index]=value;self.assertFalse(self.review()[0]);self.state['characters'][0][index]=old
  for f in((0,0),(1,1),(0,1)):
   self.state['character_spell'][0][2:]=f;self.assertFalse(self.review()[0])
 def test_existing_routes_and_invalid_ownership_defer(self):
  for s in(63644,63645):
   self.state['character_spell'].append([1,s,1,0]);self.assertFalse(self.review()[0]);self.state['character_spell'].pop()
  self.state['character_skills']=[[1,183,400,400]];self.assertFalse(self.review()[0]);self.state['character_skills']=[]
  self.state['character_talent']=[[1,123456,0]];self.assertFalse(self.review()[0])
 def test_whole_teacher_family_and_separate_purchase_action(self):
  self.state['character_spell'] += [[1,63706,1,0],[1,63707,1,0],[1,63624,1,0]]
  before=copy.deepcopy(self.state);r=self.review();self.assertEqual(r[0],[(1,s,1,0)for s in(63680,63706,63707)]);self.assertEqual(r[3]['selected_characters'],1);self.assertEqual(before,self.state)
  self.state['character_spell'][2][3]=1;self.assertFalse(self.review()[0])
 def test_metadata_changes_cannot_widen_contract(self):
  for change in('mechanic','script','extra_child','incoming','aura'):
   self.tc=copy.deepcopy(type(self).tc);self.ac=copy.deepcopy(type(self).ac)
   if change=='mechanic':self.tc.spells[63680][74]=0
   elif change=='script':self.ac.scripts[63680].add('unknown')
   elif change=='extra_child':self.tc.learns[63680].append((6603,1,False))
   elif change=='incoming':self.tc.learn_parents[63680].add(6603)
   else:self.tc.aura_owners[63680].add(12345)
   self.assertFalse(self.review()[0])
 def test_exact_count_and_cli(self):
  with self.assertRaises(CleanupError):select(self.state,self.tc,self.ac,2)
  a=parser().parse_args(['plan','dual-spec-teacher','--migration-inspection','latest','--preview']);self.assertTrue(a.dual_spec_teacher)
if __name__=='__main__':unittest.main()
