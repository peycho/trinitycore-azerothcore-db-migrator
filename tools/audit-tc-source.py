#!/usr/bin/env python3
"""Read-only TC source-health audit. Produces evidence, never cleanup SQL.

Run against a stopped restored copy with SELECT-only credentials. Native health
and migration compatibility are distinct; this tool cannot approve either a
cleanup or a migration. All data queries share one read-only InnoDB snapshot.
"""
import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'lib'))
from spells import Database, MetadataQueryError, digest, read_dbc


def file_digest(path):
    hasher = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(1024*1024):
            hasher.update(block)
    return hasher.hexdigest()


class AuditDatabase(Database):
    def rows(self, label, query):
        # A batch can produce a large result before mysql reads its next
        # statement. File-backed stdin/stderr avoid either pipe deadlocking.
        hasher = hashlib.sha256()
        with tempfile.TemporaryFile() as source, tempfile.TemporaryFile() as errors:
            source.write(query.encode())
            source.seek(0)
            with subprocess.Popen(['mysql', *self.arguments, '--batch', '--skip-raw',
                                   '--skip-column-names', '--quick', '--unbuffered'], stdin=source,
                                  stdout=subprocess.PIPE, stderr=errors) as process:
                try:
                    for line in process.stdout:
                        hasher.update(line)
                        yield line.decode().rstrip('\n').split('\t')
                    if process.wait():
                        errors.seek(0)
                        raise MetadataQueryError(label, errors.read().decode().strip())
                finally:
                    if process.poll() is None:
                        process.terminate()
                        process.wait()
        self.fingerprints[label] = hasher.hexdigest()


def ident(value):
    if not re.fullmatch(r'[A-Za-z0-9_]+', value):
        raise ValueError('Schema/table/column names must contain only ASCII letters, digits and underscores')
    return '`' + value + '`'


def mysql_arguments(values):
    allowed = ('--defaults-extra-file=', '--defaults-file=', '--host=', '--port=', '--user=',
               '--socket=', '--protocol=', '--ssl-mode=', '--ssl-ca=', '--ssl-cert=', '--ssl-key=',
               '--connect-timeout=', '--default-character-set=', '--login-path=')
    if any(value != '--no-defaults' and not value.startswith(allowed) for value in values):
        raise ValueError('Use documented long MySQL connection options; executable/force options and inline passwords are forbidden')
    return [*values, '--skip-force', '--init-command=SET SESSION transaction_read_only=ON']


class Findings:
    def __init__(self, output):
        self.file = (output/'findings.tsv').open('w', newline='')
        self.writer = csv.writer(self.file, delimiter='\t', lineterminator='\n')
        self.writer.writerow(['classification', 'schema', 'table', 'source_key', 'reason_code', 'evidence'])
        self.counts = Counter()

    def add(self, classification, schema, table, key, reason, evidence):
        self.counts[(classification, reason)] += 1
        self.writer.writerow([classification, schema, table, key, reason,
                              json.dumps(evidence, sort_keys=True, separators=(',', ':'))])


def catalog(directory, profile, scope):
    stores, hashes = {}, {}
    names = ['Spell', 'Talent', 'TalentTab'] + (['SkillLine'] if scope == 'all' else [])
    for name in names:
        stores[name], hashes[name+'.dbc'] = read_dbc(directory/(name+'.dbc'), profile['stores'][name]['formats']['tc'])
    ranks = defaultdict(list)
    for row in stores['Talent'].values():
        tab = stores['TalentTab'].get(row[1])
        for rank, spell in enumerate(row[4:9], 1):
            if spell:
                ranks[spell].append((row[0], rank, tab[20] if tab else 0))
    return stores, ranks, hashes


