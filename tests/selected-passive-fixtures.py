"""Synthetic WDBC with stock direct passive identities and effects."""
import importlib.util
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('direct_passive_base',ROOT/'tests/spell-fixtures.py')
base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)
original=base.stores
# family, class, tab, class skill, ranks, effects, auras, rank base points
FAMILIES=[
 (128,1,161,26,[12295,12676,12677],[6,6,6],[4,108,108],[[4,20,20],[9,41,41],[14,62,62]]),
 (130,1,161,26,[16462,16463,16464,16465,16466],[6,0,0],[47,0,0],[[i,0,0]for i in range(5)]),
 (1432,2,382,594,[20205,20206,20207,20209,20208],[6,0,0],[108,0,0],[[i,0,0]for i in (13,27,41,55,69)]),
 (1638,5,203,78,[27839,27840],[6,0,0],[108,0,0],[[32,0,0],[66,0,0]]),
 (1938,6,398,770,[48978,49390,49391,49392,49393],[6,3,0],[285,0,0],[[179,0,0],[89,1,0],[59,2,0],[44,3,0],[35,4,0]])]


def stores(profile):
    data=original(profile)
    def record(store,ident):
        row=[0]*len(profile['stores'][store]['columns']);row[0]=ident;data[store][ident]=row;return row
    for family,cls,tab,skill,ranks,effects,auras,amounts in FAMILIES:
        record('TalentTab',tab)[20]=1<<(cls-1)
        record('SkillLine',skill)[1]=7
        record('SkillRaceClassInfo',skill)[1:7]=[skill,4095,1<<(cls-1),1040,0,0]
        talent=record('Talent',family);talent[1]=tab;talent[4:4+len(ranks)]=ranks
        if family==1638:talent[13]=484
        for index,spell in enumerate(ranks):
            row=record('Spell',spell);row[4]=448 if family==1638 else 464
            if family==1938:row[9]=512
            if family==128:row[12]=131072
            row[71:74]=effects;row[74:77]=[int(e!=0)for e in effects]
            row[80:83]=amounts[index];row[86:89]=[int(e==6)for e in effects];row[95:98]=auras
            if family==128:row[111:113]=[2,2]
            elif family==1432:row[110]=9
            elif family==1638:row[110]=8
            elif family==1938:row[110]=1
            ability=record('SkillLineAbility',spell);ability[1:8]=[skill,spell,0,1<<(cls-1),0,0,1]
    # Shadow prerequisite, selected exactly; its effects are not retirement candidates.
    record('Spell',17323)[4]=464
    talent=record('Talent',484);talent[1]=203;talent[4]=17323
    return data


base.stores=stores
base.CHAINS += [f[4]for f in FAMILIES]
