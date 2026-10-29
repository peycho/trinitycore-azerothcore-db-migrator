"""Bounded, read-only context for a saved first-failure migration report."""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Sequence
import csv
import io
import json
from pathlib import Path
import re
import tarfile
from typing import Any, TYPE_CHECKING

from cleanup_disabled_history import read_world
from cleanup_files import (
    PROFILE,
    fail,
    now,
    private_dir,
    seal,
    sha,
    token,
    write_json,
)
from cleanup_plans import metadata, require_shape, sha_json, snapshot
from cleanup_types import DatabaseRow, Evidence

if TYPE_CHECKING:
    from cleanup_config import Settings
    from cleanup_workspace import Workspace


MAX_BYTES, MAX_CHARACTERS, MAX_ROWS = 128 * 1024 * 1024, 40000, 5000000
FIELDS = {
    'characters': ['guid', 'race', 'class', 'level', 'activeTalentGroup',
        'talentGroupsCount', 'online', 'at_login'],
    'character_spell': ['guid', 'spell', 'active', 'disabled'],
    'character_talent': ['guid', 'spell', 'talentGroup'],
    'character_skills': ['guid', 'skill', 'value', 'max'],
}


def read_report(path: Path) -> tuple[Evidence, list[DatabaseRow]]:
    path = Path(path)
    if not path.is_file() or path.stat().st_size > MAX_BYTES:
        fail('BLOCKER_REPORT_INVALID',
            'Expected a readable blocker TSV no larger than 128 MiB')
    data = path.read_bytes()
    if len(data) > MAX_BYTES:
        fail('BLOCKER_REPORT_INVALID', 'Blocker report exceeds 128 MiB')
    try:
        reader = csv.reader(io.StringIO(data.decode('utf-8')), delimiter='\t',
            strict=True)
        if next(reader, []) != ['guid', 'spell', 'reason_code', 'detail']:
            fail('BLOCKER_REPORT_INVALID',
                'Expected guid/spell/reason_code/detail TSV header')
        rows, seen = [], set()
        for number, row in enumerate(reader, 2):
            if (len(row) != 4 or not re.fullmatch('[1-9][0-9]{0,9}', row[0])
                or int(row[0]) > 0xffffffff or row[0] in seen
                or not re.fullmatch('\\*|[1-9][0-9]{0,9}', row[1])
                or (row[1] != '*' and int(row[1]) > 0xffffffff)
                or not re.fullmatch('[A-Z][A-Z0-9_]{0,79}', row[2])
                or len(row[3]) > 16384 or any(ord(c) < 32 for c in row[
                    3])):
                fail('BLOCKER_REPORT_INVALID',
                    'Invalid or duplicate first-character failure at TSV '
                    f'row {number}')
            seen.add(row[0])
            rows.append(row)
            if len(rows) > MAX_CHARACTERS:
                fail('BLOCKER_REPORT_BOUND',
                    'Blocker context is bounded to 40000 characters')
    except (UnicodeError, csv.Error):
        fail('BLOCKER_REPORT_INVALID',
            'Blocker TSV must contain valid UTF-8 and four columns per '
            'row')
    if not rows:
        fail('BLOCKER_REPORT_EMPTY',
            'The report contains no blocker rows to inspect')
    return data, rows


def groups(rows: Sequence[Sequence[Any]]) -> list[tuple[Any, ...]]:
    counts = Counter()
    for guid, spell, reason, detail in rows:
        anchor = re.match('^(?:(?:tc|ac):\\s*)?([1-9][0-9]*)(?=:|\\s|$)',
            detail)
        flags = re.search('stored_flags=\\(([01]), ([01])\\)', detail)
        counts[reason, anchor[1] if anchor else spell,
            flags[1] if flags else '', flags[2] if flags else '',
            detail] += 1
    return ([(*key, count) for key, count in sorted(counts.items(),
        key=lambda pair: (pair[0][0], -pair[1], pair[0][1:]))])