def audit_character(guid, rows, stores, ranks, custom_spells, complete_spell_catalog, schema, findings):
    rows = list(rows)  # bounded to one character, not the entire database
    state = next((tuple(map(int, row[2:6])) for row in rows if row[1] == '0'), None)
    selected, by_talent = defaultdict(set), defaultdict(list)
    for _, kind, a, b, c, _ in rows:
        a, b, c = map(int, (a, b, c))
        table = {'1': 'character_talent', '2': 'character_skills', '3': 'character_spell'}.get(kind)
        key = f'{guid}:{a}' + (f':{b}' if kind == '1' else '')
        if state is None:
            if table:
                findings.add('ORPHAN', schema, table, key, 'CHILD_WITHOUT_CHARACTER', {'guid': guid, 'id': a})
            continue
        race, cls, active, groups = state
        if kind == '0':
            if groups not in (1, 2) or not 0 <= active < groups:
                findings.add('INVALID', schema, 'characters', guid, 'INVALID_SPECIALIZATION_STATE',
                             {'activeTalentGroup': active, 'talentGroupsCount': groups})
            if race not in {1,2,3,4,5,6,7,8,10,11} or cls not in {1,2,3,4,5,6,7,8,9,11}:
                findings.add('REVIEW', schema, 'characters', guid, 'NONSTANDARD_RACE_CLASS', {'race': race, 'class': cls})
        elif kind == '1':
            selected[a].add(b)
            if a not in ranks:
                findings.add('INVALID', schema, table, key, 'TALENT_VALUE_IS_NOT_RANK_SPELL',
                    {'spell': a, 'talentGroup': b, 'matchesTalentEntryId': a in stores['Talent'],
                     'policy': 'Review full-row archive/removal; never infer a replacement rank'})
            else:
                matches = [(talent, rank) for talent, rank, mask in ranks[a] if 1 <= cls <= 32 and mask & (1 << (cls-1))]
                if not matches:
                    findings.add('INVALID', schema, table, key, 'TALENT_CLASS_MISMATCH', {'spell': a, 'class': cls})
                elif len(matches) > 1:
                    findings.add('REVIEW', schema, table, key, 'AMBIGUOUS_TALENT_METADATA', {'spell': a})
                else:
                    by_talent[(matches[0][0], b)].append(a)
            if not 0 <= b < groups or groups not in (1, 2):
                findings.add('INVALID', schema, table, key, 'TALENT_GROUP_OUT_OF_RANGE', {'talentGroup': b, 'talentGroupsCount': groups})
        elif kind == '2':
            if a not in stores.get('SkillLine', {}):
                findings.add('REVIEW', schema, table, key, 'UNKNOWN_SKILL_ID', {'skill': a})
            if b > c:
                findings.add('INVALID', schema, table, key, 'SKILL_VALUE_EXCEEDS_CAP', {'skill': a, 'value': b, 'max': c})
        elif kind == '3':
            if complete_spell_catalog and a not in stores['Spell'] and a not in custom_spells:
                findings.add('INVALID', schema, table, key, 'UNKNOWN_SPELL_ID', {'spell': a})
            if b not in (0, 1) or c not in (0, 1):
                findings.add('INVALID', schema, table, key, 'INVALID_SPELL_FLAGS', {'spell': a, 'active': b, 'disabled': c})
            if a in ranks and a not in selected:
                findings.add('REVIEW', schema, table, key,
                    'DISABLED_UNOWNED_TALENT_HISTORY' if c else 'ENABLED_UNOWNED_TALENT_SPELL',
                    {'spell': a, 'active': b, 'disabled': c, 'policy': 'No activation, deletion or guessed ownership'})
            elif a in ranks and ((not c and active not in selected[a]) or (c and active in selected[a])):
                findings.add('REVIEW',schema,table,key,'TALENT_SPELL_SPEC_STATE_CONFLICT',
                             {'spell':a,'activeTalentGroup':active,'selectedGroups':sorted(selected[a]),'disabled':c})
    for (talent, group), spells in sorted(by_talent.items()):
        if len(spells) > 1:
            findings.add('REVIEW', schema, 'character_talent', f'{guid}:{talent}:{group}', 'MULTIPLE_TALENT_RANKS_IN_GROUP',
                         {'talentEntry': talent, 'talentGroup': group, 'spells': sorted(spells)})


class Queries:
    def __init__(self, inventory, findings, coverage):
        self.inventory, self.findings, self.coverage = inventory, findings, coverage
        self.used = set()
        self.statements = []

    def require(self, name, requirements):
        missing = [f'{schema}.{table}.{column}' for schema, table, columns in requirements
                   for column in columns if (column.lower() not in self.inventory.get((schema, table), {}).get('columns', {})
                   or self.inventory.get((schema, table), {}).get('type') != 'BASE TABLE')]
        self.coverage.append([name, 'SKIPPED' if missing else 'CHECKED', ','.join(missing)])
        if missing:
            return False
        self.used.update((schema, table) for schema, table, _ in requirements)
        return True

    def add(self, name, query):
        self.statements.append(f"SELECT 'progress','{name}';\n{query};")

    def orphan(self, schema, child, column, parent_schema, parent, parent_column, nonzero=False):
        name = f'{child}.{column}->{parent_schema}.{parent}.{parent_column}'
        if not self.require(name, [(schema, child, [column]), (parent_schema, parent, [parent_column])]):
            return
        condition = f'AND s.{ident(column)}<>0' if nonzero else ''
        keys = sorted(name for name,info in self.inventory[(schema,child)]['columns'].items() if info[3] == 'PRI')
        key = 'JSON_OBJECT(' + ','.join(f"'{name}',s.{ident(name)}" for name in keys or [column]) + ')'
        self.add(name, f"SELECT 'finding','ORPHAN','{schema}','{child}',{key},'MISSING_PARENT','{name}' "
            f'FROM {ident(schema)}.{ident(child)} s LEFT JOIN {ident(parent_schema)}.{ident(parent)} p '
            f'ON p.{ident(parent_column)}=s.{ident(column)} WHERE p.{ident(parent_column)} IS NULL {condition} '
            f'ORDER BY s.{ident(column)}')


