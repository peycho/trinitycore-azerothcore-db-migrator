"""Explicit preparation exception: insert absent native bookkeeping skills only."""
from collections import Counter, defaultdict
import hashlib
import json
import re
import uuid

from cleanup_console import ROOT, PROFILE, fail, sha, verify
from cleanup_plans import finish, metadata, planner, render, require_shape, sha_json
from cleanup_active_reset import TABLES, KEYS
from cleanup_disabled_history import aggregate, check_sets, read_world
from cleanup_trained_history import inspection
from cleanup_migration_evidence import FIELDS
from cleanup_plans import snapshot
from spells import Unsupported

POLICY = 'tc-missing-native-skills-v1'
ANCHORS = {183:{2382:(25,60,0),63644:(162,0,0),63645:(162,0,0)},
           776:{53428:(47,0,0),53341:(53,3,0),53343:(53,3,0)}}
NAMES = {'generic':183,'runeforging':776}


def select(state, effective, requested):
    """Known enabled anchors authorize only the exact native missing skill row."""
    chosen = {NAMES[name] for name in requested}
    chars = {r[0]:r for r in state['characters']}
    books,skills = defaultdict(dict),defaultdict(dict)
    for g,s,a,d in state['character_spell']:
        books[g][s]=(a,d)
    for g,s,v,m in state['character_skills']:
        skills[g][s]=(v,m)
    selected,excluded,proof = [],[],[]
    for guid,c in sorted(chars.items()):
        _,race,cls,level,active,groups,online,login = c
        for skill in sorted(chosen):
            if skill in skills[guid]:
                continue  # Existing rows, including malformed rows, are never changed.
            anchors = sorted(set(books[guid]) & ANCHORS[skill].keys())
            if not anchors:
                continue
            reason = ''
            if cls not in (1,2,3,4,5,6,7,8,9,11) or not 1<=race<=32 or not 1<=level<=80 or groups not in (1,2) or not 0<=active<groups:
                reason='DEFER_NATIVE_SKILL_CHARACTER_STATE'
            elif online:
                reason='DEFER_ONLINE_CHARACTER'
            elif login & 4:
                reason='DEFER_PENDING_NATIVE_RESET'
            elif skill==776 and cls!=6:
                reason='DEFER_FOREIGN_CLASS_SKILL'
            valid=[]
            for anchor in anchors:
                if reason:
                    break
                flags=books[guid][anchor]
                if flags!=(1,0):
                    continue
                if anchor in (63644,63645) and groups!=2:
                    continue  # A switch button alone never establishes dual-spec ownership.
                record=effective.spells.get(anchor,[])
                if (not record or tuple(record[71:74])!=ANCHORS[skill][anchor]
                        or record[12] or record[20] or any(record[116:119])
                        or anchor in effective.talents or effective.chain(anchor)!=(anchor,)
                        or effective.skill_effect(anchor) is not None or effective.requires[anchor]):
                    reason='DEFER_NATIVE_SKILL_SPELL_CONTRACT';break
                try:
                    effective.check_spell(anchor)
                except Unsupported:
                    reason='DEFER_NATIVE_SKILL_SPELL_CONTRACT';break
                abilities=[r for r in effective.abilities[anchor] if r[1]==skill
                    and (not r[3] or r[3]&(1<<(race-1))) and (not r[4] or r[4]&(1<<(cls-1)))
                    and (r[9]==2 or skill==776 and r[10]==0)]
                infos=[r for r in effective.stores['SkillRaceClassInfo'].values() if r[1]==skill
                    and (not r[2] or r[2]&(1<<(race-1))) and (not r[3] or r[3]&(1<<(cls-1)))]
                line=effective.stores['SkillLine'].get(skill,[])
                if (not abilities or not infos or not line or line[1]!=(12 if skill==183 else 7)
                        or any(r[6] in effective.stores['SkillTiers'] for r in infos)
                        or any(r[6]!=0 for r in infos)
                        or (skill==183 and any(r[4]!=1170 for r in infos))
                        or (skill==776 and any(r[4]!=128 or r[3]!=32 for r in infos))):
                    reason='DEFER_NATIVE_SKILL_METADATA';break
                valid.append((anchor,sorted(r[0] for r in abilities),sorted(r[0] for r in infos)))
            if not reason and not valid:
                reason='DEFER_NO_ENABLED_NATIVE_SKILL_ANCHOR'
            if reason:
                excluded.append((guid,skill,reason));continue
            value=level*5 if skill==183 else 1
            selected.append((guid,skill,value,value))
            proof.append({'guid':guid,'skill':skill,'value':value,'cap':value,'original':'ABSENT',
                'level':level,'anchors':[{'spell':s,'flags':[1,0],'ability_ids':a,'race_class_ids':r} for s,a,r in valid],
                'native_policy':'ALWAYS_MAX_LEVEL_TIMES_FIVE' if skill==183 else 'DEATH_KNIGHT_MONO_1_1'})
    return selected,excluded,proof


