#!/usr/bin/env python3
"""Complete forbidden families require source/target, ownership and item proofs."""
from pathlib import Path
import sys,copy,importlib.util,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'lib'))
import cleanup_foreign_skills as foreign
from cleanup_console import CleanupError
spec=importlib.util.spec_from_file_location('eligibility_fixtures',ROOT/'tests/spell-eligibility-tests.py');base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)
class FamilyTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):base.EligibilityTests.setUpClass()
 @classmethod
 def tearDownClass(cls):base.EligibilityTests.tearDownClass()
 def setUp(self):
  base.EligibilityTests.setUp(self);self.state['character_skills'].append([1,267,400,400]);self.items={'rows':[],'zero_template_counts':{'tc':0,'ac':0}};self.gear={'inventory':[],'items':[]}
 def family(self,**kwargs):return foreign.select(self.state,self.tc,self.ac,preview=True,items=self.items,equipment=self.gear,default_skills=kwargs.pop('default_skills',{}),**kwargs)
 def test_complete_class_family_and_only_its_stored_skill(self):
  before=copy.deepcopy(self.state);r=self.family();self.assertEqual(r[0],[(1,465,0,0),(1,48942,1,0)]);self.assertEqual(r[3]['retired_skills'],[[1,267,400,400]]);self.assertEqual(self.state,before)
  self.state['characters'][0][7]|=4;self.assertTrue(self.family()[0]);self.assertTrue(self.family()[3]['eligibility_proofs'][0]['pending_native_reset_preserved'])
 def test_native_class_or_source_target_disagreement(self):
  self.state['characters'][0][2]=2;self.state['character_talent']=[];self.assertFalse(self.family()[0]);self.state['characters'][0][2]=1
  for r in self.ac.stores['SkillRaceClassInfo'].values():
   if r[1]==267:r[3]|=1
  self.assertFalse(self.family()[0])
 def test_selected_authority_and_shared_exposure(self):
  self.tc.talent_learn_owners[465].add(12282);self.assertEqual({r[2]for r in self.family()[1]},{'DEFER_SELECTED_TALENT_FAMILY'});self.tc.talent_learn_owners[465].clear()
  self.tc.abilities[6603].append([9901,267,6603,0,0,0,0,1,0,2,0,0,0,0]);self.assertEqual({r[2]for r in self.family()[1]},{'DEFER_FOREIGN_SKILL_SHARED_EXPOSURE'})
 def test_known_boundary_or_unreviewed_script(self):
  self.tc.learn_parents[465].add(6603);self.assertEqual({r[2]for r in self.family()[1]},{'DEFER_FOREIGN_SKILL_KNOWN_BOUNDARY'});self.tc.learn_parents[465].clear()
  self.ac.scripts[465].add('unknown');self.assertEqual({r[2]for r in self.family()[1]},{'DEFER_FOREIGN_SKILL_NATIVE_CONTRACT'})
 def teacher(self,children):
  self.state['character_spell'].append([1,900099,1,0])
  for m in(self.tc,self.ac):
   row=m.spells[6603][:];row[0]=900099;row[71:74]=[36]*len(children)+[0]*(3-len(children));row[116:119]=children+[0]*(3-len(children));row[86:89]=[1]*len(children)+[0]*(3-len(children));m.spells[900099]=row
   m.learns[900099]=[(s,1,False)for s in children];m.effect_learns[900099]=list(m.learns[900099]);m.learn_parents[465].add(900099)
 def test_pure_teacher_whole_family_and_mixed_boundary(self):
  self.teacher([465]);r=self.family();self.assertTrue(any(s==900099 for g,s,a,d in r[0]));self.assertEqual(r[3]['skill_rows_removed'],1)
  self.tc.spells[900099][72]=36;self.tc.spells[900099][87]=1;self.tc.spells[900099][117]=6603;self.assertFalse(self.family()[0])
 def test_absent_child_training_is_a_separate_policy(self):
  self.teacher([465]);self.state['character_spell']=[r for r in self.state['character_spell']if r[1]not in(465,48942)]
  self.assertFalse(self.family()[0])
  r=self.family(training_actions=True);self.assertEqual(r[0],[(1,900099,1,0)]);self.assertIn(465,r[3]['eligibility_proofs'][0]['catalog_family_including_absent_children'])
  self.items['rows']=[[1,10,10,1,1234,1234,0,0,465,1234,0,0,465]];self.assertFalse(self.family(training_actions=True)[0]);self.items['rows']=[]
  for m in(self.tc,self.ac):m.spells[900099][86]=25
  self.assertFalse(self.family()[0]);self.assertTrue(self.family(training_actions=True)[0])
  self.ac.scripts[465].add('unknown');self.assertFalse(self.family(training_actions=True)[0])
 def test_unknown_future_child_cannot_be_discarded(self):
  self.teacher([465,6603]);self.assertFalse(self.family()[0])
  self.state['character_spell']=[r for r in self.state['character_spell']if r[1]!=6603];self.assertFalse(self.family()[0])
 def test_owned_items_defaults_and_native_invalid_records(self):
  self.items['rows']=[[1,10,10,1,1234,1234,267,1,0,1234,267,1,0]];self.assertFalse(self.family()[0])
  self.items['rows']=[[1,10,10,1,0,None,None,None,None,None,None,None,None],[1,11,*([None]*11)]];self.assertTrue(self.family()[0])
  self.items['rows'][0][4]=999;self.assertFalse(self.family()[0]);self.items['rows']=[]
  defaults={'tc':{'layout':{'columns':[['playercreateinfo_skills',f]for f in('raceMask','classMask','skill','rank')]},'rows':{'playercreateinfo_skills':[[0,0,267,0]]}}};self.assertFalse(self.family(default_skills=defaults)[0])
 def test_proficiency_conflicts_defer_without_moving_items(self):
  for m in(self.tc,self.ac):m.spells[465][71]=60;m.spells[465][68]=2;m.spells[465][69]=1<<5
  self.gear={'inventory':[[1,0,15,10]],'items':[[10,1,1234,1]+[1234,2,5,17,0,0]*2+[1,0,0,0,0]]}
  before=copy.deepcopy(self.gear);self.assertEqual({r[2]for r in self.family()[1]},{'DEFER_EQUIPPED_RETIRED_PROFICIENCY'});self.assertEqual(self.gear,before)
 def test_no_profession_racial_or_riding_scope_and_exact_count(self):
  for m in(self.tc,self.ac):m.stores['SkillLine'][267][1]=11
  self.assertFalse(self.family()[0])
  with self.assertRaises(CleanupError):foreign.select(self.state,self.tc,self.ac,1,items=self.items,equipment=self.gear,default_skills={})
if __name__=='__main__':unittest.main()
