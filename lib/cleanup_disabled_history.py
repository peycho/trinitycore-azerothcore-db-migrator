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
import cleanup_selected_rank_history as selected_history
import cleanup_trained_history as trained_history
import cleanup_ordinary_history as ordinary_history
import cleanup_death_coil as death_coil
import cleanup_ownership as ownership
import cleanup_eligibility as eligibility
import cleanup_pet_teaching as pet_teaching
import cleanup_inactive_legacy as inactive_legacy
import cleanup_selected_passive as direct_passive
import cleanup_shaman_dual_wield as shaman
import cleanup_obsolete_riding as riding
import cleanup_skill_teaching as skill_teaching
import cleanup_professions as professions
import cleanup_specializations as specializations

POLICY = 'tc-disabled-unselected-direct-talent-history-v1'
SCRIPT_POLICY = 'tc-disabled-reviewed-script-talent-history-v2'
POLICIES = (POLICY, SCRIPT_POLICY, relations.POLICY, relations.ROUTE_POLICY, selected_history.POLICY, trained_history.POLICY, trained_history.CHILD_POLICY, ordinary_history.POLICY, ordinary_history.INACTIVE_DEFAULT_POLICY, ordinary_history.TRAINING_POLICY, death_coil.POLICY, *ownership.POLICIES, *eligibility.POLICIES, *pet_teaching.POLICIES, *inactive_legacy.POLICIES, *direct_passive.POLICIES, *shaman.POLICIES, *riding.POLICIES, *skill_teaching.POLICIES, *professions.POLICIES, *specializations.POLICIES)
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


def read_world(settings, *, exact_numeric=False):
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
        if exact_numeric:
            from cleanup_active_reset import exact_hex
            types = {r[1]:r[2] for r in layout['columns'] if r[0] == table}
            hashed = "SHA2(CONCAT_WS('|',"+','.join(f"IFNULL({exact_hex('`'+name+'`',types[name])},'N')" for name in fields)+'),256)'
        else:
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
    effective.history_default_spells = ordinary_history.history_default_spells(layout,state)
    return effective, {'layout':dict(layout),'rows':state,'digests':digests}


def check_metadata(settings, manifest):
    from cleanup_native_skills import SWITCH_POLICY, SWITCH_ACK
    if manifest.get('policy') == SWITCH_POLICY:
        if (manifest.get('native_switch_ack') != SWITCH_ACK
                or manifest.get('numeric_fingerprint') != 'EXACT_FRACTIONAL_V1'
                or sha(ROOT/'lib/cleanup_native_skills.py') != manifest.get('native_skill_reader_sha256')
                or sha(ROOT/'lib/cleanup_active_reset.py') != manifest.get('numeric_reader_sha256')
                or sha(ROOT/'lib/cleanup_eligibility.py') != manifest.get('world_guard_reader_sha256')):
            fail('NATIVE_SWITCH_POLICY_DRIFT','Known-switch skill policy or exact numeric/world guards differ; retain original toolkit')
    if manifest.get('policy') == ordinary_history.TRAINING_POLICY:
        if (manifest.get('training_prerequisite_ack') != ordinary_history.TRAINING_ACK
                or sha(ROOT/'lib/cleanup_ordinary_history.py') != manifest.get('ordinary_reader_sha256')
                or sha(ROOT/'lib/cleanup_eligibility.py') != manifest.get('world_guard_reader_sha256')
                or manifest.get('numeric_fingerprint') != 'EXACT_FRACTIONAL_V1'
                or sha(ROOT/'lib/cleanup_active_reset.py') != manifest.get('numeric_reader_sha256')
                or ordinary_history.configuration_contract(settings,training_prerequisites=True) != manifest.get('configuration_contract')):
            fail('ORDINARY_TRAINING_POLICY_DRIFT','Ordinary training policy, guards, metadata reader or configuration differs; retain original toolkit')
    if manifest.get('policy') in (*eligibility.POLICIES, *pet_teaching.POLICIES, *inactive_legacy.POLICIES, *direct_passive.POLICIES, *shaman.POLICIES, *riding.POLICIES, *skill_teaching.POLICIES, *professions.POLICIES, *specializations.POLICIES):
        if (manifest.get('numeric_fingerprint') != 'EXACT_FRACTIONAL_V1'
                or sha(ROOT/'lib/cleanup_active_reset.py') != manifest.get('numeric_reader_sha256')):
            fail('ELIGIBILITY_POLICY_DRIFT','Exact numeric fingerprint contract differs from this candidate')
        if sha(ROOT/'lib/cleanup_eligibility.py') != manifest.get('eligibility_reader_sha256'):
            fail('ELIGIBILITY_POLICY_DRIFT','Eligibility selector differs; retain the original toolkit for restoration')
        if eligibility.configuration_contract(settings) != manifest.get('configuration_contract'):
            fail('ELIGIBILITY_CONFIG_DRIFT','Eligibility configuration differs from the reviewed candidate')
    if manifest.get('policy') == eligibility.RACIAL_POLICY:
        if (manifest.get('racial_ack') != eligibility.RACIAL_ACK
                or sha(eligibility.RACIAL_CATALOG) != manifest.get('racial_catalog_sha256')):
            fail('RACIAL_POLICY_DRIFT','Reviewed racial acknowledgement or catalog changed; retain original toolkit')
    if manifest.get('policy') == eligibility.ABSENT_TEACHER_POLICY and manifest.get('absent_teacher_ack') != eligibility.ABSENT_TEACHER_ACK:
        fail('ABSENT_TEACHER_ACK_INVALID','Absent-teacher contract differs from the reviewed batch')
    if manifest.get('policy') in pet_teaching.POLICIES and sha(ROOT/'lib/cleanup_pet_teaching.py') != manifest.get('pet_teaching_reader_sha256'):
        fail('PET_TEACHING_POLICY_DRIFT','Pet-teaching selector differs; retain the original toolkit for restoration')
    if manifest.get('policy') == specializations.POLICY:
        if (manifest.get('specialization_ack') != specializations.ACK
                or sha(ROOT/'lib/cleanup_specializations.py') != manifest.get('specialization_reader_sha256')
                or sha(specializations.CATALOG) != manifest.get('specialization_catalog_sha256')
                or sha(ROOT/'lib/cleanup_professions.py') != manifest.get('profession_reader_sha256')
                or sha(professions.CATALOG) != manifest.get('profession_catalog_sha256')):
            fail('SPECIALIZATION_POLICY_DRIFT','Specialization selector or fixed catalogs changed; retain original toolkit')
        if specializations.native_sources(settings.paths) != manifest.get('specialization_native_sources'):
            fail('SPECIALIZATION_NATIVE_SOURCE_DRIFT','Native specialization/equipment consumers changed')
        if specializations.read_equipment(settings,manifest['character_guids']) != manifest.get('specialization_equipment'):
            fail('SPECIALIZATION_EQUIPMENT_DRIFT','Equipment or item requirement evidence changed')
    if manifest.get('policy') == professions.POLICY:
        if (manifest.get('profession_activation_ack') != professions.ACK
                or sha(ROOT/'lib/cleanup_professions.py') != manifest.get('profession_reader_sha256')
                or sha(professions.CATALOG) != manifest.get('profession_catalog_sha256')):
            fail('PROFESSION_POLICY_DRIFT','Profession activation reader or fixed catalog differs; retain original toolkit')
    if manifest.get('policy') == skill_teaching.POLICY:
        if (manifest.get('skill_teaching_ack') != skill_teaching.ACK
                or sha(ROOT/'lib/cleanup_skill_teaching.py') != manifest.get('skill_teaching_reader_sha256')
                or sha(skill_teaching.CATALOG) != manifest.get('skill_teaching_catalog_sha256')):
            fail('SKILL_TEACHER_POLICY_DRIFT','Skill-teaching selector or fixed catalog differs; retain original toolkit')
    if manifest.get('policy') in riding.POLICIES:
        invalid_items = manifest.get('policy') == riding.INVALID_ITEMS_POLICY
        if (manifest.get('riding_ack') != (riding.INVALID_ITEMS_ACK if invalid_items else riding.ACK)
                or sha(ROOT/'lib/cleanup_obsolete_riding.py') != manifest.get('riding_reader_sha256')
                or sha(riding.CATALOG) != manifest.get('riding_catalog_sha256')
                or sha(ROOT/'lib/cleanup_shaman_dual_wield.py') != manifest.get('starting_skill_reader_sha256')
                or riding.native_sources(settings.paths,native_invalid_items=invalid_items) != manifest.get('riding_native_sources')
                or invalid_items and sha(riding.ITEM_CATALOG) != manifest.get('riding_item_catalog_sha256')):
            fail('OBSOLETE_RIDING_POLICY_DRIFT','Obsolete riding contract differs; retain the original toolkit')
        if riding.defaults(settings) != manifest.get('riding_default_skills'):
            fail('OBSOLETE_RIDING_DEFAULT_DRIFT','Starting-skill inputs changed')
        guids = manifest['character_guids']
        if riding.read_items(settings,guids,native_invalid_items=invalid_items) != manifest.get('riding_items'):
            fail('OBSOLETE_RIDING_ITEM_DRIFT','Owned/inventory/mail item requirements changed')
    if manifest.get('policy') == shaman.POLICY:
        if (manifest.get('shaman_ack') != shaman.ACK
                or sha(ROOT/'lib/cleanup_shaman_dual_wield.py') != manifest.get('shaman_reader_sha256')):
            fail('SHAMAN_POLICY_DRIFT','Shaman coupled repair contract differs; retain original toolkit')
        if shaman.defaults(settings) != manifest.get('shaman_default_skills'):
            fail('SHAMAN_DEFAULT_DRIFT','Native starting-skill metadata changed')
    if manifest.get('policy') == direct_passive.POLICY:
        if (manifest.get('direct_passive_ack') != direct_passive.ACK
                or sha(ROOT/'lib/cleanup_selected_passive.py') != manifest.get('direct_passive_reader_sha256')
                or sha(ROOT/'lib/cleanup_ownership.py') != manifest.get('ownership_reader_sha256')):
            fail('DIRECT_PASSIVE_POLICY_DRIFT','Direct passive authority contract differs; retain original toolkit')
    if manifest.get('policy') == inactive_legacy.POLICY:
        if (manifest.get('inactive_legacy_ack') != inactive_legacy.ACK
                or sha(ROOT/'lib/cleanup_inactive_legacy.py') != manifest.get('inactive_legacy_reader_sha256')):
            fail('INACTIVE_LEGACY_POLICY_DRIFT','Inactive legacy selector or acknowledgement differs; retain original toolkit')
    if manifest.get('policy') == pet_teaching.COWER_POLICY:
        if (manifest.get('cower_ack') != pet_teaching.COWER_ACK
                or pet_teaching.cower_sources(settings.paths) != manifest.get('cower_native_contract')):
            fail('COWER_NATIVE_CONTRACT_DRIFT','Native Cower contract differs from the reviewed batch')
    if manifest.get('policy') in ownership.POLICIES and sha(ROOT/'lib/cleanup_ownership.py') != manifest.get('ownership_reader_sha256'):
        fail('OWNERSHIP_POLICY_DRIFT','Ownership selection code differs from this reviewed batch; retain its original toolkit for restore')
    if manifest.get('policy') == ownership.FOREIGN_POLICY:
        if (manifest.get('foreign_family_ack') != ownership.FOREIGN_ACK
                or manifest.get('numeric_fingerprint') != 'EXACT_FRACTIONAL_V1'
                or sha(ROOT/'lib/cleanup_active_reset.py') != manifest.get('numeric_reader_sha256')
                or sha(ROOT/'lib/cleanup_eligibility.py') != manifest.get('world_guard_reader_sha256')):
            fail('OWNERSHIP_FOREIGN_POLICY_DRIFT','Foreign-family policy or exact numeric/world guards differ; retain original toolkit')
    if manifest.get('policy') == ownership.PREFIX_POLICY:
        if (manifest.get('native_prefix_ack') != ownership.PREFIX_ACK
                or manifest.get('numeric_fingerprint') != 'EXACT_FRACTIONAL_V1'
                or sha(ROOT/'lib/cleanup_active_reset.py') != manifest.get('numeric_reader_sha256')
                or sha(ROOT/'lib/cleanup_eligibility.py') != manifest.get('world_guard_reader_sha256')):
            fail('OWNERSHIP_PREFIX_POLICY_DRIFT','Native-prefix policy or exact numeric/world guards differ; retain original toolkit')
    if manifest.get('policy') == ownership.REKEY_POLICY:
        if (manifest.get('native_rekey_ack') != ownership.REKEY_ACK
                or manifest.get('numeric_fingerprint') != 'EXACT_FRACTIONAL_V1'
                or sha(ROOT/'lib/cleanup_active_reset.py') != manifest.get('numeric_reader_sha256')
                or sha(ROOT/'lib/cleanup_eligibility.py') != manifest.get('world_guard_reader_sha256')):
            fail('OWNERSHIP_REKEY_POLICY_DRIFT','Passive rekey policy or exact numeric/world guards differ; retain original toolkit')
    if manifest.get('policy') == ownership.AURA_ALIAS_POLICY:
        if (manifest.get('aura_alias_ack') != ownership.AURA_ALIAS_ACK
                or manifest.get('numeric_fingerprint') != 'EXACT_FRACTIONAL_V1'
                or sha(ROOT/'lib/cleanup_active_reset.py') != manifest.get('numeric_reader_sha256')
                or sha(ROOT/'lib/cleanup_eligibility.py') != manifest.get('world_guard_reader_sha256')):
            fail('OWNERSHIP_ALIAS_POLICY_DRIFT','Aura-alias policy or exact numeric/world guards differ; retain original toolkit')
    if manifest.get('policy') == ordinary_history.INACTIVE_DEFAULT_POLICY:
        if ordinary_history.configuration_contract(settings) != manifest.get('configuration_contract'):
            fail('ORDINARY_HISTORY_CONFIG_DRIFT','Configuration contract differs from the reviewed ordinary-history batch')
    if manifest.get('policy') == death_coil.POLICY:
        if death_coil.configuration_contract(settings) != manifest.get('configuration_contract'):
            fail('DEATH_COIL_CONFIG_DRIFT','Configuration contract differs from the reviewed Death Coil batch')
    settings.check_paths()
    if sha(PROFILE/'spell-metadata.json') != manifest.get('metadata_profile_sha256'):
        fail('HISTORY_METADATA_DRIFT','Spell metadata policy differs from the reviewed batch')
    for key,entry in manifest.get('core_compatibility',{}).items():
        if settings.compatibility.get(key,{}).get('manifest_sha256') != entry.get('manifest_sha256'):
            fail('CORE_PROFILE_MISMATCH','Core compatibility manifests differ from the reviewed history batch')
    effective, world = read_world(settings,exact_numeric=manifest.get('policy') in (*eligibility.POLICIES, *pet_teaching.POLICIES, *inactive_legacy.POLICIES, *direct_passive.POLICIES, *shaman.POLICIES, *riding.POLICIES, *skill_teaching.POLICIES, *professions.POLICIES, *specializations.POLICIES, ordinary_history.TRAINING_POLICY, ownership.FOREIGN_POLICY, ownership.PREFIX_POLICY, ownership.AURA_ALIAS_POLICY, ownership.REKEY_POLICY, SWITCH_POLICY))
    if sha_json(world) != manifest.get('world_sha256') or effective.hashes != manifest.get('semantic_dbc_sha256'):
        fail('HISTORY_METADATA_DRIFT','Effective TC world/DBC metadata differs from this reviewed history batch')
    if manifest.get('policy') in (*eligibility.POLICIES, *pet_teaching.POLICIES, *inactive_legacy.POLICIES, *direct_passive.POLICIES, *shaman.POLICIES, *riding.POLICIES, *skill_teaching.POLICIES, *professions.POLICIES, *specializations.POLICIES):
        target, captured = eligibility.read_target(settings)
        if sha_json(captured) != manifest.get('target_world_sha256') or target.hashes != manifest.get('target_dbc_sha256'):
            fail('ELIGIBILITY_TARGET_DRIFT','Effective AC world/DBC metadata differs from the reviewed candidate')


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


