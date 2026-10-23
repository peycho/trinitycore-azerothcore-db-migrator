"""Opt-in retirement of an unselected Shaman Dual Wield spell AND skill.

Skill 118 independently regrants 674. Never use this contract for other classes,
selected builds, occupied off-hands or a spell-only deletion.
"""
from collections import defaultdict
from cleanup_console import fail
from spells import Unsupported

POLICY = 'tc-unselected-shaman-dual-wield-skill-retirement-v1'
POLICIES = (POLICY,)
ACK = 'RETIRE_UNSELECTED_SHAMAN_SPELL_AND_SKILL_EMPTY_OFFHAND'


def contract(meta):
    shapes = {674: {4:80,28:1,35:101,46:1,68:4294967295,71:40,86:1},
              30798: {4:159646096,5:2147483648,28:1,35:101,46:1,68:4294967295,71:36,86:1,116:674}}
    for s, values in shapes.items():
        row = meta.spells.get(s, [])
        if len(row)<212 or any(row[i] != values.get(i,0) for i in (*range(4,131),*range(208,212))):return False
        if (meta.predecessors(s) or meta.requires[s] or meta.prerequisite_users[s]
                or meta.scripts[s] or meta.aura_owners[s] or s in meta.world_aura_owners
                or s in meta.additional or s==30798 and s in meta.trainer_taught):return False
        try:meta.check_spell(s)
        except Unsupported:return False
    # Shared 674 is offered by ordinary class trainers in AC. Trainer lists
    # do not execute at login; only the exact talent parent must be absent.
    talent = meta.talent_rows.get(30798, [])
    if (meta.talents.get(30798)!=(1690,1) or 674 in meta.talents
            or talent != [1690,263,6,1,30798,0,0,0,0,0,0,0,0,616,0,0,0,0,0,0,0,0,0]
            or meta.stores['TalentTab'].get(263,[0]*21)[20]!=64
            or meta.learns[30798]!=[(674,True,True)] or meta.effect_learns[30798]!=[(674,True,True)]
            or meta.learns[674] or meta.effect_learns[674] or meta.learn_parents[30798]
            or set(meta.learn_parents[674])!={30798} or set(meta.talent_learn_owners.get(674,()))!={30798}
            or meta.skill_effect(674)!=(118,1,1,1)
            or meta.abilities[674]!=[[610,118,674,0,109,0,0,1,0,2,0,0,0,0]]
            or meta.abilities[30798]!=[[14446,373,30798,0,64,0,0,1,0,0,0,0,0,0]]
            or meta.stores['SkillLine'].get(118,[0,0])[1]!=6):return False
    infos = [r for r in meta.stores['SkillRaceClassInfo'].values() if r[1]==118 and r[3]&64]
    if infos != [[883,118,32767,64,402,0,0,0]]:return False
    # No alternate reward or cast wrapper may recreate the retired pair.
    if [r for r in meta.stores['SkillLineAbility'].values() if r[1]==118] != meta.abilities[674]:return False
    if any(s not in (674,30798) and (118 in row[110:113] or 674 in row[116:119] or 30798 in row[116:119])
           for s,row in meta.spells.items()):return False
    return True


