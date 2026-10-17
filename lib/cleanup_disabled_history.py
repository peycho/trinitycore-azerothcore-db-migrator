"""Archive only disabled, unselected direct talent history on a preparation copy."""
from collections import Counter, defaultdict
import csv
import io
import json
import re
import uuid

from cleanup_console import ROOT, PROFILE, fail, identifier, local_id, sha, verify, write_json
from cleanup_plans import finish, metadata, planner, ranks, require_shape, sha_json, snapshot
from cleanup_active_reset import TABLES, KEYS, columns, row_hash
from cleanup_spell_history import audit_inputs, classify
from spells import Metadata, Unsupported
import cleanup_talent_relations as relations

POLICY = 'tc-disabled-unselected-direct-talent-history-v1'
SCRIPT_POLICY = 'tc-disabled-reviewed-script-talent-history-v2'
POLICIES = (POLICY, SCRIPT_POLICY, relations.POLICY)
MAX_GUIDS, MAX_SELECTED, MAX_PER_GUID = 40000, 500000, 10000
WORLD = {'spell_ranks':['first_spell_id','spell_id','rank'],
         'spell_required':['spell_id','req_spell'],
         'spell_learn_spell':['entry','SpellID','Active'],
         'spell_script_names':['spell_id','ScriptName'],
         'spell_custom_attr':['entry','attributes'],
         'playercreateinfo_spell_custom':['racemask','classmask','Spell']}


def inspection(settings, work, inspection_id):
    path = work.session/'inspections'/local_id(inspection_id)
    contents = verify(path)
    required = {'inspection.json','input-state.json','spell-history.tsv','summary.tsv','README.md'}
    if set(contents) != required:
        fail('HISTORY_INSPECTION_INVALID','Expected a complete direct spell-history inspection')
    report = json.loads(contents['inspection.json'])
    state = json.loads(contents['input-state.json'])
    if (report.get('status') != 'COMPLETE_REVIEW_ONLY' or report.get('source_schema') != settings.schemas['characters']
            or report.get('source_uuid') != work.current()['identity']['uuid']
            or report.get('input_state_sha256') != sha_json(state)):
        fail('HISTORY_INSPECTION_INVALID','Inspection status, source or snapshot differs')
    _, audit, fingerprints, expected = audit_inputs(settings,work,report['audit'])
    if report.get('audit_files_sha256') != fingerprints:
        fail('HISTORY_INSPECTION_INVALID','Inspection references a different sealed audit')
    stores, _, dbc = ranks(settings)
    if report.get('dbc_sha256') != dbc:
        fail('DBC_DRIFT','Inspection DBC files differ')
    rows = classify(state,stores,expected)
    saved = list(csv.reader(io.StringIO(contents['spell-history.tsv'].decode()),delimiter='\t'))[1:]
    if saved != [[str(value) for value in row] for row in rows]:
        fail('HISTORY_INSPECTION_INVALID','Inspection dispositions differ from recomputed ownership')
    return path, report, state, rows, audit


