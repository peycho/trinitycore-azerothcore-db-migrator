"""Synthetic WDBC/world fixtures reproduce fixed native action contracts."""
from pathlib import Path
from collections import defaultdict
import importlib.util,json
ROOT=Path(__file__).resolve().parents[1];RULES=json.loads((ROOT/'lib/cleanup_native_action_catalog.json').read_text())
spec=importlib.util.spec_from_file_location('native_action_base',ROOT/'tests/spell-fixtures.py');base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)
original=base.stores
CHAINS={core:sorted({tuple(r['chain'])for r in RULES[core].values()if len(r['chain'])>1})for core in('tc','ac')}
# Base assets write one WDBC dataset for both cores. Rank differences live in SQL.
def stores(profile):
 data=original(profile)
 def record(store,sp):
  row=[0]*len(profile['stores'][store]['columns']);row[0]=sp;data[store][sp]=row;return row
 members=set(map(int,RULES['tc']))
 for key,r in RULES['tc'].items():
  sp=int(key);row=record('Spell',sp)
  for i,v in r['mechanics'].items():row[int(i)]=v
  for ident in list(data['SkillLineAbility']):
   if data['SkillLineAbility'][ident][2]==sp:del data['SkillLineAbility'][ident]
  for ability in r['abilities']:data['SkillLineAbility'][ability[0]]=ability[:]
 edges=defaultdict(set)
 for key,r in RULES['tc'].items():
  for parent in r['parents']:
   if parent not in members:edges[parent].add(int(key))
 for parent,children in edges.items():
  row=record('Spell',parent)
  if len(children)>3:raise AssertionError('Fixture needs explicit multi-child teacher')
  for i,ch in enumerate(sorted(children)):row[71+i]=36;row[86+i]=1;row[116+i]=ch
 for key,r in RULES['skills']['tc'].items():
  sk=int(key)
  if r['line']is not None:record('SkillLine',sk)[1]=r['line'][1]
  else:data['SkillLine'].pop(sk,None)
  for ident in list(data['SkillRaceClassInfo']):
   if data['SkillRaceClassInfo'][ident][1]==sk:del data['SkillRaceClassInfo'][ident]
  for row in r['infos']:data['SkillRaceClassInfo'][row[0]]=row[:]
  for ident,row in r['tiers'].items():data['SkillTiers'][int(ident)]=row[:]
 return data
base.stores=stores;original_seed=base.seed_worlds

def seed_worlds(sql,tc,ac,world,aworld,profile):
 original_seed(sql,tc,ac,world,aworld,profile)
 for core,schema in(('tc',world),('ac',aworld)):
  ids=','.join(RULES[core]);sql('DELETE FROM spell_ranks WHERE spell_id IN('+ids+');',schema)
  ranks=sorted({(ch[0],sp,k)for ch in CHAINS[core]for k,sp in enumerate(ch,1)})
  if ranks:sql('INSERT INTO spell_ranks VALUES '+','.join(f'({a},{b},{c})'for a,b,c in ranks),schema)
  required=sorted({(int(key),dep)for key,r in RULES[core].items()for dep in r['requires']})
  if required:sql('REPLACE INTO spell_required VALUES '+','.join(f'({a},{b})'for a,b in required),schema)
  # Most edges derive from DBC; explicit TC-only world overrides remain data.
  if core=='tc':
   extra=sorted({(int(key),ch,active)for key,r in RULES[core].items()for ch,active,auto in r['learns']if [ch,active,auto]not in r['effect_learns']})
   if extra:sql('REPLACE INTO spell_learn_spell VALUES '+','.join(f'({a},{b},{c})'for a,b,c in extra),schema)
base.seed_worlds=seed_worlds
