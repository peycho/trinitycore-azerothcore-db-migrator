#!/usr/bin/env python3
"""Horse pair retirement uses its own frozen catalog and retains modern Riding."""
import copy,importlib.util,json,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'lib'))
from cleanup_obsolete_riding import contract,select,candidate_guids
from cleanup_console import CleanupError,parser
from spells import Metadata,reconstruct,Unsupported
def module(name,path):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
assets=module('horse_assets',ROOT/'tests/obsolete-horse-fixtures.py');semantic=module('horse_semantic',ROOT/'tests/spell-state-tests.py')
class HorseTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.temp=tempfile.TemporaryDirectory();p=Path(cls.temp.name);profile=json.loads((ROOT/'compatibility/tc335-acwotlk-v2/spell-metadata.json').read_text());assets.base.write_assets(p,profile)
  cls.tc=Metadata('tc',p/'tc-dbc','tc',profile,assets.world(semantic.World));cls.ac=Metadata('ac',p/'ac-dbc','ac',profile,assets.world(semantic.World))
 @classmethod
 def tearDownClass(cls):cls.temp.cleanup()
 def setUp(self):
  self.tc=copy.deepcopy(type(self).tc);self.ac=copy.deepcopy(type(self).ac)
  self.state={'characters':[[1,11,8,80,0,1,0,0]],'character_talent':[],'character_spell':[[1,824,1,0],[1,34091,1,0],[1,6603,1,0]],'character_skills':[[1,148,1,75],[1,762,300,300]]}
  self.items=[[1,10,10,1,1234,1234,762,300,0,1234,762,300,0]]
 def review(self,**kw):return select(self.state,self.tc,self.ac,preview=True,legacy_horse=True,native_invalid_items=True,zero_template_counts={'tc':0,'ac':0},items=self.items,default_skills=kw.pop('default_skills',{}),**kw)
 def test_exact_catalog_and_reconstruction(self):
  for m in(self.tc,self.ac):self.assertTrue(contract(m,legacy_horse=True));self.assertFalse(contract(m))
  before=copy.deepcopy(self.state);r=self.review();self.assertEqual(r[0],[(1,824,1,0)]);self.assertEqual(r[3]['eligibility_proofs'][0]['retired_skill'],[148,1,75]);self.assertEqual(self.state,before)
  with self.assertRaises(Unsupported):reconstruct((11,8,0,1),{824:(1,0),34091:(1,0),6603:(1,0)},{},{148:(1,75),762:(300,300)},self.tc,self.ac,'tc-to-ac',level=80)
  out=reconstruct((11,8,0,1),{34091:(1,0),6603:(1,0)},{},{762:(300,300)},self.tc,self.ac,'tc-to-ac',level=80);self.assertNotIn(824,out);self.assertIn(34091,out)
 def test_eligibility_pair_modern_anchor_and_reset_guards(self):
  for index,value in((1,1),(3,0),(6,1),(7,4)):
   old=self.state['characters'][0][index];self.state['characters'][0][index]=value;self.assertFalse(self.review()[0]);self.state['characters'][0][index]=old
  self.state['character_spell'].append([1,6743,1,0]);self.assertFalse(self.review()[0]);self.state['character_spell'].pop()
  self.state['character_skills'][1][3]=225;self.assertFalse(self.review()[0])
 def test_items_and_native_invalid_exceptions(self):
  self.items += [[1,11,11,1,0,None,None,None,None,None,None,None,None],[1,12,*([None]*11)]]
  r=self.review();self.assertEqual(r[3]['native_invalid_item_rows_retained'],2)
  for pos,value in((6,148),(8,824),(10,148),(12,824)):
   old=self.items[0][pos];self.items[0][pos]=value;self.assertFalse(self.review()[0]);self.items[0][pos]=old
  self.items[-1][2]=12;self.items[-1][3]=1;self.items[-1][4]=777;self.assertFalse(self.review()[0])
 def test_defaults_and_changed_catalog(self):
  defaults={'tc':{'layout':{'columns':[['playercreateinfo_skills',f]for f in('raceMask','classMask','skill','rank')]},'rows':{'playercreateinfo_skills':[[0,0,148,0]]}}}
  self.assertFalse(self.review(default_skills=defaults)[0]);defaults['tc']['rows']['playercreateinfo_skills'][0][2]=149;self.assertTrue(self.review(default_skills=defaults)[0])
  self.ac.spells[824][110]=149;self.assertFalse(self.review()[0])
 def test_scope_and_expected_count(self):
  self.assertEqual(candidate_guids(self.state,legacy_horse=True),[1]);self.assertEqual(candidate_guids(self.state),[])
  with self.assertRaises(CleanupError):select(self.state,self.tc,self.ac,2,legacy_horse=True,native_invalid_items=True,zero_template_counts={'tc':0,'ac':0},items=self.items,default_skills={})
  a=parser().parse_args(['plan','obsolete-riding','--horse','--migration-inspection','latest','--preview']);self.assertTrue(a.horse)
if __name__=='__main__':unittest.main()