def skill_cells(rows):
    grouped=defaultdict(list)
    for row in sorted(rows):
        # Native character_skills has exactly these four unsigned integer fields.
        value='|'.join(format(x,'X') for x in row)
        grouped[row[0]].append(hashlib.sha256(value.encode()).hexdigest())
    return [('character_skills',g,len(items),hashlib.sha256(''.join(items).encode()).hexdigest())
            for g,items in sorted(grouped.items())]


def plan_native_skills(settings,work,args,output):
    if (not args.preview and not 1<=(args.expect_rows or 0)<=10000) or len(set(args.skills))!=len(args.skills):
        fail('NATIVE_SKILL_SELECTION_MISMATCH','Select distinct skill policies and expect between 1 and 10000 insertions')
    if not args.migration_inspection:
        captures=sorted(p.name for p in (work.session/'inspections').glob('*-migration-blockers-*') if p.is_dir())
        if not captures:
            fail('MIGRATION_INSPECTION_REQUIRED','Capture a migration blocker context in this session first')
        args.migration_inspection=captures[-1]
    print('Using migration inspection: '+args.migration_inspection,flush=True)
    path,_,_,context,audit,captured_world,captured_layout,report=inspection(settings,work,args.migration_inspection)
    effective,world=read_world(settings)
    if world!=captured_world or effective.hashes!=report['dbc_sha256']:
        fail('NATIVE_SKILL_METADATA_DRIFT','Effective TC world/DBC differs from the captured migration context')
    selected,excluded,proof=select(context,effective,args.skills)
    summary={'selected_rows':len(selected),'by_skill':dict(Counter(r[1] for r in selected)),
             'deferred':dict(Counter(r[2] for r in excluded)),'scope_characters':len(context['characters'])}
    (work.operation/'native-skill-review.json').write_text(json.dumps({'summary':summary,'proofs':proof,'excluded':excluded},indent=2)+'\n')
    print('Native missing-skill review (read-only): '+json.dumps(summary,sort_keys=True),flush=True)
    if args.preview:
        print('PREVIEW: captured evidence only; no SQL package, active batch or source changes. Details: '+str(work.operation/'native-skill-review.json'),flush=True)
        return False
    if len(selected)!=args.expect_rows:
        fail('NATIVE_SKILL_SELECTION_MISMATCH',f'Expected {args.expect_rows} insertions; review selected {len(selected)} exact rows',
             'Inspect native-skill-review.json in this operation; no cleanup package or source changes were made.')
    source=settings.schemas['characters'];guids=sorted({r[0]for r in selected});guid_set=set(guids)
    meta=metadata(settings,TABLES)
    if dict(meta)!=captured_layout:
        fail('NATIVE_SKILL_SCHEMA_DRIFT','Source layout differs from captured context')
    for table in TABLES:
        shape=require_shape(meta,table,set(KEYS[table]))
        if {n for n,v in shape.items() if v[2]=='PRI'}!=set(KEYS[table]):
            fail('UNSUPPORTED_SCHEMA','Native primary keys required: '+table)
    if [r[1:5] for r in meta['columns'] if r[0]=='character_skills']!=[
        ['guid','int unsigned','NO','PRI'],['skill','smallint unsigned','NO','PRI'],
        ['value','smallint unsigned','NO',''],['max','smallint unsigned','NO','']]:
        fail('NATIVE_SKILL_SCHEMA_UNSUPPORTED','New skill rows require exactly the native four columns; custom skill columns need a reviewed default policy')
    if len(meta['columns'])>512 or any('on update'in r[5].lower()for r in meta['columns']):
        fail('UNSUPPORTED_COLUMN','Native skill repair requires at most 512 columns without automatic updates')
    scope=','.join(str(r[0])for r in context['characters']);selector=','.join(map(str,guids));queries=[]
    for table,fields in FIELDS.items():
        cols=','.join('`'+f+'`'for f in fields);order=','.join(KEYS[table])
        queries.append(('context_'+table,f'SELECT JSON_ARRAY({cols}) row_value FROM `{source}`.`{table}` WHERE guid IN ({scope}) ORDER BY {order} LIMIT 5000001'))
    for table in TABLES:
        query=aggregate(meta,table,source,f's.guid IN ({selector})')
        queries.append(('sets',f"SELECT JSON_ARRAY('{table}',guid,n,h) row_value FROM ({query}) a ORDER BY guid"))
    old_sql=settings.sql
    def bounded(query,*a,**kw):
        return old_sql("SET SESSION time_zone='+00:00';\nSET SESSION group_concat_max_len=6400001;\n"+query,*a,**kw)
    settings.sql=bounded
    try:
        live=snapshot(settings,queries)
    finally:
        settings.sql=old_sql
    # Capture order is guid/talentGroup/spell; the key hash uses guid/spell/group.
    if any(sorted(live['context_'+table])!=sorted(context[table])for table in FIELDS):
        fail('NATIVE_SKILL_INPUT_DRIFT','Complete captured semantic source state changed; capture a new blocker context')
    cells=sorted(tuple(r)for r in live['sets'])
    old_skills=[r for r in context['character_skills'] if r[0]in guid_set]
    if skill_cells(old_skills)!=[r for r in cells if r[0]=='character_skills']:
        fail('NATIVE_SKILL_INPUT_DRIFT','Native skill row fingerprints differ from captured numeric fields')
    after=skill_cells(old_skills+[list(r)for r in selected])
    counts={table:sum(r[2]for r in cells if r[0]==table)for table in TABLES}
    if counts['characters']!=len(guids) or sum(counts.values())>5000000 or any(r[2]>10000 or not re.fullmatch('[a-f0-9]{64}',str(r[3]))for r in cells+after):
        fail('NATIVE_SKILL_SNAPSHOT_BOUND','Full affected snapshots exceed safe bounds or lack valid digests')
    template=ROOT/'tools/native-skill-repair.sql.in';inspection_sha=sha(path/'SHA256SUMS')
    batch=sha_json({'policy':POLICY,'inspection':inspection_sha,'selected':selected,'proof':proof,'world':world,'metadata':meta,'template':sha(template),'id':output.name})
    archive='tc_native_skills_'+uuid.uuid4().hex[:20]
    blocks=check_sets(meta,source,archive,counts,changed_table='character_skills')
    values={'SOURCE':source,'ARCHIVE':archive,'UUID':work.current()['identity']['uuid'],'BATCH':batch,
        'AUDIT':report['source_state_sha256'],'COUNT':len(selected),'GUID_COUNT':len(guids),
        'EXPECTED_HASH':planner.key_hash(selected),'SNAPSHOT_COUNT':len(cells),'SNAPSHOT_HASH':planner.key_hash(cells),
        'COLUMN_COUNT':len(meta['columns']),'COLUMN_HASH':planner.key_hash(meta['columns']),
        'CONCAT_LIMIT':max(6400001,len(cells)*160,len(selected)*80,len(meta['columns'])*2048),
        'EXPECTED_INSERT':planner.insert_values('expected_skills',selected),'SNAPSHOT_INSERT':planner.insert_values('expected_snapshot',cells),
        'AFTER_INSERT':planner.insert_values('expected_after',after),'AFTER_COUNT':len(after),'AFTER_HASH':planner.key_hash(after),
        'COLUMN_INSERT':planner.insert_values('reviewed_columns',meta['columns']),'GUID_INSERT':planner.insert_values('affected',[(g,)for g in guids]),
        'CHECK_ORIGINAL':blocks['original'],'CHECK_ARCHIVE':blocks['archive'],'CHECK_APPLIED':blocks['applied'],
        'ARCHIVE_INSERT':'\n'.join(f'  INSERT INTO {table}_before SELECT s.* FROM `{source}`.{table} s JOIN affected g ON g.guid=s.guid;'for table in TABLES)}
    checks=[]
    for table,count,checksum in world['digests']:
        fields=[r[1]for r in world['layout']['columns']if r[0]==table]
        hashed="SHA2(CONCAT_WS('|',"+','.join(f"IFNULL(HEX(`{f}`),'N')"for f in fields)+'),256)'
        checks.append(f" IF (SELECT COUNT(*) FROM `{settings.schemas['world']}`.`{table}`)<>{count} OR NOT ((SELECT SHA2(COALESCE(GROUP_CONCAT({hashed} ORDER BY BINARY {hashed} SEPARATOR ''),''),256) FROM `{settings.schemas['world']}`.`{table}`)<=>'{checksum}') THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Native skill world input drift'; END IF;")
    values['WORLD_CHECKS']='\n'.join(checks)
    final_effective,final_world=read_world(settings)
    if metadata(settings,TABLES)!=meta or final_world!=world or final_effective.hashes!=effective.hashes or sha(path/'SHA256SUMS')!=inspection_sha:
        fail('NATIVE_SKILL_METADATA_DRIFT','Source metadata or sealed context changed while planning')
    verify(path)
    manifest={'policy':POLICY,'archive_schema':archive,'batch_key':batch,'selected_rows':len(selected),
        'affected_characters':len(guids),'character_guids':guids,'inspection_id':path.name,'inspection_sha256':inspection_sha,
        'audit_sha256':report['source_state_sha256'],'world_sha256':sha_json(world),'semantic_dbc_sha256':effective.hashes,
        'dbc_sha256':{name.removeprefix('tc.'):h for name,h in effective.hashes.items()},'metadata_profile_sha256':sha(PROFILE/'spell-metadata.json'),
        'expected_sha256':values['EXPECTED_HASH'],'template_sha256':sha(template),'archived_rows':counts,
        'requested_skills':args.skills,'skill_counts':summary['by_skill'],'excluded_rows':len(excluded),'excluded_reason_counts':summary['deferred'],
        'native_skill_proofs':proof,'skill_policy':'Insert absent reviewed native skill rows only; no updates to existing skills, no spell or talent changes'}
    status=f"SELECT * FROM `{archive}`.batch;\nSELECT e.*,s.value current_value,s.max current_cap FROM `{archive}`.expected_skills e LEFT JOIN `{source}`.character_skills s ON s.guid=e.guid AND s.skill=e.skill ORDER BY e.guid,e.skill;\n"
    tsv='guid\tskill\tnew_value\tnew_cap\n'+''.join('\t'.join(map(str,r))+'\n'for r in selected)
    finish(settings,work,output,manifest,render(template,values),tsv,status,'skill_cleanup_ack')
    # Extra diagnostics are part of the same sealed candidate, never an apply selection by themselves.
    from cleanup_console import seal
    (output/'excluded-rows.tsv').write_text('guid\tskill\treason_code\n'+''.join('\t'.join(map(str,r))+'\n'for r in excluded))
    (output/'native-skill-proof.json').write_text(json.dumps(proof,indent=2)+'\n');seal(output)
