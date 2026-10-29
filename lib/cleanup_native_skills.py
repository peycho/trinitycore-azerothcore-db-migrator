"""Explicit preparation policies for absent skills and reviewed Generic
normalization.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Literal, TYPE_CHECKING
import uuid

from cleanup_active_reset import KEYS, TABLES
from cleanup_disabled_history import aggregate, check_sets, read_world
from cleanup_files import PROFILE, ROOT, fail, sha, verify
from cleanup_migration_evidence import FIELDS
from cleanup_plans import (
    finish,
    metadata,
    planner,
    render,
    require_shape,
    sha_json,
    snapshot,
)
import cleanup_racial_skills as racial
from cleanup_trained_history import inspection
from cleanup_types import DatabaseState, DeferredRow, SpellRow
from spells import Unsupported, consumed_teacher_rule

if TYPE_CHECKING:
    from cleanup_config import Settings
    from cleanup_workspace import Workspace
    from spell_metadata import Metadata


POLICY = 'tc-missing-native-skills-v1'
GENERIC_POLICY = 'tc-native-generic-skills-v2'
SWITCH_POLICY = 'tc-known-generic-switch-skill-v3'
SWITCH_ACK = 'KNOWN_SWITCH_SKILL_ONLY'
PENDING_POLICY = 'tc-pending-reset-known-generic-skill-v4'
POLICIES = (POLICY, GENERIC_POLICY, SWITCH_POLICY, PENDING_POLICY,
    racial.POLICY)
ANCHORS = {183: {2382: (25, 60, 0), 63644: (162, 0, 0), 63645: (162, 0, 0)},
    776: {53428: (47, 0, 0), 53341: (53, 3, 0), 53343: (53, 3, 0)}}
NAMES = {'generic': 183, 'runeforging': 776}
GENERIC_SYSTEM_ACTIONS = {2382, 3365, 3050, 6233, 6246, 6247, 6477, 6478, 6603,
    7266, 7267,
    7355, 8386, 9125, 21651, 21652, 22027, 22810, 2479,
    27764, 27762,
    27763, 34082, 45927, 52665, 61437, 63645, 63644,
    68398}


def generic_reward_contract(effective: Metadata) -> list[int] | None:
    """Bound native Generic rewards to reviewed stock system actions only."""
    rewards = set()
    for abilities in effective.abilities.values():
        for a in abilities:
            if a[1] != 183 or a[9] not in (1, 2):
                continue
            s = a[2]
            record = effective.spells.get(s, [])
            if (s not in GENERIC_SYSTEM_ACTIONS or a[9] != 2 or a[8] or a[10]
                or a[11]
                or not record or s in effective.talents or s
                in effective.additional
                or effective.chain(s) != (s,) or effective.requires[s]
                or effective.learns[s] or effective.effect_learns[s]
                or effective.scripts[s]
                or set(record[71:74]) & {36, 40, 44, 47, 118} or set(
                    record[95:98]) & {30, 98}):
                return None
            try:
                effective.check_spell(s)
            except Unsupported:
                return None
            rewards.add(s)
    return sorted(rewards)


def pending_sources(paths: Mapping[str, Path | None]) -> dict[str, str] | None:
    """Pin native reset consumers; this policy never runs or completes a
    reset.
    """
    result = {}
    name = 'src/server/game/Entities/Player/Player.cpp'
    for core, prefix in (('tc', 'trinitycore'), ('ac', 'azerothcore')):
        manifest = ({n.strip(): h for h, n in (line.split(None, 1) for line
            in (PROFILE / (prefix + '-semantic.sha256')).read_text(
            ).splitlines())})
        expected = manifest[name]
        if sha(paths[core + '_source'] / name) != expected:
            fail('PENDING_GENERIC_NATIVE_DRIFT',
                'Native reset consumer differs: ' + core)
        result[core] = {name: expected}
    return result


def select(
    state: DatabaseState,
    effective: Metadata,
    requested: str,
    normalize_generic: bool = False,
    *,
    known_generic_switch: bool = False,
    pending_generic: bool = False,
    known_racials: bool = False,
    target: str = None,
) -> tuple[list[SpellRow], list[DeferredRow], list[tuple[Any, ...]]]:
    """V1 inserts; v2 normalizes Generic; v3 relaxes only switch spec count."""
    if known_racials:
        if (known_generic_switch or pending_generic or normalize_generic
            or requested != ['racial'] or target is None):
            fail('NATIVE_RACIAL_SCOPE',
                'Known-racial policy requires only --skills racial and '
                'both catalogs')
        return racial.select(state, effective, target)
    if 'racial' in requested:
        fail('NATIVE_RACIAL_SCOPE', '--skills racial requires --known-racials')
    if pending_generic:
        known_generic_switch = True
    if (known_generic_switch and (normalize_generic or requested != [
        'generic'])):
        fail('NATIVE_SKILL_POLICY_SCOPE',
            'Known-switch policy inserts absent Generic only; no '
            'normalization or other skills')
    chosen = {NAMES[name] for name in requested}
    generic_rewards = (generic_reward_contract(effective)
        if known_generic_switch else None)
    chars = {r[0]: r for r in state['characters']}
    books, skills = defaultdict(dict), defaultdict(dict)
    for g, s, a, d in state['character_spell']:
        books[g][s] = (a, d)
    for g, s, v, m in state['character_skills']:
        skills[g][s] = (v, m)
    selected, excluded, proof = [], [], []
    for guid, c in sorted(chars.items()):
        _, race, cls, level, active, groups, online, login = c
        if pending_generic and not login & 4:
            continue
        for skill in sorted(chosen):
            original = skills[guid].get(skill)
            if (original is not None and (not normalize_generic or skill
                != 183 or original == (level * 5, level * 5))):
                continue
            anchors = sorted(set(books[guid]) & (set(ANCHORS[skill]) | ({
                63680} if normalize_generic and skill == 183 else set())))
            if pending_generic:
                anchors = [s for s in anchors if s == 2382]
            if not anchors:
                continue
            reason = ''
            if (cls not in (1, 2, 3, 4, 5, 6, 7, 8, 9, 11) or not 1 <= race
                <= 32 or not 1 <= level <= 80 or groups not in (1, 2) or not 0
                <= active < groups):
                reason = 'DEFER_NATIVE_SKILL_CHARACTER_STATE'
            elif ((normalize_generic or known_generic_switch) and len(skills[
                guid]) + (original is None) > 127):
                reason = 'DEFER_NATIVE_SKILL_SLOT_LIMIT'
            elif original is not None and original[0] == 0:
                reason = 'DEFER_ZERO_VALUE_NATIVE_SKILL'
            elif online:
                reason = 'DEFER_ONLINE_CHARACTER'
            elif login & 4 and not pending_generic:
                reason = 'DEFER_PENDING_NATIVE_RESET'
            elif skill == 776 and cls != 6:
                reason = 'DEFER_FOREIGN_CLASS_SKILL'
            elif known_generic_switch and generic_rewards is None:
                reason = 'DEFER_NATIVE_GENERIC_REWARD_CATALOG'
            valid = []
            teacher_proof = None
            for anchor in anchors:
                if reason:
                    break
                flags = books[guid][anchor]
                if flags != (1, 0):
                    continue
                if (anchor in (63644, 63645) and groups != 2
                    and not known_generic_switch):
                    # A switch button alone never establishes dual-spec
                    # ownership.
                    continue
                if anchor == 63680:
                    if groups != 2:
                        continue
                    try:
                        # Preparation proves TC's native load route only.
                        # Supply the proposed
                        # skill to the contract to check mechanics without
                        # mutating source state.
                        teacher_proof = consumed_teacher_rule(anchor, (race,
                            cls, active, groups), flags,
                            {183: (level * 5, level * 5)}, effective,
                            effective, 'tc-to-ac', level)
                    except (Unsupported, KeyError):
                        reason = 'DEFER_NATIVE_SKILL_TEACHER_CONTRACT'; break
                    valid.append((anchor, [], []))
                    continue
                record = effective.spells.get(anchor, [])
                if (not record or tuple(record[71:74]) != ANCHORS[skill][
                    anchor]
                    or record[12] or record[20] or any(record[116:119])
                    or anchor in effective.talents or effective.chain(
                        anchor) != (anchor,)
                    or effective.skill_effect(anchor) is not None
                    or effective.requires[anchor]):
                    reason = 'DEFER_NATIVE_SKILL_SPELL_CONTRACT'
                    break
                if known_generic_switch and anchor in (63644, 63645) and (
                    record[4] & 64 or effective.learns[anchor]
                    or effective.effect_learns[anchor]
                    or effective.scripts[anchor]):
                    reason = 'DEFER_NATIVE_SKILL_SPELL_CONTRACT'
                    break
                try:
                    effective.check_spell(anchor)
                except Unsupported:
                    reason = 'DEFER_NATIVE_SKILL_SPELL_CONTRACT'; break
                abilities = [r for r in effective.abilities[anchor] if r[1]
                    == skill
                    and (not r[3] or r[3] & (1 << (race - 1))) and (not r[4]
                        or r[4] & (1 << (cls - 1)))
                    and (r[9] == 2 or skill == 776 and r[10] == 0)]
                infos = [r for r in effective.stores[
                    'SkillRaceClassInfo'].values() if r[1] == skill
                    and (not r[2] or r[2] & (1 << (race - 1))) and (not r[3]
                        or r[3] & (1 << (cls - 1)))]
                line = effective.stores['SkillLine'].get(skill, [])
                if (not abilities or not infos or not line or line[1] != (12
                    if skill == 183 else 7)
                    or any(r[6] in effective.stores['SkillTiers'] for r
                        in infos)
                    or any(r[6] != 0 for r in infos)
                    or (skill == 183 and any(r[4] != 1170 or (
                        normalize_generic or known_generic_switch) and r[5]
                        != 0
                        for r in infos))
                    or (skill == 776 and any(r[4] != 128 or r[3] != 32
                        for r in infos))):
                    reason = 'DEFER_NATIVE_SKILL_METADATA'
                    break
                valid.append((anchor, sorted(r[0] for r in abilities), sorted(
                    r[0] for r in infos)))
            if not reason and not valid:
                reason = 'DEFER_NO_ENABLED_NATIVE_SKILL_ANCHOR'
            if reason:
                excluded.append((guid, skill, reason))
                continue
            value = level * 5 if skill == 183 else 1
            selected.append((guid, skill, value, value))
            proof.append({'guid': guid, 'skill': skill, 'value': value,
                'cap': value, 'original': 'ABSENT' if original is None
                else list(original),
                'action': 'INSERT' if original is None
                else 'NORMALIZE_GENERIC',
                ** ({'teacher_contract': teacher_proof} if teacher_proof else {
                }),
                'level': level, 'anchors': [{'spell': s, 'flags': [1, 0],
                    'ability_ids': a, 'race_class_ids': r} for s, a, r
                    in valid],
                ** ({'anchor_contract': 'KNOWN_GENERIC_SWITCH_V3',
                    'talent_groups': groups,
                    'active_talent_group': active, 'spec_ownership_change': 0,
                    'native_generic_reward_spells': generic_rewards,
                    'sql_spell_rows_inserted': 0}
                    if known_generic_switch else {}),
                ** ({'pending_native_reset_preserved': True,
                    'anchor_contract': 'KNOWN_GENERIC_2382_PENDING_RESET',
                    'reset_executed': False} if pending_generic else {}),
                'native_policy': 'ALWAYS_MAX_LEVEL_TIMES_FIVE' if skill == 183
                else 'DEATH_KNIGHT_MONO_1_1'})
    return selected, excluded, proof


def render_skill_sql(text: str, values: Mapping[str, Any]) -> str:
    for key in ('SOURCE', 'PRIOR_COUNT', 'INSERT_COUNT'):
        text = text.replace('@' + key + '@', str(values[key]))
    return text


def skill_cells(
    rows: Iterable[Sequence[Any]],
) -> list[tuple[str, int, int, str]]:
    grouped = defaultdict(list)
    for row in sorted(rows):
        # Native character_skills has exactly these four unsigned integer
        # fields.
        value = '|'.join(format(x, 'X') for x in row)
        grouped[row[0]].append(hashlib.sha256(value.encode()).hexdigest())
    return [('character_skills', g, len(items), hashlib.sha256(''.join(
        items).encode()).hexdigest())
        for g, items in sorted(grouped.items())]


def plan_native_skills(
    settings: Settings,
    work: Workspace,
    args: argparse.Namespace,
    output: Path,
) -> Literal[False] | None:
    normalize_generic = getattr(args, 'normalize_generic', False)
    known_racials = getattr(args, 'known_racials', False)
    pending_generic = getattr(args, 'pending_generic', False)
    known_switch = (getattr(args, 'known_generic_switch', False)
        or pending_generic or known_racials)
    native_reset_sources = (pending_sources(settings.paths) if pending_generic
        else None)
    if (known_switch and (normalize_generic or args.skills != (['racial']
        if known_racials else['generic']))):
        fail('NATIVE_SKILL_POLICY_SCOPE',
            '--known-generic-switch is a separate insertion-only policy '
            'requiring --skills generic')
    policy = (racial.POLICY if known_racials else PENDING_POLICY
        if pending_generic else SWITCH_POLICY if known_switch
        else GENERIC_POLICY if normalize_generic else POLICY)
    selector_reader = (sha(ROOT / 'lib/cleanup_native_skills.py')
        if known_switch else None)
    numeric_reader = (sha(ROOT / 'lib/cleanup_active_reset.py')
        if known_switch else None)
    world_reader = (sha(ROOT / 'lib/cleanup_eligibility.py') if known_switch
        else None)
    if normalize_generic and args.skills != ['generic']:
        fail('NATIVE_SKILL_POLICY_SCOPE',
            '--normalize-generic requires --skills generic; existing '
            'other skills are outside this policy')
    if ((not args.preview and not 1 <= (args.expect_rows or 0) <= 10000)
        or len(set(args.skills)) != len(args.skills)):
        fail('NATIVE_SKILL_SELECTION_MISMATCH',
            'Select distinct skill policies and expect between 1 and '
            '10000 skill changes')
    if not args.migration_inspection:
        captures = sorted(p.name for p in (work.session / 'inspections').glob(
            '*-migration-blockers-*') if p.is_dir())
        if not captures:
            fail('MIGRATION_INSPECTION_REQUIRED',
                'Capture a migration blocker context in this session '
                'first')
        args.migration_inspection = captures[-1]
    print('Using migration inspection: ' + args.migration_inspection,
        flush=True)
    (path, _, _, context, audit, captured_world, captured_layout,
        report) = inspection(settings, work, args.migration_inspection)
    effective, world = read_world(settings, exact_numeric=known_switch)
    same_world = (all(world[k] == captured_world[k] for k in ('layout',
        'rows')) if known_switch else world == captured_world)
    if not same_world or effective.hashes != report['dbc_sha256']:
        fail('NATIVE_SKILL_METADATA_DRIFT',
            'Effective TC world/DBC differs from the captured migration '
            'context')
    target = target_world = None
    if known_racials:
        from cleanup_eligibility import read_target
        target, target_world = read_target(settings)
        racial_native_sources = racial.native_sources(settings.paths)
    selected, excluded, proof = select(context, effective, args.skills,
        normalize_generic, known_generic_switch=known_switch
        and not known_racials, pending_generic=pending_generic,
        known_racials=known_racials, target=target)
    prior = ([(p['guid'], p['skill'], *p['original']) for p in proof if p[
        'original'] != 'ABSENT'])
    inserted = len(selected) - len(prior)
    summary = {'inserted_rows': inserted, 'normalized_rows': len(prior),
        'selected_rows': len(selected), 'by_skill': dict(Counter(r[1] for r
            in selected)),
        'deferred': dict(Counter(r[2] for r in excluded)),
        'scope_characters': len(context['characters'])}
    if known_switch:
        summary['native_reward_policy'] = (
            'Reviewed stock Generic actions may be restored at login; '
            'SQL inserts no spells and changes no spec ownership'
        )
    if known_racials:
        summary.update(
            native_racial_rewards='Explicitly restore verified stock racial abilities through '
            'native skill loading; no SQL spell insertion',
            pending_resets_preserved=True)
    if pending_generic:
        summary.update(pending_native_reset_preserved=True,
            reset_executed=False, anchor_spell=2382)
    (work.operation / 'native-skill-review.json').write_text(json.dumps({
        'summary': summary, 'proofs': proof, 'excluded': excluded}, indent=2)
        + '\n')
    print('Native skill review (read-only): ' + json.dumps(summary,
        sort_keys=True), flush=True)
    if args.preview:
        print('PREVIEW: captured evidence only; no SQL package, active batch '
            'or source changes. Details: ' + str(
                work.operation / 'native-skill-review.json'),
            flush=True)
        return False
    if len(selected) != args.expect_rows:
        fail('NATIVE_SKILL_SELECTION_MISMATCH',
            f'Expected {args.expect_rows} skill changes; review selected '
            f'{len(selected)} exact rows',
            'Inspect native-skill-review.json in this operation; no '
            'cleanup package or source changes were made.')
    source = settings.schemas['characters']
    guids = sorted({r[0] for r in selected})
    guid_set = set(guids)
    meta = metadata(settings, TABLES)
    if dict(meta) != captured_layout:
        fail('NATIVE_SKILL_SCHEMA_DRIFT',
            'Source layout differs from captured context')
    for table in TABLES:
        shape = require_shape(meta, table, set(KEYS[table]))
        if {n for n, v in shape.items() if v[2] == 'PRI'} != set(KEYS[table]):
            fail('UNSUPPORTED_SCHEMA', 'Native primary keys required: '
                + table)
    if [r[1:5] for r in meta['columns'] if r[0] == 'character_skills'] != [
        ['guid', 'int unsigned', 'NO', 'PRI'], ['skill', 'smallint unsigned',
            'NO', 'PRI'],
        ['value', 'smallint unsigned', 'NO', ''], ['max', 'smallint unsigned',
            'NO', '']]:
        fail('NATIVE_SKILL_SCHEMA_UNSUPPORTED',
            'New skill rows require exactly the native four columns; '
            'custom skill columns need a reviewed default policy')
    if (len(meta['columns']) > 512 or any('on update' in r[5].lower() for r
        in meta['columns'])):
        fail('UNSUPPORTED_COLUMN',
            'Native skill repair requires at most 512 columns without '
            'automatic updates')
    scope = ','.join(str(r[0]) for r in context['characters'])
    selector = ','.join(map(str, guids))
    queries = []
    for table, fields in FIELDS.items():
        cols = ','.join('`' + f + '`' for f in fields)
        order = ','.join(KEYS[table])
        queries.append(('context_' + table,
            f'SELECT JSON_ARRAY({cols}) row_value FROM `{source}`.`{table}` '
            f'WHERE guid IN ({scope}) ORDER BY {order} LIMIT 5000001'))
    for table in TABLES:
        query = aggregate(meta, table, source, f's.guid IN ({selector})',
            exact_numeric=known_switch)
        queries.append(('sets',
            f"SELECT JSON_ARRAY('{table}',guid,n,h) row_value FROM ({query}) "
            'a ORDER BY guid'))
    live = snapshot(settings, queries,
        session_prefix="SET SESSION time_zone='+00:00';\nSET SESSION "
        'group_concat_max_len=6400001;\n')
    # Capture order is guid/talentGroup/spell; the key hash uses
    # guid/spell/group.
    if any(sorted(live['context_' + table]) != sorted(context[table])
        for table in FIELDS):
        fail('NATIVE_SKILL_INPUT_DRIFT',
            'Complete captured semantic source state changed; capture a '
            'new blocker context')
    cells = sorted(tuple(r) for r in live['sets'])
    old_skills = [r for r in context['character_skills'] if r[0] in guid_set]
    if (skill_cells(old_skills) != [r for r in cells if r[0]
        == 'character_skills']):
        fail('NATIVE_SKILL_INPUT_DRIFT',
            'Native skill row fingerprints differ from captured numeric '
            'fields')
    selected_keys = {(r[0], r[1]) for r in selected}
    after = skill_cells([r for r in old_skills if (r[0], r[1]) not
        in selected_keys] + [list(r) for r in selected])
    counts = ({table: sum(r[2] for r in cells if r[0] == table) for table
        in TABLES})
    if (counts['characters'] != len(guids) or sum(counts.values()) > 5000000
        or any(r[2] > 10000 or not re.fullmatch('[a-f0-9]{64}', str(r[3]))
            for r in cells + after)):
        fail('NATIVE_SKILL_SNAPSHOT_BOUND',
            'Full affected snapshots exceed safe bounds or lack valid '
            'digests')
    template = (ROOT / ('tools/native-generic-repair.sql.in'
        if normalize_generic else 'tools/native-skill-repair.sql.in'))
    inspection_sha = sha(path / 'SHA256SUMS')
    batch = sha_json({'policy': policy, 'inspection': inspection_sha,
        'selected': selected, 'proof': proof, 'world': world, 'metadata': meta,
        'template': sha(template), 'id': output.name,
        ** ({'selector': selector_reader,
            'numeric_reader': numeric_reader, 'world_reader': world_reader}
            if known_switch else {})})
    archive = 'tc_native_skills_' + uuid.uuid4().hex[:20]
    blocks = check_sets(meta, source, archive, counts,
        changed_table='character_skills', exact_numeric=known_switch)
    values = {'SOURCE': source, 'ARCHIVE': archive, 'UUID': work.current()[
        'identity']['uuid'], 'BATCH': batch,
        'AUDIT': report['source_state_sha256'], 'COUNT': len(selected),
        'GUID_COUNT': len(guids),
        'EXPECTED_HASH': planner.key_hash(selected), 'SNAPSHOT_COUNT': len(
            cells), 'SNAPSHOT_HASH': planner.key_hash(cells),
        'COLUMN_COUNT': len(meta['columns']), 'COLUMN_HASH': planner.key_hash(
            meta['columns']),
        'CONCAT_LIMIT': max(6400001, len(cells) * 160, len(selected) * 80, len(
            meta['columns']) * 2048),
        'EXPECTED_INSERT': planner.insert_values('expected_skills', selected),
        'SNAPSHOT_INSERT': planner.insert_values('expected_snapshot', cells),
        'AFTER_INSERT': planner.insert_values('expected_after', after),
        'AFTER_COUNT': len(after), 'AFTER_HASH': planner.key_hash(after),
        'COLUMN_INSERT': planner.insert_values('reviewed_columns', meta[
            'columns']), 'GUID_INSERT': planner.insert_values('affected', [(g,)
                for g in guids]),
        'CHECK_ORIGINAL': blocks['original'], 'CHECK_ARCHIVE': blocks[
            'archive'], 'CHECK_APPLIED': blocks['applied'],
        'ARCHIVE_INSERT': '\n'.join(
            f'  INSERT INTO {table}_before SELECT s.* FROM `{source}`.{table}'
            ' s JOIN affected g ON g.guid=s.guid;' for table in TABLES)}
    if normalize_generic:
        values.update({'PRIOR_INSERT': planner.insert_values('expected_prior',
            prior) if prior else '',
            'PRIOR_COUNT': len(prior), 'PRIOR_HASH': planner.key_hash(prior)
            if prior else hashlib.sha256(b'').hexdigest(),
            'INSERT_COUNT': inserted,
            'APPLY_UPDATE': (
                '''  UPDATE `@SOURCE@`.character_skills s JOIN expected_prior p ON p.guid=s.guid AND p.skill=s.skill
   JOIN expected_skills e ON e.guid=s.guid AND e.skill=s.skill SET s.value=e.value,s.max=e.cap;
  IF ROW_COUNT()<>@PRIOR_COUNT@ THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Generic normalization count differs'; END IF;''' if prior else ''),
            'APPLY_INSERT': (
                '''  INSERT INTO `@SOURCE@`.character_skills(guid,skill,value,max)
   SELECT e.guid,e.skill,e.value,e.cap FROM expected_skills e LEFT JOIN expected_prior p ON p.guid=e.guid AND p.skill=e.skill
   WHERE p.guid IS NULL ORDER BY e.guid,e.skill;
  IF ROW_COUNT()<>@INSERT_COUNT@ THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Native skill insertion count differs'; END IF;''' if inserted else ''),
            'RESTORE_UPDATE': (
                '''  UPDATE `@SOURCE@`.character_skills s JOIN expected_prior p ON p.guid=s.guid AND p.skill=s.skill SET s.value=p.value,s.max=p.cap;
  IF ROW_COUNT()<>@PRIOR_COUNT@ THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Generic inverse update count differs'; END IF;''' if prior else ''),
            'RESTORE_DELETE': (
                '''  DELETE s FROM `@SOURCE@`.character_skills s JOIN expected_skills e ON e.guid=s.guid AND e.skill=s.skill
   LEFT JOIN expected_prior p ON p.guid=e.guid AND p.skill=e.skill WHERE p.guid IS NULL;
  IF ROW_COUNT()<>@INSERT_COUNT@ THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Native skill inverse deletion count differs'; END IF;''' if inserted else '')})
        # Render nested SQL fragments before the enclosing template, in a fixed
        # order.
        for key in ('APPLY_UPDATE', 'APPLY_INSERT', 'RESTORE_UPDATE',
            'RESTORE_DELETE'):
            values[key] = render_skill_sql(values[key], values)
    checks = []
    if normalize_generic:
        names = ','.join("'" + row[0] + "'" for row in world['layout'][
            'tables'])
        column_hash = planner.key_hash(world['layout']['columns'])
        table_hash = planner.key_hash(world['layout']['tables'])
        schema = settings.schemas['world']
        checks.append(
            f""" IF (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA='{schema}' AND TABLE_NAME IN ({names}))<>{len(world['layout']['columns'])}
 OR NOT ((SELECT SHA2(COALESCE(GROUP_CONCAT(CONCAT_WS(':',TABLE_NAME,COLUMN_NAME,COLUMN_TYPE,IS_NULLABLE,ORDINAL_POSITION,EXTRA)
     ORDER BY BINARY TABLE_NAME,ORDINAL_POSITION SEPARATOR '|'),''),256) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA='{schema}' AND TABLE_NAME IN ({names}))<=>'{column_hash}')
 OR (SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA='{schema}' AND TABLE_NAME IN ({names}))<>{len(world['layout']['tables'])}
 OR NOT ((SELECT SHA2(COALESCE(GROUP_CONCAT(CONCAT_WS(':',TABLE_NAME,ENGINE,TABLE_TYPE) ORDER BY BINARY TABLE_NAME SEPARATOR '|'),''),256)
     FROM information_schema.TABLES WHERE TABLE_SCHEMA='{schema}' AND TABLE_NAME IN ({names}))<=>'{table_hash}') THEN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Native skill world layout or engine drift'; END IF;""")
    for table, count, checksum in world['digests']:
        fields = [r[1] for r in world['layout']['columns'] if r[0] == table]
        hashed = ("SHA2(CONCAT_WS('|'," + ','.join(f"IFNULL(HEX(`{f}`),'N')"
            for f in fields) + '),256)')
        checks.append(
            f" IF (SELECT COUNT(*) FROM `{settings.schemas['world']}`.`"
            f'{table}`)<>{count} OR NOT ((SELECT SHA2(COALESCE(GROUP_CONCAT('
            f"{hashed} ORDER BY BINARY {hashed} SEPARATOR ''),''),256) FROM `"
            f"{settings.schemas['world']}`.`{table}`)<=>'{checksum}') THEN "
            "SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Native skill world "
            "input drift'; END IF;")
    values['ALLOWED_SKILLS'] = ('101,125,126,754' if known_racials
        else '183,776')
    values['RESET_STATE_TEST'] = ('0' if known_racials
        else '(c.at_login & 4)=0' if pending_generic
        else '(c.at_login & 4)<>0')
    values['WORLD_CHECKS'] = '\n'.join(checks)
    if known_switch:
        from cleanup_eligibility import world_checks
        values[
            'WORLD_CHECKS'] = """IF NOT (BINARY @native_generic_switch_ack <=> BINARY 'KNOWN_SWITCH_SKILL_ONLY') THEN
 SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Explicit known Generic switch-skill acknowledgement required'; END IF;
""" + world_checks(settings.schemas['world'], world)
        if (sha(ROOT / 'lib/cleanup_native_skills.py') != selector_reader
            or sha(ROOT / 'lib/cleanup_active_reset.py') != numeric_reader
            or sha(ROOT / 'lib/cleanup_eligibility.py') != world_reader):
            fail('NATIVE_SWITCH_POLICY_DRIFT',
                'Native switch-skill policy or exact numeric/world '
                'guards changed during planning')
    if known_racials:
        from cleanup_eligibility import read_target, world_checks
        values['WORLD_CHECKS'] = (
            "IF NOT (BINARY @native_racial_skills_ack <=> BINARY '"
            f"{racial.ACK}') OR NOT (BINARY @eligibility_tc_all_spells "
            "<=> BINARY '0') OR NOT (BINARY "
            "@eligibility_ac_custom_spells <=> BINARY '0') THEN SIGNAL "
            "SQLSTATE '45000' SET MESSAGE_TEXT='Explicit native racial "
            "skill/reward acknowledgement required'; END IF;\n"
        ) + world_checks(settings.schemas['world'], world) + world_checks(
            settings.get('target', 'world'), target_world)
        final_target, final_target_world = read_target(settings)
        if (final_target.hashes != target.hashes or final_target_world
            != target_world or racial.native_sources(settings.paths)
            != racial_native_sources):
            fail('NATIVE_RACIAL_METADATA_DRIFT',
                'Racial target metadata or native consumers changed')
    final_effective, final_world = read_world(settings,
        exact_numeric=known_switch)
    if (metadata(settings, TABLES) != meta or final_world != world
        or final_effective.hashes != effective.hashes or sha(
            path / 'SHA256SUMS') != inspection_sha):
        fail('NATIVE_SKILL_METADATA_DRIFT',
            'Source metadata or sealed context changed while planning')
    verify(path)
    manifest = {'policy': policy, 'archive_schema': archive,
        'batch_key': batch, 'selected_rows': len(selected),
        'affected_characters': len(guids), 'character_guids': guids,
        'inspection_id': path.name, 'inspection_sha256': inspection_sha,
        'audit_sha256': report['source_state_sha256'],
        'world_sha256': sha_json(world),
        'semantic_dbc_sha256': effective.hashes,
        'dbc_sha256': {name.removeprefix('tc.'): h for name, h
            in effective.hashes.items()}, 'metadata_profile_sha256': sha(
                PROFILE / 'spell-metadata.json'),
        'expected_sha256': values['EXPECTED_HASH'], 'template_sha256': sha(
            template), 'archived_rows': counts,
        'inserted_rows': inserted, 'normalized_rows': len(prior),
        'requested_skills': args.skills, 'skill_counts': summary['by_skill'],
        'excluded_rows': len(excluded), 'excluded_reason_counts': summary[
            'deferred'],
        'native_skill_proofs': proof, 'skill_policy': (
            'Normalize only reviewed Generic 183 to native level*5; '
            'insert justified absent Generic; no other '
            'skill/spell/talent changes'
            if normalize_generic
            else 'Insert absent reviewed native skill rows only; no updates '
            'to existing skills, no spell or talent changes')}
    if known_switch:
        manifest.update(native_switch_ack=SWITCH_ACK,
            native_skill_reader_sha256=selector_reader,
            numeric_fingerprint='EXACT_FRACTIONAL_V1',
            numeric_reader_sha256=numeric_reader,
            world_guard_reader_sha256=world_reader,
            skill_policy='Insert absent Generic only from verified enabled known '
            'spells; switch buttons do not require two specs for native '
            'skill acquisition; no spec, talent, spell or existing skill '
            'changes')
    if known_racials:
        manifest.update(native_racial_ack=racial.ACK, racial_reader_sha256=sha(
            ROOT / 'lib/cleanup_racial_skills.py'), racial_catalog_sha256=sha(
                racial.CATALOG), racial_native_sources=racial_native_sources,
            target_world_sha256=sha_json(target_world),
            target_dbc_sha256=target.hashes,
            skill_policy='Insert only verified absent native racial skills from '
            'existing legitimate known anchors; explicitly allow exact '
            'stock racial rewards at login; no SQL spell insertion or '
            'talent/skill/flag rewrite')
    if pending_generic:
        manifest.update(pending_native_sources=native_reset_sources,
            skill_policy='Insert absent Generic 183 only from enabled known 2382 '
            'while retaining pending native reset bit and all ownership, '
            'spells, other skills and character state; no login/reset '
            'executed')
    status = (
        f'SELECT * FROM `{archive}`.batch;\nSELECT e.*,s.value '
        f'current_value,s.max current_cap FROM `{archive}'
        f'`.expected_skills e LEFT JOIN `{source}`.character_skills s ON '
        's.guid=e.guid AND s.skill=e.skill ORDER BY e.guid,e.skill;\n'
    )
    if normalize_generic:
        status = (f'SELECT * FROM `{archive}`.batch;\nSELECT '
            "e.guid,e.skill,IF(p.guid IS NULL,'INSERT','NORMALIZE_GENERIC') "
            'action,p.value original_value,p.cap original_cap,e.value '
            'expected_value,e.cap expected_cap,s.value current_value,s.max '
            f'current_cap FROM `{archive}`.expected_skills e LEFT JOIN `'
            f'{archive}`.expected_prior p ON p.guid=e.guid AND '
            f'p.skill=e.skill LEFT JOIN `{source}`.character_skills s ON '
            's.guid=e.guid AND s.skill=e.skill ORDER BY e.guid,e.skill;\n')
    tsv = ('guid\tskill\told_value\told_cap\tnew_value\tnew_cap\taction\n'
        + ''.join('\t'.join(map(str, (p['guid'], p['skill'], * (('ABSENT',
            'ABSENT') if p['original'] == 'ABSENT' else p['original']), p[
                'value'],
            p['cap'], p['action']))) + '\n' for p in proof))
    finish(settings, work, output, manifest, render(template, values), tsv,
        status, 'skill_cleanup_ack')
    # Extra diagnostics are part of the same sealed candidate, never an apply
    # selection by themselves.
    from cleanup_files import seal
    (output / 'excluded-rows.tsv').write_text('guid\tskill\treason_code\n'
        + ''.join('\t'.join(map(str, r)) + '\n' for r in excluded))
    (output / 'native-skill-proof.json').write_text(json.dumps(proof,
        indent=2) + '\n')
    seal(output)
