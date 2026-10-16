#!/usr/bin/env python3
"""Bidirectional tests against a caller-provisioned disposable MySQL 8.4 server."""
import gzip
import hashlib
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
import uuid
import importlib.util

ROOT, WORK = map(Path, sys.argv[1:])
TOOLKIT = WORK / 'toolkit'
TC = Path(os.environ['TRINITYCORE_DIR'])
AC = Path(os.environ['AZEROTHCORE_DIR'])
MYSQL = shutil.which('mysql')
PORT = os.environ['REHEARSAL_MYSQL_PORT']
OPTION_FILE = os.environ.get('REHEARSAL_MYSQL_DEFAULTS_FILE', '')
RUNNER_OPTION_FILE = WORK / 'migration-client.cnf'
RUNNER_OPTION_FILE.write_text('[client]\npassword=\n')
RUNNER_OPTION_FILE.chmod(0o600)
MYSQL_ARGS = ([f'--defaults-extra-file={OPTION_FILE}'] if OPTION_FILE else ['--no-defaults']) + [
    '--host=127.0.0.1', f'--port={PORT}', '--protocol=TCP', '--user=root',
    '--default-character-set=utf8mb4', '--batch', '--raw', '--skip-column-names',
    "--init-command=SET SESSION time_zone='+00:00'",
]
PREFIX = 'migrator_test_' + uuid.uuid4().hex[:12]
SCHEMAS = [PREFIX + suffix for suffix in ('_auth', '_chars', '_ac_auth', '_ac_chars',
                                        '_tc_auth', '_tc_chars', '_fcontrol', '_rcontrol', '_world')]
AUTH, CHARS, AC_AUTH, AC_CHARS, TC_AUTH, TC_CHARS, FC, RC, WORLD = SCHEMAS
AC_WORLD = PREFIX + '_ac_world'
SCHEMAS.append(AC_WORLD)
spec = importlib.util.spec_from_file_location('spell_fixtures', ROOT/'tests/spell-fixtures.py')
SPELL_FIXTURES = importlib.util.module_from_spec(spec)
spec.loader.exec_module(SPELL_FIXTURES)
import json
SPELL_PROFILE = json.loads((TOOLKIT/'compatibility'/os.environ['COMPATIBILITY_PROFILE']/'spell-metadata.json').read_text())
SPELL_FIXTURES.write_assets(WORK,SPELL_PROFILE)
USER = PREFIX
LOG = WORK / 'rehearsal.log'
OWNED_SCHEMAS = []
OWNED_USER = False
CONFIG_VALUES = {}


def sql(query, database=None):
    command = [MYSQL, *MYSQL_ARGS]
    if database:
        command += [f'--database={database}']
    result = subprocess.run(command, input=query, text=True, capture_output=True)
    if result.returncode:
        raise AssertionError(result.stderr + '\n' + query[:1200])
    return result.stdout.strip()


def equal(query, expected):
    actual = sql(query)
    assert actual == str(expected), (query, actual, expected)


def config(direction, suffix=''):
    forward = direction == 'tc-to-ac'
    source_auth, source_chars = (AUTH, CHARS) if forward else (AC_AUTH, AC_CHARS)
    target_auth, target_chars, control = (AC_AUTH, AC_CHARS, FC) if forward else (TC_AUTH, TC_CHARS, RC)
    path = WORK / (direction + suffix + '.env')
    # Administrator credentials must never be reused for the blank-password
    # disposable migration user. All endpoints remain on localhost.
    values = dict(MYSQL_DEFAULTS_FILE=str(RUNNER_OPTION_FILE), MYSQL_HOST='127.0.0.1', MYSQL_PORT=PORT,
                  MYSQL_USER=USER, MYSQL_SOCKET='', MIGRATION_DIRECTION=direction,
                  SOURCE_AUTH_SCHEMA=source_auth, SOURCE_CHARACTERS_SCHEMA=source_chars,
                  SOURCE_WORLD_SCHEMA=WORLD if forward else AC_WORLD,
                  TARGET_WORLD_SCHEMA=AC_WORLD if forward else WORLD,
                  TRINITYCORE_DBC_DIR=str(WORK/'tc-dbc'),AZEROTHCORE_DBC_DIR=str(WORK/'ac-dbc'),
                  TARGET_AUTH_SCHEMA=target_auth,
                  TARGET_CHARACTERS_SCHEMA=target_chars, CONTROL_SCHEMA=control, REALM_ID='1',
                  TRINITYCORE_DIR=str(TC), AZEROTHCORE_DIR=str(AC),
                  COMPATIBILITY_PROFILE=os.environ['COMPATIBILITY_PROFILE'],
                  LOAD_CHUNK_SIZE='1', CLEANUP_CHUNK_SIZE='1', LARGE_TABLE_ROWS='1',
                  DEFER_SECONDARY_INDEXES='1', REQUIRE_QUIESCENT='0',
                  ALLOW_SOURCE_ARCHIVE='1', ALLOW_GAMEPLAY_ARCHIVE='1',
                  ARCHIVE_DIR=str(WORK / 'archives'), MIGRATION_RUN_ID=str(uuid.uuid4()))
    # shlex.quote preserves option-file and checkout paths exactly.
    import shlex
    path.write_text(''.join(f'{key}={shlex.quote(value)}\n' for key, value in values.items()))
    CONFIG_VALUES[path] = values
    return path, values