def read_world(settings):
    """Capture effective TC input tables in one read-only consistent snapshot."""
    world = settings.schemas['world']
    names = ['spell_dbc', *WORLD]
    quoted = ','.join("'"+name+"'" for name in names)
    layout = snapshot(settings,[('columns',
        "SELECT JSON_ARRAY(TABLE_NAME,COLUMN_NAME,COLUMN_TYPE,IS_NULLABLE,ORDINAL_POSITION,EXTRA) row_value "
        f"FROM information_schema.COLUMNS WHERE TABLE_SCHEMA='{world}' AND TABLE_NAME IN ({quoted}) "
        "ORDER BY BINARY TABLE_NAME,ORDINAL_POSITION"),('tables',
        f"SELECT JSON_ARRAY(TABLE_NAME,ENGINE,TABLE_TYPE) row_value FROM information_schema.TABLES WHERE TABLE_SCHEMA='{world}' "
        f"AND TABLE_NAME IN ({quoted}) ORDER BY BINARY TABLE_NAME")])
    if sorted(layout['tables']) != sorted([[name,'InnoDB','BASE TABLE'] for name in names]):
        fail('HISTORY_WORLD_UNSUPPORTED','Required native TC world metadata tables must exist and use InnoDB')
    queries = []
    for table in names:
        fields = [identifier(row[1]) for row in layout['columns'] if row[0] == table]
        if not fields or len(fields) > 256:
            fail('HISTORY_WORLD_UNSUPPORTED','Missing or oversized TC world layout: '+table)
        expressions = ','.join('`'+name+'`' for name in fields)
        queries.append((table,f'SELECT JSON_ARRAY({expressions}) row_value FROM `{world}`.`{table}` LIMIT 100001'))
        hashed = 'SHA2(CONCAT_WS(\'|\','+','.join(f"IFNULL(HEX(`{name}`),'N')" for name in fields)+'),256)'
        queries.append(('digests',f"SELECT JSON_ARRAY('{table}',COUNT(*),SHA2(COALESCE(GROUP_CONCAT({hashed} "
                        f"ORDER BY BINARY {hashed} SEPARATOR ''),''),256)) row_value FROM `{world}`.`{table}`"))
    original_sql = settings.sql
    def bounded_sql(query, *args, **kwargs):
        return original_sql("SET SESSION time_zone='+00:00';\nSET SESSION group_concat_max_len=6400001;\n"+query,*args,**kwargs)
    settings.sql = bounded_sql
    try:
        state = snapshot(settings,queries)
    finally:
        settings.sql = original_sql
    if any(len(state[name]) > 100000 for name in names):
        fail('HISTORY_WORLD_UNSUPPORTED','TC world metadata exceeds the 100000-row per-table bound')
    if snapshot(settings,[('columns',
        "SELECT JSON_ARRAY(TABLE_NAME,COLUMN_NAME,COLUMN_TYPE,IS_NULLABLE,ORDINAL_POSITION,EXTRA) row_value "
        f"FROM information_schema.COLUMNS WHERE TABLE_SCHEMA='{world}' AND TABLE_NAME IN ({quoted}) "
        "ORDER BY BINARY TABLE_NAME,ORDINAL_POSITION"),('tables',
        f"SELECT JSON_ARRAY(TABLE_NAME,ENGINE,TABLE_TYPE) row_value FROM information_schema.TABLES WHERE TABLE_SCHEMA='{world}' "
        f"AND TABLE_NAME IN ({quoted}) ORDER BY BINARY TABLE_NAME")]) != layout:
        fail('SCHEMA_DRIFT','World metadata layout changed during planning')
    # Canonical multisets preserve duplicates and ignore physical row order.
    digests = sorted(state['digests'])
    if any(not isinstance(row[2],str) or not re.fullmatch('[a-f0-9]{64}',row[2]) for row in digests):
        fail('HISTORY_WORLD_UNSUPPORTED','World content digest could not be computed')
    state = {name:sorted(state[name],key=lambda row:json.dumps(row,separators=(',',':'))) for name in names}
    class CapturedWorld:
        def rows(self, label, query):
            if label == 'tc.spell_dbc.layout':
                return [[r[1],r[2],r[3],r[4]] for r in layout['columns'] if r[0] == 'spell_dbc']
            if label == 'tc.spell_dbc':
                return state['spell_dbc']
            fail('HISTORY_WORLD_UNSUPPORTED','Unexpected metadata query: '+label)
        def table(self, schema, table, fields, optional=False):
            actual = [r[1] for r in layout['columns'] if r[0] == table]
            positions = {name.lower():index for index,name in enumerate(actual)}
            if schema != world or table not in WORLD or not {name.lower() for name in fields} <= set(positions):
                fail('HISTORY_WORLD_UNSUPPORTED','Missing effective world fields: '+table)
            return [[row[positions[field.lower()]] for field in fields] for row in state[table]]
    profile = json.loads((PROFILE/'spell-metadata.json').read_text())
    try:
        effective = Metadata('tc',settings.paths['tc_dbc'],world,profile,CapturedWorld())
    except Unsupported as error:
        fail(error.reason,'TC history metadata: '+str(error))
    fields = [row[1].lower() for row in layout['columns'] if row[0]=='playercreateinfo_spell_custom']
    if not set(name.lower() for name in WORLD['playercreateinfo_spell_custom'])<=set(fields):
        fail('HISTORY_WORLD_UNSUPPORTED','Missing native custom starting-spell fields')
    effective.history_default_spells = {int(row[fields.index('spell')]) for row in state['playercreateinfo_spell_custom']}
    return effective, {'layout':dict(layout),'rows':state,'digests':digests}