def select(state,tc,ac,expected=None,*,preview=False,offhand,default_skills):
    books, talents, skills = defaultdict(dict), defaultdict(list), defaultdict(dict)
    for g,s,a,d in state['character_spell']:books[g][s]=(a,d)
    for g,s,k in state['character_talent']:talents[g].append((s,k))
    for g,s,v,m in state['character_skills']:skills[g][s]=(v,m)
    selected, excluded, proofs = [], [], []
    valid_metadata = contract(tc) and contract(ac)
    for g,race,cls,level,active,groups,online,flags in state['characters']:
        if cls!=7 or 674 not in books[g]:continue
        reason=None
        if flags&4:reason='DEFER_PENDING_NATIVE_RESET'
        elif online or race not in (2,6,11) or not 1<=level<=80 or groups not in (1,2) or active not in range(groups):
            reason='DEFER_SHAMAN_CHARACTER_STATE'
        elif not valid_metadata:reason='DEFER_SHAMAN_NATIVE_CONTRACT'
        else:
            seen=set()
            for s,k in talents[g]:
                identity=tc.talents.get(s)
                tab=tc.stores['TalentTab'].get(tc.talent_rows[s][1],[]) if identity else []
                key=(identity[0] if identity else -1,k)
                if (not identity or ac.talents.get(s)!=identity or s in tc.invalid_talents or s in ac.invalid_talents
                        or ac.talent_rows.get(s)!=tc.talent_rows[s] or len(tab)<21 or not tab[20]&64
                        or ac.stores['TalentTab'].get(tc.talent_rows[s][1],[0]*21)[20]!=tab[20]
                        or k not in range(groups) or key in seen):
                    reason='DEFER_SHAMAN_TALENT_STATE';break
                seen.add(key)
            if reason is None:
                if any(s==30798 for s,_ in talents[g]) or 30798 in books[g]:reason='DEFER_SELECTED_OR_STORED_DUAL_WIELD_TALENT'
                elif any(s!=674 and any(40 in m.spells.get(s,[0]*74)[71:74] or
                        any(m.spells.get(s,[0]*119)[71+i]==44 and m.spells[s][110+i]==118 for i in range(3))
                        for m in (tc,ac)) for s in books[g]):reason='DEFER_ALTERNATE_DUAL_WIELD_SKILL_ANCHOR'
                elif books[g][674]!=(1,0):reason='DEFER_SHAMAN_SPELL_FLAGS'
                elif skills[g].get(118)!=(1,level*5):reason='DEFER_SHAMAN_NATIVE_SKILL_STATE'
                elif g in offhand:reason='DEFER_OCCUPIED_OFFHAND'
                elif default_skill_blocks(default_skills,race):reason='DEFER_NATIVE_DEFAULT_SKILL_ROUTE'
        if reason:
            excluded.append((g,674,reason));continue
        selected.append((g,674,1,0))
        proofs.append({'guid':g,'retired_spell':674,'retired_skill':[118,*skills[g][118]],
                       'selected_talent_30798':False,'offhand':'EMPTY_FRESH_LIVE_QUERY',
                       'native_reward_mask':109,'shaman_class_bit':64,'spell_only_repair_safe':False})
    if not preview and expected!=len(selected):
        fail('SHAMAN_SELECTION_MISMATCH',f'Expected {expected} selected spell/skill pairs; reviewed selection is {len(selected)}')
    summary={'reviewed_candidate_rows':len(selected)+len(excluded),'selected_rows':len(selected),
             'selected_characters':len(selected),'selected_groups':len(selected),'selected_direct_rows':0,
             'selected_related_rows':len(selected),'enabled_rows_removed':len(selected),'disabled_rows_removed':0,
             'skill_rows_changed':len(selected),'skill_rows_removed':len(selected),'spell_rows_inserted':0,
             'deferred_candidate_rows':len(excluded),'eligibility_proofs':proofs,
             'native_policy':'Retire paired enabled 674 and native skill 118 only for unselected Shamans with empty off-hand; both builds, every other skill, all inventory/items and login flags preserved; no grants'}
    return selected,excluded,[],summary,[]


def inventory(settings,context):
    from cleanup_plans import metadata, require_shape, snapshot
    meta=metadata(settings,['character_inventory'])
    require_shape(meta,'character_inventory',{'guid','bag','slot','item'})
    source=settings.schemas['characters']
    guids=sorted(r[0] for r in context['characters'] if r[2]==7)
    ids=','.join(map(str,guids)) or '0'
    rows=snapshot(settings,[('offhand',f'SELECT JSON_ARRAY(guid,bag,slot,item) row_value FROM `{source}`.character_inventory '
                           f'WHERE guid IN ({ids}) AND bag=0 AND slot=16 ORDER BY guid,item LIMIT 40001')])['offhand']
    if len(rows)>40000:fail('SHAMAN_INVENTORY_BOUND','Too many off-hand rows')
    return meta, rows


