"""Exact live state and projected post-repair fingerprints."""
from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from cleanup_active_reset import KEYS, TABLES, columns
from cleanup_disabled_history import (
    MAX_GUIDS,
    MAX_PER_GUID,
    aggregate,
    enabled_ids_query,
    retirement_join,
)
from cleanup_files import fail
from cleanup_history_models import (
    HistoryEvidence,
    HistoryOptions,
    HistoryPolicy,
    HistorySelection,
    HistorySnapshot,
)
from cleanup_plans import metadata, require_shape, sha_json, snapshot
import cleanup_talent_relations as relations

if TYPE_CHECKING:
    from cleanup_config import Settings


def capture_history_snapshot(
    settings: Settings,
    evidence: HistoryEvidence,
    options: HistoryOptions,
    selection: HistorySelection,
    policy: HistoryPolicy,
) -> HistorySnapshot:
    live = None
    print('Fingerprinting complete spell/talent/skill/character state for '
        f'{len(selection.guids)} characters (read-only)', flush=True)
    selector = ','.join(map(str, selection.guids))
    source = settings.schemas['characters']
    meta = metadata(settings, TABLES)
    if options.trained_mode and dict(meta) != evidence.captured_layout:
        fail('HISTORY_SCHEMA_DRIFT',
            'Source layout differs from the captured migration context')
    inspected_meta = {key: [row for row in value if row[0] in ('characters',
        'character_talent', 'character_spell')]
        for key, value in meta.items()}
    if sha_json(inspected_meta) != evidence.report.get('metadata_sha256'):
        fail('HISTORY_SCHEMA_DRIFT',
            'Source columns differ from the retained inspection')
    for table in TABLES:
        shape = require_shape(meta, table, set(KEYS[table]))
        if ({name for name, value in shape.items() if value[2] == 'PRI'}
            != set(KEYS[table])):
            fail('UNSUPPORTED_SCHEMA', 'Native primary keys required: '
                + table)
    if (len(meta['columns']) > 512 or any('on update' in row[5].lower()
        for row in meta['columns'])):
        fail('UNSUPPORTED_COLUMN',
            'History policy requires at most 512 columns without '
            'automatic updates')
    if (options.parent_mode and set(columns(meta, 'character_spell')) != {
        'guid', 'spell', 'active', 'disabled'}):
        fail('UNSUPPORTED_PARENT_COLUMNS',
            'Parent-specialization repair requires stock character_spell '
            'columns')
    if (options.rekey_mode and set(columns(meta, 'character_spell')) != {
        'guid', 'spell', 'active', 'disabled'}):
        fail('UNSUPPORTED_REKEY_COLUMNS',
            'Passive rekey requires stock character_spell columns; '
            'custom spell-specific fields require separate review')
    queries = []
    for table in TABLES:
        query = aggregate(meta, table, source, f's.guid IN ({selector})',
            exact_numeric=options.exact_mode)
        queries.append(('sets',
            f"SELECT JSON_ARRAY('{table}',guid,n,h) row_value FROM ({query}) "
            'a ORDER BY guid'))
    # Exact live inspection inputs reject same-count ownership/flags changes.
    scope = (' WHERE guid IN (' + ','.join(str(r[0]) for r in evidence.context[
        'characters']) + ')' if options.trained_mode else '')
    for label, fields, table in (
        ('characters',
            'guid,race,class,activeTalentGroup,talentGroupsCount,online,at_login',
            'characters'),
        ('talents', 'guid,spell,talentGroup', 'character_talent')):
        queries.append((label,
            f'SELECT JSON_ARRAY({fields}) row_value FROM `{source}`.{table}'
            f'{scope} ORDER BY {fields}'))
    catalog = ','.join(map(str, sorted(evidence.effective.talents)))
    queries.append(('spells',
        'SELECT JSON_ARRAY(guid,spell,active,disabled) row_value FROM `'
        f'{source}`.character_spell WHERE spell IN ({catalog})' + (' AND'
            + scope.removeprefix(' WHERE') if options.trained_mode else '')
        + ' ORDER BY guid,spell'))
    queries.append(('enabled_ids', enabled_ids_query(source)))
    if policy.include_relations:
        queries.append(('relation_spells', relations.stored_query(source,
            selection.guids)))
    if options.trained_mode:
        from cleanup_migration_evidence import FIELDS
        for table, fields in FIELDS.items():
            column_sql = ','.join('`' + field + '`' for field in fields)
            keys = ({'characters': 'guid', 'character_spell': 'guid,spell',
                'character_talent': 'guid,talentGroup,spell',
                'character_skills': 'guid,skill'} [table])
            queries.append(('context_' + table,
                f'SELECT JSON_ARRAY({column_sql}) row_value FROM `{source}`.`'
                f'{table}`{scope} ORDER BY {keys} LIMIT '
                f'{relations.MAX_ROWS + 1}'))
    # Project exact per-character removals with one bounded key relation.
    # Large OR trees made whole-snapshot planning quadratic in character count.
    retired_join = retirement_join(selection.selected)
    remaining = f's.guid IN ({selector}) AND retired.guid IS NULL'
    query = aggregate(meta, 'character_spell', source, remaining,
        exact_numeric=options.exact_mode, join=retired_join)
    if options.rekey_mode:
        # Hash projected stock rows in NEW-key order. Materialize one bounded
        # mapping relation rather than evaluating every mapping for every row.
        mapping_json = json.dumps(selection.rekeys, separators= (',', ':'))
        mapped = 'COALESCE(rekey.to_spell,s.`spell`)'
        join = (
            f"LEFT JOIN JSON_TABLE('{mapping_json}','$[*]' COLUMNS(guid INT "
            "UNSIGNED PATH '$[0]',from_spell INT UNSIGNED PATH "
            "'$[1]',to_spell INT UNSIGNED PATH '$[2]')) rekey ON "
            'rekey.guid=s.guid AND rekey.from_spell=s.spell')
        query = aggregate(meta, 'character_spell', source,
            f's.guid IN ({selector})', exact_numeric=True, join=join)
        query = query.replace('s.`spell`', mapped)
    if options.profession_mode:
        pairs = json.dumps([[r[0], r[1]] for r in selection.selected],
            separators= (',', ':'))
        join = (f"LEFT JOIN JSON_TABLE('{pairs}','$[*]' COLUMNS(guid INT "
            "UNSIGNED PATH '$[0]',spell INT UNSIGNED PATH '$[1]')) activate "
            'ON activate.guid=s.guid AND activate.spell=s.spell')
        query = aggregate(meta, 'character_spell', source,
            f's.guid IN ({selector})', exact_numeric=True, join=join)
        query = query.replace('s.`active`',
            'IF(activate.guid IS NULL,s.`active`,1)')
    if options.parent_mode:
        parent_ids = json.dumps(selection.guids, separators= (',', ':'))
        parents = (
            "SELECT p.guid,9787 spell,1 active,0 disabled FROM JSON_TABLE('"
            f"{parent_ids}','$[*]' COLUMNS(guid INT UNSIGNED PATH '$')) p")
        projected_source = (
            f'(SELECT s.guid,s.spell,s.active,s.disabled FROM `{source}'
            f'`.character_spell s {retired_join} WHERE {remaining} UNION ALL '
            f'{parents})')
        query = aggregate(meta, 'character_spell', source,
            f's.guid IN ({selector})', exact_numeric=True)
        query = query.replace(f'`{source}`.`character_spell` s',
            projected_source + ' s')
    queries.append(('after',
        "SELECT JSON_ARRAY('character_spell',guid,n,h) row_value FROM ("
        f'{query}) a ORDER BY guid'))
    if options.foreign_skill_mode:
        skill_projection = json.dumps([[g, k] for g, k, v, c
            in selection.retired_skill_rows], separators= (',', ':'))
        skill_join = (
            "LEFT JOIN (SELECT DISTINCT k.guid,k.skill FROM JSON_TABLE('"
            f"{skill_projection}','$[*]' COLUMNS(guid INT UNSIGNED PATH "
            "'$[0]',skill SMALLINT UNSIGNED PATH '$[1]')) k) retired_skills "
            'ON retired_skills.guid=s.guid AND retired_skills.skill=s.skill')
        query = aggregate(meta, 'character_skills', source,
            f's.guid IN ({selector}) AND retired_skills.guid IS NULL',
            exact_numeric=True, join=skill_join)
        queries.append(('after',
            "SELECT JSON_ARRAY('character_skills',guid,n,h) row_value "
            f'FROM ({query}) a ORDER BY guid'))
    if options.shaman_mode or options.riding_mode:
        retired_skill = ((148 if options.riding_horse else 149)
            if options.riding_mode else 118)
        query = aggregate(meta, 'character_skills', source,
            f's.guid IN ({selector}) AND s.skill<>{retired_skill}',
            exact_numeric=True)
        queries.append(('after',
            "SELECT JSON_ARRAY('character_skills',guid,n,h) row_value "
            f'FROM ({query}) a ORDER BY guid'))
    # Each digest is bounded per character, not one concatenation of millions
    # of source rows. Counts are checked before any executable package exists.
    live = snapshot(
        settings, queries,
        session_prefix="SET SESSION time_zone='+00:00';\nSET SESSION "
        'group_concat_max_len=640001;\n',
    )
    if any(live[label] != evidence.state[label] for label in ('characters',
        'talents', 'spells', 'enabled_ids')):
        fail('HISTORY_INPUT_DRIFT',
            'Live ownership/character state/direct spell flags differ '
            'from inspection',
            'Retain this inspection. After source edits, run a new full '
            'audit and inspection; no preflight is needed.')
    if (options.trained_mode and any(live['context_' + table]
        != evidence.context[table] for table in evidence.context)):
        fail('HISTORY_INPUT_DRIFT',
            'Full semantic source context changed; capture a new migration '
            'blocker inspection before planning')
    if (policy.include_relations and live['relation_spells'] != [r for r
        in selection.relation_rows if r[0] in selection.guid_set]):
        fail('HISTORY_INPUT_DRIFT',
            'Related spell keys/flags changed between relationship review '
            'and full-row fingerprinting')
    cells = sorted(tuple(row) for row in live['sets'])
    after = sorted(tuple(row) for row in live['after'])
    if (any(row[2] > MAX_PER_GUID or not isinstance(row[3], str)
        or not re.fullmatch('[a-f0-9]{64}', row[3]) for row in cells
        + after)
        or len(cells) > 4 * MAX_GUIDS):
        fail('HISTORY_SNAPSHOT_BOUND',
            'Snapshot exceeds 10000 rows per character/table or 40000 '
            'characters')
    counts = ({table: sum(row[2] for row in cells if row[0] == table)
        for table in TABLES})
    if (counts['characters'] != len(selection.guids) or sum(counts.values(
    )) > 5_000_000):
        fail('HISTORY_SNAPSHOT_BOUND',
            'Missing affected characters or more than 5000000 archived '
            'rows')
    return HistorySnapshot(
        after=after,
        cells=cells,
        counts=counts,
        live=live,
        meta=meta,
        source=source,
    )
