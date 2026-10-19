"""Native skill metadata shared by preparation policy tests."""
import importlib.util
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('native_skill_base',ROOT/'tests/spell-fixtures.py')
base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)
original=base.stores

def stores(profile):
    data=original(profile)
    def row(name,ident):
        result=[0]*len(profile['stores'][name]['columns']);result[0]=ident;data[name][ident]=result;return result
    row('SkillLine',183)[1]=12
    for ident,r in list(data['SkillRaceClassInfo'].items()):
        if r[1]==183:del data['SkillRaceClassInfo'][ident]
    row('SkillRaceClassInfo',5)[1:7]=[183,0xffffffff,262143,1170,0,0]
    for ident,effects,ability in [(2382,[25,60,0],1441),(63644,[162,0,0],20868),(63645,[162,0,0],20867)]:
        r=row('Spell',ident);r[71:74]=effects
        a=row('SkillLineAbility',ability);a[1],a[2],a[9]=183,ident,2
    return data

base.stores=stores