def inventory_guard(source,meta):
    from cleanup_plans import planner
    return f"""IF (SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA='{source}'
 AND TABLE_NAME='character_inventory' AND ENGINE='InnoDB' AND TABLE_TYPE='BASE TABLE')<>1
 OR (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA='{source}' AND TABLE_NAME='character_inventory')<>{len(meta['columns'])}
 OR NOT ((SELECT SHA2(GROUP_CONCAT(CONCAT_WS(':',TABLE_NAME,COLUMN_NAME,COLUMN_TYPE,IS_NULLABLE,COLUMN_KEY,EXTRA,
 COALESCE(GENERATION_EXPRESSION,''),ORDINAL_POSITION) ORDER BY BINARY TABLE_NAME,ORDINAL_POSITION SEPARATOR '|'),256)
 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA='{source}' AND TABLE_NAME='character_inventory')<=>'{planner.key_hash(meta['columns'])}') THEN
 SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Shaman inventory layout or engine changed'; END IF;
 IF EXISTS(SELECT 1 FROM `{source}`.character_inventory i JOIN affected g ON g.guid=i.guid WHERE i.bag=0 AND i.slot=16) THEN
 SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Shaman off-hand must remain empty; no item relocation is authorized'; END IF;
"""


def defaults(settings):
    """Seal both native starting-skill tables; defaults can re-add absent skills."""
    from copy import copy
    from cleanup_plans import metadata, snapshot, require_shape
    from cleanup_active_reset import exact_hex
    result={}
    for core,schema in (('tc',settings.schemas['world']),('ac',settings.ini.get('target','world'))):
        view=copy(settings);view.schemas={**settings.schemas,'characters':schema}
        meta=metadata(view,['playercreateinfo_skills'])
        require_shape(meta,'playercreateinfo_skills',{'raceMask','classMask','skill','rank'})
        fields=[r[1] for r in meta['columns']]
        if any(r[2].split('(')[0].split()[0] not in ('int','smallint','tinyint','mediumint')
               for r in meta['columns'] if r[1] in ('raceMask','classMask','skill','rank')):
            fail('SHAMAN_DEFAULT_METADATA','Starting-skill masks/identifiers must be native integers')
        # Comments/custom columns remain part of the full exact world digest.
        hashed="SHA2(CONCAT_WS('|',"+','.join(f"IFNULL({exact_hex('`'+r[1]+'`',r[2])},'N')" for r in meta['columns'])+'),256)'
        original_sql=settings.sql
        def bounded(query,*a,**kw):return original_sql("SET SESSION group_concat_max_len=6400001; SET SESSION time_zone='+00:00';\n"+query,*a,**kw)
        settings.sql=bounded
        try:
            captured=snapshot(settings,[('rows',f"SELECT JSON_ARRAY({','.join('`'+f+'`' for f in fields)}) row_value FROM `{schema}`.playercreateinfo_skills LIMIT 10001"),
            ('digests',f"SELECT JSON_ARRAY('playercreateinfo_skills',COUNT(*),SHA2(COALESCE(GROUP_CONCAT({hashed} ORDER BY BINARY {hashed} SEPARATOR ''),''),256)) row_value FROM `{schema}`.playercreateinfo_skills")])
        finally:
            settings.sql=original_sql
        if len(captured['rows'])>10000 or captured['digests'][0][1]!=len(captured['rows']):
            fail('SHAMAN_DEFAULT_BOUND','Starting-skill metadata exceeds 10000 rows')
        if metadata(view,['playercreateinfo_skills'])!=meta:fail('SHAMAN_DEFAULT_DRIFT','Starting-skill schema changed')
        layout={'columns':[[r[0],r[1],r[2],r[3],r[7],r[5]]for r in meta['columns']], 'tables':meta['tables']}
        result[core]={'schema':schema,'layout':layout,'rows':{'playercreateinfo_skills':sorted(captured['rows'],key=repr)},'digests':captured['digests']}
    return result


def default_skill_blocks(capture,race):
    for world in capture.values():
        fields=[r[1] for r in world['layout']['columns']]
        for row in world['rows']['playercreateinfo_skills']:
            r=dict(zip(fields,row))
            if r['skill']==118 and (not r['classMask'] or r['classMask']&64) and (not r['raceMask'] or r['raceMask']&(1<<(race-1))):return True
    return False
