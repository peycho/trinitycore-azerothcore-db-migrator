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
