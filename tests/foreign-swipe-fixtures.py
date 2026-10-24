"""Fixed stock Swipe ranks in synthetic books; no private character data."""
import json
from pathlib import Path
RULES=json.loads((Path(__file__).resolve().parents[1]/'lib/cleanup_foreign_swipe_catalog.json').read_text())
CHAIN=RULES['tc']['779']['chain']

def extend(data,profile):
    for spell,entry in RULES['tc'].items():
        spell=int(spell);row=[0]*len(profile['stores']['Spell']['columns']);row[0]=spell
        for i,v in entry['mechanics'].items():row[int(i)]=v
        data['Spell'][spell]=row
        for ident in list(data['SkillLineAbility']):
            if data['SkillLineAbility'][ident][2]==spell:del data['SkillLineAbility'][ident]
        for ability in entry['abilities']:data['SkillLineAbility'][ability[0]]=ability.copy()
    if 5487 not in data['Spell']:
        row=[0]*len(profile['stores']['Spell']['columns']);row[0]=5487;data['Spell'][5487]=row
    row=[0]*len(profile['stores']['SkillLine']['columns']);row[0]=134;row[1]=7;data['SkillLine'][134]=row
    for ident in list(data['SkillRaceClassInfo']):
        if data['SkillRaceClassInfo'][ident][1]==134:del data['SkillRaceClassInfo'][ident]
    for row in RULES['tc_skill_info']:data['SkillRaceClassInfo'][row[0]]=row.copy()
    return data