def aggregate(meta, table, database, scope, alias='s', *, exact_numeric=False, join=''):
    keys = ','.join(f'{alias}.`{name}`' for name in KEYS[table])
    size = '+'.join(f'COALESCE(OCTET_LENGTH({alias}.`{name}`),0)' for name in columns(meta,table))
    hashed = f'IF(({size})<=1048576,{row_hash(meta,table,alias,exact_numeric=exact_numeric)},NULL)'
    return (f'SELECT {alias}.guid,COUNT(*) n,IF(COUNT({hashed})=COUNT(*),SHA2(GROUP_CONCAT({hashed} '
            f'ORDER BY {keys} SEPARATOR \'\'),256),NULL) h FROM `{database}`.`{table}` {alias} {join} '
            f'WHERE {scope} GROUP BY {alias}.guid')


def enabled_ids_query(source):
    return (f'SELECT JSON_ARRAY(spell) row_value FROM (SELECT DISTINCT spell FROM `{source}`.character_spell '
            'WHERE disabled=0) enabled_spells ORDER BY spell')


def check_sets(meta, source, archive, counts, changed_table='character_spell', *, exact_numeric=False):
    blocks = {}
    for phase in ('original','archive','applied'):
        lines = []
        for table in TABLES:
            db = archive if phase == 'archive' else source
            actual_table = table+'_before' if phase == 'archive' else table
            query = aggregate(meta,table,db,'s.guid IN (SELECT guid FROM affected)',exact_numeric=exact_numeric)
            if phase == 'archive':
                query = query.replace(f'`{db}`.`{table}`',f'`{db}`.`{actual_table}`')
            expected = 'expected_snapshot'
            if phase == 'applied' and table in ((changed_table,) if isinstance(changed_table,str) else changed_table):
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
    riding_mode = getattr(args,'obsolete_riding',False)
    riding_invalid_items = riding_mode and getattr(args,'native_invalid_items',False)
    riding_reader = sha(ROOT/'lib/cleanup_obsolete_riding.py') if riding_mode else None
    riding_catalog = sha(riding.CATALOG) if riding_mode else None
    riding_item_catalog = sha(riding.ITEM_CATALOG) if riding_invalid_items else None
    specialization_mode = getattr(args,'specialization_retirement',False)
    specialization_reader = sha(ROOT/'lib/cleanup_specializations.py') if specialization_mode else None
    specialization_catalog = sha(specializations.CATALOG) if specialization_mode else None
    profession_mode = getattr(args,'profession_activation',False)
    profession_reader = sha(ROOT/'lib/cleanup_professions.py') if profession_mode or specialization_mode else None
    profession_catalog = sha(professions.CATALOG) if profession_mode or specialization_mode else None
    skill_teaching_mode = getattr(args,'skill_teaching',False)
    teaching_reader = sha(ROOT/'lib/cleanup_skill_teaching.py') if skill_teaching_mode else None
    teaching_catalog = sha(skill_teaching.CATALOG) if skill_teaching_mode else None
    shaman_mode = getattr(args,'unselected_shaman_dual_wield',False)
    shaman_reader = sha(ROOT/'lib/cleanup_shaman_dual_wield.py') if shaman_mode else None
    direct_mode = getattr(args,'selected_direct_passives',False)
    direct_reader = sha(ROOT/'lib/cleanup_selected_passive.py') if direct_mode else None
    direct_ownership_reader = sha(ROOT/'lib/cleanup_ownership.py') if direct_mode else None
    pet_mode = getattr(args,'pet_teaching',False)
    legacy_mode = getattr(args,'inactive_legacy',False)
    two_world_mode = getattr(args,'spell_eligibility',False) or pet_mode or legacy_mode or direct_mode or shaman_mode or skill_teaching_mode or profession_mode or specialization_mode or riding_mode
    legacy_reader = sha(ROOT/'lib/cleanup_inactive_legacy.py') if legacy_mode else None
    pet_reader = sha(ROOT/'lib/cleanup_pet_teaching.py') if pet_mode else None
    reviewed_cower = pet_mode and getattr(args,'reviewed_cower',False)
    absent_teachers = getattr(args,'spell_eligibility',False) and getattr(args,'absent_teachers',False)
    racial_mode = getattr(args,'spell_eligibility',False) and getattr(args,'reviewed_racials',False)
    racial_catalog = sha(eligibility.RACIAL_CATALOG) if racial_mode else None
    cower_proof = pet_teaching.cower_sources(settings.paths) if reviewed_cower else None
    native_selector = riding if riding_mode else specializations if specialization_mode else professions if profession_mode else skill_teaching if skill_teaching_mode else shaman if shaman_mode else direct_passive if direct_mode else inactive_legacy if legacy_mode else pet_teaching if pet_mode else eligibility
    eligibility_reader = sha(ROOT/'lib/cleanup_eligibility.py') if two_world_mode else None
    ownership_mode = getattr(args,'talent_ownership',False) and not (direct_mode or shaman_mode)
    ownership_reader = sha(ROOT/'lib/cleanup_ownership.py') if ownership_mode else None
    foreign_mode = ownership_mode and getattr(args,'foreign_class_families',False)
    prefix_mode = ownership_mode and getattr(args,'native_passive_prefixes',False)
    alias_mode = ownership_mode and getattr(args,'reviewed_aura_aliases',False)
    rekey_mode = ownership_mode and getattr(args,'native_passive_rekey',False)
    if shaman_mode and not getattr(args,'migration_inspection',None):
        fail('SHAMAN_INSPECTION_REQUIRED','Coupled Shaman repair requires --migration-inspection')
    if direct_mode and any(getattr(args,key,False)for key in ('foreign_class_families','native_passive_prefixes','reviewed_aura_aliases','native_passive_rekey')):
        fail('HISTORY_POLICY_CONFLICT','Direct passive authority is a separate ownership policy')
    if sum((prefix_mode,foreign_mode,alias_mode,rekey_mode)) > 1:
        fail('HISTORY_POLICY_CONFLICT','Ownership extensions are separate policies')
    trained_mode = bool(getattr(args,'migration_inspection',None))
    child_mode = getattr(args,'orphaned_talent_children',False)
    ordinary_mode = getattr(args,'ordinary_spell_history',False)
    inactive_defaults = getattr(args,'inactive_custom_defaults',False)
    native_death_coil = getattr(args,'native_death_coil',False)
    training_prerequisites = getattr(args,'training_prerequisites',False)
    strong_history_mode = training_prerequisites or foreign_mode or prefix_mode or alias_mode or rekey_mode
    exact_mode = two_world_mode or strong_history_mode
    ordinary_reader = sha(ROOT/'lib/cleanup_ordinary_history.py') if training_prerequisites else None
    world_guard_reader = sha(ROOT/'lib/cleanup_eligibility.py') if strong_history_mode else None
    numeric_reader = sha(ROOT/'lib/cleanup_active_reset.py') if strong_history_mode else None
    if training_prerequisites and (inactive_defaults or native_death_coil or not ordinary_mode):
        fail('HISTORY_POLICY_CONFLICT','--training-prerequisites is a separate ordinary-history policy')
    if native_death_coil and (inactive_defaults or not ordinary_mode):
        fail('HISTORY_POLICY_CONFLICT','--native-death-coil is a separate ordinary-history policy')
    config_contract = (ordinary_history.configuration_contract(settings,training_prerequisites=True) if training_prerequisites else
                       eligibility.configuration_contract(settings) if two_world_mode else
                       death_coil.configuration_contract(settings) if native_death_coil else
                       ordinary_history.configuration_contract(settings) if inactive_defaults else None)
    preview = getattr(args,'preview',False)
    if child_mode and not trained_mode:
        fail('HISTORY_POLICY_CONFLICT','--orphaned-talent-children requires --migration-inspection')
    if ordinary_mode and not trained_mode:
        fail('HISTORY_POLICY_CONFLICT','Ordinary spell history requires --migration-inspection')
    if preview and not (child_mode or ordinary_mode or ownership_mode or two_world_mode):
        fail('HISTORY_POLICY_CONFLICT','--preview requires the explicit talent-child or ordinary-history policy')
    selected_mode = getattr(args,'selected_rank_history',False)
    if trained_mode and any(getattr(args,field,False) for field in ('include_reviewed_scripts','include_inert_relations','include_reviewed_routes','selected_rank_history')):
        fail('HISTORY_POLICY_CONFLICT','--migration-inspection cannot be combined with other direct-history modes')
    if selected_mode and any(getattr(args,field,False) for field in ('include_reviewed_scripts','include_inert_relations','include_reviewed_routes')):
        fail('HISTORY_POLICY_CONFLICT','--selected-rank-history cannot be combined with another history mode')
    inspection_id = args.inspection
    if getattr(args,'audit',None):
        from cleanup_spell_history import inspect_history
        inspection_id = inspect_history(settings,work,args).name
    if trained_mode:
        path,report,state,context,audit,captured_world,captured_layout,capture_report=trained_history.inspection(settings,work,args.migration_inspection)
        rows=[]
    else:
        path, report, state, rows, audit = inspection(settings,work,inspection_id)
    if rekey_mode and {r[1] for r in captured_layout['columns'] if r[0]=='character_spell'} != {'guid','spell','active','disabled'}:
        fail('UNSUPPORTED_REKEY_COLUMNS','Passive rekey requires stock character_spell columns; custom spell-specific fields require separate review')
    inspection_sha = sha(path/'SHA256SUMS')
    print('Reviewing effective TC world/DBC learning routes (read-only)',flush=True)
    effective, world = read_world(settings,exact_numeric=exact_mode)
    # Older sealed inspections retain their historical numeric digest. The
    # full typed rows/layout and asset hashes still have to match exactly;
    # new eligibility packets then use the stronger digest at every phase.
    same_world = (all(world[k]==captured_world[k] for k in ('layout','rows')) if exact_mode
                  else world==captured_world) if trained_mode else True
    if trained_mode and (not same_world or effective.hashes!=capture_report['dbc_sha256']):
        fail('HISTORY_METADATA_DRIFT','Effective TC metadata differs from the captured migration context')
    state['enabled_ids'] = snapshot(settings,[('ids',enabled_ids_query(settings.schemas['characters']))])['ids']
    include_routes = getattr(args,'include_reviewed_routes',False)
    include_relations = getattr(args,'include_inert_relations',False) or include_routes or trained_mode
    include_scripts = getattr(args,'include_reviewed_scripts',False) or include_relations or selected_mode
    policy = trained_history.POLICY if trained_mode else selected_history.POLICY if selected_mode else relations.ROUTE_POLICY if include_routes else relations.POLICY if include_relations else SCRIPT_POLICY if include_scripts else POLICY
    if child_mode:
        policy = trained_history.CHILD_POLICY
    if ordinary_mode:
        policy = (ordinary_history.TRAINING_POLICY if training_prerequisites else death_coil.POLICY if native_death_coil else
                  ordinary_history.INACTIVE_DEFAULT_POLICY if inactive_defaults else ordinary_history.POLICY)
    if ownership_mode:
        policy = ownership.REKEY_POLICY if rekey_mode else ownership.AURA_ALIAS_POLICY if alias_mode else ownership.PREFIX_POLICY if prefix_mode else ownership.FOREIGN_POLICY if foreign_mode else ownership.POLICY
    if two_world_mode:
        policy = (riding.INVALID_ITEMS_POLICY if riding_invalid_items else pet_teaching.COWER_POLICY if reviewed_cower else
                  eligibility.ABSENT_TEACHER_POLICY if absent_teachers else
                  eligibility.RACIAL_POLICY if racial_mode else native_selector.POLICY)
        print('Capturing effective AC world/DBC eligibility inputs (read-only)',flush=True)
        target_effective, target_world = eligibility.read_target(settings)
    relation_rows,relation_proof,relation_summary,relation_edges = [],[],{},[]
    rank_proof = []
    native_base_proofs = []
    training_proofs = []
    ownership_native_proofs = []
    rekeys = []
    if specialization_mode:
        specialization_native_sources = specializations.native_sources(settings.paths)
        equipment = specializations.read_equipment(settings,[r[0] for r in context['characters']])
    if riding_mode:
        riding_sources = riding.native_sources(settings.paths,native_invalid_items=riding_invalid_items)
        riding_items = riding.read_items(settings,[r[0] for r in context['characters']],native_invalid_items=riding_invalid_items)
        riding_defaults = riding.defaults(settings)
    if shaman_mode:
        inventory_meta, offhand_rows = shaman.inventory(settings,context)
        default_skills = shaman.defaults(settings)
    if trained_mode:
        check_retained_scripts(state,effective)
        relation_rows=context['character_spell']
        if two_world_mode:
            selected,excluded,relation_proof,relation_summary,relation_edges=native_selector.select(
                context,effective,target_effective,args.expect_review_rows,preview=preview,
                **({'items':riding_items['rows'],'default_skills':riding_defaults,'native_invalid_items':riding_invalid_items,
                    'zero_template_counts':riding_items.get('zero_template_counts')} if riding_mode else {'equipment':equipment['rows']} if specialization_mode else {'offhand':{r[0] for r in offhand_rows},'default_skills':default_skills} if shaman_mode else {'reviewed_cower':True} if reviewed_cower else {'absent_teachers':True} if absent_teachers else {'reviewed_racials':True} if racial_mode else {}))
            eligibility_proofs = relation_summary.pop('eligibility_proofs')
        elif ownership_mode:
            selected,excluded,relation_proof,relation_summary,relation_edges=ownership.select(
                context,effective,args.expect_review_rows,preview=preview,source_dir=settings.paths['tc_source'],
                foreign_class_families=foreign_mode,native_passive_prefixes=prefix_mode,reviewed_aura_aliases=alias_mode,native_passive_rekey=rekey_mode)
            ownership_native_proofs = relation_summary.pop('native_owner_proofs')
            rekeys = relation_summary.pop('rekeys',[])
            if rekey_mode:
                relation_summary['rekeys'] = rekeys
        elif ordinary_mode:
            selected,excluded,relation_proof,relation_summary,relation_edges=ordinary_history.select(
                context,effective,args.expect_review_rows,preview=preview,inactive_custom_defaults=inactive_defaults,
                native_death_coil=native_death_coil,training_prerequisites=training_prerequisites)
            native_base_proofs = relation_summary.pop('native_base_proofs',[])
            training_proofs = relation_summary.pop('training_prerequisite_proofs',[])
        else:
            selected,excluded,relation_proof,relation_summary,relation_edges=trained_history.select(
                context,effective,args.expect_review_rows,orphan_children=child_mode,preview=preview)
        if child_mode or ordinary_mode or ownership_mode or two_world_mode:
            review_name = 'obsolete-riding-review.json' if riding_mode else 'specialization-retirement-review.json' if specialization_mode else 'profession-activation-review.json' if profession_mode else 'skill-teaching-review.json' if skill_teaching_mode else 'shaman-dual-wield-review.json' if shaman_mode else 'selected-passive-review.json' if direct_mode else 'inactive-legacy-review.json' if legacy_mode else 'pet-teaching-review.json' if pet_mode else 'spell-eligibility-review.json' if two_world_mode else 'talent-ownership-review.json' if ownership_mode else 'ordinary-spell-review.json' if ordinary_mode else 'talent-child-review.json'
            review_label = 'Obsolete riding spell/skill' if riding_mode else 'Inactive specialization retirement' if specialization_mode else 'Ordinary profession activation' if profession_mode else 'Redundant skill-teaching' if skill_teaching_mode else 'Coupled Shaman spell/skill' if shaman_mode else 'Selected direct passive' if direct_mode else 'Inactive legacy' if legacy_mode else 'Pet-teaching' if pet_mode else 'Spell-eligibility' if two_world_mode else 'Talent-ownership' if ownership_mode else 'Ordinary-spell' if ordinary_mode else 'Talent-child'
            review={'policy':policy,'migration_inspection':path.name,'scope_characters':len(context['characters']),
                    'summary':relation_summary,'selected':selected,'excluded':excluded,
                    'deferred':dict(Counter(row[2] for row in excluded)),
                    'limitations':['Captured-state review, not a live full-row verification or cleanup approval',
                                   'Planning rechecks the complete captured semantic scope and full affected originals']}
            if config_contract is not None:
                review['configuration_contract'] = config_contract
            if ownership_mode:
                review['native_owner_proofs'] = ownership_native_proofs
            if two_world_mode:
                review['eligibility_proofs'] = eligibility_proofs
                review['target_world_sha256'] = sha_json(target_world)
                review['target_dbc_sha256'] = target_effective.hashes
            if specialization_mode:
                review['equipment'] = equipment
            if riding_mode:
                review['items'] = riding_items
                review['starting_skills'] = riding_defaults
            if reviewed_cower:
                review['cower_native_contract'] = cower_proof
            if training_prerequisites:
                review['training_prerequisite_proofs'] = training_proofs
            if native_death_coil:
                review['native_base_proofs'] = native_base_proofs
            write_json(work.operation/review_name,review)
            print(review_label+' review (read-only): '+json.dumps({**relation_summary,'deferred':review['deferred']},sort_keys=True),flush=True)
            if preview:
                print('PREVIEW: captured evidence only; no SQL package, active batch or source changes. Details: '+str(work.operation/review_name),flush=True)
                return False
            if not selected:
                fail('OWNERSHIP_SELECTION_MISMATCH','No eligible ownership repair rows')
    elif selected_mode:
        check_retained_scripts(state,effective)
        selected,excluded,rank_proof = selected_history.select(rows,state,effective,args.expect_review_rows)
    elif include_relations:
        review_guids = sorted({r[0] for r in rows if r[9]=='REVIEW_DISABLED_NO_SELECTED_FAMILY'})
        if not review_guids or len(review_guids)>MAX_GUIDS:
            fail('HISTORY_RELATION_BOUND','No review characters or more than 40000 characters')
        print('Reviewing complete related spell state per character (read-only)',flush=True)
        relation_rows = snapshot(settings,[('rows',relations.stored_query(settings.schemas['characters'],review_guids))])['rows']
        check_retained_scripts(state,effective)
        selected,excluded,relation_proof,relation_summary,relation_edges = relations.select(
            rows,state,effective,relation_rows,args.expect_review_rows,include_routes)
    else:
        selected, excluded = select(rows,state,effective,args.expect_review_rows,include_scripts)
    bindings = script_bindings(effective) if include_scripts and not ordinary_mode else []
    if include_relations:
        bindings = sorted(set(bindings) | {(family,spell,name,'') for _,family,spell,*_ in relation_proof
                                         for name in effective.scripts[spell]})
    selected_families = {effective.talents[row[1]][0] for row in selected if row[1] in effective.talents}
    if child_mode or ordinary_mode or ownership_mode or two_world_mode:
        selected_families |= {row[1] for row in relation_proof}
    reviewed = [row[:3] for row in bindings if row[0] in selected_families]
    scripted_families = {entry[0] for entry in reviewed}
    guids = sorted({row[0] for row in selected})
    guid_set = set(guids)
    print(f'Fingerprinting complete spell/talent/skill/character state for {len(guids)} characters (read-only)',flush=True)
    selector = ','.join(map(str,guids))
    source = settings.schemas['characters']
    meta = metadata(settings,TABLES)
    if trained_mode and dict(meta)!=captured_layout:
        fail('HISTORY_SCHEMA_DRIFT','Source layout differs from the captured migration context')
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
    if rekey_mode and set(columns(meta,'character_spell')) != {'guid','spell','active','disabled'}:
        fail('UNSUPPORTED_REKEY_COLUMNS','Passive rekey requires stock character_spell columns; custom spell-specific fields require separate review')
    queries = []
    for table in TABLES:
        query = aggregate(meta,table,source,f's.guid IN ({selector})',exact_numeric=exact_mode)
        queries.append(('sets',f"SELECT JSON_ARRAY('{table}',guid,n,h) row_value FROM ({query}) a ORDER BY guid"))
    # Exact live inspection inputs reject same-count ownership/flags changes.
    scope = ' WHERE guid IN ('+','.join(str(r[0]) for r in context['characters'])+')' if trained_mode else ''
    for label, fields, table in (
            ('characters','guid,race,class,activeTalentGroup,talentGroupsCount,online,at_login','characters'),
            ('talents','guid,spell,talentGroup','character_talent')):
        queries.append((label,f'SELECT JSON_ARRAY({fields}) row_value FROM `{source}`.{table}{scope} ORDER BY {fields}'))
    catalog = ','.join(map(str,sorted(effective.talents)))
    queries.append(('spells',f'SELECT JSON_ARRAY(guid,spell,active,disabled) row_value FROM `{source}`.character_spell '
                    f'WHERE spell IN ({catalog})'+(' AND'+scope.removeprefix(' WHERE') if trained_mode else '')+' ORDER BY guid,spell'))
    queries.append(('enabled_ids',enabled_ids_query(source)))
    if include_relations:
        queries.append(('relation_spells',relations.stored_query(source,guids)))
    if trained_mode:
        from cleanup_migration_evidence import FIELDS
        for table,fields in FIELDS.items():
            column_sql=','.join('`'+field+'`' for field in fields)
            keys={'characters':'guid','character_spell':'guid,spell','character_talent':'guid,talentGroup,spell','character_skills':'guid,skill'}[table]
            queries.append(('context_'+table,f'SELECT JSON_ARRAY({column_sql}) row_value FROM `{source}`.`{table}`{scope} ORDER BY {keys} LIMIT {relations.MAX_ROWS+1}'))
    # Generate the post-delete digest by excluding exact selected pairs using
    # bounded row-valued IN lists grouped by GUID, never a spell-wide DELETE.
    by_guid = defaultdict(list)
    for guid,spell,_,_ in selected:
        by_guid[guid].append(spell)
    exclusion = ' OR '.join('(s.guid='+str(guid)+' AND s.spell IN ('+','.join(map(str,spells))+'))'
                            for guid,spells in sorted(by_guid.items()))
    query = aggregate(meta,'character_spell',source,f's.guid IN ({selector}) AND NOT ({exclusion})',exact_numeric=exact_mode)
    if rekey_mode:
        # Hash projected stock rows in NEW-key order. Materialize one bounded
        # mapping relation rather than evaluating every mapping for every row.
        mapping_json = json.dumps(rekeys,separators=(',',':'))
        mapped = 'COALESCE(rekey.to_spell,s.`spell`)'
        join = (f"LEFT JOIN JSON_TABLE('{mapping_json}','$[*]' COLUMNS("
                "guid INT UNSIGNED PATH '$[0]',from_spell INT UNSIGNED PATH '$[1]',"
                "to_spell INT UNSIGNED PATH '$[2]')) rekey "
                'ON rekey.guid=s.guid AND rekey.from_spell=s.spell')
        query = aggregate(meta,'character_spell',source,f's.guid IN ({selector})',exact_numeric=True,join=join)
        query = query.replace('s.`spell`',mapped)
    if profession_mode:
        pairs=json.dumps([[r[0],r[1]] for r in selected],separators=(',',':'))
        join=(f"LEFT JOIN JSON_TABLE('{pairs}','$[*]' COLUMNS("
              "guid INT UNSIGNED PATH '$[0]',spell INT UNSIGNED PATH '$[1]')) activate "
              'ON activate.guid=s.guid AND activate.spell=s.spell')
        query=aggregate(meta,'character_spell',source,f's.guid IN ({selector})',exact_numeric=True,join=join)
        query=query.replace('s.`active`','IF(activate.guid IS NULL,s.`active`,1)')
    queries.append(('after',f"SELECT JSON_ARRAY('character_spell',guid,n,h) row_value FROM ({query}) a ORDER BY guid"))
    if shaman_mode or riding_mode:
        retired_skill = 149 if riding_mode else 118
        query=aggregate(meta,'character_skills',source,f's.guid IN ({selector}) AND s.skill<>{retired_skill}',exact_numeric=True)
        queries.append(('after',f"SELECT JSON_ARRAY('character_skills',guid,n,h) row_value FROM ({query}) a ORDER BY guid"))
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
    if trained_mode and any(live['context_'+table]!=context[table] for table in context):
        fail('HISTORY_INPUT_DRIFT','Full semantic source context changed; capture a new migration blocker inspection before planning')
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
    template = ROOT/('tools/obsolete-riding-repair.sql.in' if riding_mode else 'tools/profession-activation-repair.sql.in' if profession_mode else 'tools/shaman-dual-wield-repair.sql.in' if shaman_mode else 'tools/inactive-legacy-repair.sql.in' if legacy_mode else 'tools/pet-teaching-repair.sql.in' if pet_mode else 'tools/spell-eligibility-repair.sql.in' if two_world_mode else
                    'tools/passive-rekey-repair.sql.in' if rekey_mode else 'tools/talent-ownership-repair.sql.in' if ownership_mode else 'tools/disabled-talent-history.sql.in')
    batch_inputs = {'policy':policy,'inspection':sha(path/'SHA256SUMS'),'snapshot':cells,'after':after,
                    'selection':selected,'world':world,'meta':meta,'template':sha(template),'id':output.name}
    if training_prerequisites:
        batch_inputs.update(training_prerequisite_proofs=training_proofs,ordinary_reader_sha256=ordinary_reader,
                            numeric_reader_sha256=numeric_reader,
                            world_guard_reader_sha256=world_guard_reader)
    if foreign_mode or prefix_mode or alias_mode or rekey_mode:
        batch_inputs.update(numeric_reader_sha256=numeric_reader,world_guard_reader_sha256=world_guard_reader)
    if ownership_mode:
        batch_inputs.update(ownership_reader_sha256=ownership_reader,ownership_proofs=relation_proof,
                            native_owner_proofs=ownership_native_proofs)
    if two_world_mode:
        batch_inputs.update(eligibility_reader_sha256=eligibility_reader,eligibility_proofs=eligibility_proofs,
                            target_world=target_world,target_dbc_sha256=target_effective.hashes,
                            numeric_reader_sha256=sha(ROOT/'lib/cleanup_active_reset.py'))
    if racial_mode:
        batch_inputs.update(racial_catalog_sha256=racial_catalog,racial_ack=eligibility.RACIAL_ACK)
    if config_contract is not None:
        batch_inputs['configuration_contract'] = config_contract
    if native_death_coil:
        batch_inputs['native_base_proofs'] = native_base_proofs
    if specialization_mode:
        batch_inputs.update(specialization_reader_sha256=specialization_reader,specialization_catalog_sha256=specialization_catalog,
                            profession_reader_sha256=profession_reader,profession_catalog_sha256=profession_catalog,
                            equipment=specializations.restricted(equipment,guids),native_sources=specialization_native_sources)
    if profession_mode:
        batch_inputs.update(profession_reader_sha256=profession_reader,profession_catalog_sha256=profession_catalog)
    if skill_teaching_mode:
        batch_inputs.update(skill_teaching_reader_sha256=teaching_reader,skill_teaching_catalog_sha256=teaching_catalog)
    if shaman_mode:
        batch_inputs.update(shaman_reader_sha256=shaman_reader,inventory_metadata=inventory_meta,shaman_default_skills=default_skills)
    if riding_mode:
        batch_inputs.update(riding_reader_sha256=riding_reader,riding_catalog_sha256=riding_catalog,
                            riding_items=riding.restricted(riding_items,guids),riding_default_skills=riding_defaults,
                            riding_native_sources=riding_sources,starting_skill_reader_sha256=sha(ROOT/'lib/cleanup_shaman_dual_wield.py'))
    if riding_invalid_items:
        batch_inputs['riding_item_catalog_sha256'] = riding_item_catalog
    if direct_mode:
        batch_inputs.update(direct_passive_reader_sha256=direct_reader,ownership_reader_sha256=direct_ownership_reader)
    if legacy_mode:
        batch_inputs['inactive_legacy_reader_sha256'] = legacy_reader
    if pet_mode:
        batch_inputs['pet_teaching_reader_sha256'] = pet_reader
    if reviewed_cower:
        batch_inputs['cower_native_contract'] = cower_proof
    if rekey_mode:
        batch_inputs['rekeys'] = rekeys
    batch = sha_json(batch_inputs)
    archive = ('tc_obsolete_riding_' if riding_mode else 'tc_specialization_' if specialization_mode else 'tc_profession_' if profession_mode else 'tc_skill_teacher_' if skill_teaching_mode else 'tc_shaman_dual_' if shaman_mode else 'tc_direct_passive_' if direct_mode else 'tc_inactive_legacy_' if legacy_mode else 'tc_pet_teaching_' if pet_mode else 'tc_eligibility_' if two_world_mode else 'tc_ownership_' if ownership_mode else 'tc_disabled_history_')+uuid.uuid4().hex[:20]
    blocks = check_sets(meta,source,archive,counts,changed_table=('character_spell','character_skills') if shaman_mode or riding_mode else 'character_spell',exact_numeric=exact_mode)
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
    if rekey_mode:
        values.update(MAPPING_INSERT=planner.insert_values('expected_rekeys',rekeys),
                      MAPPING_HASH=planner.key_hash(rekeys))
    world_checks = []
    for table,count,checksum in world['digests']:
        fields = [row[1] for row in world['layout']['columns'] if row[0]==table]
        hashed = 'SHA2(CONCAT_WS(\'|\','+','.join(f"IFNULL(HEX(`{name}`),'N')" for name in fields)+'),256)'
        world_checks.append(f'''IF (SELECT COUNT(*) FROM `{settings.schemas['world']}`.`{table}`)<>{count}
 OR NOT ((SELECT SHA2(COALESCE(GROUP_CONCAT({hashed} ORDER BY BINARY {hashed} SEPARATOR ''),''),256)
     FROM `{settings.schemas['world']}`.`{table}`)<=>'{checksum}') THEN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='World metadata content changed: {table}'; END IF;''')
    values['WORLD_CHECKS'] = eligibility.world_checks(settings.schemas['world'],world) if strong_history_mode else '\n'.join(world_checks)
    if ownership_mode:
        schema = settings.schemas['world']
        names = ','.join("'"+r[0]+"'" for r in world['layout']['tables'])
        layout_checks = f"""IF (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA='{schema}' AND TABLE_NAME IN ({names}))<>{len(world['layout']['columns'])}
 OR NOT ((SELECT SHA2(COALESCE(GROUP_CONCAT(CONCAT_WS(':',TABLE_NAME,COLUMN_NAME,COLUMN_TYPE,IS_NULLABLE,ORDINAL_POSITION,EXTRA)
 ORDER BY BINARY TABLE_NAME,ORDINAL_POSITION SEPARATOR '|'),''),256) FROM information_schema.COLUMNS
 WHERE TABLE_SCHEMA='{schema}' AND TABLE_NAME IN ({names}))<=>'{planner.key_hash(world['layout']['columns'])}')
 OR (SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA='{schema}' AND TABLE_NAME IN ({names}))<>{len(world['layout']['tables'])}
 OR NOT ((SELECT SHA2(COALESCE(GROUP_CONCAT(CONCAT_WS(':',TABLE_NAME,ENGINE,TABLE_TYPE) ORDER BY BINARY TABLE_NAME SEPARATOR '|'),''),256)
 FROM information_schema.TABLES WHERE TABLE_SCHEMA='{schema}' AND TABLE_NAME IN ({names}))<=>'{planner.key_hash(world['layout']['tables'])}') THEN
 SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Ownership world layout or engine drift'; END IF;
"""
        values['WORLD_CHECKS'] = """IF NOT (BINARY @talent_ownership_ack <=> BINARY 'SELECTED_TALENTS_AUTHORITATIVE') THEN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Explicit selected-talent ownership repair acknowledgement required'; END IF;
""" + layout_checks + values['WORLD_CHECKS']
    if foreign_mode:
        values['WORLD_CHECKS'] = """IF NOT (BINARY @talent_foreign_family_ack <=> BINARY 'UNSELECTED_FOREIGN_FAMILIES_ONLY') THEN
 SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Explicit unselected foreign-family acknowledgement required'; END IF;
""" + values['WORLD_CHECKS']
    if prefix_mode:
        values['WORLD_CHECKS'] = """IF NOT (BINARY @talent_native_prefix_ack <=> BINARY 'RETAIN_AUTHORIZED_HIGHER_ANCHORS') THEN
 SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Explicit retained native passive prefix acknowledgement required'; END IF;
""" + values['WORLD_CHECKS']
    if rekey_mode:
        values['WORLD_CHECKS'] = """IF NOT (BINARY @talent_native_rekey_ack <=> BINARY 'ONLY_ALREADY_KNOWN_SELECTED_LOWER_PASSIVES') THEN
 SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Explicit already-known selected lower passive acknowledgement required'; END IF;
""" + values['WORLD_CHECKS']
    if alias_mode:
        values['WORLD_CHECKS'] = """IF NOT (BINARY @talent_aura_alias_ack <=> BINARY 'UNSELECTED_REVIEWED_AURA_ALIASES_ONLY') THEN
 SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Explicit reviewed aura alias acknowledgement required'; END IF;
""" + values['WORLD_CHECKS']
    if config_contract is not None and not two_world_mode:
        values['WORLD_CHECKS'] = """IF NOT (BINARY @ordinary_history_all_spells <=> BINARY '0') THEN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Explicit PlayerStart.AllSpells=0 assertion required for ordinary history v2'; END IF;
""" + values['WORLD_CHECKS']
    if training_prerequisites:
        values['WORLD_CHECKS'] = """IF NOT (BINARY @ordinary_training_ack <=> BINARY 'REVIEWED_TRAINING_PREREQUISITES_ONLY') THEN
 SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Explicit reviewed ordinary training prerequisites acknowledgement required'; END IF;
""" + values['WORLD_CHECKS']
    if native_death_coil:
        values['WORLD_CHECKS'] = """IF NOT (BINARY @ordinary_history_native_base <=> BINARY '47541') THEN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Explicit native Death Coil rank 1 availability assertion required'; END IF;
""" + values['WORLD_CHECKS']
    if two_world_mode:
        ack_var = 'obsolete_riding_ack' if riding_mode else 'specialization_retirement_ack' if specialization_mode else 'profession_activation_ack' if profession_mode else 'skill_teaching_ack' if skill_teaching_mode else 'shaman_dual_wield_ack' if shaman_mode else 'direct_passive_ack' if direct_mode else 'inactive_legacy_ack' if legacy_mode else 'pet_teaching_ack' if pet_mode else 'spell_eligibility_ack'
        native_ack = riding.INVALID_ITEMS_ACK if riding_invalid_items else native_selector.ACK
        config_prefix = 'pet_teaching' if pet_mode else 'eligibility'
        values['WORLD_CHECKS'] = f"""IF NOT (BINARY @{ack_var} <=> BINARY '{native_ack}')
 OR NOT (BINARY @{config_prefix}_tc_all_spells <=> BINARY '0')
 OR NOT (BINARY @{config_prefix}_ac_custom_spells <=> BINARY '0') THEN
 SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Explicit {"pet-teaching" if pet_mode else "eligibility"} repair and native custom-start-off assertions required'; END IF;
""" + eligibility.world_checks(settings.schemas['world'],world) + '\n' + eligibility.world_checks(config_contract['target_world'],target_world)
    if specialization_mode:
        values['WORLD_CHECKS'] = specializations.equipment_guard(settings,equipment,guids) + '\n' + values['WORLD_CHECKS']
    if shaman_mode:
        values['WORLD_CHECKS'] = shaman.inventory_guard(source,inventory_meta) + values['WORLD_CHECKS']
        values['WORLD_CHECKS'] += '\n' + '\n'.join(eligibility.world_checks(w['schema'],w) for w in default_skills.values())
    if riding_mode:
        values['WORLD_CHECKS'] = riding.items_guard(settings,riding_items,guids,native_invalid_items=riding_invalid_items) + values['WORLD_CHECKS']
        values['WORLD_CHECKS'] += '\n' + '\n'.join(eligibility.world_checks(w['schema'],w) for w in riding_defaults.values())
    if direct_mode:
        values['WORLD_CHECKS'] = """IF NOT (BINARY @talent_ownership_ack <=> BINARY 'SELECTED_TALENTS_AUTHORITATIVE') THEN
 SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Explicit selected-talent ownership repair acknowledgement required'; END IF;
""" + values['WORLD_CHECKS']
    if racial_mode:
        values['WORLD_CHECKS'] = """IF NOT (BINARY @eligibility_racials_ack <=> BINARY 'RETIRE_ONLY_REVIEWED_WRONG_RACE_RACIALS') THEN
 SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Explicit reviewed racial retirement acknowledgement required'; END IF;
""" + values['WORLD_CHECKS']
    if absent_teachers:
        values['WORLD_CHECKS'] = """IF NOT (BINARY @eligibility_absent_teachers_ack <=> BINARY 'VERIFIED_TEACHERS_ABSENT') THEN
 SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Explicit absent-teacher eligibility acknowledgement required'; END IF;
""" + values['WORLD_CHECKS']
    if reviewed_cower:
        values['WORLD_CHECKS'] = """IF NOT (BINARY @pet_teaching_cower_ack <=> BINARY 'REVIEWED_COWER_CHILD_ONLY') THEN
 SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Explicit reviewed Cower child acknowledgement required'; END IF;
""" + values['WORLD_CHECKS']
        if pet_teaching.cower_sources(settings.paths) != cower_proof:
            fail('COWER_NATIVE_SOURCE_DRIFT','Cower source contract changed during planning')
    if training_prerequisites and (sha(ROOT/'lib/cleanup_ordinary_history.py') != ordinary_reader
            or sha(ROOT/'lib/cleanup_eligibility.py') != world_guard_reader
            or sha(ROOT/'lib/cleanup_active_reset.py') != numeric_reader):
        fail('ORDINARY_TRAINING_POLICY_DRIFT','Training policy or numeric/world guards changed during planning')
    if (foreign_mode or prefix_mode or alias_mode or rekey_mode) and (sha(ROOT/'lib/cleanup_eligibility.py') != world_guard_reader
            or sha(ROOT/'lib/cleanup_active_reset.py') != numeric_reader):
        fail('OWNERSHIP_REKEY_POLICY_DRIFT' if rekey_mode else 'OWNERSHIP_ALIAS_POLICY_DRIFT' if alias_mode else 'OWNERSHIP_PREFIX_POLICY_DRIFT' if prefix_mode else 'OWNERSHIP_FOREIGN_POLICY_DRIFT',
             'Exact numeric/world guards changed during planning')
    final_effective, final_world = read_world(settings,exact_numeric=exact_mode)
    if metadata(settings,TABLES)!=meta or final_world!=world or final_effective.hashes!=effective.hashes:
        fail('HISTORY_METADATA_DRIFT','Source schema/world metadata changed while planning')
    if ownership_mode and sha(ROOT/'lib/cleanup_ownership.py') != ownership_reader:
        fail('OWNERSHIP_POLICY_DRIFT','Ownership selector changed while planning')
    if two_world_mode:
        final_target, final_target_world = eligibility.read_target(settings)
        if (final_target_world != target_world or final_target.hashes != target_effective.hashes
                or sha(ROOT/'lib/cleanup_eligibility.py') != eligibility_reader
                or racial_mode and sha(eligibility.RACIAL_CATALOG) != racial_catalog
                or pet_mode and sha(ROOT/'lib/cleanup_pet_teaching.py') != pet_reader
                or legacy_mode and sha(ROOT/'lib/cleanup_inactive_legacy.py') != legacy_reader
                or specialization_mode and (sha(ROOT/'lib/cleanup_specializations.py') != specialization_reader
                                            or sha(specializations.CATALOG) != specialization_catalog
                                            or sha(ROOT/'lib/cleanup_professions.py') != profession_reader
                                            or sha(professions.CATALOG) != profession_catalog
                                            or specializations.native_sources(settings.paths) != specialization_native_sources
                                            or specializations.read_equipment(settings,[r[0] for r in context['characters']]) != equipment)
                or profession_mode and (sha(ROOT/'lib/cleanup_professions.py') != profession_reader
                                        or sha(professions.CATALOG) != profession_catalog)
                or skill_teaching_mode and (sha(ROOT/'lib/cleanup_skill_teaching.py') != teaching_reader
                                           or sha(skill_teaching.CATALOG) != teaching_catalog)
                or shaman_mode and (sha(ROOT/'lib/cleanup_shaman_dual_wield.py') != shaman_reader
                                    or shaman.inventory(settings,context) != (inventory_meta,offhand_rows)
                                    or shaman.defaults(settings) != default_skills)
                or riding_mode and (sha(ROOT/'lib/cleanup_obsolete_riding.py') != riding_reader
                                    or sha(riding.CATALOG) != riding_catalog
                                    or riding_invalid_items and sha(riding.ITEM_CATALOG) != riding_item_catalog
                                    or riding.native_sources(settings.paths,native_invalid_items=riding_invalid_items) != riding_sources
                                    or riding.read_items(settings,[r[0] for r in context['characters']],native_invalid_items=riding_invalid_items) != riding_items
                                    or riding.defaults(settings) != riding_defaults)
                or direct_mode and (sha(ROOT/'lib/cleanup_selected_passive.py') != direct_reader
                                    or sha(ROOT/'lib/cleanup_ownership.py') != direct_ownership_reader)):
            fail('ELIGIBILITY_TARGET_DRIFT','Eligibility reader or AC inputs changed during planning')
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
    if config_contract is not None:
        manifest['configuration_contract'] = config_contract
    if training_prerequisites:
        manifest.update(training_prerequisite_proofs=training_proofs,
                        training_prerequisite_ack=ordinary_history.TRAINING_ACK,
                        ordinary_reader_sha256=ordinary_reader,
                        world_guard_reader_sha256=world_guard_reader,
                        numeric_fingerprint='EXACT_FRACTIONAL_V1',
                        numeric_reader_sha256=numeric_reader)
    if native_death_coil:
        manifest['native_base_proofs'] = native_base_proofs
    if include_scripts:
        manifest.update(reviewed_script_bindings=reviewed,
            scripted_selected_rows=sum(row[1] in effective.talents and effective.talents[row[1]][0] in scripted_families for row in selected),
            script_contract='NO_SPELLBOOK_MUTATION; pinned TC AddSpell disabled path; no alternate routes/dependencies/skill effects')
    if selected_mode:
        manifest.update(review_disposition=selected_history.DISPOSITION,selected_rank_rows=len(selected),
            native_policy='Archive only disabled direct ranks selected by neither spec; preserve exact existing character_talent selections in both groups and every selected spell row/flag, skills and login flags; no highest-rank inference, activation or reset',
            script_contract='NO_SPELLBOOK_MUTATION; no mixed ranks, teaching/prerequisite/skill/default routes or enabled unselected sibling')
    if include_relations:
        manifest.update(relation_summary)
        if ordinary_mode:
            manifest['scripted_selected_rows'] = sum(bool(effective.scripts[row[1]]) for row in selected)
        manifest['relationship_state_sha256'] = sha_json(live['relation_spells'])
        manifest['script_contract'] = 'NO_SPELLBOOK_MUTATION on every related member; isolated wholly disabled group; no enabled availability, selected ownership, conflicting incoming routes or skill effects'
        if include_routes:
            manifest['script_contract'] = 'NO_SPELLBOOK_MUTATION; exact reviewed teaching wrappers; wholly disabled removals; shared 674 and skill 118 preserved for inert shaman 30798 root-only exception'
    if foreign_mode:
        manifest.update(foreign_family_ack=ownership.FOREIGN_ACK,numeric_fingerprint='EXACT_FRACTIONAL_V1',
                        numeric_reader_sha256=numeric_reader,world_guard_reader_sha256=world_guard_reader)
    if prefix_mode:
        manifest.update(native_prefix_ack=ownership.PREFIX_ACK,numeric_fingerprint='EXACT_FRACTIONAL_V1',
                        numeric_reader_sha256=numeric_reader,world_guard_reader_sha256=world_guard_reader)
    if alias_mode:
        manifest.update(aura_alias_ack=ownership.AURA_ALIAS_ACK,numeric_fingerprint='EXACT_FRACTIONAL_V1',
                        numeric_reader_sha256=numeric_reader,world_guard_reader_sha256=world_guard_reader)
    if rekey_mode:
        manifest.update(native_rekey_ack=ownership.REKEY_ACK,rekeys=rekeys,rekeys_sha256=values['MAPPING_HASH'],
                        numeric_fingerprint='EXACT_FRACTIONAL_V1',numeric_reader_sha256=numeric_reader,
                        world_guard_reader_sha256=world_guard_reader)
    if ownership_mode:
        manifest['script_contract'] = 'Isolated verified TC talent families; selected runtime routes require correct existing anchors and reviewed native contracts; no skill/profession/default/shared routes'
        manifest['ownership_ack'] = ownership.ACK
        manifest['ownership_reader_sha256'] = ownership_reader
        manifest['native_owner_proofs'] = ownership_native_proofs
    if two_world_mode:
        manifest.update(eligibility_ack=eligibility.ACK,eligibility_reader_sha256=eligibility_reader,
                        target_world_sha256=sha_json(target_world),target_dbc_sha256=target_effective.hashes,
                        numeric_fingerprint='EXACT_FRACTIONAL_V1',
                        numeric_reader_sha256=sha(ROOT/'lib/cleanup_active_reset.py'),
                        script_contract='No removed family script or dependency; both native skill catalogs agree')
    if specialization_mode:
        manifest.update(specialization_ack=specializations.ACK,specialization_reader_sha256=specialization_reader,
                        specialization_catalog_sha256=specialization_catalog,profession_reader_sha256=profession_reader,
                        profession_catalog_sha256=profession_catalog,specialization_equipment=specializations.restricted(equipment,guids),
                        specialization_native_sources=specialization_native_sources,native_policy=relation_summary['native_policy'],
                        script_contract='Fixed inactive competitors only; retain verified active choice; exact equipped item requirements in both worlds')
    if profession_mode:
        manifest.update(profession_activation_ack=professions.ACK,profession_reader_sha256=profession_reader,
                        profession_catalog_sha256=profession_catalog,native_policy=relation_summary['native_policy'],
                        script_contract='Exact ordinary profession ranks only; explicit activation; no SQL spell effects or missing ranks')
    if skill_teaching_mode:
        manifest.update(skill_teaching_ack=skill_teaching.ACK,skill_teaching_reader_sha256=teaching_reader,
                        skill_teaching_catalog_sha256=teaching_catalog,native_policy=relation_summary['native_policy'],
                        script_contract='Exact redundant skill-step teacher; every child has a retained enabled known anchor; skills and recipes preserved')
    if shaman_mode:
        manifest.update(shaman_ack=shaman.ACK,shaman_reader_sha256=shaman_reader,inventory_metadata=inventory_meta,shaman_default_skills=default_skills,
                        native_policy=relation_summary['native_policy'],
                        script_contract='Paired unselected Shaman 674/118 retirement; no alternate native routes; empty off-hand required')
    if riding_mode:
        manifest.update(riding_ack=riding.INVALID_ITEMS_ACK if riding_invalid_items else riding.ACK,riding_reader_sha256=riding_reader,riding_catalog_sha256=riding_catalog,
                        riding_items=riding.restricted(riding_items,guids),riding_default_skills=riding_defaults,
                        riding_native_sources=riding_sources,starting_skill_reader_sha256=sha(ROOT/'lib/cleanup_shaman_dual_wield.py'),
                        native_policy=relation_summary['native_policy'],
                        script_contract='Forbidden Wolf Riding pair only; retain verified modern Riding; item requirements and dependencies checked in both worlds')
    if riding_invalid_items:
        manifest.update(riding_item_catalog_sha256=riding_item_catalog,
                        native_invalid_items_retained=sum(len(p['native_invalid_items_retained']) for p in eligibility_proofs),
                        script_contract='Verified missing-instance references and zero-entry instances retained unchanged; both worlds lack template zero; all valid item requirements checked; unknown nonzero templates defer')
    if direct_mode:
        manifest.update(direct_passive_ack=direct_passive.ACK,direct_passive_reader_sha256=direct_reader,
                        ownership_reader_sha256=direct_ownership_reader,ownership_ack=ownership.ACK,
                        script_contract='Exact selected lower direct passive auras; wrong unselected higher ranks retired; no TC lower-rank reconstruction assumed')
    if legacy_mode:
        manifest.update(inactive_legacy_ack=inactive_legacy.ACK,inactive_legacy_reader_sha256=legacy_reader,
                        script_contract='Exact scriptless singleton legacy catalog; only inactive/non-disabled removals; retained active spells and all native talent/skill data unchanged; no inferred ranks')
    if racial_mode:
        manifest.update(racial_ack=eligibility.RACIAL_ACK,racial_catalog_sha256=racial_catalog,
                        native_policy=relation_summary['native_policy'],
                        script_contract='Four fixed singleton stock racials; verified wrong race; no scripts, dependencies, stored racial skills or grants')
    if absent_teachers:
        manifest.update(absent_teacher_ack=eligibility.ABSENT_TEACHER_ACK,
                        script_contract='No removed family scripts; exact single-child teachers absent in full books; no other dependency')
    if pet_mode:
        manifest.update(pet_teaching_ack=pet_teaching.ACK,pet_teaching_reader_sha256=pet_reader,
                        script_contract='Verified pet-target teaching wrappers only; no scripts, skills, talents or player-learning routes')
    if reviewed_cower:
        manifest.update(cower_ack=pet_teaching.COWER_ACK,cower_native_contract=cower_proof,
                        script_contract='Only exact reviewed Cower child amount callbacks; no wrapper or other child scripts')
    if trained_mode:
        manifest.update(migration_inspection_id=path.name,source_context_sha256=capture_report['source_state_sha256'],
                        reviewed_character_scope=len(context['characters']))
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
    if profession_mode:
        status = status[:status.index('SELECT COUNT(*) AS selected_rows')] + f'''SELECT COUNT(*) selected_rows,
SUM(s.spell IS NOT NULL AND s.active=0 AND s.disabled=0) inactive_rows,
SUM(s.spell IS NOT NULL AND s.active=1 AND s.disabled=0) activated_rows
FROM `{archive}`.expected_spells e LEFT JOIN `{source}`.character_spell s ON s.guid=e.guid AND s.spell=e.spell;
SELECT e.guid,e.spell,e.active AS original_active,s.active AS current_active,s.disabled
FROM `{archive}`.expected_spells e LEFT JOIN `{source}`.character_spell s ON s.guid=e.guid AND s.spell=e.spell
ORDER BY e.guid,e.spell LIMIT 100;
'''
    if shaman_mode:
        status += f'''SELECT a.guid,a.skill,a.value,a.max AS archived_cap,s.skill IS NOT NULL AS still_stored
FROM `{archive}`.character_skills_before a JOIN `{archive}`.affected g ON g.guid=a.guid
LEFT JOIN `{source}`.character_skills s ON s.guid=a.guid AND s.skill=a.skill WHERE a.skill=118 ORDER BY a.guid LIMIT 100;
'''
    if riding_mode:
        status += f'''SELECT a.guid,a.skill,a.value,a.max AS archived_cap,s.skill IS NOT NULL AS still_stored
FROM `{archive}`.character_skills_before a JOIN `{archive}`.affected g ON g.guid=a.guid
LEFT JOIN `{source}`.character_skills s ON s.guid=a.guid AND s.skill=a.skill WHERE a.skill=149 ORDER BY a.guid LIMIT 100;
SELECT s.guid,s.skill,s.value,s.max AS current_cap FROM `{source}`.character_skills s
JOIN `{archive}`.affected g ON g.guid=s.guid WHERE s.skill=762 ORDER BY s.guid LIMIT 100;
'''
    if rekey_mode:
        status += f'''SELECT e.guid,e.from_spell,e.to_spell,s.active,s.disabled
FROM `{archive}`.expected_rekeys e LEFT JOIN `{source}`.character_spell s
ON s.guid=e.guid AND s.spell=e.to_spell ORDER BY e.guid,e.from_spell LIMIT 100;
'''
    rendered = render_text(template,values)
    if specialization_mode:
        rendered = rendered.replace('ineligible ordinary','inactive competing specialization')
    if skill_teaching_mode:
        rendered = rendered.replace('ineligible ordinary','redundant skill-teaching wrapper')
    finish(settings,work,output,manifest,rendered,
           'guid\tspell\tactive\tdisabled\n'+''.join('\t'.join(map(str,row))+'\n' for row in selected),status)
    (output/'excluded-rows.tsv').write_text('guid\tspell\treason\n'+''.join('\t'.join(map(str,row))+'\n' for row in excluded))
    if training_prerequisites:
        write_json(output/'ordinary-training-proof.json',training_proofs)
    if native_death_coil:
        write_json(output/'native-base-review.json',{'policy':policy,'configuration_contract':config_contract,
                   'proofs':native_base_proofs,'sql_spell_rows_inserted':0,'sql_skill_rows_changed':0,
                   'native_availability_change':'Only rank 1 from existing Unholy skill; no higher-rank inference'})
    if rekey_mode:
        (output/'spell-rekeys.tsv').write_text('guid\tfrom_spell\tto_spell\n'+''.join('\t'.join(map(str,row))+'\n' for row in rekeys))
    if ownership_mode:
        write_json(output/'ownership-native-proof.json', ownership_native_proofs)
    if two_world_mode:
        write_json(output/('obsolete-riding-native-proof.json' if riding_mode else 'specialization-native-proof.json' if specialization_mode else 'profession-activation-native-proof.json' if profession_mode else 'skill-teaching-native-proof.json' if skill_teaching_mode else 'shaman-native-proof.json' if shaman_mode else 'selected-passive-native-proof.json' if direct_mode else 'inactive-legacy-native-proof.json' if legacy_mode else 'pet-teaching-native-proof.json' if pet_mode else 'eligibility-native-proof.json'), eligibility_proofs)
        write_json(output/'target-metadata.json',target_world)
    if reviewed_cower:
        write_json(output/'cower-native-contract.json',cower_proof)
    if include_scripts:
        script_family_column = 'ordinary_first_spell' if ordinary_mode else 'talent_entry'
        (output/'scripted-family-review.tsv').write_text(script_family_column+'\tspell\tscript\tstatus\treason\n'+''.join(
            '\t'.join(map(str,(family,spell,name,'DEFERRED' if reason else 'REVIEWED_NO_SPELLBOOK_MUTATION',reason)))+'\n'
            for family,spell,name,reason in bindings))
    if include_relations:
        family_column = 'ordinary_first_spell' if ordinary_mode or two_world_mode else 'talent_entry'
        (output/'relationship-review.tsv').write_text('guid\t'+family_column+'\tspell\trole\tdisposition\tactive\tdisabled\n'+
            ''.join('\t'.join(map(str,r))+'\n' for r in relation_proof))
        selected_nodes = {r[2] for r in relation_proof}
        (output/'relationship-edges.tsv').write_text('parent\tchild\trelationship\n'+''.join(
            '\t'.join(map(str,r))+'\n' for r in relation_edges if r[0] in selected_nodes and r[1] in selected_nodes))
    if selected_mode:
        (output/'selected-rank-review.tsv').write_text('guid\tspell\ttalent_rank\tactive\tdisabled\ttalent_entry\tselected_spell_group_rank\tselected_spell_flags\tdecision\n'+
            ''.join('\t'.join(map(str,r))+'\n' for r in rank_proof))
    write_json(output/'metadata.json',world)
    from cleanup_console import seal
    seal(output)
    if riding_mode:
        print(f'Reviewed {relation_summary["reviewed_candidate_rows"]} obsolete riding candidates; selected {len(selected)} spell/skill pairs; deferred {len(excluded)}; no source changes')
    elif specialization_mode:
        print(f'Reviewed {relation_summary["reviewed_candidate_rows"]} inactive specialization rows; selected {len(selected)} exact competitors; deferred {len(excluded)}; no source changes')
    elif profession_mode:
        print(f'Reviewed {relation_summary["reviewed_candidate_rows"]} inactive profession candidates; selected {len(selected)} existing rows for activation; deferred {len(excluded)}; no source changes')
    elif skill_teaching_mode:
        print(f'Reviewed {relation_summary["reviewed_candidate_rows"]} skill-teaching candidates; selected {len(selected)} exact redundant wrappers; deferred {len(excluded)}; no source changes')
    elif direct_mode:
        print(f'Reviewed {relation_summary["reviewed_candidate_rows"]} talent conflicts; selected {len(selected)} direct passive rows; deferred {len(excluded)}; no source changes')
    elif legacy_mode:
        print(f'Reviewed {relation_summary["reviewed_candidate_rows"]} inactive legacy rows; selected {len(selected)} exact rows; deferred {len(excluded)}; no source changes')
    elif pet_mode:
        print(f'Reviewed {relation_summary["reviewed_candidate_rows"]} pet-teaching candidates; selected {len(selected)} exact player rows; deferred {len(excluded)}; no source changes')
    elif two_world_mode:
        print(f'Reviewed {relation_summary["reviewed_candidate_rows"]} ineligible stored rows; selected {len(selected)} exact rows; deferred {len(excluded)}; no source changes')
    elif ownership_mode:
        print(f'Reviewed {relation_summary["reviewed_candidate_rows"]} conflicting spell candidates; selected {len(selected)} exact rows; deferred {len(excluded)}; no source changes')
    elif ordinary_mode:
        print(f'Reviewed {args.expect_review_rows} disabled ordinary candidates; selected {len(selected)} exact rows; deferred {len(excluded)} candidate rows; no source changes')
    elif child_mode:
        print(f'Reviewed {args.expect_review_rows} disabled talent-child candidates; selected {len(selected)} exact rows; deferred {len(excluded)} candidate rows; no source changes')
    elif trained_mode:
        print(f'Reviewed {args.expect_review_rows} disabled trained rows; selected {len(selected)} exact rows; deferred {len(excluded)} trained rows; no source changes')
    elif include_relations:
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
