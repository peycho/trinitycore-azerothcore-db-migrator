"""Synthetic fixed specialization and ordinary-rank catalogs."""
import importlib.util,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('specialty_ordinary',ROOT/'tests/profession-activation-fixtures.py')
ordinary=importlib.util.module_from_spec(spec);spec.loader.exec_module(ordinary)
base=ordinary.base;original=base.stores
RULES=json.loads((ROOT/'lib/cleanup_specialization_catalog.json').read_text())


def stores(profile):
    data=original(profile)
    for s,entry in RULES['tc'].items():
        s=int(s);row=[0]*len(profile['stores']['Spell']['columns']);row[0]=s
        for i,v in entry['mechanics'].items():row[int(i)]=v
        data['Spell'][s]=row
        for a in list(data['SkillLineAbility']):
            if data['SkillLineAbility'][a][2]==s:del data['SkillLineAbility'][a]
        for ability in entry['abilities']:data['SkillLineAbility'][ability[0]]=ability.copy()
    return data


base.stores=stores
original_seed=base.seed_worlds
# Ordinary fixtures already add all stock requirements other than the three
# TC Weaponsmith-to-subspecialty links.
EXTRA=[(s,r)for core in ('tc',)for s,e in RULES[core].items()for r in e['requires']if (int(s),r)not in ordinary.REQUIRED]


def seed_worlds(sql,tc,ac,world,aworld,profile):
    original_seed(sql,tc,ac,world,aworld,profile)
    if EXTRA:sql('INSERT INTO spell_required VALUES '+','.join(f'({s},{r})'for s,r in EXTRA),world)


base.seed_worlds=seed_worlds


def world(base_world):
    class World(type(ordinary.world(base_world))):
        def table(self,schema,table,columns):
            rows=super().table(schema,table,columns)
            if table=='spell_required' and schema!='ac':rows += [[str(s),str(r)]for s,r in EXTRA]
            return sorted(rows,key=lambda r:int(r[0]))
    return World()
