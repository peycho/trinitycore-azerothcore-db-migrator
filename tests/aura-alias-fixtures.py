"""Synthetic paladin registrations and area-aura helper metadata."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('aura_alias_base',ROOT/'tests/spell-fixtures.py')
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
original = base.stores
FAMILIES = [(1422,[20138,20139,20140],'spell_pal_improved_devotion_aura'),
            (1450,[20254,20255,20256],'spell_pal_improved_concentraction_aura'),
            (1756,[31869],'spell_pal_sanctified_retribution'),
            (2148,[53379,53484,53648],'spell_pal_swift_retribution')]


def stores(profile):
    data = original(profile)
    def row(name,ident):
        record = [0]*len(profile['stores'][name]['columns'])
        record[0] = ident
        data[name][ident] = record
        return record
    for family,ranks,_ in FAMILIES:
        row('TalentTab',family)[20] = 2
        talent = row('Talent',family)
        talent[1],talent[4:4+len(ranks)] = family,ranks
        for spell in ranks:
            record = row('Spell',spell)
            record[4],record[71],record[95] = 64,6,107
    for ident,attrs,effects,targets,auras in [
        (63510,[151323008,0,17,1114112,2097152,0,0,4],[0,65,65],[1,1,1,0,0,0],[0,234,234]),
        (63514,[151323008,0,17,1114112,2097152,0,0,4],[0,65,0],[1,1,0,0,0,0],[0,118,0]),
        (63531,[151323008,0,17,1114112,2097152,0,0,0],[0,65,65],[0,1,1,0,0,0],[0,79,193])]:
        record = row('Spell',ident)
        record[4:12],record[71:74],record[86:92],record[95:98] = attrs,effects,targets,auras
    return data


base.stores = stores