def inventory(db, schemas):
    values = ','.join("'" + schema + "'" for schema in sorted(schemas))
    query = f'''SELECT 'T',TABLE_SCHEMA,TABLE_NAME,COALESCE(ENGINE,''),TABLE_TYPE,'',''
        FROM information_schema.TABLES WHERE TABLE_SCHEMA IN ({values})
        UNION ALL SELECT 'C',TABLE_SCHEMA,TABLE_NAME,COLUMN_NAME,COLUMN_TYPE,IS_NULLABLE,COLUMN_KEY
        FROM information_schema.COLUMNS WHERE TABLE_SCHEMA IN ({values})
        ORDER BY 1,2,3,4,5,6,7;'''
    rows = list(db.rows('schema-inventory', query))
    result = {}
    for kind, schema, table, a, b, c, d in rows:
        entry = result.setdefault((schema, table), {'columns': {}})
        if kind == 'T':
            entry.update(engine=a, type=b)
        else:
            entry['columns'][a.lower()] = (a, b, c, d)
    return result, rows


def build_queries(args, tables, findings, coverage):
    q = Queries(tables, findings, coverage)
    chars, auth, world = args.characters_schema, args.auth_schema, args.world_schema
    q.add('server', "SELECT 'server',@@version,@@server_uuid,@@transaction_read_only")
    required = [(chars,'characters',['guid','race','class','activeTalentGroup','talentGroupsCount']),
                (chars,'character_talent',['guid','spell','talentGroup'])]
    if args.scope == 'all':
        required += [(chars,'character_spell',['guid','spell','active','disabled']),
                     (chars,'character_skills',['guid','skill','value','max'])]
    if not q.require('native-character-state', required):
        raise ValueError('Required native TC columns are missing; inspect coverage.tsv and schema inventory before upgrading any schema')
    selects = [f'SELECT guid,0 kind,race a,class b,activeTalentGroup c,talentGroupsCount d FROM {ident(chars)}.characters',
               f'SELECT guid,1,spell,talentGroup,0,0 FROM {ident(chars)}.character_talent']
    if args.scope == 'all':
        selects += [f'SELECT guid,2,skill,value,max,0 FROM {ident(chars)}.character_skills',
                    f'SELECT guid,3,spell,active,disabled,0 FROM {ident(chars)}.character_spell']
    overlay = q.require('TC-custom-spell-catalog', [(world,'spell_dbc',['Id'])])
    if overlay:
        q.add('TC-custom-spell-catalog', f"SELECT 'custom-spell',Id FROM {ident(world)}.spell_dbc ORDER BY Id")
    q.add('character-state', "SELECT 'state',guid,kind,a,b,c,d FROM (" + ' UNION ALL '.join(selects) + ') inputs ORDER BY guid,kind,a,b,c,d')
    if args.scope == 'all':
        q.orphan(chars,'characters','account',auth,'account','id',True)
        for child in ['character_action','character_aura','character_inventory',
                      'character_glyphs','character_queststatus','character_queststatus_rewarded',
                      'character_achievement','character_achievement_progress','character_reputation','guild_member']:
            q.orphan(chars,child,'guid',chars,'characters','guid')
        for child, column, parent, parent_column, nonzero in [
            ('character_pet','owner','characters','guid',False),
            ('pet_spell','guid','character_pet','id',False),('pet_aura','guid','character_pet','id',False),
            ('pet_spell_cooldown','guid','character_pet','id',False),
            ('character_inventory','item','item_instance','guid',False),
            ('character_inventory','bag','item_instance','guid',True),
            ('mail','receiver','characters','guid',False),('mail_items','mail_id','mail','id',False),
            ('mail_items','item_guid','item_instance','guid',False),
            ('guild_member','guildid','guild','guildid',False),
            ('guild_bank_item','guildid','guild','guildid',False),
            ('guild_bank_item','item_guid','item_instance','guid',False),
            ('auctionhouse','itemguid','item_instance','guid',False)]:
            q.orphan(chars,child,column,chars,parent,parent_column,nonzero)
        if q.require('item-template', [(chars,'item_instance',['guid','itemEntry']), (world,'item_template',['entry'])]):
            q.add('item-template', f"SELECT 'finding','REVIEW','{chars}','item_instance',i.guid,'ITEM_TEMPLATE_MISSING',i.itemEntry "
                  f'FROM {ident(chars)}.item_instance i LEFT JOIN {ident(world)}.item_template t ON t.entry=i.itemEntry '
                  'WHERE t.entry IS NULL ORDER BY i.guid')
        for table in ['character_queststatus','character_queststatus_rewarded']:
            if q.require(table+'-template', [(chars,table,['guid','quest']), (world,'quest_template',['ID'])]):
                q.add(table+'-template', f"SELECT 'finding','REVIEW','{chars}','{table}',CONCAT(c.guid,':',c.quest),'QUEST_TEMPLATE_MISSING',c.quest "
                      f'FROM {ident(chars)}.{ident(table)} c LEFT JOIN {ident(world)}.quest_template q ON q.ID=c.quest '
                      'WHERE q.ID IS NULL ORDER BY c.guid,c.quest')
        roots = [('character_inventory','item'),('mail_items','item_guid'),('guild_bank_item','item_guid'),('auctionhouse','itemguid')]
        if q.require('duplicate-item-placements', [(chars,table,[column]) for table,column in roots]):
            union = ' UNION ALL '.join(f"SELECT {ident(column)} item,'{table}' location FROM {ident(chars)}.{ident(table)}" for table,column in roots)
            q.add('duplicate-item-placements', f"SELECT 'finding','REVIEW','{chars}','item_instance',item,'ITEM_MULTIPLE_ROOT_REFERENCES',COUNT(*) "
                  f'FROM ({union}) roots GROUP BY item HAVING COUNT(*)>1 ORDER BY item')
    return q, overlay