def run(command, expected=None, env=None):
    result = subprocess.run(command, text=True, capture_output=True, env=env)
    with LOG.open('a') as output:
        output.write(result.stdout + result.stderr)
    if expected:
        assert result.returncode != 0 and expected in result.stderr, result.stderr[-2500:]
    elif result.returncode:
        raise AssertionError(result.stderr[-6500:])
    return result


def phase(cfg, name, expected=None):
    return run([str(TOOLKIT / 'bin/migrate.sh'), '--config', str(cfg), name], expected)


def library(cfg, body, expected=None):
    script = '''set -Eeuo pipefail
MIGRATION_ROOT=$1
for module in common compatibility preflight assemble archive load sanitize validate representations spells; do
    source "$MIGRATION_ROOT/lib/$module.sh"
done
trap cleanup_compatibility_state EXIT
load_configuration "$2"
create_run_id
''' + body
    return run(['bash', '-c', script, '_', str(TOOLKIT), str(cfg)], expected)


def guard(direction, reason=None):
    cfg, values = config(direction, '-guard')
    library(cfg, 'check_source_representations', 'Source representations' if reason else None)
    report = TOOLKIT / 'reports' / values['MIGRATION_RUN_ID'] / 'source-blockers.tsv'
    if reason:
        assert reason in report.read_text(), report.read_text()


def snapshot(*schemas):
    # Stable native DDL and sorted binary-safe data, independent of table order.
    hashes = []
    for schema in schemas:
        tables = sql(f"SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA='{schema}' "
                     "AND TABLE_TYPE='BASE TABLE' ORDER BY TABLE_NAME").splitlines()
        for table in tables:
            hashes.append(sql(f' SHOW CREATE TABLE `{schema}`.`{table}`'))
            columns = sql(f"SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA='{schema}' "
                          f"AND TABLE_NAME='{table}' ORDER BY ORDINAL_POSITION").splitlines()
            select = ','.join(f'IFNULL(HEX(CAST(`{c}` AS BINARY)),\'NULL\')' for c in columns)
            hashes.extend(sorted(sql(f'SELECT {select} FROM `{schema}`.`{table}`').splitlines()))
    return hashlib.sha256('\n'.join(hashes).encode()).hexdigest()


def interrupt(cfg, name, token, after_ddl=False, after_commit=False, resume=True):
    """Pause a real MySQL session, kill its process group, then resume the runner."""
    proxy_dir = WORK / 'proxy'
    proxy_dir.mkdir(exist_ok=True)
    proxy = proxy_dir / 'mysql'
    proxy.write_text('''#!/usr/bin/env python3
import os,sys
args=sys.argv[1:]
if '-e' in args:
    i=args.index('-e')+1
    statement=args[i]
    token=os.environ.get('MIGRATOR_PAUSE_TOKEN','')
    if token and token in statement:
        if os.environ.get('MIGRATOR_AFTER_DDL')=='1' or os.environ.get('MIGRATOR_AFTER_COMMIT')=='1':
            args[i]=statement+'; DO SLEEP(30);'
        elif 'COMMIT;' in statement:
            args[i]=statement.replace('COMMIT;','DO SLEEP(30); COMMIT;',1)
    if os.environ.get('MIGRATOR_FAIL_TOKEN') and os.environ['MIGRATOR_FAIL_TOKEN'] in statement and 'COMMIT;' in statement:
        args[i]=statement.replace('COMMIT;',"SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='fixture rollback'; COMMIT;",1)
os.execv(os.environ['MIGRATOR_REAL_MYSQL'],[os.environ['MIGRATOR_REAL_MYSQL'],*args])
''')
    proxy.chmod(0o755)
    env = os.environ | dict(PATH=str(proxy_dir) + ':' + os.environ['PATH'],
                            MIGRATOR_REAL_MYSQL=MYSQL, MIGRATOR_PAUSE_TOKEN=token,
                            MIGRATOR_AFTER_DDL='1' if after_ddl else '0',
                            MIGRATOR_AFTER_COMMIT='1' if after_commit else '0')
    with LOG.open('a') as output:
        proc = subprocess.Popen([str(TOOLKIT / 'bin/migrate.sh'), '--config', str(cfg), name],
                                stdout=output, stderr=output, env=env, start_new_session=True)
        deadline = time.monotonic() + 90
        try:
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    raise AssertionError('Interruption point was not reached: ' + LOG.read_text()[-2000:])
                if sql(f"SELECT COUNT(*) FROM information_schema.PROCESSLIST WHERE USER='{USER}' "
                       "AND STATE='User sleep'") != '0':
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait(timeout=10)
                    break
                time.sleep(0.1)
            else:
                raise AssertionError('Timed out waiting for interruption point')
        finally:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=10)
    # Wait for server-side disconnect/rollback before inspecting or replaying.
    deadline = time.monotonic() + 10
    while sql(f"SELECT COUNT(*) FROM information_schema.PROCESSLIST WHERE USER='{USER}'") != '0':
        assert time.monotonic() < deadline, 'Interrupted connection did not close'
        time.sleep(0.1)
    values = CONFIG_VALUES[cfg]
    control, run_id = values['CONTROL_SCHEMA'], values['MIGRATION_RUN_ID']
    equal(f"SELECT status FROM `{control}`.phase_checkpoint WHERE run_id='{run_id}' AND phase_name='{name}'", 'RUNNING')
    if 'item_loot_items' in token:
        equal(f'SELECT COUNT(*) FROM `{TC_CHARS}`.item_loot_items', 0)
        equal(f"SELECT COUNT(*) FROM `{control}`.chunk_checkpoint WHERE run_id='{run_id}' "
              "AND target_table='item_loot_items+item_loot_money'", 0)
    if 'pet_spell`' in token:
        equal(f'SELECT COUNT(*) FROM `{AC_CHARS}`.pet_spell WHERE guid=777', 1)
    if after_ddl:
        assert int(sql(f"SELECT COUNT(*) FROM `{control}`.deferred_index WHERE status='DROPPED'")) > 0
    if resume:
        phase(cfg, name)


