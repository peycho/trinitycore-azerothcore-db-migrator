"""Read-only review of direct talent spell history, never a deletion
selector.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from collections.abc import Sequence
import csv
import json
from pathlib import Path
import re
from typing import Any, TYPE_CHECKING

from cleanup_files import (
    PROFILE,
    ROOT,
    fail,
    local_id,
    seal,
    sha,
    token,
    write_json,
)
from cleanup_plans import (
    metadata,
    planner,
    ranks,
    require_shape,
    sha_json,
    snapshot,
)
from cleanup_types import DatabaseState, DbcStores, Evidence
from spell_common import reader_hashes

if TYPE_CHECKING:
    from cleanup_config import Settings
    from cleanup_workspace import Workspace


REASONS = {'DISABLED_UNOWNED_TALENT_HISTORY', 'ENABLED_UNOWNED_TALENT_SPELL'}
TABLES = ('characters', 'character_talent', 'character_spell')
LIMITS = {'characters': 1_000_000, 'character_talent': 5_000_000,
    'character_spell': 10_000_000}


def audit_inputs(
    settings: Settings,
    work: Workspace,
    audit_id: str,
) -> tuple[Path, Evidence, dict[str, str], Evidence]:
    if not audit_id:
        pointer = work.session / 'latest-audit.json'
        if not pointer.is_file():
            fail('AUDIT_REQUIRED',
                'Spell history inspection requires a completed full audit in '
                'this session')
        audit_id = json.loads(pointer.read_text())['audit']
    directory = work.session / 'audits' / local_id(audit_id)
    if directory.is_symlink():
        fail('SYMLINK_REFUSED', 'Audit directory cannot be a symlink')
    sums = directory / 'SHA256SUMS'
    if sums.is_symlink() or not sums.is_file():
        fail('AUDIT_CHANGED',
            'Audit checksum manifest is missing or symlinked')
    fingerprints = {}
    for line in sums.read_text().splitlines():
        match = re.fullmatch('([a-f0-9]{64})  ([A-Za-z0-9_.-]+)', line)
        if (not match or match[2] not in planner.REPORTS or match[2]
            in fingerprints):
            fail('AUDIT_CHANGED', 'Invalid or duplicate audit checksum entry')
        path = directory / match[2]
        if path.is_symlink() or not path.is_file() or sha(path) != match[1]:
            fail('AUDIT_CHANGED', 'Audit report checksum differs: ' + match[2])
        fingerprints[match[2]] = match[1]
    if set(fingerprints) != planner.REPORTS:
        fail('AUDIT_CHANGED', 'Required full audit reports are missing')
    fingerprints['SHA256SUMS'] = sha(sums)
    audit = json.loads((directory / 'audit.json').read_text())
    if (audit.get('status') != 'COMPLETE' or audit.get('limitations') != []
        or audit.get('scope') not in ('all', 'character-state')):
        fail('FULL_AUDIT_REQUIRED',
            'Spell history inspection needs a complete character-state '
            'or full audit without coverage limitations')
    if (audit.get('schemas') != settings.schemas
        or audit.get('server', {}).get('uuid') != work.current()[
            'identity']['uuid']):
        fail('AUDIT_SESSION_MISMATCH',
            'Audit source identity differs from the current session')
    producers = {'audit_tool_sha256': ROOT / 'tools/audit-tc-source.py',
        'metadata_reader_sha256': ROOT / 'lib/spells.py',
        'layout_profile_sha256': PROFILE / 'spell-metadata.json'}
    if (any(audit.get(key) != sha(path) for key, path in producers.items())
        or ('spell_reader_sha256' in audit and audit['spell_reader_sha256']
            != reader_hashes(ROOT))):
        fail('AUDIT_PRODUCER_CHANGED',
            'Audit producer/layout differs; run a fresh full audit')
    dbc = audit.get('dbc_sha256', {})
    if (set(dbc) != {'Spell.dbc', 'Talent.dbc', 'TalentTab.dbc',
        'SkillLine.dbc'}
        or any(sha(settings.paths['tc_dbc'] / name) != checksum for name,
            checksum in dbc.items())):
        fail('DBC_DRIFT', 'DBC assets differ from the full audit')
    if (not re.fullmatch('[a-f0-9]{64}', str(audit.get(
        'audited_results_sha256', '')))
        or any(type(audit.get('audited_input_rows', {}).get(
            table)) is not int
            or not 0 <= audit['audited_input_rows'][table] <= LIMITS[
                table] for table in TABLES)):
        fail('HISTORY_INPUT_UNSUPPORTED',
            'Audit counts/digest are missing or exceed bounded '
            'inspection limits')
    expected = {}
    counts = Counter()
    with (directory / 'findings.tsv').open(newline='') as stream:
        for row in csv.DictReader(stream, delimiter='\t'):
            if row['reason_code'] not in REASONS:
                continue
            if (row['classification'] != 'REVIEW' or row['schema']
                != settings.schemas['characters']
                or row['table'] != 'character_spell'
                or not re.fullmatch('[0-9]+:[0-9]+', row['source_key'])):
                fail('HISTORY_EVIDENCE_INVALID',
                    'Unexpected spell history schema/table/key')
            key = tuple(map(int, row['source_key'].split(':')))
            evidence = json.loads(row['evidence'])
            spell, active, disabled = ((evidence.get(name) for name in (
                'spell', 'active', 'disabled')))
            if (any(type(value) is not int for value in (spell, active,
                disabled))
                or not all(1 <= value <= 4294967295 for value in key)
                or spell != key[1] or active not in (0, 1) or disabled not
                in (0, 1)
                or bool(disabled) != (row['reason_code']
                    == 'DISABLED_UNOWNED_TALENT_HISTORY')
                or key in expected):
                fail('HISTORY_EVIDENCE_INVALID',
                    'Duplicate or invalid spell history evidence')
            expected[key] = (active, disabled)
            counts[row['reason_code']] += 1
    summary = Counter()
    with (directory / 'summary.tsv').open(newline='') as stream:
        seen = set()
        for row in csv.DictReader(stream, delimiter='\t'):
            if row['reason_code'] in REASONS:
                if (row['classification'] != 'REVIEW' or row['reason_code']
                    in seen):
                    fail('HISTORY_EVIDENCE_INVALID',
                        'Duplicate or invalid spell history summary')
                seen.add(row['reason_code'])
                summary[row['reason_code']] = int(row['rows_found'])
    if counts != summary:
        fail('HISTORY_EVIDENCE_INVALID',
            'Spell history summary differs from exact finding keys')
    return directory, audit, fingerprints, expected


def classify(
    state: DatabaseState,
    stores: DbcStores,
    expected: Sequence[Sequence[Any]],
) -> list[tuple[Any, ...]]:
    """Recompute the audit's exact-ID findings, then inspect whole talent
    families.
    """
    catalog = defaultdict(list)
    for row in stores['Talent'].values():
        tab = stores['TalentTab'].get(row[1])
        for rank, spell in enumerate(row[4:9], 1):
            if spell:
                catalog[spell].append((row[0], rank, tab[20] if tab else 0))
    characters = {row[0]: row for row in state['characters']}
    selected, families, invalid = defaultdict(set), defaultdict(list), set()
    for guid, spell, group in state['talents']:
        selected[guid].add(spell)
        char = characters.get(guid)
        matches = catalog.get(spell, [])
        if (char is None or len(matches) != 1 or not 1 <= char[2] <= 32
            or not matches[0][2] & (1 << (char[2] - 1)) or not 0
            <= group < char[4]):
            invalid.add(guid)
        elif matches:
            families[guid, matches[0][0]].append((spell, group, matches[0][1]))
    for (guid, _), values in families.items():
        if len({value[1] for value in values}) != len(values):
            invalid.add(guid)
    live = {(guid, spell): (active, disabled) for guid, spell, active,
        disabled in state['spells']
        if guid in characters and spell in catalog and spell not
        in selected[guid]}
    if live != expected:
        fail('HISTORY_INPUT_DRIFT',
            'Live direct talent history keys/flags differ from the audit',
            'No cleanup occurred. Use a fresh full audit after source '
            'changes; do not rerun migration preflight.')
    rows = []
    for (guid, spell), (active, disabled) in sorted(live.items()):
        _, race, cls, active_group, groups, online, at_login = characters[guid]
        matches = catalog[spell]
        family, rank, mask = matches[0]
        related = sorted(families[guid, family]) if len(matches) == 1 else[]
        if (groups not in (1, 2) or not 0 <= active_group < groups or cls not
            in {1, 2, 3, 4, 5, 6, 7, 8, 9, 11}):
            disposition = 'DEFER_INVALID_CHARACTER_STATE'
        elif online:
            disposition = 'DEFER_ONLINE_CHARACTER'
        elif at_login & 4:
            disposition = 'DEFER_PENDING_NATIVE_RESET'
        elif guid in invalid:
            disposition = 'DEFER_INVALID_TALENT_SELECTION'
        elif len(matches) != 1 or not mask:
            disposition = 'DEFER_AMBIGUOUS_TALENT_METADATA'
        elif not mask & (1 << (cls - 1)):
            disposition = 'REVIEW_FOREIGN_CLASS_TALENT'
        elif spell not in stores['Spell']:
            disposition = 'DEFER_MISSING_SPELL_METADATA'
        elif related:
            disposition = ('REVIEW_DISABLED_OTHER_SELECTED_RANK' if disabled
                else 'REVIEW_ENABLED_OTHER_SELECTED_RANK')
        else:
            disposition = ('REVIEW_DISABLED_NO_SELECTED_FAMILY' if disabled
                else 'REVIEW_ENABLED_NO_SELECTED_FAMILY')
        rows.append([guid, spell, active, disabled, cls, race, active_group,
            groups, at_login,
            disposition, family if len(matches) == 1 else '', rank
            if len(matches) == 1 else '',
            json.dumps(related, separators= (',', ':'))])
    return rows


def inspect_history(
    settings: Settings,
    work: Workspace,
    args: argparse.Namespace,
) -> Path:
    settings.check_paths()
    directory, audit, fingerprints, expected = audit_inputs(settings, work,
        args.audit)
    stores, catalog, dbc = ranks(settings)
    meta = metadata(settings, TABLES)
    for table, fields in (('characters', {'guid', 'race', 'class',
        'activeTalentGroup', 'talentGroupsCount', 'online', 'at_login'}),
        ('character_talent', {'guid', 'spell',
            'talentGroup'}),
        ('character_spell', {'guid', 'spell', 'active',
            'disabled'})):
        shape = require_shape(meta, table, fields)
        keys = {'characters': {'guid'}, 'character_talent': {'guid', 'spell',
            'talentGroup'},
            'character_spell': {'guid', 'spell'}} [table]
        if ({name for name, value in shape.items() if value[2] == 'PRI'}
            != keys):
            fail('UNSUPPORTED_SCHEMA',
                'Spell history inspection requires native primary keys: '
                + table)
    source = settings.schemas['characters']
    selector = ','.join(map(str, catalog))
    print('Inspecting direct talent spell history and both talent groups '
        '(read-only)', flush=True)
    state = snapshot(settings, [
        ('counts', f'SELECT JSON_ARRAY((SELECT COUNT(*) FROM `{source}'
            f'`.characters),(SELECT COUNT(*) FROM `{source}'
            f'`.character_talent),(SELECT COUNT(*) FROM `{source}'
            '`.character_spell)) row_value'),
        ('characters', 'SELECT '
            'JSON_ARRAY(guid,race,class,activeTalentGroup,talentGroupsCount,online,at_login) '
            f'row_value FROM `{source}`.characters ORDER BY guid LIMIT '
            f"{LIMITS['characters'] + 1}"),
        ('talents',
            'SELECT JSON_ARRAY(guid,spell,talentGroup) row_value FROM `'
            f'{source}`.character_talent ORDER BY guid,spell,talentGroup '
            f"LIMIT {LIMITS['character_talent'] + 1}"),
        ('spells',
            'SELECT JSON_ARRAY(guid,spell,active,disabled) row_value FROM `'
            f'{source}`.character_spell WHERE spell IN ({selector}) ORDER BY '
            f"guid,spell LIMIT {LIMITS['character_spell'] + 1}")])
    for table, count in zip(TABLES, state['counts'][0]):
        if count != audit['audited_input_rows'][table]:
            fail('HISTORY_INPUT_DRIFT',
                'Source row count differs from the full audit: ' + table)
    rows = classify(state, stores, expected)
    if metadata(settings, TABLES) != meta:
        fail('HISTORY_SCHEMA_DRIFT', 'Source schema changed during inspection')
    if any(sha(settings.paths['tc_dbc'] / name) != checksum for name, checksum
        in audit['dbc_sha256'].items()):
        fail('DBC_DRIFT', 'DBC assets changed during inspection')
    # Revalidate the retained audit too; it remains the exact evidence
    # reference.
    if audit_inputs(settings, work, directory.name)[2] != fingerprints:
        fail('AUDIT_CHANGED', 'Audit files changed during inspection')
    output = work.session / 'inspections' / token('spell-history')
    output.mkdir(parents=True, mode=0o700)
    (output / 'INCOMPLETE').touch()
    write_json(output / 'input-state.json', dict(state))
    headers = ['guid', 'spell', 'active', 'disabled', 'class', 'race',
        'active_group', 'group_count', 'at_login',
        'disposition', 'talent_entry', 'talent_rank',
        'selected_family_spell_group_rank']
    with (output / 'spell-history.tsv').open('w', newline='') as stream:
        writer = csv.writer(stream, delimiter='\t', lineterminator='\n')
        writer.writerow(headers)
        writer.writerows(rows)
    grouped = Counter((row[9], row[1], row[4]) for row in rows)
    with (output / 'summary.tsv').open('w', newline='') as stream:
        writer = csv.writer(stream, delimiter='\t', lineterminator='\n')
        writer.writerow(['disposition', 'spell', 'class', 'rows_found'])
        writer.writerows([*key, value] for key, value in sorted(grouped.items(
        )))
    totals = Counter(row[9] for row in rows)
    write_json(output / 'inspection.json', {
        'status': 'COMPLETE_REVIEW_ONLY', 'cleanup_approval': 'NOT_GRANTED',
        'migration_approval': 'UNREVIEWED',
        'audit': directory.name, 'audit_results_sha256': audit[
            'audited_results_sha256'],
        'audit_files_sha256': fingerprints, 'dbc_sha256': dbc,
        'source_schema': source,
        'source_uuid': audit['server']['uuid'], 'input_state_sha256': sha_json(
            dict(state)),
        'metadata_sha256': sha_json(meta), 'inspection_tool_sha256': sha(
            __file__),
        'rows_reviewed': len(rows), 'dispositions': dict(sorted(totals.items(
        ))),
        'limitations': [
            'Direct Talent.dbc ranks only; excludes indirect talent-unlocked '
            'spell chains',
            'No world overlays, scripts, ordinary learning routes or '
            'runtime dependencies reviewed',
            'Audit row counts and exact history keys/flags checked; this '
            'is a new live read snapshot, not an exact full-database '
            'audit replay',
            'No cleanup selection, SQL, archive, ownership changes or '
            'native login performed']})
    (output / 'README.md').write_text('''# Direct talent spell history review

This inspection performs no database writes and creates no cleanup batch. It
does not change the active batch used by prepare/apply/restore. All rows remain
REVIEW or DEFER; no disposition authorizes deletion or activation.

Read inspection.json and summary.tsv, then the exact spell-history.tsv rows.
Both talent groups are checked. A selected different rank of the same talent
is reported separately. Pending native resets, online characters, invalid
ownership and ambiguous metadata are deferred. Input-state.json records the
read-only snapshot; reports are private and sealed with SHA256SUMS.

Disabled does not mean corrupt. Before any cleanup, review effective world/DBC
relationships and native load/unlearn behavior, then implement an explicitly
reviewed exact-row archive/apply/restore policy. Enabled cases need separate
decisions. Preserve custom items and quest history. No migration approval or
native gameplay acceptance follows from this report.
''')
    seal(output)
    (output / 'INCOMPLETE').unlink()
    print('INSPECTED ' + str(len(rows))
        + ' direct talent history rows; no database changes')
    for disposition, count in sorted(totals.items()):
        print(disposition + '\t' + str(count))
    print('Reports: ' + str(output))
    return output
