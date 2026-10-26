#!/usr/bin/env python3
"""Equipment-aware retirement guards, deterministic native placement, no mutation."""
import copy,importlib.util,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'lib'))
import cleanup_shaman_offhand as repair
from cleanup_console import parser
spec=importlib.util.spec_from_file_location('pair_tests',ROOT/'tests/shaman-dual-wield-tests.py');pair=importlib.util.module_from_spec(spec);spec.loader.exec_module(pair)

class OffhandTests(pair.ShamanTests):
 def capture(self,inventory_type=22,item_class=2,subclass=13):
  item=[10,1,100,1]+[100,item_class,subclass,inventory_type,0,0]*2+[1,0,0,0,0]
  return {'inventory':[[1,0,16,10]],'items':[item],'item_ids':[10]}
 def test_weapon_and_pending_reset(self):
  capture=self.capture();before=copy.deepcopy((self.state,capture));self.state['characters'][0][7]|=4
  result=repair.select(self.state,self.tc,self.ac,preview=True,capture=capture,default_skills={})
  self.assertEqual(result[0],[(1,674,1,0)]);self.assertEqual(result[3]['inventory_moves'],[[1,10,16,23]])
  self.assertTrue(result[3]['eligibility_proofs'][0]['pending_native_reset_preserved']);self.assertEqual(capture,before[1]);self.assertEqual(self.state['characters'][0][7],36)
 def test_shield_retained_and_requires_skill(self):
  capture=self.capture(14,4,6);self.assertFalse(repair.select(self.state,self.tc,self.ac,preview=True,capture=capture,default_skills={})[0])
  self.state['character_skills'].append([1,433,1,1]);r=repair.select(self.state,self.tc,self.ac,preview=True,capture=capture,default_skills={})
  self.assertEqual(r[0],[(1,674,1,0)]);self.assertEqual(r[3]['inventory_moves'],[])
 def test_backpack_then_bank_and_full(self):
  c=self.capture();c['inventory'] += [[1,0,s,1000+s]for s in range(23,39)]
  self.assertEqual(repair.placement(self.state,c)[1]['moves'],[[1,10,16,39]])
  c['inventory'] += [[1,0,s,1000+s]for s in range(39,67)]
  self.assertEqual(repair.placement(self.state,c)[1]['reason'],'DEFER_NO_NATIVE_STORAGE_SLOT')
 def test_item_owner_templates_placements_auras(self):
  for position,value in ((1,2),(2,0),(3,2),(4,None),(10,200),(16,2),(17,1),(18,1),(19,1),(20,1),(8,118),(9,674)):
   c=self.capture();c['items'][0][position]=value
   self.assertTrue(repair.placement(self.state,c)[1]['reason'],(position,value))
 def test_duplicate_items_and_slots(self):
  for extra in ([1,0,17,10],[1,0,16,11]):
   c=self.capture();c['inventory'].append(extra)
   self.assertEqual(repair.placement(self.state,c)[1]['reason'],'DEFER_DUPLICATE_ITEM_PLACEMENT')
 def test_mainhand_and_shield_native_rules(self):
  c=self.capture();c['inventory'].append([1,0,15,11]);c['items'].append([11,1,101,1]+[101,2,10,17,0,0]*2+[1,0,0,0,0])
  self.assertEqual(repair.placement(self.state,c)[1]['reason'],'DEFER_MAINHAND_CONTRACT')
 def test_talent_authority_still_blocks(self):
  c=self.capture();self.state['character_talent']=[[1,30798,1]]
  self.assertFalse(repair.select(self.state,self.tc,self.ac,preview=True,capture=c,default_skills={})[0])
 def test_independent_cli_policy(self):
  a=parser().parse_args(['plan','talent-ownership','--migration-inspection','latest','--reconcile-shaman-offhand','--preview']);self.assertTrue(a.reconcile_shaman_offhand)
  with self.assertRaises(SystemExit):parser().parse_args(['plan','talent-ownership','--migration-inspection','latest','--unselected-shaman-dual-wield','--reconcile-shaman-offhand','--preview'])

if __name__=='__main__':unittest.main()
