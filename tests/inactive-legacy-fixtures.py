"""Stock legacy Bloodthirst IDs, deliberately WITHOUT invented rank chains."""
import importlib.util
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('inactive_legacy_base',ROOT/'tests/spell-fixtures.py')
base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)
original=base.stores
LEGACY=(23892,23893,23894,25251,30335)


def stores(profile):
    data=original(profile)
    def row(name,ident):
        values=[0]*len(profile['stores'][name]['columns']);values[0]=ident
        data[name][ident]=values;return values
    for ident in (23881,*LEGACY):
        record=row('Spell',ident)
        record[4:12]=[327696,134218240,0,0,0,0,0,0]
        record[19],record[41]=1,1
        record[71:119]=[0]*48
        for offset,value in ((0,2),(3,1),(9,44),(15,6)):record[71+offset]=value
        record[208:212]=[4,0,1024,0]
    data['Spell'][23881][72]=3
    tab=row('TalentTab',167);tab[20]=1
    talent=row('Talent',167);talent[1]=167;talent[4]=23881;talent[19]=1
    return data


base.stores=stores