def run(args, output, findings):
    schemas = {args.characters_schema, args.auth_schema, args.world_schema}
    for value in schemas:
        ident(value)
    if len(schemas) != 3:
        raise ValueError('Characters, auth and world schemas must be distinct')
    code_hashes = {path:file_digest(path) for path in [Path(__file__),ROOT/'lib/spells.py']}
    db = AuditDatabase(mysql_arguments(args.mysql))
    profile_bytes = args.layout_profile.read_bytes()
    profile = json.loads(profile_bytes)
    if profile.get('version') != 1:
        raise ValueError('Unsupported DBC layout-profile version')
    stores, ranks, dbc_hashes = catalog(args.tc_dbc, profile, args.scope)
    tables, schema_rows = inventory(db, schemas)
    write_tsv(output/'schema-inventory.tsv', ['kind','schema','table','name_or_engine','type','nullable','key'], schema_rows)
    coverage = []
    try:
        queries, complete_catalog = build_queries(args, tables, findings, coverage)
    finally:
        write_tsv(output/'coverage.tsv', ['check','status','missing_columns'], coverage)
    custom_spells, state_group, current_guid = set(), [], None
    processed = 0
    sql = 'SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ;\nSTART TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY;\n'
    sql += '\n'.join(queries.statements) + '\nROLLBACK;'
    (output/'audit-queries.sql').write_text(sql)
    servers, input_counts = [], Counter()
    for row in db.rows('source-snapshot', sql):
        if row[0] != 'state' and current_guid is not None:
            audit_character(current_guid,state_group,stores,ranks,custom_spells,complete_catalog,args.characters_schema,findings)
            state_group, current_guid = [], None
        if row[0] == 'progress':
            print('Auditing ' + row[1], file=sys.stderr, flush=True)
        elif row[0] == 'server':
            servers.append(row[1:])
        elif row[0] == 'custom-spell':
            spell = int(row[1])
            custom_spells.add(spell)
            if spell in stores['Spell']:
                findings.add('REVIEW',args.world_schema,'spell_dbc',spell,'TC_DBC_OVERLAY_COLLISION',{'spell':spell})
        elif row[0] == 'state':
            guid = int(row[1])
            input_counts[{'0':'characters','1':'character_talent','2':'character_skills','3':'character_spell'}[row[2]]] += 1
            if current_guid is not None and current_guid != guid:
                audit_character(current_guid,state_group,stores,ranks,custom_spells,complete_catalog,args.characters_schema,findings)
                processed += 1
                if processed % 10000 == 0:
                    print(f'Audited {processed} character keys',file=sys.stderr,flush=True)
                state_group = []
            current_guid = guid
            state_group.append(row[1:])
        elif row[0] == 'finding':
            _, classification, schema, table, key, reason, detail = row
            findings.add(classification,schema,table,key,reason,{'observed':detail})
        else:
            raise ValueError('Unexpected audit protocol record')
    if current_guid is not None:
        audit_character(current_guid,state_group,stores,ranks,custom_spells,complete_catalog,args.characters_schema,findings)
    if not servers or servers[0][2] != '1':
        raise ValueError('Read-only transaction was not confirmed')
    _, after = inventory(db, schemas)
    if schema_rows != after:
        raise ValueError('Schema changed during audit; results are incomplete')
    for name, sha in dbc_hashes.items():
        if file_digest(args.tc_dbc/name) != sha:
            raise ValueError('DBC changed during audit; results are incomplete')
    if file_digest(args.layout_profile) != digest(profile_bytes) or any(
            file_digest(path) != sha for path,sha in code_hashes.items()):
        raise ValueError('Audit code or layout profile changed during audit; results are incomplete')
    limitations = [name for name,status,_ in coverage if status == 'SKIPPED']
    for schema,table in sorted(queries.used):
        if tables[(schema,table)].get('engine') != 'InnoDB':
            limitations.append(f'Non-InnoDB input: {schema}.{table}')
    return {'status':'COMPLETE_WITH_LIMITATIONS' if limitations else 'COMPLETE', 'scope':args.scope,
            'limitations':limitations,
            'server':dict(zip(['version','uuid','transaction_read_only'],servers[0])),
            'schemas':{'characters':args.characters_schema,'auth':args.auth_schema,'world':args.world_schema},
            'dbc_sha256':dbc_hashes, 'layout_profile_sha256':digest(profile_bytes),
            'audited_results_sha256':db.fingerprints['source-snapshot'],
            'audited_input_rows':dict(sorted(input_counts.items())),
            'audit_tool_sha256':code_hashes[Path(__file__)],
            'metadata_reader_sha256':code_hashes[ROOT/'lib/spells.py'],
            'migration_approval':'NOT_GRANTED', 'cleanup_approval':'NOT_GRANTED'}


