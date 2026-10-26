#!/usr/bin/env python3
"""Fixed native action contracts, selected ownership, anchors and item boundaries."""
from pathlib import Path
from collections import defaultdict
from types import SimpleNamespace
import sys,copy,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'lib'))
import cleanup_native_actions as actions
from spells import Metadata

class NativeActions(unittest.TestCase):
 def setUp(self):
  rules=actions.rules();self.metas=[]
  for core in('tc','ac'):
   m=SimpleNamespace(core=core,spells={},abilities=defaultdict(list),learns=defaultdict(list),effect_learns=defaultdict(list),requires=defaultdict(set),prerequisite_users=defaultdict(set),learn_parents=defaultdict(set),scripts=defaultdict(set),talents={},talent_rows={},invalid_talents=set(),talent_learn_owners={},aura_owners=defaultdict(set),world_aura_owners=set(),additional={},stores={'SkillLine':{},'SkillRaceClassInfo':{},'SkillTiers':{},'TalentTab':{}})
   for key,r in rules[core].items():
    sp=int(key);row=[0]*234;row[0]=sp
    for i,v in r['mechanics'].items():row[int(i)]=v
    m.spells[sp]=row;m.abilities[sp]=copy.deepcopy(r['abilities']);m.learns[sp]=[tuple(x)for x in r['learns']];m.effect_learns[sp]=[tuple(x)for x in r['effect_learns']]
    for attr,key2 in [('requires','requires'),('prerequisite_users','required_by'),('learn_parents','parents'),('scripts','scripts')]:getattr(m,attr)[sp]=set(r[key2])
   for key,r in rules['skills'][core].items():
    sk=int(key)
    if r['line']is not None:m.stores['SkillLine'][sk]=copy.deepcopy(r['line'])
    for row in r['infos']:m.stores['SkillRaceClassInfo'][row[0]]=row[:]
    m.stores['SkillTiers'].update({int(k):v[:]for k,v in r['tiers'].items()})
   m.chain=lambda sp,m=m:tuple(rules[m.core].get(str(sp),{'chain':[sp]})['chain'])
   m.predecessors=lambda sp,m=m:m.chain(sp)[:m.chain(sp).index(sp)]
   m.check_spell=lambda sp:None;m.skill_effect=lambda sp,m=m:Metadata.skill_effect(m,sp)
   self.metas.append(m)
  self.state={'characters':[[1,1,8,80,0,1,0,0]],'character_spell':[],'character_skills':[],'character_talent':[]}
  self.items={'rows':[],'zero_template_counts':{'tc':0,'ac':0}};self.gear={'inventory':[],'items':[]}
 def review(self,action):return actions.select(self.state,*self.metas,preview=True,items=self.items,equipment=self.gear,default_skills={},action=action)
 def test_redundant_teacher_retains_higher_child_cap_and_pending_state(self):
  self.state['character_spell']=[[1,7415,1,0],[1,28029,1,0]];self.state['character_skills']=[[1,333,1,375]]
  self.assertTrue(self.review('redundant-teachers')[0]);self.state['characters'][0][7]=4
  before=copy.deepcopy(self.state);r=self.review('redundant-teachers');self.assertEqual(r[0],[(1,7415,1,0)]);self.assertEqual(self.state,before);self.assertEqual(r[3]['retired_skills'],[])
  self.state['character_spell'][1][3]=1;self.assertFalse(self.review('redundant-teachers')[0])
 def test_obsolete_lockpicking_step_is_not_reinterpreted(self):
  self.state['characters'][0][2]=4;self.state['character_spell']=[[1,1809,1,0],[1,1804,1,0]];self.state['character_skills']=[[1,633,1,400]]
  self.assertTrue(self.review('redundant-teachers')[0]);self.state['character_skills'].append([1,242,1,1]);self.assertFalse(self.review('redundant-teachers')[0])
 def test_unusable_specialization_is_explicit_and_never_a_skill_clamp(self):
  self.state['character_spell']=[[1,9788,0,0]];self.state['character_skills']=[[1,164,1,375]]
  self.assertEqual(self.review('unusable-specializations')[0],[(1,9788,0,0)]);self.assertEqual(actions.scope(self.state,*self.metas,'unusable-specializations'),[1]);self.state['character_skills'][0][2]=225;self.assertFalse(self.review('unusable-specializations')[0]);self.assertEqual(actions.scope(self.state,*self.metas,'unusable-specializations'),[])
 def test_transient_ids_and_actual_auras_are_separate(self):
  self.state['character_spell']=[[1,51726,1,0],[1,51734,1,0],[1,51735,1,0]]
  self.assertEqual(len(self.review('transient-combat')[0]),3);self.metas[1].learn_parents[51734].add(6603);self.assertEqual(len(self.review('transient-combat')[0]),2)
 def test_obsolete_training_requires_modern_anchor_and_absent_old_pair(self):
  self.state['character_spell']=[[1,6745,1,0],[1,34091,1,0]];self.state['character_skills']=[[1,762,300,300]]
  self.assertTrue(self.review('obsolete-teachers')[0]);self.state['character_spell'].append([1,828,1,0]);self.assertFalse(self.review('obsolete-teachers')[0])
 def test_catalog_matching_both_modified_cores_is_still_rejected(self):
  self.state['character_spell']=[[1,59888,1,0]]
  for m in self.metas:m.spells[59888][71]^=1
  self.assertFalse(self.review('transient-combat')[0])
 def test_forbidden_pair_removes_only_native_forbidden_skill_and_empty_offhand(self):
  self.state['character_spell']=[[1,42459,1,0],[1,674,1,0]];self.state['character_skills']=[[1,118,1,400],[1,762,300,300]]
  r=self.review('forbidden-pairs');self.assertEqual(len(r[0]),2);self.assertEqual(r[3]['retired_skills'],[[1,118,1,400]])
  self.gear={'inventory':[[1,0,16,10]],'items':[[10,1,1000,1]+[1000,2,5,17,0,0]*2+[1,0,0,0,0]]}
  self.assertFalse(self.review('forbidden-pairs')[0]);self.gear={'inventory':[],'items':[]};self.state['characters'][0][2]=1
  self.assertFalse(self.review('forbidden-pairs')[0])
 def test_forbidden_pair_stows_verified_weapon_and_retains_exact_inventory(self):
  self.state['character_spell']=[[1,42459,1,0]];self.state['character_skills']=[[1,118,1,400]]
  self.gear={'inventory':[[1,0,16,10],[1,0,23,20]],'items':[[10,1,1000,1]+[1000,2,15,22,0,0]*2+[1,0,0,0,0]]}
  before=copy.deepcopy(self.gear);r=self.review('forbidden-pairs-stowing')
  self.assertEqual(r[0],[(1,42459,1,0)]);self.assertEqual(r[3]['inventory_moves'],[[1,10,16,24]]);self.assertEqual(self.gear,before)
  self.gear['inventory']+=[[1,0,slot,slot+100]for slot in range(24,67)]
  self.assertFalse(self.review('forbidden-pairs-stowing')[0])
 def test_items_known_dependencies_invalid_talents_and_online_defer(self):
  self.state['character_spell']=[[1,59888,1,0]]
  self.items['rows']=[[1,10,10,1,1000,1000,0,0,59888,1000,0,0,59888]];self.assertFalse(self.review('transient-combat')[0]);self.items['rows']=[]
  self.state['character_talent']=[[1,1234567,0]];self.assertFalse(self.review('transient-combat')[0]);self.state['character_talent']=[]
  self.state['characters'][0][6]=1;self.assertFalse(self.review('transient-combat')[0])
if __name__=='__main__':unittest.main()
