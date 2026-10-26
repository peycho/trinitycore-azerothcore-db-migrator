"""Reconstruct four absent native racial skills from existing legitimate spells.

A skill can restore its exact native racial rewards at login. This is explicit
availability repair, never permission to add a foreign racial or change talents.
"""
from collections import defaultdict
import json
from cleanup_console import ROOT, PROFILE, fail, sha
from cleanup_talent_relations import MAX_ROWS, validate_stored
from spells import Unsupported

POLICY='tc-known-racial-native-skills-v5'
ACK='RESTORE_FIXED_NATIVE_RACIAL_SKILLS_AND_STOCK_REWARDS'
CATALOG=ROOT/'lib/cleanup_racial_skill_catalog.json'


def native_sources(paths):
    names=('src/server/game/Entities/Player/Player.cpp','src/server/game/Entities/Unit/Unit.h',
           'src/server/game/Globals/ObjectMgr.cpp')
    result={}
    for core,prefix in (('tc','trinitycore'),('ac','azerothcore')):
        manifest={n.strip():h for h,n in (line.split(None,1)for line in (PROFILE/(prefix+'-semantic.sha256')).read_text().splitlines())}
        result[core]={}
        for name in names:
            if sha(paths[core+'_source']/name)!=manifest[name]:
                fail('RACIAL_SKILL_NATIVE_DRIFT','Native racial skill/reward consumer differs: '+core+':'+name)
            result[core][name]=manifest[name]
    return result


def contract(meta,skill,rules):
    rule=rules[meta.core][str(skill)]
    abilities=sorted(r for r in meta.stores['SkillLineAbility'].values()if r[1]==skill)
    infos=sorted(r for r in meta.stores['SkillRaceClassInfo'].values()if r[1]==skill)
    if (meta.stores['SkillLine'].get(skill,[0,0])[1]!=rule['category'] or rule['category']!=9
            or abilities!=rule['abilities'] or infos!=rule['infos'] or not infos
            or any(not r[4]&0x10 or r[5]or r[6]for r in infos)):
        return False
    for key,expected in rule['spells'].items():
        spell=int(key);r=meta.spells.get(spell,[])
        if (len(r)<212 or any(r[i]!=expected['mechanics'].get(str(i),0)for i in (*range(4,131),*range(208,212)))
                or list(meta.chain(spell))!=expected['chain'] or expected['chain']!=[spell]
                or sorted(meta.scripts[spell])!=expected['scripts']
                or any(meta.script_policy.get(name)!='NO_SPELLBOOK_MUTATION'for name in meta.scripts[spell])
                or sorted(meta.requires[spell])!=expected['requires'] or expected['requires']
                or sorted(meta.prerequisite_users[spell])!=expected['prerequisite_users'] or expected['prerequisite_users']
                or sorted(meta.learn_parents[spell])!=expected['learn_parents']
                or [list(x)for x in meta.learns[spell]]!=expected['learns']
                or [list(x)for x in meta.effect_learns[spell]]!=expected['effect_learns']
                or spell in meta.talents or meta.talent_learn_owners.get(spell)
                or meta.aura_owners.get(spell)or spell in meta.world_aura_owners or spell in meta.additional
                or meta.skill_effect(spell)or set(r[71:74])&{40,44,47,118}):return False
        try:meta.check_spell(spell)
        except Unsupported:return False
    return True


def rewards(meta,skill,race,cls,value):
    return {a[2]for a in meta.stores['SkillLineAbility'].values()if a[1]==skill and a[9]==2 and a[7]<=value
            and(not a[3]or a[3]&(1<<(race-1)))and(not a[4]or a[4]&(1<<(cls-1)))}


def select(state,tc,ac):
    validate_stored(state['character_spell'])
    if not 1<=len(state['characters'])<=40000 or sum(map(len,state.values()))>MAX_ROWS:
        fail('RACIAL_SKILL_BOUND','Captured scope exceeds reviewed bounds')
    rules=json.loads(CATALOG.read_text());books=defaultdict(dict);skills=defaultdict(dict)
    chars={r[0]:r for r in state['characters']}
    for g,s,a,d in state['character_spell']:
        if g not in chars:fail('RACIAL_SKILL_INPUT','Out-of-scope spell')
        books[g][s]=(a,d)
    for g,s,v,m in state['character_skills']:
        if g not in chars:fail('RACIAL_SKILL_INPUT','Out-of-scope skill')
        skills[g][s]=(v,m)
    safe={int(s):all(contract(m,int(s),rules)for m in (tc,ac))for s in rules['anchors']}
    selected,excluded,proof=[],[],[]
    for g,race,cls,level,active,groups,online,flags in state['characters']:
        added=0
        for key,anchors in sorted(rules['anchors'].items(),key=lambda x:int(x[0])):
            skill=int(key);known=[s for s in anchors if books[g].get(s)==(1,0)]
            if skill in skills[g]or not known:continue
            reason='';eligible=[];reward=set()
            if race not in(1,2,3,4,5,6,7,8,10,11)or cls not in(1,2,3,4,5,6,7,8,9,11)or not 1<=level<=80 or groups not in(1,2)or not 0<=active<groups:
                reason='DEFER_RACIAL_SKILL_CHARACTER_STATE'
            elif online:reason='DEFER_ONLINE_CHARACTER'
            elif len(skills[g])+added+1>127:reason='DEFER_NATIVE_SKILL_SLOT_LIMIT'
            elif not safe[skill]:reason='DEFER_RACIAL_SKILL_METADATA'
            else:
                value=level*5
                pair=[]
                for meta in(tc,ac):
                    infos=[r for r in meta.stores['SkillRaceClassInfo'].values()if r[1]==skill
                           and(not r[2]or r[2]&(1<<(race-1)))and(not r[3]or r[3]&(1<<(cls-1)))]
                    if len(infos)!=1:reason='DEFER_FOREIGN_RACIAL_SKILL';break
                    pair.append(rewards(meta,skill,race,cls,value))
                if not reason and(pair[0]!=pair[1]or not pair[0]):reason='DEFER_RACIAL_REWARD_MISMATCH'
                if not reason:
                    reward=pair[0];eligible=sorted(set(known)&reward)
                    if not eligible:reason='DEFER_FOREIGN_RACIAL_ANCHOR'
                    elif any(s in books[g]and books[g][s]!=(1,0)for s in reward):reason='DEFER_STORED_RACIAL_FLAGS'
                    elif any(child not in reward for m in(tc,ac)for s in reward for child,_,_ in m.learns[s]+m.effect_learns[s]):
                        reason='DEFER_RACIAL_DEPENDENCY'
            if reason:excluded.append((g,skill,reason));continue
            selected.append((g,skill,value,value));added+=1
            proof.append({'guid':g,'skill':skill,'value':value,'cap':value,'original':'ABSENT','action':'INSERT',
                'level':level,'race':race,'class':cls,'anchors':eligible,'native_reward_spells':sorted(reward),
                'missing_native_reward_spells':sorted(reward-set(books[g])),'pending_native_reset_preserved':bool(flags&4),
                'reset_executed':False,'sql_spell_rows_inserted':0,'native_policy':'RACIAL_ALWAYS_MAX_LEVEL_TIMES_FIVE'})
    return sorted(selected),sorted(excluded),proof
