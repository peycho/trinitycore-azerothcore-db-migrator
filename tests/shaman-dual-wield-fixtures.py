"""Stock 30798/674/118 mechanics in synthetic WDBC assets."""
import importlib.util
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('shaman_fixture_base',ROOT/'tests/spell-fixtures.py')
base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)
original=base.stores


def stores(profile):
    data=original(profile)
    def record(store,ident):
        row=[0]*len(profile['stores'][store]['columns']);row[0]=ident;data[store][ident]=row;return row
    for s,fields in {674:{4:80,28:1,35:101,46:1,68:4294967295,71:40,86:1},
                     30798:{4:159646096,5:2147483648,28:1,35:101,46:1,68:4294967295,71:36,86:1,116:674}}.items():
        row=record('Spell',s)
        for i,v in fields.items():row[i]=v
    data['Talent'][1690]=[1690,263,6,1,30798,0,0,0,0,0,0,0,0,616,0,0,0,0,0,0,0,0,0]
    record('TalentTab',263)[20]=64
    data['SkillLineAbility'].pop(674,None)
    data['SkillLineAbility'][610]=[610,118,674,0,109,0,0,1,0,2,0,0,0,0]
    data['SkillLineAbility'][14446]=[14446,373,30798,0,64,0,0,1,0,0,0,0,0,0]
    for i in [i for i,r in data['SkillRaceClassInfo'].items() if r[1]==118]:del data['SkillRaceClassInfo'][i]
    for row in ([131,118,32767,8,146,1,0,0],[132,118,32767,5,146,20,0,0],
                [883,118,32767,64,402,0,0,0],[913,118,262143,32,146,0,0,0]):
        data['SkillRaceClassInfo'][row[0]]=row
    record('SkillLine',118)[1]=6
    return data


base.stores=stores