def inspect(
    settings: Settings,
    work: Workspace,
    args: argparse.Namespace,
) -> Path:
    settings.check_paths()
    all_characters = getattr(args, 'all_characters', False)
    if all_characters:
        source = settings.schemas['characters']
        guids = [int(row) for row in settings.sql(
            f'SELECT guid FROM `{source}`.characters ORDER BY guid LIMIT '
            f'{MAX_CHARACTERS + 1};').splitlines()]
        if (not guids or len(guids) > MAX_CHARACTERS or any(not 1 <= g
            <= 0xffffffff for g in guids)):
            fail('BLOCKER_REPORT_BOUND',
                'Whole-source preparation requires 1-40000 native '
                'character keys')
        rows = ([[str(g), '*', 'PREPARATION_SCOPE',
            'Whole-source review; not a migration failure'] for g in guids])
        data = ('guid\tspell\treason_code\tdetail\n' + ''.join('\t'.join(r)
            + '\n' for r in rows)).encode()
    else:
        data, rows = read_report(args.report)
    output = work.session / 'inspections' / token('migration-blockers')
    private_dir(output)
    (output / 'INCOMPLETE').touch()
    print('Read-only blocker context; reports: ' + str(output), flush=True)
    (output / 'spell-state-blockers.tsv').write_bytes(data)
    with (output / 'groups.tsv').open('w', newline='') as stream:
        writer = csv.writer(stream, delimiter='\t', lineterminator='\n')
        writer.writerow(['reason_code', 'spell', 'reported_active',
            'reported_disabled', 'detail', 'characters'])
        writer.writerows(groups(rows))
    guids = sorted(int(row[0]) for row in rows)
    selector = ','.join(map(str, guids))
    source = settings.schemas['characters']
    before = metadata(settings, FIELDS)
    for table, fields in FIELDS.items():
        require_shape(before, table, fields)
    print(f'Capturing complete spell/talent/skill context for {len(guids)} '
        'reported characters (read-only)', flush=True)
    queries = []
    for table, fields in FIELDS.items():
        columns = ','.join('`' + field + '`' for field in fields)
        keys = ({'characters': 'guid', 'character_spell': 'guid,spell',
            'character_talent': 'guid,talentGroup,spell',
            'character_skills': 'guid,skill'} [table])
        queries.append((table,
            f'SELECT JSON_ARRAY({columns}) row_value FROM `{source}`.`{table}'
            f'` WHERE guid IN ({selector}) ORDER BY {keys} LIMIT '
            f'{MAX_ROWS + 1}'))
    captured = snapshot(settings, queries)
    state = {table: captured.get(table, []) for table in FIELDS}
    if all_characters and {r[0] for r in state['characters']} != set(guids):
        fail('SOURCE_SCOPE_DRIFT',
            'Character population changed during whole-source capture')
    if all_characters and [int(row) for row in settings.sql(
        f'SELECT guid FROM `{source}`.characters ORDER BY guid LIMIT '
        f'{MAX_CHARACTERS + 1};').splitlines()] != guids:
        fail('SOURCE_SCOPE_DRIFT',
            'Character population changed during whole-source capture')
    if sum(len(state.get(table, [])) for table in FIELDS) > MAX_ROWS:
        fail('BLOCKER_CONTEXT_BOUND',
            'Source context exceeds 5000000 rows; no evidence is '
            'truncated')
    if metadata(settings, FIELDS) != before:
        fail('SCHEMA_DRIFT',
            'Source layout changed during blocker context capture')
    write_json(output / 'source-state.json', {'fields': FIELDS, 'rows': state})
    write_json(output / 'source-layout.json', before)
    print('Capturing effective TC world relationships and DBC fingerprints '
        '(read-only)', flush=True)
    effective, world = read_world(settings)
    write_json(output / 'tc-world.json', world)
    (output / 'spell-metadata-profile.json').write_bytes((
        PROFILE / 'spell-metadata.json').read_bytes())
    by_guid = {guid: {table: [] for table in FIELDS} for guid in guids}
    for table in FIELDS:
        for row in state.get(table, []):
            by_guid[row[0]][table].append(row)
    with (output / 'character-context.jsonl').open('w') as stream:
        for row in rows:
            guid = int(row[0])
            context = by_guid[guid]
            detail = row[3]
            anchor = re.match('^(?:(?:tc|ac):\\s*)?([1-9][0-9]*)(?=:|\\s|$)',
                detail)
            anchor = int(anchor[1]) if anchor else None
            flags = re.search('stored_flags=\\(([01]), ([01])\\)', detail)
            actual = next((s[2:4] for s in context['character_spell'] if s[1]
                == anchor), None)
            comparison = (('MATCH' if actual == [int(flags[1]), int(flags[2])]
                else 'DIFFERS_FROM_SAVED_REPORT') if flags
                else 'NO_REPORTED_FLAGS')
            item = {'guid': guid, 'reason_code': row[2], 'detail': detail,
                'reported_flags_comparison': comparison,
                'source_character_present': bool(context['characters']),
                **context}
            stream.write(json.dumps(item, sort_keys=True, separators= (',',
                ':')) + '\n')
    write_json(output / 'inspection.json', {
        'status': 'COMPLETE_REVIEW_ONLY', 'created_utc': now(),
        'cleanup_approval': 'NOT_GRANTED', 'migration_approval': 'UNREVIEWED',
        'reported_characters': len(rows), 'reason_counts': dict(sorted(Counter(
            row[2] for row in rows).items())),
        'scope': 'ALL_SOURCE_CHARACTERS' if all_characters
        else 'SAVED_REPORT_CHARACTERS',
        'scope_roster_sha256': sha_json(guids) if all_characters else None,
        'source_schema': source, 'source_uuid': work.current()['identity'][
            'uuid'],
        'source_state_sha256': sha_json(state), 'world_sha256': sha_json(
            world),
        'dbc_sha256': effective.hashes,
        'core_compatibility': settings.compatibility,
        'input_report_sha256': sha(output / 'spell-state-blockers.tsv'),
        'tool_sha256': sha(__file__),
        'limitations': [
            'First failure per reported character only; not an exhaustive '
            'migration audit',
            'Source context is a new read-only snapshot, not a replay or '
            'validation of the saved migration run',
            'Captures listed semantic fields, not full-row restoration '
            'archives',
            'TC world snapshot is separate from the source character '
            'snapshot; target world overlays are not captured',
            'No source writes, cleanup batch, SQL execution package, '
            'ownership authorization or gameplay acceptance']})
    (output / 'README.md').write_text((
        'Whole-source preparation scope; PREPARATION_SCOPE rows are review '
        'markers, not migration failures.\n\n' if all_characters else '')
        + '# Migration blocker context (private)\n\nReview groups.tsv and '
        'character-context.jsonl. Source-state.json lists the exact\n'
        'field order and captured rows for every reported character; '
        'tc-world.json retains\neffective TC input tables and their '
        'layouts/fingerprints. DBC hashes and the\nreviewed profile are '
        'retained. No database credentials are exported.\n\nThis is new '
        'read-only diagnostic evidence, not a cleanup selection or a '
        'successful\nmigration. It cannot authorize deleting enabled '
        'spells, resetting talents, adding\nskills or ignoring '
        'predecessor obligations. No active cleanup batch is changed.\n'
        'The report is first-failure-only. No target-world overlays are '
        'captured. Source\nsemantic fields and TC world metadata use '
        'separate consistent read snapshots.\n\nRetain this private '
        'directory and SHA256SUMS. A tar archive of the whole directory\n'
        'can be transferred for offline review; do not publish player '
        'evidence.\n')
    (output / 'INCOMPLETE').unlink()
    seal(output)
    print(f'INSPECTED {len(rows)} migration blocker characters; no database '
        f'changes\nReports: {output}')
    if getattr(args, 'bundle', False):
        bundle = work.operation / 'migration-blocker-context.tar.gz'
        with tarfile.open(bundle, 'x:gz') as archive:
            for path in sorted(output.iterdir()):
                archive.add(path, arcname=path.name, recursive=False)
        bundle.chmod(0o600)
        write_json(work.operation / 'bundle.json', {'path': str(bundle),
            'sha256': sha(bundle), 'inspection': output.name})
        print('Bundle: ' + str(bundle))
    return output
