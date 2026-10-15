#!/usr/bin/env python3
"""Generate reviewable SQL for audited non-rank TC talent rows; never connect to MySQL."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'lib'))
from spells import read_dbc

REASON = 'TALENT_VALUE_IS_NOT_RANK_SPELL'
REPORTS = {'audit.json', 'findings.tsv', 'summary.tsv', 'schema-inventory.tsv',
           'coverage.tsv', 'cleanup-review.tsv', 'audit-queries.sql'}
TEMPLATE = ROOT/'tools/talent-cleanup.sql.in'
PROFILE = ROOT/'compatibility/tc335-acwotlk-v2/spell-metadata.json'


def sha(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(1024*1024):
            result.update(block)
    return result.hexdigest()


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_]{1,64}', value):
        raise ValueError('Identifiers must contain 1-64 ASCII letters, digits or underscores')
    return value


def sql_string(value):
    # Only generated metadata/identifiers reach SQL literals, never item/player text.
    if not re.fullmatch(r'[A-Za-z0-9_:.,=|() -]*', value):
        raise ValueError('Unsupported SQL metadata literal')
    return "'" + value + "'"


def table_rows(path):
    with path.open(newline='') as stream:
        yield from csv.DictReader(stream, delimiter='\t')


def load_inputs(audit_dir, dbc_dir, expect_rows):
    if not 1 <= expect_rows <= 1_000_000:
        raise ValueError('--expect-rows must be between 1 and 1000000')
    if (audit_dir/'SHA256SUMS').is_symlink():
        raise ValueError('Symlinked audit checksum manifests are unsupported')
    listed = {}
    for line in (audit_dir/'SHA256SUMS').read_text().splitlines():
        match = re.fullmatch(r'([a-f0-9]{64})  ([A-Za-z0-9_.-]+)', line)
        if not match or match[2] not in REPORTS or match[2] in listed:
            raise ValueError('Unsupported/duplicate audit checksum entry')
        listed[match[2]] = match[1]
    if listed.keys() != REPORTS:
        raise ValueError('Audit checksum manifest must cover the seven native reports')
    fingerprints = {audit_dir/'SHA256SUMS': sha(audit_dir/'SHA256SUMS')}
    for name, checksum in listed.items():
        path = audit_dir/name
        if path.is_symlink() or sha(path) != checksum:
            raise ValueError('Audit report checksum mismatch: ' + name)
        fingerprints[path] = checksum
    audit = json.loads((audit_dir/'audit.json').read_text())
    if (audit.get('status') != 'COMPLETE' or audit.get('limitations') != []
            or audit.get('scope') not in ('all', 'talents')):
        raise ValueError('A COMPLETE audit without coverage limitations is required')
    schemas = audit['schemas']
    if set(schemas) != {'characters', 'auth', 'world'} or len(set(schemas.values())) != 3:
        raise ValueError('Audit must identify three distinct input schemas')
    for value in schemas.values():
        identifier(value)
    server = audit['server']
    if (str(uuid.UUID(server['uuid'])) != server['uuid'] or not server['version'].startswith('8.4.')
            or server['transaction_read_only'] != '1'):
        raise ValueError('Expected a read-only MySQL 8.4 audit with a canonical server UUID')
    for field, path in [('audit_tool_sha256', ROOT/'tools/audit-tc-source.py'),
                        ('metadata_reader_sha256', ROOT/'lib/spells.py'),
                        ('layout_profile_sha256', PROFILE)]:
        checksum = sha(path)
        if audit[field] != checksum:
            raise ValueError('Audit producer/layout differs from this toolkit: ' + field)
        fingerprints[path] = checksum
    for path in (Path(__file__), TEMPLATE, ROOT/'tools/talent-cleanup-README.md.in'):
        fingerprints[path] = sha(path)
    catalog_names = {'Spell.dbc', 'Talent.dbc', 'TalentTab.dbc'}
    if audit['scope'] == 'all':
        catalog_names.add('SkillLine.dbc')
    if set(audit['dbc_sha256']) != catalog_names:
        raise ValueError('Unexpected audit DBC fingerprint set')
    for name, checksum in audit['dbc_sha256'].items():
        path = dbc_dir/name
        if sha(path) != checksum:
            raise ValueError('DBC fingerprint mismatch: ' + name)
        fingerprints[path] = checksum
    profile = json.loads(PROFILE.read_text())
    talents, _ = read_dbc(dbc_dir/'Talent.dbc', profile['stores']['Talent']['formats']['tc'])
    ranks = sorted({spell for talent in talents.values() for spell in talent[4:9] if spell})
    if not ranks or len(ranks) > 100_000 or max(ranks) > 16777215:
        raise ValueError('Unsupported or empty talent rank catalog')
    rank_set = set(ranks)
    expected, evidence_rows = set(), []
    for row in table_rows(audit_dir/'findings.tsv'):
        if row['reason_code'] != REASON:
            continue
        if (row['classification'] != 'INVALID' or row['schema'] != schemas['characters']
                or row['table'] != 'character_talent'):
            raise ValueError('Selected reason belongs to an unexpected schema/table/classification')
        key = row['source_key']
        if not re.fullmatch(r'[0-9]+:[0-9]+:[0-9]+', key):
            raise ValueError('Invalid talent source key')
        guid, spell, group = map(int, key.split(':'))
        if not 1 <= guid <= 4294967295 or not 0 <= spell <= 16777215 or not 0 <= group <= 255:
            raise ValueError('Talent source key outside native unsigned domains')
        detail = json.loads(row['evidence'])
        if (detail['spell'] != spell or detail['talentGroup'] != group
                or type(detail['matchesTalentEntryId']) is not bool
                or detail['matchesTalentEntryId'] != (spell in talents)):
            raise ValueError('Talent evidence disagrees with its key or matching DBC')
        if spell in rank_set:
            raise ValueError('Refusing removal of a selectable talent rank: ' + str(spell))
        value = (guid, spell, group)
        if value in expected:
            raise ValueError('Duplicate selected talent key')
        expected.add(value)
        evidence_rows.append((guid, spell, group, int(detail['matchesTalentEntryId'])))
    summaries = [row for row in table_rows(audit_dir/'summary.tsv')
                 if row['classification'] == 'INVALID' and row['reason_code'] == REASON]
    if len(summaries) != 1 or int(summaries[0]['rows_found']) != len(expected) or len(expected) != expect_rows:
        raise ValueError('Selected keys, audit summary and --expect-rows must agree exactly')
    source_count = audit['audited_input_rows']['character_talent']
    if type(source_count) is not int or source_count < expect_rows:
        raise ValueError('Invalid audited character_talent count')
    columns, tables = {}, {}
    for row in table_rows(audit_dir/'schema-inventory.tsv'):
        if row['schema'] != schemas['characters'] or row['table'] not in ('characters', 'character_talent'):
            continue
        table = row['table']
        if row['kind'] == 'T':
            tables[table] = (row['name_or_engine'], row['type'])
        elif row['kind'] == 'C':
            name = identifier(row['name_or_engine'])
            if (table, name) in columns:
                raise ValueError('Duplicate inventory column')
            columns[(table, name)] = (row['type'], row['nullable'], row['key'])
    if tables != {name: ('InnoDB', 'BASE TABLE') for name in ('characters', 'character_talent')}:
        raise ValueError('Native InnoDB character and talent tables required')
    if {name for table, name in columns if table == 'character_talent'} != {'guid', 'spell', 'talentGroup'}:
        raise ValueError('Only the reviewed three-column TC talent representation is supported')
    for name, native_type in [('guid', 'int unsigned'), ('spell', 'mediumint unsigned'), ('talentGroup', 'tinyint unsigned')]:
        if columns[('character_talent', name)] != (native_type, 'NO', 'PRI'):
            raise ValueError('Talent column differs from reviewed native schema: ' + name)
    char_columns = sorted(name for table, name in columns if table == 'characters')
    if not {'guid', 'online', 'class', 'race', 'level', 'activeTalentGroup', 'talentGroupsCount'} <= set(char_columns):
        raise ValueError('Required character state columns missing')
    if [name for name in char_columns if columns[('characters', name)][2] == 'PRI'] != ['guid']:
        raise ValueError('Native unique character GUID primary key required')
    for value in columns.values():
        if not re.fullmatch(r'[A-Za-z0-9 (),]+', value[0]) or value[1] not in ('YES', 'NO'):
            raise ValueError('Unsupported audited column type/nullability')
    if not re.fullmatch('[a-f0-9]{64}', audit['audited_results_sha256']):
        raise ValueError('Invalid audited-result digest')
    return {'audit': audit, 'rows': sorted(expected), 'evidence': sorted(evidence_rows),
            'reports': {**listed, 'SHA256SUMS': fingerprints[audit_dir/'SHA256SUMS']},
            'ranks': ranks, 'columns': columns, 'characters': char_columns, 'fingerprints': fingerprints}


def insert_values(table, rows):
    statements = []
    for start in range(0, len(rows), 200):
        values = ['('+','.join(str(v) if type(v) is int else sql_string(v) for v in row)+')'
                  for row in rows[start:start+200]]
        statements.append('INSERT INTO '+table+' VALUES\n'+',\n'.join(values)+';')
    return '\n'.join(statements)


def key_hash(rows):
    return hashlib.sha256('|'.join(':'.join(map(str, row)) for row in rows).encode()).hexdigest()


def render(data, archive_schema=None):
    audit, rows, columns = data['audit'], data['rows'], data['columns']
    inputs = {'policy': 'tc-invalid-talent-rank-v1', 'audit': audit,
              'selected': rows, 'generator_sha256': data['fingerprints'][Path(__file__)],
              'template_sha256': data['fingerprints'][TEMPLATE]}
    batch = hashlib.sha256(json.dumps(inputs, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    archive = identifier(archive_schema or 'tc_talent_cleanup_'+batch[:16])
    if archive in audit['schemas'].values():
        raise ValueError('Archive schema must differ from every input schema')
    rank_hash = key_hash([(spell,) for spell in data['ranks']])
    column_rows = [(table, name, *info) for (table, name), info in sorted(columns.items())]
    column_hash = key_hash(column_rows)
    manifest = {'policy': inputs['policy'], 'batch_key': batch, 'archive_schema': archive,
                'source_schema': audit['schemas']['characters'], 'source_uuid': audit['server']['uuid'],
                'audit_sha256': audit['audited_results_sha256'], 'report_fingerprints': data['reports'],
                'dbc_sha256': audit['dbc_sha256'], 'generator_sha256': inputs['generator_sha256'],
                'template_sha256': inputs['template_sha256'], 'selected_sha256': key_hash(rows),
                'rank_catalog_sha256': rank_hash, 'audited_source_talent_rows': audit['audited_input_rows']['character_talent'],
                'selected_rows': len(rows), 'affected_characters': len({row[0] for row in rows}),
                'distinct_non_rank_values': len({row[1] for row in rows}),
                'matches_talent_entry_id_rows': sum(row[3] for row in data['evidence']),
                'status': 'CANDIDATE_FOR_REVIEW_NOT_APPLIED', 'migration_approval': 'UNREVIEWED'}
    # Constant catalog/expected hashes are checked by the generated procedures.
    # All source identifiers have been validated; arbitrary text is never SQL.
    values = {'SOURCE': audit['schemas']['characters'], 'ARCHIVE': archive,
              'UUID': audit['server']['uuid'], 'BATCH': batch, 'AUDIT': audit['audited_results_sha256'],
              'EXPECTED_HASH': key_hash(rows), 'RANK_HASH': rank_hash, 'COLUMN_HASH': column_hash,
              'COUNT': str(len(rows)), 'GUID_COUNT': str(manifest['affected_characters']),
              'SOURCE_COUNT': str(audit['audited_input_rows']['character_talent']),
              'AFTER_COUNT': str(audit['audited_input_rows']['character_talent']-len(rows)),
              'RANK_COUNT': str(len(data['ranks'])), 'COLUMN_COUNT': str(len(columns)),
              'CONCAT_LIMIT': str(max(8192, len(rows)*40, len(data['ranks'])*12, len(columns)*1024)),
              'EXPECTED_INSERT': insert_values('expected', rows),
              'RANK_INSERT': insert_values('valid_rank_spell', [(spell,) for spell in data['ranks']]),
              'COLUMN_INSERT': insert_values('reviewed_columns', column_rows),
              'CHAR_EQUAL': ' AND '.join(f'(BINARY s.`{name}` <=> BINARY a.`{name}`)' for name in data['characters'])}
    setup = TEMPLATE.read_text()
    for key, value in values.items():
        setup = setup.replace('@'+key+'@', value)
    if re.search(r'@[A-Z_]+@', setup):
        raise ValueError('Unexpanded SQL template token')
    files = {'00-setup.sql': setup, 'manifest.json': json.dumps(manifest, sort_keys=True, indent=2)+'\n'}
    for number, action in [(1, 'prepare'), (2, 'apply'), (3, 'restore')]:
        files[f'0{number}-{action}.sql'] = (
            '-- Fresh batch connection with --skip-force; no interactive SOURCE.\n'
            '-- Explicit stopped preparation-copy acknowledgement required.\n'
            f'CALL `{archive}`.{action}_batch();\n')
    files['04-status.sql'] = f'''-- SELECT only. Retain privately; source keys describe archived rows.
SELECT * FROM `{archive}`.batch;
SELECT 'expected' AS object,COUNT(*) AS rows_found FROM `{archive}`.expected
UNION ALL SELECT 'character_before',COUNT(*) FROM `{archive}`.character_before
UNION ALL SELECT 'talent_before',COUNT(*) FROM `{archive}`.talent_before
UNION ALL SELECT 'talent_removed',COUNT(*) FROM `{archive}`.talent_removed;
SELECT guid,COUNT(*) AS archived_invalid_rows FROM `{archive}`.talent_removed GROUP BY guid ORDER BY guid;
SELECT guid,spell,talentGroup FROM `{archive}`.talent_removed ORDER BY guid,spell,talentGroup;
'''
    readme = (ROOT/'tools/talent-cleanup-README.md.in').read_text()
    for key, value in values.items():
        readme = readme.replace('@'+key+'@', value)
    files['README.md'] = readme
    return files, manifest


def generate(audit_dir, dbc_dir, expect_rows, output, archive_schema=None):
    data = load_inputs(audit_dir, dbc_dir, expect_rows)
    files, manifest = render(data, archive_schema)
    for path, checksum in data['fingerprints'].items():
        if sha(path) != checksum:
            raise ValueError('Input changed while generating candidate: ' + path.name)
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    # A failed write leaves a conspicuous incomplete package; never overwrite it.
    marker = output/'INCOMPLETE'
    marker.write_text('Generation did not finish. Do not execute this package.\n')
    marker.chmod(0o600)
    for name, text in files.items():
        path = output/name
        path.write_text(text)
        path.chmod(0o600)
    with (output/'selected-rows.tsv').open('w', newline='') as stream:
        writer = csv.writer(stream, delimiter='\t', lineterminator='\n')
        writer.writerow(['guid', 'spell', 'talentGroup', 'matchesTalentEntryId'])
        writer.writerows(data['evidence'])
    (output/'selected-rows.tsv').chmod(0o600)
    for path, checksum in data['fingerprints'].items():
        if sha(path) != checksum:
            raise ValueError('Input changed during candidate write: ' + path.name)
    sums = ''.join(sha(path)+'  '+path.name+'\n' for path in sorted(output.iterdir()) if path != marker)
    (output/'SHA256SUMS').write_text(sums)
    (output/'SHA256SUMS').chmod(0o600)
    marker.unlink()
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit-dir', type=Path, required=True)
    parser.add_argument('--tc-dbc', type=Path, required=True)
    parser.add_argument('--expect-rows', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--archive-schema')
    args = parser.parse_args()
    os.umask(0o077)
    try:
        manifest = generate(args.audit_dir, args.tc_dbc, args.expect_rows, args.output, args.archive_schema)
    except (ValueError, OSError, KeyError, TypeError, csv.Error) as error:
        print('Talent cleanup planning failed: '+str(error), file=sys.stderr)
        return 2
    print(f"CANDIDATE: {manifest['selected_rows']} exact rows across {manifest['affected_characters']} characters; no database connection or changes")
    print('Review '+str(args.output/'README.md')+'; archive schema: '+manifest['archive_schema'])
    return 0


if __name__ == '__main__':
    sys.exit(main())
