"""Synthetic WDBC contracts using reviewed stock wrapper/child identifiers."""
from cleanup_pet_teaching import CONTRACTS


def extend(data, profile):
    def record(store, ident):
        row = [0] * len(profile['stores'][store]['columns'])
        row[0] = ident
        data[store][ident] = row
        return row
    for pairs in CONTRACTS.values():
        for parent,child in pairs:
            row = record('Spell',parent)
            row[4],row[71],row[86],row[116] = 262400,36,5,child
            record('Spell',child)[71] = 3
    tab = record('TalentTab',900050)
    tab[20] = 4
    for ident,spell in ((900050,900050),(900051,900051)):
        record('Spell',spell)[4] = 64
        talent = record('Talent',ident)
        talent[1],talent[4] = 900050,spell
    return data


def cower(data):
    """Actual child metadata; no player teaching flags or additional grants."""
    row=data['Spell'][1742]
    row[4:12]=[65536,0,67108864,0,0,0,0,0]
    row[71:74]=[6,6,0];row[86:92]=[1,1,0,0,0,0]
    row[95:98]=[87,33,0];row[116:119]=[0,0,0]
    row[133]=958;row[208:212]=[9,0,268435456,0]
    return data
