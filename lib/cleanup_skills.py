"""Explicit preparation policy: clamp audited skill values to stored caps."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import re
from typing import TYPE_CHECKING
import uuid

from cleanup_files import PROFILE, ROOT, fail, local_id, sha
from cleanup_plans import (
    equality,
    finish,
    metadata,
    planner,
    render,
    require_shape,
    sha_json,
    snapshot,
    write_json,
)
from cleanup_types import Evidence, SpellRow
from spell_common import reader_hashes

if TYPE_CHECKING:
    from cleanup_config import Settings
    from cleanup_workspace import Workspace


def audit_inputs(
    settings: Settings,
    work: Workspace,
    args: argparse.Namespace,
) -> tuple[Path, Evidence, dict[str, str], list[SpellRow]]:
    if not 1 <= args.expect_rows <= 10000:
        fail('SKILL_SELECTION_MISMATCH',
            '--expect-rows must be between 1 and 10000')
    audit_id = args.audit
    if not audit_id:
        pointer = work.session / 'latest-audit.json'
        if not pointer.is_file():
            fail('AUDIT_REQUIRED',
                'Run a full audit in this session before planning skill '
                'cleanup')
        audit_id = json.loads(pointer.read_text())['audit']
    directory = work.session / 'audits' / local_id(audit_id)
    if directory.is_symlink():
        fail('SYMLINK_REFUSED', 'Audit directory cannot be a symlink')
    required = {'audit.json', 'findings.tsv', 'summary.tsv', 'coverage.tsv',
        'schema-inventory.tsv',
        'audit-queries.sql', 'cleanup-review.tsv'}
    manifest = directory / 'SHA256SUMS'
    if manifest.is_symlink():
        fail('AUDIT_CHANGED', 'Symlinked audit checksum manifest refused')
    fingerprints = {}
    for line in manifest.read_text().splitlines():
        match = re.fullmatch('([a-f0-9]{64})  ([A-Za-z0-9_.-]+)', line)
        if not match or match[2] not in required or match[2] in fingerprints:
            fail('AUDIT_CHANGED', 'Invalid or duplicate audit checksum entry')
        path = directory / match[2]
        if path.is_symlink() or not path.is_file() or sha(path) != match[1]:
            fail('AUDIT_CHANGED', 'Audit report checksum differs: ' + match[2])
        fingerprints[match[2]] = match[1]
    if set(fingerprints) != required:
        fail('AUDIT_CHANGED', 'Required full audit reports are missing')
    fingerprints['SHA256SUMS'] = sha(manifest)
    status = json.loads((directory / 'audit.json').read_text())
    if (status.get('status') != 'COMPLETE' or status.get('limitations') != []
        or status.get('scope') not in ('all', 'character-state')):
        fail('FULL_AUDIT_REQUIRED',
            'Skill cleanup requires a complete character-state or full audit '
            'without coverage limitations')
    if (status.get('schemas') != settings.schemas
        or status.get('server', {}).get('uuid') != work.current()[
            'identity']['uuid']):
        fail('AUDIT_SESSION_MISMATCH',
            'Audit source identity differs from the current session')
    if (not re.fullmatch('[a-f0-9]{64}', str(status.get(
        'audited_results_sha256', '')))
        or type(status.get('audited_input_rows', {}).get(
            'character_skills')) is not int
        or status['audited_input_rows']['character_skills'] < 1):
        fail('SKILL_EVIDENCE_INVALID',
            'Full audit result digest or skill input count is invalid')
    producers = {'audit_tool_sha256': ROOT / 'tools/audit-tc-source.py',
        'metadata_reader_sha256': ROOT / 'lib/spells.py',
        'layout_profile_sha256': PROFILE / 'spell-metadata.json'}
    if (any(status.get(key) != sha(path) for key, path in producers.items())
        or ('spell_reader_sha256' in status and status['spell_reader_sha256']
            != reader_hashes(ROOT))):
        fail('AUDIT_PRODUCER_CHANGED',
            'Audit producer/layout differs; run a fresh full audit')
    dbc = status.get('dbc_sha256', {})
    if (set(dbc) != {'Spell.dbc', 'Talent.dbc', 'TalentTab.dbc',
        'SkillLine.dbc'}):
        fail('DBC_DRIFT', 'Full audit DBC fingerprints are incomplete')
    if any(sha(settings.paths['tc_dbc'] / name) != checksum for name, checksum
        in dbc.items()):
        fail('DBC_DRIFT', 'DBC assets differ from the full audit')
    profile = json.loads((PROFILE / 'spell-metadata.json').read_text())
    skills, _ = planner.read_dbc(settings.paths['tc_dbc'] / 'SkillLine.dbc',
        profile['stores']['SkillLine']['formats']['tc'])
    selected = []
    with (directory / 'findings.tsv').open(newline='') as stream:
        for row in csv.DictReader(stream, delimiter='\t'):
            if row['reason_code'] != 'SKILL_VALUE_EXCEEDS_CAP':
                continue
            if (row['classification'] != 'INVALID' or row['schema']
                != settings.schemas['characters']
                or row['table'] != 'character_skills' or not re.fullmatch(
                    '[0-9]+:[0-9]+', row['source_key'])):
                fail('SKILL_EVIDENCE_INVALID',
                    'Unexpected skill finding schema/table/key')
            guid, skill = map(int, row['source_key'].split(':'))
            evidence = json.loads(row['evidence'])
            value, maximum = evidence.get('value'), evidence.get('max')
            if (any(type(v) is not int for v in (value, maximum, evidence.get(
                'skill')))
                or evidence['skill'] != skill or skill not in skills
                or not 1 <= guid <= 4294967295
                or not 1 <= skill <= 65535 or not 0 < maximum < value
                <= 65535):
                fail('SKILL_CLAMP_UNSUPPORTED',
                    'Only known skills with positive stored caps and '
                    'strictly larger native values can be clamped')
            selected.append((guid, skill, value, maximum))
            if len(selected) > 10000:
                fail('SKILL_SELECTION_MISMATCH',
                    'Skill selection exceeds the 10000-row reviewed '
                    'batch bound')
    if (len({(r[0], r[1]) for r in selected}) != len(selected)
        or not 1 <= len(selected) <= 10000 or len(selected)
        != args.expect_rows):
        fail('SKILL_SELECTION_MISMATCH',
            'Exact skill keys differ from --expect-rows, are duplicated '
            'or exceed the 10000-row bound')
    with (directory / 'summary.tsv').open(newline='') as stream:
        summaries = [r for r in csv.DictReader(stream, delimiter='\t')
            if r['classification'] == 'INVALID' and r['reason_code']
            == 'SKILL_VALUE_EXCEEDS_CAP']
    if len(summaries) != 1 or int(summaries[0]['rows_found']) != len(selected):
        fail('SKILL_SELECTION_MISMATCH',
            'Skill summary differs from exact finding keys')
    return directory, status, fingerprints, sorted(selected)


def plan_skills(
    settings: Settings,
    work: Workspace,
    args: argparse.Namespace,
    output: Path,
) -> None:
    directory, audit, fingerprints, selected = audit_inputs(settings, work,
        args)
    source = settings.schemas['characters']
    meta = metadata(settings, ['characters', 'character_skills'])
    shape = require_shape(meta, 'character_skills', {'guid', 'skill', 'value',
        'max'})
    native = {'guid': ('int unsigned', 'NO', 'PRI'), 'skill': (
        'smallint unsigned', 'NO', 'PRI'),
        'value': ('smallint unsigned', 'NO', ''), 'max': (
            'smallint unsigned', 'NO', '')}
    if (any(shape[k] != v for k, v in native.items()) or {k for k, v
        in shape.items() if v[2] == 'PRI'} != {'guid', 'skill'}):
        fail('UNSUPPORTED_SCHEMA',
            'Skill clamp needs native guid/skill keys and unsigned '
            'value/max columns')
    chars = require_shape(meta, 'characters', {'guid', 'online'})
    if (chars['guid'] != ('int unsigned', 'NO', 'PRI') or [k for k, v
        in chars.items() if v[2] == 'PRI'] != ['guid']):
        fail('UNSUPPORTED_SCHEMA',
            'Skill clamp needs a native unique character GUID')
    if (len(meta['columns']) > 512 or any('on update' in r[5].lower() for r
        in meta['columns'])):
        fail('UNSUPPORTED_COLUMN',
            'Skill cleanup does not support ON UPDATE columns or more than '
            '512 columns')
    guids = sorted({r[0] for r in selected})
    selector = ','.join(map(str, guids))
    state = snapshot(settings, [
        ('invalid',
            'SELECT JSON_ARRAY(s.guid,s.skill,s.value,s.max) row_value FROM `'
            f'{source}`.character_skills s JOIN `{source}`.characters c ON '
            'c.guid=s.guid WHERE s.value>s.max ORDER BY s.guid,s.skill'),
        ('characters',
            f'SELECT JSON_ARRAY(guid,online) row_value FROM `{source}'
            f'`.characters WHERE guid IN ({selector}) ORDER BY guid'),
        ('counts', f'SELECT JSON_ARRAY(COUNT(*),SUM(guid IN ({selector}))) '
            f'row_value FROM `{source}`.character_skills')])
    write_json(work.operation / 'evidence.json', {'state': state,
        'metadata': meta})
    if [tuple(r) for r in state['invalid']] != selected:
        fail('SKILL_INPUT_DRIFT',
            'Live over-cap skill keys or values differ from the full audit; '
            'run a new audit')
    if state['characters'] != [[guid, 0] for guid in guids]:
        fail('SKILL_CHARACTER_UNAVAILABLE',
            'Every affected character must exist and be offline')
    source_count, before_count = state['counts'][0]
    if source_count != audit['audited_input_rows']['character_skills']:
        fail('SKILL_INPUT_DRIFT',
            'Source skill row count differs from the full audit')
    template = ROOT / 'tools/skill-cleanup.sql.in'
    archive = 'tc_skills_' + uuid.uuid4().hex[:24]
    batch_key = sha_json({'session': work.session.name, 'id': output.name,
        'selected': selected, 'metadata': meta,
        'audit': fingerprints, 'template': sha(template)})
    columns = sorted(meta['columns'], key=lambda r: (r[0], r[7]))
    value_equality = ' AND '.join(
        '(a.`value` <=> IF(e.guid IS NULL,b.`value`,e.cap))' if r[1] == 'value'
        else f'(BINARY a.`{r[1]}` <=> BINARY b.`{r[1]}`)'
        for r in columns if r[0] == 'character_skills')
    values = {'SOURCE': source, 'ARCHIVE': archive, 'UUID': work.current()[
        'identity']['uuid'],
        'BATCH': batch_key, 'AUDIT': audit['audited_results_sha256'],
        'COUNT': len(selected), 'GUID_COUNT': len(guids),
        'SOURCE_COUNT': source_count, 'BEFORE_COUNT': before_count,
        'EXPECTED_HASH': planner.key_hash(selected),
        'EXPECTED_INSERT': planner.insert_values('expected', selected),
        'COLUMN_COUNT': len(columns),
        'COLUMN_HASH': planner.key_hash(columns),
        'COLUMN_INSERT': planner.insert_values('reviewed_columns', columns),
        'ARCHIVE_COLUMNS': len(columns) + sum(r[0] == 'character_skills' for r
            in columns),
        'CONCAT_LIMIT': max(8192, len(selected) * 100, len(columns) * 2048),
        'CHAR_EQUAL': equality(meta, 'characters'), 'SKILL_EQUAL': equality(
            meta, 'character_skills'),
        'SKILL_AFTER_EQUAL': value_equality}
    for name, expected in fingerprints.items():
        if sha(directory / name) != expected:
            fail('AUDIT_CHANGED', 'Audit changed while planning skills')
    if metadata(settings, ['characters', 'character_skills']) != meta:
        fail('SCHEMA_DRIFT', 'Source metadata changed while planning')
    manifest = {'policy': 'tc-skill-clamp-stored-cap-v1',
        'archive_schema': archive, 'batch_key': batch_key,
        'selected_rows': len(selected), 'affected_characters': len(guids),
        'character_guids': guids,
        'before_skill_rows': before_count,
        'audited_source_skill_rows': source_count,
        'audit_id': directory.name, 'audit_sha256': audit[
            'audited_results_sha256'],
        'report_fingerprints': fingerprints, 'dbc_sha256': audit['dbc_sha256'],
        'expected_sha256': planner.key_hash(selected),
        'metadata_sha256': sha_json(meta), 'template_sha256': sha(template),
        'value_policy': 'Clamp only audited value > existing positive max; never '
        'increase values/caps or infer GM status'}
    status = f'''SELECT * FROM `{archive}`.batch;
SELECT 'expected' AS object,COUNT(*) AS rows_found FROM `{archive}`.expected
UNION ALL SELECT 'character_before',COUNT(*) FROM `{archive}`.character_before
UNION ALL SELECT 'skill_before',COUNT(*) FROM `{archive}`.skill_before
UNION ALL SELECT 'skill_after',COUNT(*) FROM `{archive}`.skill_after;
SELECT e.guid,e.skill,e.old_value,e.cap AS unchanged_maximum,e.cap AS planned_value,
 s.value AS current_value,s.max AS current_maximum FROM `{archive}`.expected e
 LEFT JOIN `{source}`.character_skills s ON s.guid=e.guid AND s.skill=e.skill ORDER BY e.guid,e.skill;
'''
    selected_tsv = 'guid\tskill\toriginal_value\tmaximum\tnew_value\n' + ''.join(
        '\t'.join(map(str, (*r, r[3]))) + '\n' for r in selected)
    finish(settings, work, output, manifest, render(template, values),
        selected_tsv, status, 'skill_cleanup_ack')
