"""Fixed stock racial metadata in synthetic books; no private character evidence."""
import json
from pathlib import Path
RULES=json.loads((Path(__file__).resolve().parents[1]/'lib/cleanup_racial_catalog.json').read_text())


def extend(data, profile):
    for spell, entry in RULES['tc'].items():
        spell=int(spell)
        row=[0]*len(profile['stores']['Spell']['columns']);row[0]=spell
        for i,v in entry['mechanics'].items():row[int(i)]=v
        data['Spell'][spell]=row
        for ident in list(data['SkillLineAbility']):
            if data['SkillLineAbility'][ident][2]==spell:del data['SkillLineAbility'][ident]
        for ability in entry['abilities']:data['SkillLineAbility'][ability[0]]=ability.copy()
    for skill, entry in RULES['skill_metadata']['tc'].items():
        skill=int(skill)
        row=[0]*len(profile['stores']['SkillLine']['columns']);row[0]=skill;row[1]=entry['category']
        data['SkillLine'][skill]=row
        for ident in list(data['SkillRaceClassInfo']):
            if data['SkillRaceClassInfo'][ident][1]==skill:del data['SkillRaceClassInfo'][ident]
        for row in entry['infos']:data['SkillRaceClassInfo'][row[0]]=row.copy()
    return data