def check_metadata(settings, manifest):
    settings.check_paths()
    if sha(PROFILE/'spell-metadata.json') != manifest.get('metadata_profile_sha256'):
        fail('HISTORY_METADATA_DRIFT','Spell metadata policy differs from the reviewed batch')
    for key,entry in manifest.get('core_compatibility',{}).items():
        if settings.compatibility.get(key,{}).get('manifest_sha256') != entry.get('manifest_sha256'):
            fail('CORE_PROFILE_MISMATCH','Core compatibility manifests differ from the reviewed history batch')
    effective, world = read_world(settings)
    if sha_json(world) != manifest.get('world_sha256') or effective.hashes != manifest.get('semantic_dbc_sha256'):
        fail('HISTORY_METADATA_DRIFT','Effective TC world/DBC metadata differs from this reviewed history batch')


def script_bindings(effective):
    """Review every direct-family binding against the protected TC contract.

    The broader reconstruction checker also supports runtime aura helpers and
    cast-only research spells. Neither contract authorizes history cleanup.
    Only the existing NO_SPELLBOOK_MUTATION contract is eligible here.
    """
    bindings = []
    for spell, (family, _) in sorted(effective.talents.items()):
        for name in sorted(effective.scripts[spell]):
            reason = ''
            if effective.script_policy.get(name) != 'NO_SPELLBOOK_MUTATION':
                reason = 'UNREVIEWED_HISTORY_SCRIPT'
            else:
                try:
                    effective.check_script(spell, name)
                except Unsupported as error:
                    reason = error.reason
            bindings.append((family, spell, name, reason))
    return bindings


def check_retained_scripts(state, effective):
    # Review the passive/direct talent parents which TC can cast while loading.
    # The same protected script checker is used by semantic reconstruction.
    parents = {spell for _,spell,_ in state['talents']}
    parents.update(row[0] for row in state.get('enabled_ids',[]))
    for spell in sorted(parents):
        try:
            for name in sorted(effective.scripts[spell]):
                effective.check_script(spell,name)
        except Unsupported as error:
            fail(error.reason,'Selected talent script needs review before history cleanup: '+str(error))


