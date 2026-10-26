"""Fixed stock riding mechanics in small synthetic WDBC/SQL fixtures."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('riding_fixture_base',ROOT/'tests/spell-fixtures.py')
base = importlib.util.module_from_spec(spec); spec.loader.exec_module(base)
original = base.stores
RULES = json.loads((ROOT/'lib/cleanup_obsolete_riding_catalog.json').read_text())


def stores(profile):
    data = original(profile)
    rule = RULES['tc']
    for s,expected in rule['spells'].items():
        row = [0]*len(profile['stores']['Spell']['columns']); row[0] = int(s)
        for i,v in expected['mechanics'].items(): row[int(i)] = v
        data['Spell'][int(s)] = row
    for s,expected in rule['skills'].items():
        skill = int(s)
        row = [0]*len(profile['stores']['SkillLine']['columns'])
        for i,v in expected['line'].items(): row[int(i)] = v
        data['SkillLine'][skill] = row
        for i,r in expected['tiers'].items(): data['SkillTiers'][int(i)] = r[:]
        for table,field,records in (('SkillRaceClassInfo',1,expected['infos']),('SkillLineAbility',1,expected['abilities'])):
            for i in [i for i,r in data[table].items() if r[field] == skill]: del data[table][i]
            for r in records: data[table][r[0]] = list(r)
    # AC learns are DBC effects. TC additionally has the Flight Form world link.
    children = {}
    for child,expected in RULES['ac']['spells'].items():
        for parent in expected['learn_parents']: children.setdefault(parent,[]).append(int(child))
    for parent,spells in children.items():
        if str(parent) in RULES['tc']['spells']: continue
        row = [0]*len(profile['stores']['Spell']['columns']); row[0] = parent
        for i,child in enumerate(spells): row[71+i] = 36; row[116+i] = child
        data['Spell'][parent] = row
    for spell in (23161,23214,34767):
        row = data['Spell'][6603][:]; row[0] = spell; data['Spell'][spell] = row
    return data


base.stores = stores


def world(parent):
    class World(parent):
        def table(self,schema,table,fields,optional=False):
            rows = super().table(schema,table,fields)
            if table == 'spell_ranks':
                rows += [[33388,s,i+1] for i,s in enumerate((33388,33391,34090,34091))]
            if table == 'spell_learn_spell':
                rows += [[33943,34090,1]]
            if table == 'spell_required':
                rows += [[s,33391] for s in (23161,23214,34767)]
            return rows
    return World()


def seed(sql,tc,ac,world_schema,ac_schema,profile):
    base.seed_worlds(sql,tc,ac,world_schema,ac_schema,profile)
    for schema in (world_schema,ac_schema):
        sql('DELETE FROM spell_ranks WHERE first_spell_id=33388;',schema)
        sql('INSERT INTO spell_ranks VALUES(33388,33388,1),(33388,33391,2),(33388,34090,3),(33388,34091,4);',schema)
    for schema in (world_schema,ac_schema):
        sql('INSERT INTO spell_required VALUES(23161,33391),(23214,33391),(34767,33391);',schema)
