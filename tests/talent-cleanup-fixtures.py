"""Private synthetic audit packages for the offline talent cleanup planner."""
import csv
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


planner = module('talent_planner', ROOT/'tools/plan-talent-cleanup.py')
assets = module('talent_assets', ROOT/'tests/spell-fixtures.py')


def tsv(path, header, rows):
    with path.open('w', newline='') as stream:
        writer = csv.writer(stream, delimiter='\t', lineterminator='\n')
        writer.writerow(header)
        writer.writerows(rows)


def seal(audit_dir):
    (audit_dir/'SHA256SUMS').write_text(''.join(planner.sha(audit_dir/name)+'  '+name+'\n'
                                               for name in sorted(planner.REPORTS)))


def fixture(directory):
    directory = Path(directory)
    profile = json.loads(planner.PROFILE.read_text())
    assets.write_assets(directory, profile)
    audit = directory/'audit'
    audit.mkdir()
    data = {'status': 'COMPLETE', 'limitations': [], 'scope': 'talents',
            'schemas': {'characters': 'tc_fixture_chars', 'auth': 'tc_fixture_auth', 'world': 'tc_fixture_world'},
            'server': {'version': '8.4.10', 'uuid': '12345678-1234-1234-1234-123456789abc', 'transaction_read_only': '1'},
            'audit_tool_sha256': planner.sha(ROOT/'tools/audit-tc-source.py'),
            'metadata_reader_sha256': planner.sha(ROOT/'lib/spells.py'),
            'layout_profile_sha256': planner.sha(planner.PROFILE),
            'audited_results_sha256': 'a'*64, 'audited_input_rows': {'character_talent': 7, 'characters': 2},
            'dbc_sha256': {name+'.dbc': planner.sha(directory/'tc-dbc'/(name+'.dbc')) for name in ('Spell', 'Talent', 'TalentTab')}}
    (audit/'audit.json').write_text(json.dumps(data))
    findings = []
    for guid, spell, group in [(1,130,0), (1,142,0), (2,442,0)]:
        findings.append(['INVALID', 'tc_fixture_chars', 'character_talent', f'{guid}:{spell}:{group}', planner.REASON,
                         json.dumps({'spell': spell, 'talentGroup': group, 'matchesTalentEntryId': False})])
    findings.append(['REVIEW', 'tc_fixture_chars', 'character_spell', '1:12296', 'DISABLED_UNOWNED_TALENT_HISTORY', '{}'])
    tsv(audit/'findings.tsv', ['classification','schema','table','source_key','reason_code','evidence'], findings)
    tsv(audit/'summary.tsv', ['classification','reason_code','rows_found'], [('INVALID',planner.REASON,3)])
    columns = [('guid','int unsigned','NO','PRI'), ('class','tinyint unsigned','NO',''),
               ('race','tinyint unsigned','NO',''), ('level','tinyint unsigned','NO',''),
               ('online','tinyint unsigned','NO',''), ('activeTalentGroup','tinyint unsigned','NO',''),
               ('talentGroupsCount','tinyint unsigned','NO',''), ('legacy_note','varchar(40)','YES','')]
    inventory = [['T','tc_fixture_chars',table,'InnoDB','BASE TABLE','',''] for table in ('characters','character_talent')]
    for table, fields in [('characters', columns), ('character_talent', [
            ('guid','int unsigned','NO','PRI'), ('spell','mediumint unsigned','NO','PRI'),
            ('talentGroup','tinyint unsigned','NO','PRI')])]:
        inventory += [['C','tc_fixture_chars',table,*column] for column in fields]
    tsv(audit/'schema-inventory.tsv', ['kind','schema','table','name_or_engine','type','nullable','key'], inventory)
    tsv(audit/'coverage.tsv', ['check','status','missing_columns'], [('native-character-state','CHECKED','')])
    (audit/'cleanup-review.tsv').write_text('classification\treason_code\trows_found\trequired_action\n')
    (audit/'audit-queries.sql').write_text('START TRANSACTION READ ONLY; SELECT 1; ROLLBACK;\n')
    seal(audit)
    return audit, directory/'tc-dbc'
