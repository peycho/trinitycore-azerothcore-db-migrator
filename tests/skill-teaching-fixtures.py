"""Synthetic WDBC using the reviewed stock teaching/rank mechanics."""
import importlib.util,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
RULES=json.loads((ROOT/'lib/cleanup_skill_teaching_catalog.json').read_text())
spec=importlib.util.spec_from_file_location('teacher_base',ROOT/'tests/spell-fixtures.py')
base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base);original=base.stores
CHAINS=sorted({tuple(r['chain'])for r in RULES['tc'].values()if len(r['chain'])>1})
base.CHAINS.extend(list(c)for c in CHAINS if list(c)not in base.CHAINS)


def stores(profile):
    data=original(profile)
    def record(store,s):
        row=[0]*len(profile['stores'][store]['columns']);row[0]=s;data[store][s]=row;return row
    members={int(s)for s in RULES['tc']}
    for s,entry in RULES['tc'].items():
        s=int(s);row=record('Spell',s)
        for i,v in entry['mechanics'].items():row[int(i)]=v
        for a in list(data['SkillLineAbility']):
            if data['SkillLineAbility'][a][2]==s:del data['SkillLineAbility'][a]
        for ability in entry['abilities']:data['SkillLineAbility'][ability[0]]=ability.copy()
    edges={}
    for s,entry in RULES['tc'].items():
        for parent in entry['learn_parents']:
            if parent not in members and parent!=33943:edges.setdefault(parent,[]).append(int(s))
    for parent,children in edges.items():
        row=record('Spell',parent)
        for i,child in enumerate(children):row[71+i]=36;row[86+i]=1;row[116+i]=child
    for s,entry in RULES['skill_metadata']['tc'].items():
        skill=int(s);record('SkillLine',skill)[1]=entry['category']
        for ident in list(data['SkillRaceClassInfo']):
            if data['SkillRaceClassInfo'][ident][1]==skill:del data['SkillRaceClassInfo'][ident]
        for row in entry['infos']:data['SkillRaceClassInfo'][row[0]]=row.copy()
        for ident,row in entry['tiers'].items():data['SkillTiers'][int(ident)]=row.copy()
    record('Spell',3275)[71]=10
    for ident in (23161,23214,34767):record('Spell',ident)[71]=3
    return data


base.stores=stores
original_seed=base.seed_worlds
REQUIRED=sorted({(dependent,int(s))for s,entry in RULES['tc'].items()for dependent in entry['prerequisite_users']})


def seed_worlds(sql,tc,ac,world,aworld,profile):
    original_seed(sql,tc,ac,world,aworld,profile)
    for schema in (world,aworld):
        sql('INSERT INTO spell_required VALUES '+','.join(f'({s},{r})'for s,r in REQUIRED),schema)


base.seed_worlds=seed_worlds


def world(base_world):
    class World(base_world):
        def table(self,schema,table,columns):
            rows=super().table(schema,table,columns)
            if table=='spell_ranks':
                existing={(int(r[0]),int(r[1]))for r in rows}
                rows += [[str(chain[0]),str(s),str(k)]for chain in CHAINS for k,s in enumerate(chain,1)if(chain[0],s)not in existing]
            if table=='spell_required':rows += [[str(s),str(r)]for s,r in REQUIRED]
            return sorted(rows,key=lambda r:int(r[0]))
    return World()
