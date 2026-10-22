"""Synthetic ordinary training chains; identifiers and order match stock DBC."""
from cleanup_ordinary_history import TRAINING_CHAINS


def extend(data, profile):
    def record(store,ident):
        row=[0]*len(profile['stores'][store]['columns']);row[0]=ident
        data[store][ident]=row
        return row
    for root,chain in TRAINING_CHAINS.items():
        skill,cls=(613,5) if root in (14752,27681) else (574,11)
        record('SkillLine',skill)[1]=7
        info=record('SkillRaceClassInfo',skill);info[1],info[3]=skill,1<<(cls-1)
        for s in chain:
            row=record('Spell',s)
            row[4]=65536
            row[71:74]=[0,6,0] if root==16689 else [6,6,0] if root==339 else [6,0,0]
            row[95:98]=[0,42,0] if root==16689 else [26,3,0] if root==339 else [29,0,0]
            ability=record('SkillLineAbility',s)
            ability[1],ability[2],ability[4]=skill,s,1<<(cls-1)
    return data