def seed_pet_relations(schema, reverse=False):
    sql('''INSERT INTO pet_spell (guid,spell,active) VALUES (300,17253,1),(777,17253,1);
INSERT INTO pet_aura (guid,casterGuid,spell,effectMask,amount0,amount1,amount2,
 base_amount0,base_amount1,base_amount2) VALUES
 (300,100,17253,1,1,0,0,1,0,0),(777,100,17253,1,1,0,0,1,0,0);''', schema)
    if reverse:
        sql('INSERT INTO pet_spell_cooldown (guid,spell,category,time) VALUES (777,17253,2,2000000200)', schema)
    else:
        sql('INSERT INTO pet_spell_cooldown (guid,spell,time,categoryId,categoryEnd) '
            'VALUES (777,17253,2000000000,2,2000000200)', schema)


def assert_ready(values):
    control, target = values['CONTROL_SCHEMA'], values['TARGET_CHARACTERS_SCHEMA']
    source = values['SOURCE_CHARACTERS_SCHEMA']
    equal(f"SELECT status FROM `{control}`.migration_run WHERE run_id='{values['MIGRATION_RUN_ID']}'", 'READY')
    equal(f"SELECT COUNT(*) FROM `{control}`.validation_result WHERE severity='ERROR' AND passed=0", 0)
    equal(f"SELECT COUNT(*) FROM `{control}`.deferred_index WHERE status<>'RESTORED'", 0)
    assert int(sql(f'SELECT COUNT(*) FROM `{control}`.deferred_index')) > 0
    equal(f'''SELECT COUNT(*) FROM `{source}`.item_instance s
        LEFT JOIN `{target}`.item_instance t ON t.guid=s.guid
        WHERE s.guid IN (200,201) AND (t.guid IS NULL
          OR BINARY t.charges<>BINARY s.charges OR BINARY t.enchantments<>BINARY s.enchantments)''', 0)
    equal(f'''SELECT COUNT(*) FROM `{source}`.corpse s
        LEFT JOIN `{target}`.corpse t ON t.guid=s.guid WHERE s.guid=100
        AND (t.guid IS NULL OR BINARY t.itemCache<>BINARY s.itemCache)''', 0)
    equal(f'SELECT item_guid FROM `{target}`.guild_bank_item WHERE guildid=940 AND TabId=0 AND SlotId=0', 201)
    equal(f'''SELECT weekGames,weekWins,seasonGames,seasonWins,personalRating
        FROM `{target}`.arena_team_member WHERE guid=100''', '4\t2\t10\t5\t1540')
    for table in ('pet_aura', 'pet_spell', 'pet_spell_cooldown'):
        equal(f'SELECT COUNT(*) FROM `{target}`.{table} WHERE guid=777', 0)
        equal(f'SELECT COUNT(*) FROM `{target}`.{table} WHERE guid=300', 1)
        expected_removed = 2 if values['MIGRATION_DIRECTION'] == 'tc-to-ac' and table == 'pet_spell' else 1
        equal(f"SELECT removed_rows FROM `{control}`.cleanup_table_summary WHERE table_name='{table}'", expected_removed)


def spell_guard(reason,edit,restore):
    original_inputs = snapshot(AUTH,CHARS,WORLD,AC_WORLD)
    cfg,values = config('tc-to-ac','-spell-guard')
    sql(edit)
    try:
        library(cfg,'initialize_control_schema\nprepare_spell_snapshot capture','Spell state is incompatible')
        report = TOOLKIT/'reports'/values['MIGRATION_RUN_ID']/'spell-state-blockers.tsv'
        assert reason in report.read_text(),report.read_text()
        equal(f"SELECT COUNT(*) FROM `{FC}`.spell_input_snapshot WHERE run_id='{values['MIGRATION_RUN_ID']}'",0)
    finally:
        sql(restore)
    assert snapshot(AUTH,CHARS,WORLD,AC_WORLD)==original_inputs,'Spell guard modified an input'