def select(rows, state, effective, expected_review_rows, include_reviewed_scripts=False):
    candidates = [row for row in rows if row[9] == 'REVIEW_DISABLED_NO_SELECTED_FAMILY']
    if not 1 <= expected_review_rows <= MAX_SELECTED or len(candidates) != expected_review_rows:
        fail('HISTORY_SELECTION_MISMATCH','--expect-review-rows must equal the inspection disabled/no-selected-family total')
    enabled_families = set()
    for guid, spell, _, disabled in state['spells']:
        if not disabled and spell in effective.talents:
            enabled_families.add((guid,effective.talents[spell][0]))
    check_retained_scripts(state,effective)
    incoming = {child for links in (effective.learns,effective.effect_learns) for values in links.values()
                for child,_,_ in values}
    # An alternate skill/default learning route needs a separate representation
    # decision, even though disabled AddSpell itself returns before effects.
    skill_rewards = {spell for spell, abilities in effective.abilities.items()
                     if any(row[9] in (1,2) for row in abilities)}
    families = defaultdict(set)
    for spell,(family,_) in effective.talents.items():
        families[family].add(spell)
    bindings = script_bindings(effective) if include_reviewed_scripts else []
    rejected_scripts = {family for family, _, _, reason in bindings if reason}
    required_parents = {parent for parents in getattr(effective,'requires',{}).values() for parent in parents}
    family_exclusions = {}
    for family,members in families.items():
        if members & incoming:
            family_exclusions[family] = 'DEFER_INDEPENDENT_LEARN_ROUTE'
        elif members & skill_rewards:
            family_exclusions[family] = 'DEFER_SKILL_REWARD_ROUTE'
        elif members & getattr(effective,'history_default_spells',set()):
            family_exclusions[family] = 'DEFER_CUSTOM_DEFAULT_ROUTE'
        elif (members & required_parents or any(effective.learns[spell] or effective.effect_learns[spell] for spell in members)):
            family_exclusions[family] = 'DEFER_TALENT_DEPENDENCIES'
        elif any(effective.scripts[spell] for spell in members) and (not include_reviewed_scripts or family in rejected_scripts):
            family_exclusions[family] = 'DEFER_SCRIPTED_TALENT_FAMILY'
        elif hasattr(effective,'spells') and any(set(effective.spells[spell][71:74]) & {44,47,118} for spell in members):
            family_exclusions[family] = 'DEFER_TALENT_SKILL_EFFECT'
    selected, excluded = [], []
    for row in candidates:
        guid, spell, active, disabled = row[:4]
        family = effective.talents.get(spell,(None,None))[0]
        chain = effective.chain(spell)
        reason = None
        if (disabled != 1 or active not in (0,1) or spell in effective.invalid_talents
                or family != row[10] or effective.talents.get(spell) != (row[10],row[11])):
            reason = 'DEFER_EFFECTIVE_TALENT_IDENTITY'
        elif any(member not in effective.talents or effective.talents[member][0] != family for member in chain):
            reason = 'DEFER_MIXED_RANK_CHAIN'
        elif (guid,family) in enabled_families:
            reason = 'DEFER_ENABLED_FAMILY_SPELL'
        elif family in family_exclusions:
            reason = family_exclusions[family]
        if reason:
            excluded.append((guid,spell,reason))
        else:
            selected.append((guid,spell,active,disabled))
    if not selected:
        fail('HISTORY_NO_ELIGIBLE_ROWS','No disabled direct talent history rows satisfy this policy')
    if len({row[0] for row in selected}) > MAX_GUIDS:
        fail('HISTORY_SNAPSHOT_BOUND','Affected character count exceeds 40000; use a separately scoped policy')
    return selected,excluded


def aggregate(meta, table, database, scope, alias='s'):
    keys = ','.join(f'{alias}.`{name}`' for name in KEYS[table])
    size = '+'.join(f'COALESCE(OCTET_LENGTH({alias}.`{name}`),0)' for name in columns(meta,table))
    hashed = f'IF(({size})<=1048576,{row_hash(meta,table,alias)},NULL)'
    return (f'SELECT {alias}.guid,COUNT(*) n,IF(COUNT({hashed})=COUNT(*),SHA2(GROUP_CONCAT({hashed} '
            f'ORDER BY {keys} SEPARATOR \'\'),256),NULL) h FROM `{database}`.`{table}` {alias} '
            f'WHERE {scope} GROUP BY {alias}.guid')


def enabled_ids_query(source):
    return (f'SELECT JSON_ARRAY(spell) row_value FROM (SELECT DISTINCT spell FROM `{source}`.character_spell '
            'WHERE disabled=0) enabled_spells ORDER BY spell')


def check_sets(meta, source, archive, counts):
    blocks = {}
    for phase in ('original','archive','applied'):
        lines = []
        for table in TABLES:
            db = archive if phase == 'archive' else source
            actual_table = table+'_before' if phase == 'archive' else table
            query = aggregate(meta,table,db,'s.guid IN (SELECT guid FROM affected)')
            if phase == 'archive':
                query = query.replace(f'`{db}`.`{table}`',f'`{db}`.`{actual_table}`')
            expected = 'expected_snapshot'
            if phase == 'applied' and table == 'character_spell':
                expected = 'expected_after'
            lines.append(f''' IF (SELECT COUNT(*) FROM `{db}`.`{actual_table}` s WHERE s.guid IN (SELECT guid FROM affected))<>
     (SELECT COALESCE(SUM(row_count),0) FROM {expected} WHERE table_name='{table}')
 OR EXISTS(SELECT 1 FROM {expected} e LEFT JOIN ({query}) a ON a.guid=e.guid
     WHERE e.table_name='{table}' AND (a.guid IS NULL OR a.n<>e.row_count OR NOT (BINARY a.h<=>BINARY e.row_hash))) THEN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='{phase} {table} full-row fingerprint differs';
 END IF;''')
            if phase == 'archive':
                lines.append(f''' IF (SELECT COUNT(*) FROM `{db}`.`{actual_table}`)<> {counts[table]} THEN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Unexpected rows in {table} archive'; END IF;''')
        blocks[phase] = '\n'.join(lines)
    return blocks


