"""Public fixed stock racial assets; contains no character snapshot data."""
import json
from pathlib import Path
RULES=json.loads((Path(__file__).resolve().parents[1]/'lib/cleanup_racial_skill_catalog.json').read_text())


def extend(data,profile):
    for key,rule in RULES['tc'].items():
        skill=int(key)
        row=[0]*len(profile['stores']['SkillLine']['columns']);row[:2]=[skill,9];data['SkillLine'][skill]=row
        for ident in list(data['SkillRaceClassInfo']):
            if data['SkillRaceClassInfo'][ident][1]==skill:del data['SkillRaceClassInfo'][ident]
        for r in rule['infos']:data['SkillRaceClassInfo'][r[0]]=r.copy()
        for ident in list(data['SkillLineAbility']):
            if data['SkillLineAbility'][ident][1]==skill:del data['SkillLineAbility'][ident]
        for r in rule['abilities']:data['SkillLineAbility'][r[0]]=r.copy()
        for ident,entry in rule['spells'].items():
            row=[0]*len(profile['stores']['Spell']['columns']);row[0]=int(ident)
            for i,value in entry['mechanics'].items():row[int(i)]=value
            data['Spell'][int(ident)]=row
    return data