def write_tsv(path, header, rows):
    with path.open('w', newline='') as stream:
        writer = csv.writer(stream, delimiter='\t', lineterminator='\n')
        writer.writerow(header)
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['characters-schema','auth-schema','world-schema']:
        parser.add_argument('--'+name, required=True)
    parser.add_argument('--tc-dbc', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--layout-profile', type=Path, default=ROOT/'compatibility/tc335-acwotlk-v2/spell-metadata.json')
    parser.add_argument('--scope', choices=['talents','all'], default='all')
    parser.add_argument('--mysql', nargs=argparse.REMAINDER, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    try:
        args.output.mkdir(parents=True, exist_ok=False)
    except OSError as error:
        parser.error('A fresh writable output directory is required: ' + str(error))
    findings = Findings(args.output)
    started = datetime.now(timezone.utc).isoformat()
    status = {'status':'INCOMPLETE','scope':args.scope,'cleanup_approval':'NOT_GRANTED','migration_approval':'NOT_GRANTED'}
    try:
        status = run(args,args.output,findings)
    except Exception as error:
        # Never echo client arguments or option-file contents.
        status['error'] = str(error)
        print('Audit incomplete: ' + str(error), file=sys.stderr)
    finally:
        findings.file.close()
        status['started_utc'] = started
        status['created_utc'] = datetime.now(timezone.utc).isoformat()
        write_tsv(args.output/'summary.tsv',['classification','reason_code','rows_found'],
                  [(kind,reason,count) for (kind,reason),count in sorted(findings.counts.items())])
        write_tsv(args.output/'cleanup-review.tsv',['classification','reason_code','rows_found','required_action'],
                  [(kind,reason,count,'Review exact rows, matching metadata, preservation and full-row archive/rollback; no automatic cleanup')
                   for (kind,reason),count in sorted(findings.counts.items())])
        (args.output/'audit.json').write_text(json.dumps(status,sort_keys=True,indent=2)+'\n')
        files = sorted(path for path in args.output.iterdir() if path.is_file())
        (args.output/'SHA256SUMS').write_text(''.join(file_digest(path)+'  '+path.name+'\n' for path in files))
    print(f"{status['status']}: {sum(findings.counts.values())} finding(s); reports: {args.output}")
    if status['status'] != 'COMPLETE':
        return 2
    return 1 if findings.counts else 0


if __name__ == '__main__':
    sys.exit(main())