def plan_history(settings, work, args, output):
    path, report, state, rows, audit = inspection(settings,work,args.inspection)
    inspection_sha = sha(path/'SHA256SUMS')
    print('Reviewing effective TC world/DBC learning routes (read-only)',flush=True)
    effective, world = read_world(settings)
    state['enabled_ids'] = snapshot(settings,[('ids',enabled_ids_query(settings.schemas['characters']))])['ids']
    include_relations = getattr(args,'include_inert_relations',False)
    include_scripts = getattr(args,'include_reviewed_scripts',False) or include_relations
    policy = relations.POLICY if include_relations else SCRIPT_POLICY if include_scripts else POLICY
    relation_rows,relation_proof,relation_summary,relation_edges = [],[],{},[]
    if include_relations:
        review_guids = sorted({r[0] for r in rows if r[9]=='REVIEW_DISABLED_NO_SELECTED_FAMILY'})
        if not review_guids or len(review_guids)>MAX_GUIDS:
            fail('HISTORY_RELATION_BOUND','No review characters or more than 40000 characters')
        print('Reviewing complete related spell state per character (read-only)',flush=True)
        relation_rows = snapshot(settings,[('rows',relations.stored_query(settings.schemas['characters'],review_guids))])['rows']
        check_retained_scripts(state,effective)
        selected,excluded,relation_proof,relation_summary,relation_edges = relations.select(
            rows,state,effective,relation_rows,args.expect_review_rows)
    else:
        selected, excluded = select(rows,state,effective,args.expect_review_rows,include_scripts)
    bindings = script_bindings(effective) if include_scripts else []
    if include_relations:
        bindings = sorted(set(bindings) | {(family,spell,name,'') for _,family,spell,*_ in relation_proof
                                         for name in effective.scripts[spell]})
    selected_families = {effective.talents[row[1]][0] for row in selected if row[1] in effective.talents}
    reviewed = [row[:3] for row in bindings if row[0] in selected_families]
    scripted_families = {entry[0] for entry in reviewed}
    guids = sorted({row[0] for row in selected})
    guid_set = set(guids)
    print(f'Fingerprinting complete spell/talent/skill/character state for {len(guids)} characters (read-only)',flush=True)
    selector = ','.join(map(str,guids))
    source = settings.schemas['characters']
    meta = metadata(settings,TABLES)
    inspected_meta = {key:[row for row in value if row[0] in ('characters','character_talent','character_spell')]
                      for key,value in meta.items()}
    if sha_json(inspected_meta) != report.get('metadata_sha256'):
        fail('HISTORY_SCHEMA_DRIFT','Source columns differ from the retained inspection')
    for table in TABLES:
        shape = require_shape(meta,table,set(KEYS[table]))
        if {name for name,value in shape.items() if value[2]=='PRI'} != set(KEYS[table]):
            fail('UNSUPPORTED_SCHEMA','Native primary keys required: '+table)
    if len(meta['columns']) > 512 or any('on update' in row[5].lower() for row in meta['columns']):
        fail('UNSUPPORTED_COLUMN','History policy requires at most 512 columns without automatic updates')
    queries = []
    for table in TABLES:
        query = aggregate(meta,table,source,f's.guid IN ({selector})')
        queries.append(('sets',f"SELECT JSON_ARRAY('{table}',guid,n,h) row_value FROM ({query}) a ORDER BY guid"))
    # Exact live inspection inputs reject same-count ownership/flags changes.
    for label, fields, table in (
            ('characters','guid,race,class,activeTalentGroup,talentGroupsCount,online,at_login','characters'),
            ('talents','guid,spell,talentGroup','character_talent')):
        queries.append((label,f'SELECT JSON_ARRAY({fields}) row_value FROM `{source}`.{table} ORDER BY {fields}'))
    catalog = ','.join(map(str,sorted(effective.talents)))
    queries.append(('spells',f'SELECT JSON_ARRAY(guid,spell,active,disabled) row_value FROM `{source}`.character_spell '
                    f'WHERE spell IN ({catalog}) ORDER BY guid,spell'))
    queries.append(('enabled_ids',enabled_ids_query(source)))
    if include_relations:
        queries.append(('relation_spells',relations.stored_query(source,guids)))
    # Generate the post-delete digest by excluding exact selected pairs using
    # bounded row-valued IN lists grouped by GUID, never a spell-wide DELETE.
    by_guid = defaultdict(list)
    for guid,spell,_,_ in selected:
        by_guid[guid].append(spell)
    exclusion = ' OR '.join('(s.guid='+str(guid)+' AND s.spell IN ('+','.join(map(str,spells))+'))'
                            for guid,spells in sorted(by_guid.items()))
    query = aggregate(meta,'character_spell',source,f's.guid IN ({selector}) AND NOT ({exclusion})')
    queries.append(('after',f"SELECT JSON_ARRAY('character_spell',guid,n,h) row_value FROM ({query}) a ORDER BY guid"))
    # Each digest is bounded per character, not one concatenation of millions
    # of source rows. Counts are checked before any executable package exists.
    original_sql = settings.sql
    def bounded_sql(query, *positional, **keywords):
        return original_sql("SET SESSION time_zone='+00:00';\nSET SESSION group_concat_max_len=640001;\n"+query,*positional,**keywords)
    settings.sql = bounded_sql
    try:
        live = snapshot(settings,queries)
    finally:
        settings.sql = original_sql
    if any(live[label] != state[label] for label in ('characters','talents','spells','enabled_ids')):
        fail('HISTORY_INPUT_DRIFT','Live ownership/character state/direct spell flags differ from inspection',
             'Retain this inspection. After source edits, run a new full audit and inspection; no preflight is needed.')
    if include_relations and live['relation_spells'] != [r for r in relation_rows if r[0] in guid_set]:
        fail('HISTORY_INPUT_DRIFT','Related spell keys/flags changed between relationship review and full-row fingerprinting')
    cells = sorted(tuple(row) for row in live['sets'])
    after = sorted(tuple(row) for row in live['after'])
    if (any(row[2] > MAX_PER_GUID or not isinstance(row[3],str)
            or not re.fullmatch('[a-f0-9]{64}',row[3]) for row in cells+after)
            or len(cells)>4*MAX_GUIDS):
        fail('HISTORY_SNAPSHOT_BOUND','Snapshot exceeds 10000 rows per character/table or 40000 characters')
    counts = {table:sum(row[2] for row in cells if row[0]==table) for table in TABLES}
    if counts['characters'] != len(guids) or sum(counts.values())>5_000_000:
        fail('HISTORY_SNAPSHOT_BOUND','Missing affected characters or more than 5000000 archived rows')
    template = ROOT/'tools/disabled-talent-history.sql.in'
    batch = sha_json({'policy':policy,'inspection':sha(path/'SHA256SUMS'),'snapshot':cells,'after':after,
                     'selection':selected,'world':world,'meta':meta,'template':sha(template),'id':output.name})
    archive = 'tc_disabled_history_'+uuid.uuid4().hex[:20]
    blocks = check_sets(meta,source,archive,counts)
    values = {'SOURCE':source,'ARCHIVE':archive,'UUID':work.current()['identity']['uuid'],
        'BATCH':batch,'AUDIT':audit['audited_results_sha256'],'COUNT':len(selected),'GUID_COUNT':len(guids),
        'EXPECTED_HASH':planner.key_hash(selected),'SNAPSHOT_COUNT':len(cells),'SNAPSHOT_HASH':planner.key_hash(cells),
        'COLUMN_COUNT':len(meta['columns']),'COLUMN_HASH':planner.key_hash(meta['columns']),
        'CONCAT_LIMIT':max(6400001,len(cells)*160,len(selected)*80,len(meta['columns'])*2048),
        'EXPECTED_INSERT':planner.insert_values('expected_spells',selected),
        'SNAPSHOT_INSERT':planner.insert_values('expected_snapshot',cells),
        'AFTER_INSERT':planner.insert_values('expected_after',after),
        'AFTER_COUNT':len(after),'AFTER_HASH':planner.key_hash(after),
        'COLUMN_INSERT':planner.insert_values('reviewed_columns',meta['columns']),
        'GUID_INSERT':planner.insert_values('affected',[(guid,) for guid in guids]),
        'CHECK_ORIGINAL':blocks['original'],'CHECK_ARCHIVE':blocks['archive'],'CHECK_APPLIED':blocks['applied'],
        'ARCHIVE_INSERT':'\n'.join(f'  INSERT INTO {table}_before SELECT s.* FROM `{source}`.{table} s JOIN affected g ON g.guid=s.guid;' for table in TABLES)}
    world_checks = []
    for table,count,checksum in world['digests']:
        fields = [row[1] for row in world['layout']['columns'] if row[0]==table]
        hashed = 'SHA2(CONCAT_WS(\'|\','+','.join(f"IFNULL(HEX(`{name}`),'N')" for name in fields)+'),256)'
        world_checks.append(f'''IF (SELECT COUNT(*) FROM `{settings.schemas['world']}`.`{table}`)<>{count}
 OR NOT ((SELECT SHA2(COALESCE(GROUP_CONCAT({hashed} ORDER BY BINARY {hashed} SEPARATOR ''),''),256)
     FROM `{settings.schemas['world']}`.`{table}`)<=>'{checksum}') THEN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='World metadata content changed: {table}'; END IF;''')
    values['WORLD_CHECKS'] = '\n'.join(world_checks)
    final_effective, final_world = read_world(settings)
    if metadata(settings,TABLES)!=meta or final_world!=world or final_effective.hashes!=effective.hashes:
        fail('HISTORY_METADATA_DRIFT','Source schema/world metadata changed while planning')
    verify(path)
    if sha(path/'SHA256SUMS') != inspection_sha:
        fail('HISTORY_INSPECTION_INVALID','Retained inspection changed during planning')
    if any(sha(settings.paths['tc_dbc']/name)!=checksum for name,checksum in audit['dbc_sha256'].items()):
        fail('DBC_DRIFT','DBC files changed while planning')
    manifest = {'policy':policy,'archive_schema':archive,'batch_key':batch,'selected_rows':len(selected),
        'affected_characters':len(guids),'character_guids':guids,'inspection_id':path.name,
        'inspection_sha256':inspection_sha,'audit_id':report['audit'],
        'audit_sha256':audit['audited_results_sha256'],'dbc_sha256':audit['dbc_sha256'],
        'semantic_dbc_sha256':effective.hashes,'world_sha256':sha_json(world),
        'metadata_profile_sha256':sha(PROFILE/'spell-metadata.json'),
        'expected_sha256':values['EXPECTED_HASH'],'archived_rows':counts,'excluded_rows':len(excluded),
        'excluded_reason_counts':dict(Counter(row[2] for row in excluded)),
        'template_sha256':sha(template),
        'native_policy':'Disabled direct talent ranks only; no selected family in either spec; no activation, talent reset or grants'}
    if include_scripts:
        manifest.update(reviewed_script_bindings=reviewed,
            scripted_selected_rows=sum(row[1] in effective.talents and effective.talents[row[1]][0] in scripted_families for row in selected),
            script_contract='NO_SPELLBOOK_MUTATION; pinned TC AddSpell disabled path; no alternate routes/dependencies/skill effects')
    if include_relations:
        manifest.update(relation_summary)
        manifest['relationship_state_sha256'] = sha_json(live['relation_spells'])
        manifest['script_contract'] = 'NO_SPELLBOOK_MUTATION on every related member; isolated wholly disabled group; no enabled availability, selected ownership, conflicting incoming routes or skill effects'
    status = f'''SELECT * FROM `{archive}`.batch;
SELECT 'expected' AS object,COUNT(*) rows_found FROM `{archive}`.expected_spells
UNION ALL SELECT 'characters_before',COUNT(*) FROM `{archive}`.characters_before
UNION ALL SELECT 'talent_before',COUNT(*) FROM `{archive}`.character_talent_before
UNION ALL SELECT 'spell_before',COUNT(*) FROM `{archive}`.character_spell_before
UNION ALL SELECT 'skills_before',COUNT(*) FROM `{archive}`.character_skills_before;
SELECT COUNT(*) AS selected_rows,SUM(s.spell IS NOT NULL) AS still_stored,SUM(s.spell IS NULL) AS absent
FROM `{archive}`.expected_spells e LEFT JOIN `{source}`.character_spell s ON s.guid=e.guid AND s.spell=e.spell;
-- Exact selection is retained in selected-rows.tsv and expected_spells;
-- bound terminal/status preview independently of the cleanup population.
SELECT e.guid,e.spell,e.active,e.disabled,s.spell IS NOT NULL AS still_stored
FROM `{archive}`.expected_spells e LEFT JOIN `{source}`.character_spell s ON s.guid=e.guid AND s.spell=e.spell ORDER BY e.guid,e.spell LIMIT 100;
'''
    finish(settings,work,output,manifest,render_text(template,values),
           'guid\tspell\tactive\tdisabled\n'+''.join('\t'.join(map(str,row))+'\n' for row in selected),status)
    (output/'excluded-rows.tsv').write_text('guid\tspell\treason\n'+''.join('\t'.join(map(str,row))+'\n' for row in excluded))
    if include_scripts:
        (output/'scripted-family-review.tsv').write_text('talent_entry\tspell\tscript\tstatus\treason\n'+''.join(
            '\t'.join(map(str,(family,spell,name,'DEFERRED' if reason else 'REVIEWED_NO_SPELLBOOK_MUTATION',reason)))+'\n'
            for family,spell,name,reason in bindings))
    if include_relations:
        (output/'relationship-review.tsv').write_text('guid\ttalent_entry\tspell\trole\tdisposition\tactive\tdisabled\n'+
            ''.join('\t'.join(map(str,r))+'\n' for r in relation_proof))
        selected_nodes = {r[2] for r in relation_proof}
        (output/'relationship-edges.tsv').write_text('parent\tchild\trelationship\n'+''.join(
            '\t'.join(map(str,r))+'\n' for r in relation_edges if r[0] in selected_nodes and r[1] in selected_nodes))
    write_json(output/'metadata.json',world)
    from cleanup_console import seal
    seal(output)
    if include_relations:
        print(f'Reviewed {args.expect_review_rows} disabled direct rows; selected {relation_summary["selected_root_rows"]} direct and '
              f'{relation_summary["selected_related_rows"]} related rows; deferred {len(excluded)} direct rows; no source changes')
    else:
        print(f'Reviewed {len(selected)+len(excluded)} disabled rows; selected {len(selected)}; deferred {len(excluded)}; no source changes')
    for reason,count in sorted(Counter(row[2] for row in excluded).items()):
        print(reason+'\t'+str(count))
    if include_scripts:
        print('SELECTED_REVIEWED_SCRIPT_HISTORY\t'+str(manifest['scripted_selected_rows']))


def render_text(template, values):
    # Expand nested guard/check fragments before the normal token check.
    text = template.read_text()
    for name in ('CHECK_ORIGINAL','CHECK_ARCHIVE','CHECK_APPLIED','ARCHIVE_INSERT'):
        text = text.replace('@'+name+'@',values[name])
    for name,value in values.items():
        text = text.replace('@'+name+'@',str(value))
    if re.search(r'@[A-Z_]+@',text):
        fail('UNEXPANDED_TEMPLATE','Disabled history SQL has unresolved tokens')
    return text