def main():
    global OWNED_USER
    server_version = sql('SELECT @@version')
    assert server_version.startswith('8.4.'), f'MySQL 8.4.x is required; server reports {server_version}'
    print(f'Disposable MySQL server: {server_version}', flush=True)
    # Refuse collisions; cleanup can only drop this run's freshly owned names.
    for schema in SCHEMAS:
        equal(f"SELECT COUNT(*) FROM information_schema.SCHEMATA WHERE SCHEMA_NAME='{schema}'", 0)
    sql(f"CREATE USER '{USER}'@'%' IDENTIFIED BY ''")
    OWNED_USER = True
    forward, fv = config('tc-to-ac')
    reverse, rv = config('ac-to-tc')
    for schema in SCHEMAS:
        sql(f'CREATE DATABASE `{schema}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci')
        OWNED_SCHEMAS.append(schema)
        permissions = 'SELECT,SHOW VIEW,LOCK TABLES' if schema in (AUTH, CHARS, WORLD, AC_WORLD) else 'ALL'
        sql(f"GRANT {permissions} ON `{schema}`.* TO '{USER}'@'%'")
    # Seed native sources as the test administrator; runner credentials cannot write them.
    SPELL_FIXTURES.seed_worlds(sql,TC,AC,WORLD,AC_WORLD,SPELL_PROFILE)
    sql((TC / 'sql/base/auth_database.sql').read_text(), AUTH)
    sql((TC / 'sql/base/characters_database.sql').read_text(), CHARS)
    library(forward, '''initialize_control_schema
apply_update_directory "$SOURCE_AUTH_SCHEMA" "$TRINITYCORE_DIR/sql/updates/auth/3.3.5"
apply_update_directory "$SOURCE_CHARACTERS_SCHEMA" "$TRINITYCORE_DIR/sql/updates/characters/3.3.5"
''')
    sql((ROOT / 'tests/fixtures/auth-data.sql').read_text(), AUTH)
    sql('INSERT INTO rbac_account_permissions (accountId,permissionId,granted,realmId) '
        'VALUES (1,217,1,-1),(2,217,0,1)', AUTH)
    sql((ROOT / 'tests/fixtures/characters-data.sql').read_text(), CHARS)
    sql((ROOT / 'tests/fixtures/orphan-cleanup-data.sql').read_text(), CHARS)
    sql((ROOT / 'tests/fixtures/spell-state-data.sql').read_text(), CHARS)
    sql('UPDATE arena_team_member SET weekGames=4,weekWins=2,seasonGames=10,seasonWins=5,personalRating=1540 '
        'WHERE guid=100', CHARS)
    sql("INSERT INTO character_pet (id,entry,owner,name) VALUES (300,1,100,'RetainedPet')", CHARS)
    seed_pet_relations(CHARS)
    sql("INSERT INTO uptime (realmid,starttime,uptime,maxplayers,revision) VALUES (1,2000000000,100,5,'fixture')", AUTH)
    sql("INSERT INTO mail (id,sender,receiver,subject,body,checked) VALUES (100,101,100,'fixture','fixture',31)", CHARS)
    sql("INSERT INTO character_aura (guid,casterGuid,spell,effectMask) VALUES (100,100,123,1)", CHARS)
    sql("INSERT INTO corpse (guid,itemCache,corpseType) VALUES (100,CONCAT(REPEAT('0 ',19)),1)", CHARS)
    sql("UPDATE item_instance SET charges='1 2 3 4 5 ',enchantments=REPEAT('0 ',36) WHERE guid=200", CHARS)
    sql("INSERT INTO guild_bank_item (guildid,TabId,SlotId,item_guid) VALUES (940,0,0,201)", CHARS)
    print('Checking research and hidden talent-child blockers',flush=True)
    spell_guard('UNAUTHORIZED_TALENT_SPELL',
        f'INSERT INTO `{CHARS}`.character_spell VALUES (113,900010,1,1)',
        f'DELETE FROM `{CHARS}`.character_spell WHERE guid=113 AND spell=900010')
    spell_guard('RESEARCH_SKILL_MISSING',
        f'INSERT INTO `{CHARS}`.character_spell VALUES (114,60893,1,0)',
        f'DELETE FROM `{CHARS}`.character_spell WHERE guid=114 AND spell=60893')
    print('Checking representation boundaries', flush=True)
    for length in (16, 17, 18, 32, 33, 64):
        sql(f"UPDATE account SET username=REPEAT('A',{length}) WHERE id=1", AUTH)
        guard('tc-to-ac', 'USERNAME_NOT_AUTHENTICATABLE' if length > 17 else None)
        if length == 18:
            blocked_preflight, _ = config('tc-to-ac', '-blocked-preflight')
            phase(blocked_preflight, 'preflight', 'Source representations')
            equal(f"SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA='{AC_AUTH}'", 0)
    for count in (8, 9):
        sql(f"UPDATE account SET username=REPEAT('é',{count}) WHERE id=1", AUTH)
        guard('tc-to-ac', 'USERNAME_NOT_AUTHENTICATABLE' if count == 9 else None)
    sql("UPDATE account SET username='MIGRATION_TEST' WHERE id=1", AUTH)
    for flags in (0, 1, 31, 32, 64, 128, 255, 256, 512, 1024, 4294967295):
        sql(f'UPDATE mail SET checked={flags} WHERE id=100', CHARS)
        guard('tc-to-ac', 'UNSUPPORTED_MAIL_FLAGS' if flags & ~31 else None)
    sql('UPDATE mail SET checked=31 WHERE id=100;UPDATE character_aura SET casterGuid=0', CHARS)
    guard('tc-to-ac', 'EMPTY_AURA_CASTER')
    sql('UPDATE character_aura SET casterGuid=100', CHARS)
    sql('UPDATE uptime SET starttime=4294967295 WHERE realmid=1', AUTH)
    guard('tc-to-ac', 'UPTIME_END_OVERFLOW')
    sql('UPDATE uptime SET uptime=0 WHERE realmid=1', AUTH)
    guard('tc-to-ac')
    sql('UPDATE uptime SET starttime=2000000000,uptime=100 WHERE realmid=1', AUTH)
    # Check the repeated guard through the real load entrypoint after assembly.
    blocked_load, blocked_values = config('tc-to-ac', '-blocked-load')
    for name in ('preflight', 'archive-unsupported', 'assemble'):
        phase(blocked_load, name)
    sql("UPDATE account SET username=REPEAT('A',18) WHERE id=1", AUTH)
    phase(blocked_load, 'load-auth', 'Source representations')
    equal(f'SELECT COUNT(*) FROM `{AC_AUTH}`.account', 0)
    sql("UPDATE account SET username='MIGRATION_TEST' WHERE id=1", AUTH)
    # A reject remains fatal to that run; fresh owned targets accompany the new run.
    assert int(sql(f"SELECT COUNT(*) FROM `{FC}`.migration_reject WHERE run_id='{blocked_values['MIGRATION_RUN_ID']}'")) > 0
    for schema in (AC_AUTH, AC_CHARS):
        sql(f'DROP DATABASE `{schema}`;CREATE DATABASE `{schema}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci')
    # Rejections are tested before the final immutable source snapshot/run.
    before = snapshot(AUTH, CHARS, WORLD, AC_WORLD)
    print('Running TrinityCore -> AzerothCore', flush=True)
    for name in ('preflight', 'archive-unsupported', 'assemble', 'load-auth'):
        phase(forward, name)
    interrupt(forward, 'load-characters', f'ALTER TABLE `{AC_CHARS}`.`corpse` ADD', after_ddl=True,resume=False)
    spell_insert = f'INSERT INTO `{AC_CHARS}`.character_spell'
    interrupt(forward,'load-characters',spell_insert,resume=False)
    equal(f'SELECT COUNT(*) FROM `{AC_CHARS}`.character_spell',0)
    equal(f"SELECT COUNT(*) FROM `{FC}`.spell_provenance WHERE run_id='{fv['MIGRATION_RUN_ID']}'",0)
    fail_env = os.environ | dict(PATH=str(WORK/'proxy')+':'+os.environ['PATH'],MIGRATOR_REAL_MYSQL=MYSQL,
                                 MIGRATOR_FAIL_TOKEN=spell_insert)
    run([str(TOOLKIT/'bin/migrate.sh'),'--config',str(forward),'load-characters'],expected='MySQL query failed',env=fail_env)
    equal(f'SELECT COUNT(*) FROM `{AC_CHARS}`.character_spell',0)
    equal(f"SELECT COUNT(*) FROM `{FC}`.chunk_checkpoint WHERE run_id='{fv['MIGRATION_RUN_ID']}' AND target_table='character_spell'",0)
    interrupt(forward,'load-characters',spell_insert,after_commit=True,resume=False)
    equal(f"SELECT COUNT(*) FROM `{FC}`.chunk_checkpoint WHERE run_id='{fv['MIGRATION_RUN_ID']}' AND target_table='character_spell' AND status='COMPLETE'",1)
    assert int(sql(f'SELECT COUNT(*) FROM `{AC_CHARS}`.character_spell')) > 0
    phase(forward,'load-characters')
    interrupt(forward, 'sanitize-target', f'DELETE s FROM `{AC_CHARS}`.`pet_spell`')
    phase(forward, 'validate')
    assert_ready(fv)
    equal(f'SELECT EndTime,ShutdownType,IFNULL(ExitCode,\'NULL\'),LENGTH(ShutdownReason) FROM `{AC_AUTH}`.uptime '
          'WHERE starttime=2000000000', '2000000100\t0\tNULL\t0')
    equal(f'SELECT COUNT(*) FROM `{AC_AUTH}`.rbac_permissions WHERE id=945 AND name=\'Command: account info\'', 1)
    equal(f'SELECT COUNT(*) FROM `{AC_AUTH}`.rbac_account_permissions', 2)
    assert snapshot(AUTH, CHARS, WORLD, AC_WORLD) == before, 'Forward migration wrote to sources/worlds'
    for guid, indices, mask in [(110,[0,1,2],3),(111,[3,4],3),(112,[5,6],3),
                                (110,[7],1),(111,[8],3),(112,[9],2),(113,[10,11],3)]:
        ids = [spell for index in indices for spell in SPELL_FIXTURES.CHAINS[index]]
        equal(f'SELECT COUNT(*) FROM `{AC_CHARS}`.character_spell WHERE guid={guid} '
              f'AND spell IN ({",".join(map(str,ids))}) AND specMask={mask}',len(ids))
    # The old conversion cannot satisfy even the three audited paladin chains.
    ids = [spell for chain in SPELL_FIXTURES.CHAINS[:3] for spell in chain]
    old_known = int(sql(f'SELECT COUNT(*) FROM `{CHARS}`.character_spell WHERE guid=110 '
                        f'AND spell IN ({",".join(map(str,ids))})'))
    assert old_known < len(ids), 'Regression must fail under stored-row-only conversion'
    equal(f'SELECT COUNT(*) FROM `{AC_CHARS}`.character_spell WHERE guid=114',13)
    equal(f'SELECT COUNT(*) FROM `{AC_CHARS}`.character_spell WHERE guid=115 AND spell IN (5209,5487,9634) AND specMask=3',3)
    equal(f'SELECT specMask FROM `{AC_CHARS}`.character_spell WHERE guid=113 AND spell=38795',3)
    equal(f'SELECT specMask FROM `{AC_CHARS}`.character_spell WHERE guid=113 AND spell=60893',3)
    equal(f"SELECT JSON_LENGTH(JSON_EXTRACT(provenance,'$.authorization.load_script_contracts')) "
          f"FROM `{FC}`.spell_provenance WHERE run_id='{fv['MIGRATION_RUN_ID']}' AND guid=113 AND spell=60893",2)
    equal(f'SELECT COUNT(*) FROM `{AC_CHARS}`.character_spell WHERE guid=113 '
          'AND spell IN (38796,53736,40251,51726) AND specMask=3',4)
    equal(f'SELECT COUNT(*) FROM `{AC_CHARS}`.character_spell WHERE guid=118 AND spell IN (44440,44441)',0)
    equal(f"SELECT disposition,spec_mask FROM `{FC}`.spell_provenance WHERE run_id='{fv['MIGRATION_RUN_ID']}' AND guid=118 AND spell=44440",'RUNTIME\t1')
    equal(f"SELECT disposition,spec_mask FROM `{FC}`.spell_provenance WHERE run_id='{fv['MIGRATION_RUN_ID']}' AND guid=118 AND spell=44441",'RUNTIME\t2')
    equal(f'SELECT specMask FROM `{AC_CHARS}`.character_spell WHERE guid=110 AND spell=53407',3)
    equal(f'SELECT specMask FROM `{AC_CHARS}`.character_spell WHERE guid=116 AND spell=34074',3)
    equal(f"SELECT disposition FROM `{FC}`.spell_provenance WHERE run_id='{fv['MIGRATION_RUN_ID']}' AND guid=117 AND spell=51470",'TALENT')
    equal(f"SELECT disposition FROM `{FC}`.spell_provenance WHERE run_id='{fv['MIGRATION_RUN_ID']}' AND guid=112 AND spell=54349",'TALENT')
    equal(f'SELECT specMask FROM `{AC_CHARS}`.character_spell WHERE guid=110 AND spell=25899',2)
    equal(f'SELECT COUNT(*) FROM `{AC_CHARS}`.character_spell WHERE guid=111 AND spell=900010',0)
    equal(f"SELECT disposition FROM `{FC}`.spell_provenance WHERE run_id='{fv['MIGRATION_RUN_ID']}' AND guid=111 AND spell=900010",'RUNTIME')
    equal(f'SELECT specMask FROM `{AC_CHARS}`.character_spell WHERE guid=111 AND spell=900001',1)
    equal(f'SELECT value,max FROM `{AC_CHARS}`.character_skills WHERE guid=113 AND skill=171','320\t450')
    trainer_rows = WORK/'trainer-spells.tsv'
    trainer_rows.write_text(sql(f'SELECT guid,spell,specMask FROM `{AC_CHARS}`.character_spell ORDER BY guid,spell')+'\n')
    run(['python3',str(ROOT/'tests/trainer-spell-tests.py'),str(AC),str(trainer_rows)])
    after = snapshot(AC_AUTH, AC_CHARS)
    for name in ('preflight', 'archive-unsupported', 'assemble', 'load-auth', 'load-characters', 'sanitize-target', 'validate'):
        phase(forward, name)
    assert snapshot(AC_AUTH, AC_CHARS) == after, 'Forward rerun changed data or DDL'
    print('Checking RBAC name and scope blockers', flush=True)
    sql("INSERT INTO rbac_permissions (id,name) VALUES (99999,'Command: missing migration fixture');"
        "INSERT INTO rbac_account_permissions (accountId,permissionId,granted,realmId) VALUES (1,99999,1,1)", AUTH)
    rbac_cfg, _ = config('tc-to-ac', '-rbac')
    library(rbac_cfg, 'LOAD_KIND=auth;schemas_for_kind auth;load_rbac_account_permissions', 'permission mapping failure')
    sql('DELETE FROM rbac_account_permissions WHERE permissionId=99999;DELETE FROM rbac_permissions WHERE id=99999;'
        'INSERT INTO rbac_account_permissions (accountId,permissionId,granted,realmId) VALUES (1,217,1,2)', AUTH)
    library(rbac_cfg, 'LOAD_KIND=auth;schemas_for_kind auth;load_rbac_account_permissions', 'unsupported realm scope')
    sql('DELETE FROM rbac_account_permissions WHERE realmId=2', AUTH)
    assert snapshot(AUTH, CHARS, WORLD, AC_WORLD) == before, 'RBAC test did not restore its synthetic input'
    # The migrated native AC schemas now become the frozen reverse sources.
    for table in ('character_talent', 'character_spell', 'character_spell_cooldown',
                  'pet_spell_cooldown', 'item_loot_storage', 'channels_bans', 'channels',
                  'pet_spell', 'pet_aura'):
        sql(f'DELETE FROM {table}', AC_CHARS)
    sql((ROOT / 'tests/fixtures/azerothcore-reverse-data.sql').read_text(), AC_CHARS)
    seed_pet_relations(AC_CHARS, reverse=True)
    sql("INSERT INTO item_instance (guid,itemEntry,owner_guid,`count`,enchantments) VALUES (202,20815,100,1,'')", AC_CHARS)
    sql('''INSERT INTO item_loot_storage
        (containerGUID,itemid,`count`,item_index,randomPropertyId,randomSuffix,
         follow_loot_rules,freeforall,is_blocked,is_counted,is_underthreshold,needs_quest) VALUES
        (201,2590,3,0,-1,1,0,0,0,0,0,0),(201,2590,3,0,-1,1,0,0,0,0,0,0),
        (201,2591,4,99,0,0,1,0,0,0,0,0),(202,0,99,0,0,0,0,0,0,0,0,0)''', AC_CHARS)
    sql("UPDATE uptime SET EndTime=NULL,ShutdownType=3,ExitCode=1,ShutdownReason='fixture error' WHERE starttime=2000000000", AC_AUTH)
    sql("INSERT INTO uptime (realmid,starttime,uptime,maxplayers,revision,EndTime,ShutdownType,ExitCode,ShutdownReason) "
        "VALUES (1,2000000200,20,4,'second fixture',2000000220,1,0,'normal shutdown')", AC_AUTH)
    sql('CREATE TABLE creature (guid INT UNSIGNED PRIMARY KEY,map SMALLINT UNSIGNED);'
        'CREATE TABLE gameobject (guid INT UNSIGNED PRIMARY KEY,map SMALLINT UNSIGNED);'
        'INSERT INTO creature VALUES (700,0);INSERT INTO gameobject VALUES (701,0)', AC_WORLD)
    library(reverse, 'initialize_control_schema')
    sql('UPDATE item_loot_storage SET `count`=2147483648 WHERE itemid=2591', AC_CHARS)
    guard('ac-to-tc', 'LOOT_INTEGER_OUT_OF_RANGE')
    sql('UPDATE item_loot_storage SET `count`=4,randomSuffix=2147483648 WHERE itemid=2591', AC_CHARS)
    guard('ac-to-tc', 'LOOT_INTEGER_OUT_OF_RANGE')
    sql('UPDATE item_loot_storage SET randomSuffix=0 WHERE itemid=2591', AC_CHARS)
    sql('INSERT INTO item_loot_storage SELECT * FROM item_loot_storage WHERE containerGUID=202', AC_CHARS)
    guard('ac-to-tc', 'MULTIPLE_LOOT_MONEY_ROWS')
    sql('DELETE FROM item_loot_storage WHERE containerGUID=202 LIMIT 1', AC_CHARS)
    # Revoke former target privileges: reverse sources must now be read-only.
    for schema in (AC_AUTH, AC_CHARS):
        sql(f"REVOKE ALL PRIVILEGES ON `{schema}`.* FROM '{USER}'@'%'")
        sql(f"GRANT SELECT,SHOW VIEW,LOCK TABLES ON `{schema}`.* TO '{USER}'@'%'")
    before_reverse = snapshot(AC_AUTH, AC_CHARS, WORLD, AC_WORLD)
    print('Running AzerothCore -> TrinityCore', flush=True)
    for name in ('preflight', 'archive-unsupported', 'assemble'):
        phase(reverse, name)
    sql('INSERT INTO rbac_account_permissions (accountId,permissionId,granted,realmId) VALUES (1,945,1,1)', AC_AUTH)
    rbac_reverse, _ = config('ac-to-tc', '-rbac')
    library(rbac_reverse, 'LOAD_KIND=auth;schemas_for_kind auth;load_rbac_account_permissions', 'permission mapping failure')
    sql('DELETE FROM rbac_account_permissions WHERE permissionId=945', AC_AUTH)
    dump = next((WORK / 'archives' / rv['MIGRATION_RUN_ID']).glob('auth-uptime.sql.gz'))
    dump_contents = gzip.decompress(dump.read_bytes()).decode()
    assert all(field in dump_contents for field in ('EndTime', 'ShutdownType', 'ExitCode', 'ShutdownReason', 'fixture error'))
    hidden = dump.with_suffix('.hidden')
    dump.rename(hidden)
    phase(reverse, 'load-auth', 'archive is missing')
    equal(f'SELECT COUNT(*) FROM `{TC_AUTH}`.account', 0)
    hidden.rename(dump)
    original = dump.read_bytes()
    dump.write_bytes(original + b'corruption')
    phase(reverse, 'load-auth', 'archive checksum mismatch')
    dump.write_bytes(original)
    phase(reverse, 'load-auth')
    interrupt(reverse, 'load-characters', f'INSERT INTO `{TC_CHARS}`.item_loot_items')
    phase(reverse, 'sanitize-target')
    phase(reverse, 'validate')
    assert_ready(rv)
    equal(f'SELECT GROUP_CONCAT(item_index ORDER BY item_index) FROM `{TC_CHARS}`.item_loot_items WHERE container_id=201', '0,1,2,3')
    equal(f'SELECT COUNT(*) FROM `{TC_CHARS}`.item_loot_items WHERE container_id=201 AND item_id=2590', 2)
    equal(f'SELECT money FROM `{TC_CHARS}`.item_loot_money WHERE container_id=202', 99)
    assert (TOOLKIT / 'reports' / rv['MIGRATION_RUN_ID'] / 'loot-index-normalization.tsv').stat().st_size > 100
    assert snapshot(AC_AUTH, AC_CHARS, WORLD, AC_WORLD) == before_reverse, 'Reverse migration wrote to sources or world'
    after_reverse = snapshot(TC_AUTH, TC_CHARS)
    for name in ('preflight', 'archive-unsupported', 'assemble', 'load-auth', 'load-characters', 'sanitize-target', 'validate'):
        phase(reverse, name)
    assert snapshot(TC_AUTH, TC_CHARS) == after_reverse, 'Reverse rerun changed data or DDL'
    print('Checking spell blockers and immutable-input guards',flush=True)
    spell_guard('UNREPRESENTABLE_DISABLED_SPELL',
        f'UPDATE `{CHARS}`.character_spell SET disabled=1 WHERE guid=110 AND spell=48782',
        f'UPDATE `{CHARS}`.character_spell SET disabled=0 WHERE guid=110 AND spell=48782')
    spell_guard('UNSUPPORTED_DEPENDENT_LEARN',
        f'INSERT INTO `{CHARS}`.character_spell VALUES (113,900011,1,0)',
        f'DELETE FROM `{CHARS}`.character_spell WHERE guid=113 AND spell=900011')
    spell_guard('MALFORMED_SPELL_CHAIN',
        f'UPDATE `{WORLD}`.spell_ranks SET `rank`=3 WHERE first_spell_id=465 AND spell_id=10290',
        f'UPDATE `{WORLD}`.spell_ranks SET `rank`=2 WHERE first_spell_id=465 AND spell_id=10290')
    spell_guard('CYCLIC_SPELL_RELATIONSHIP',
        f'INSERT INTO `{WORLD}`.spell_required VALUES (48782,48942),(48942,48782)',
        f'DELETE FROM `{WORLD}`.spell_required WHERE spell_id IN (48782,48942)')
    spell_guard('INCOMPATIBLE_SPELL_CHAIN',
        f'UPDATE `{AC_WORLD}`.spell_ranks SET spell_id=900011 WHERE first_spell_id=465 AND spell_id=643',
        f'UPDATE `{AC_WORLD}`.spell_ranks SET spell_id=643 WHERE first_spell_id=465 AND spell_id=900011')
    drift, dv = config('tc-to-ac','-spell-drift')
    library(drift,'initialize_control_schema\nprepare_spell_snapshot capture')
    original_inputs = snapshot(AUTH,CHARS,WORLD,AC_WORLD)
    sql(f'UPDATE `{CHARS}`.character_spell SET spell=48781 WHERE guid=110 AND spell=48782')
    library(drift,'prepare_spell_snapshot verify','Spell inputs or reconstruction changed')
    sql(f'UPDATE `{CHARS}`.character_spell SET spell=48782 WHERE guid=110 AND spell=48781')
    sql(f'UPDATE `{AC_WORLD}`.spell_custom_attr SET attributes=1 WHERE spell_id=6603')
    library(drift,'prepare_spell_snapshot verify','Spell inputs or reconstruction changed')
    sql(f'UPDATE `{AC_WORLD}`.spell_custom_attr SET attributes=0 WHERE spell_id=6603')
    asset = WORK/'ac-dbc/Spell.dbc'
    original_asset = asset.read_bytes()
    # Change a valid, unused numeric field without changing file length.
    changed = bytearray(original_asset)
    changed[24] ^= 1
    asset.write_bytes(changed)
    library(drift,'prepare_spell_snapshot verify','Spell inputs or reconstruction changed')
    asset.write_bytes(original_asset)
    assert snapshot(AUTH,CHARS,WORLD,AC_WORLD)==original_inputs
    assert snapshot(AC_AUTH,AC_CHARS,WORLD,AC_WORLD)==before_reverse,'Spell guards modified the reverse source/worlds'
    assert snapshot(TC_AUTH,TC_CHARS)==after_reverse,'Spell guards modified the reverse target'
    print('Disposable bidirectional MySQL rehearsals passed.', flush=True)


try:
    main()
except Exception:
    print(LOG.read_text()[-8000:] if LOG.exists() else 'No runner output', file=sys.stderr)
    for control in (FC, RC):
        if control in OWNED_SCHEMAS and sql(f"SELECT COUNT(*) FROM information_schema.TABLES "
                                           f"WHERE TABLE_SCHEMA='{control}' AND TABLE_NAME='validation_result'") == '1':
            print(sql(f"SELECT check_name,observed_value,expected_value,detail FROM `{control}`.validation_result "
                      "WHERE severity='ERROR' AND passed=0"), file=sys.stderr)
    raise
finally:
    # All names are random and created by this harness; never touch other schemas.
    # A failed connection cannot justify dropping anything.
    for schema in OWNED_SCHEMAS:
        sql(f'DROP DATABASE IF EXISTS `{schema}`')
    if OWNED_USER:
        sql(f"DROP USER IF EXISTS '{USER}'@'%'")
