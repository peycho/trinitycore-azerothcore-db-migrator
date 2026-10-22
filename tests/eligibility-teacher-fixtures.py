"""Synthetic stock single-child teachers; no private character metadata."""
from cleanup_eligibility import ABSENT_TEACHERS


def extend(data, profile):
    def record(store, ident):
        row = [0]*len(profile['stores'][store]['columns'])
        row[0] = ident
        data[store][ident] = row
        return row
    for root, pairs in ABSENT_TEACHERS.items():
        skill, cls = (237,8) if root == 5504 else (354,9)
        record('SkillLine',skill)[1] = 7
        info = record('SkillRaceClassInfo',skill)
        info[1],info[3] = skill,1<<(cls-1)
        for parent, child in pairs:
            row = record('Spell',parent)
            row[4],row[71],row[116] = 262400,36,child
            if parent == 10143:
                row[86] = 25
            else:
                row[16] = 256
            record('Spell',child)[71] = 24 if root == 5504 else 28
            ability = record('SkillLineAbility',child)
            ability[1],ability[2],ability[4] = skill,child,1<<(cls-1)
    return data
