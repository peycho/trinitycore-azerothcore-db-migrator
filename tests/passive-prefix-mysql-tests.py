#!/usr/bin/env python3
"""Opt-in native passive prefix repair through the console on disposable MySQL 8.4."""
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]


def main(aura_aliases=False):
    port = os.environ.get('REHEARSAL_MYSQL_PORT', '33317')
    if (os.environ.get('MIGRATOR_DISPOSABLE_MYSQL') != '1' or not port.isascii()
            or not port.isdigit() or not 1 <= int(port) <= 65535 or int(port) == 3306):
        raise SystemExit('Requires dedicated disposable localhost MySQL on a non-production port')
    defaults = os.environ.get('REHEARSAL_MYSQL_DEFAULTS_FILE', '')
    base = (['--defaults-extra-file='+defaults] if defaults else ['--no-defaults']) + [
        '--host=127.0.0.1', '--port='+port, '--protocol=TCP', '--batch', '--raw',
        '--skip-column-names', '--skip-force', '--default-character-set=utf8mb4']

    def sql(query, database=None):
        if query.startswith('CREATE TRIGGER '):
            query = 'DELIMITER //\n'+query+'//\nDELIMITER ;\n'
        r = subprocess.run(['mysql', *base, '--user=root', *([database] if database else [])],
                           input=query, text=True, capture_output=True)
        assert r.returncode == 0, r.stderr
        return r.stdout.strip()

    version = sql('SELECT @@version;')
    assert version.startswith('8.4.'), version
    prefix = 'prefix_'+uuid.uuid4().hex[:10]
    source, auth, world, aworld = [prefix+s for s in ('_chars', '_auth', '_world', '_ac')]
    writer, reader = prefix+'_w', prefix+'_r'
    owned, users, checks, worker = [], [], [], None

    def passed(text):
        checks.append(text)
        print('PASS '+text, flush=True)

    try:
        for schema in (source, auth, world, aworld):
            sql(f'CREATE DATABASE `{schema}`;')
            owned.append(schema)
        tc = Path(os.environ.get('TRINITYCORE_DIR', ROOT.parent/'TrinityCore'))
        ac = Path(os.environ.get('AZEROTHCORE_DIR', ROOT.parent/'azerothcore-wotlk'))
        ddl = (tc/'sql/base/characters_database.sql').read_text()
        for table in ('characters', 'character_spell', 'character_talent', 'character_skills'):
            sql(re.search(r'CREATE TABLE `'+table+r'` \(.*?\) ENGINE=[^;]+;', ddl, re.S)[0], source)
        sql(f'''ALTER TABLE `{source}`.characters ADD custom_note TEXT NULL,
                ADD created TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP;
            ALTER TABLE `{source}`.character_spell ADD custom_blob VARBINARY(20) NULL,
                ADD custom_decimal DECIMAL(18,6) NULL;
            CREATE TABLE `{source}`.unrelated(id INT PRIMARY KEY,note TEXT);
            INSERT INTO `{source}`.unrelated VALUES(1,'Keep Ω');
            CREATE TABLE `{auth}`.account(id INT PRIMARY KEY);INSERT INTO `{auth}`.account VALUES(1);''')
        spec = importlib.util.spec_from_file_location('prefix_fixture', ROOT/'tests'/('aura-alias-fixtures.py' if aura_aliases else 'spell-fixtures.py'))
        assets = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(assets)
        alias_families = assets.FAMILIES if aura_aliases else []
        if aura_aliases:
            assets = assets.base
        profile = json.loads((ROOT/'compatibility/tc335-acwotlk-v2/spell-metadata.json').read_text())
        assets.seed_worlds(sql, tc, ac, world, aworld, profile)
        sql('CREATE TABLE playercreateinfo_spell_custom(racemask INT UNSIGNED,classmask INT UNSIGNED,Spell INT UNSIGNED);', world)
        sql('INSERT INTO spell_dbc(Id,EffectRealPointsPerLevel1) VALUES(900099,0.1);', world)
        expected = []
        for g in range(1,7):
            active, reset = int(g == 2), 4 if g == 3 else 32
            sql(f"INSERT INTO `{source}`.characters(guid,account,name,taximask,race,class,level,online,activeTalentGroup,talentGroupsCount,at_login,position_x,custom_note,created) "
                f"VALUES({g},1,'Prefix{g}','',4,11,80,0,{active},2,{reset},0.1,'Retain Ω','2010-01-02 03:04:05');")
            # Both selected builds differ. TC may keep a dependent lower prefix
            # even though AC uses only each exact selected passive rank.
            sql(f'INSERT INTO `{source}`.character_talent VALUES({g},37117,{active}),({g},37116,{1-active});')
            spell_rows = [(37117,1,0),(37116,1,1),(16952,1,1),(16958,0,1),
                          (16954,1,0),(16961,1,0),(6603,1,0)]
            if g == 4:
                spell_rows = [r for r in spell_rows if r[0] not in (16954,16961)]
            if g == 5:
                spell_rows = [(s,a,0 if s in (16952,16958) else d) for s,a,d in spell_rows]
            if g == 6:
                spell_rows = [(s,a,1 if s in (16954,16961) else d) for s,a,d in spell_rows]
            for s,a,d in spell_rows:
                sql(f'INSERT INTO `{source}`.character_spell VALUES({g},{s},{a},{d},0x00ff,0.100001);')
            sql(f'INSERT INTO `{source}`.character_skills VALUES({g},134,400,400),({g},171,375,450);')
            if g in (1,2):
                expected.extend([[g,16952,1,1],[g,16958,0,1]])
        sql(f"INSERT INTO `{source}`.characters(guid,account,name,taximask,race,class,level,online,activeTalentGroup,talentGroupsCount,at_login,custom_note) "
            "VALUES(7,1,'PrefixHigher','',1,6,80,0,1,2,32,'Retain Ω');")
        sql(f'INSERT INTO `{source}`.character_talent VALUES(7,61156,1),(7,61154,0);')
        for s,a,d in [(61156,1,0),(61154,1,1),(50109,1,0),(61276,1,0),(6603,1,0),
                      (50096,1,1),(50108,1,1),(61274,1,1),(61275,1,1),
                      (50110,1,0),(50111,1,0),(61277,1,0),(61278,1,0)]:
            sql(f'INSERT INTO `{source}`.character_spell VALUES(7,{s},{a},{d},0x00ff,0.100001);')
            if s in (50096,50108,61274,61275,50110,50111,61277,61278):
                expected.append([7,s,a,d])
        expected.sort()
        sql(f'INSERT INTO `{source}`.character_skills VALUES(7,770,400,400),(7,171,375,450);')
        if aura_aliases:
            expected = []
            for g in range(8,14):
                cls, login = (1 if g==12 else 2), (4 if g==10 else 32)
                sql(f"INSERT INTO `{source}`.characters(guid,account,name,taximask,race,class,level,online,activeTalentGroup,talentGroupsCount,at_login,position_x,custom_note) "
                    f"VALUES({g},1,'Alias{g}','',1,{cls},80,0,0,2,{login},0.1,'Retain Ω');")
                for _,ranks,_ in alias_families:
                    sql(f'INSERT INTO `{source}`.character_spell VALUES({g},{ranks[-1]},1,0,0x00ff,0.100001);')
                    if g in (8,13):
                        expected.append([g,ranks[-1],1,0])
                    if g==9:
                        sql(f'INSERT INTO `{source}`.character_talent VALUES({g},{ranks[0]},1);')
                sql(f'INSERT INTO `{source}`.character_spell VALUES({g},6603,1,0,0x00ff,0.100001);')
                sql(f'INSERT INTO `{source}`.character_skills VALUES({g},171,375,450);')
            for helper in (63510,63514,63531):
                sql(f'INSERT INTO `{source}`.character_spell VALUES(11,{helper},1,0,0x00ff,0.100001);')
            for _,ranks,name in alias_families:
                sql(f"INSERT INTO `{world}`.spell_script_names VALUES({-ranks[0]},'{name}');")
        for user in (writer, reader):
            sql(f"CREATE USER '{user}'@'%' IDENTIFIED BY '';")
            users.append(user)
            for schema in (source, auth, world):
                sql(f"GRANT SELECT ON `{schema}`.* TO '{user}'@'%';")
        tables = sql("SELECT CONCAT('`',TABLE_SCHEMA,'`.`',TABLE_NAME,'`') FROM information_schema.TABLES "
                     f"WHERE TABLE_SCHEMA IN ('{source}','{auth}','{world}','{aworld}') AND TABLE_TYPE='BASE TABLE' ORDER BY 1").splitlines()

        def checksum():
            return sql('CHECKSUM TABLE '+','.join(tables)+' EXTENDED;')

        baseline = checksum()
        with tempfile.TemporaryDirectory() as temp:
            work = Path(temp)
            assets.write_assets(work, profile)
            config = work/'cleanup.ini'
            config.write_text(f'''[workspace]
directory={work/'workspace'}
[source]
core=tc
characters={source}
auth={auth}
world={world}
[paths]
tc_dbc={work/'tc-dbc'}
tc_source={tc}
ac_source={ac}
[mysql]
host=127.0.0.1
port={port}
user={writer}
password=
defaults_file={defaults}
[mysql_audit]
user={reader}
password=
defaults_file={defaults}
[mysql_admin]
user=root
password=
defaults_file={defaults}
[safety]
preparation_copy=yes
writers_stopped=yes
backup_reference=dedicated-disposable-passive-prefix-fixture
''')
            config.chmod(0o600)
            command = ['python3', str(ROOT/'console'), '--config', str(config)]

            def run(*args, code=0):
                r = subprocess.run(command+list(args), text=True, capture_output=True)
                assert r.returncode == code, r.stdout+r.stderr
                return r

            run('init', '--label', 'native-passive-prefixes')
            session = work/'workspace/sessions'/json.loads((work/'workspace/current.json').read_text())['session']
            report = work/'blockers.tsv'
            report.write_text('guid\tspell\treason_code\tdetail\n'+''.join(
                f'{g}\t*\tUNREPRESENTABLE_DISABLED_SPELL\t16952\n' for g in range(1,14 if aura_aliases else 8)))
            result = run('inspect-migration-blockers', '--report', str(report))
            inspection = Path(result.stdout.split('Reports: ', 1)[1].strip()).name
            plan = ['plan','talent-ownership','--migration-inspection',inspection,
                    '--reviewed-aura-aliases' if aura_aliases else '--native-passive-prefixes']
            old = run('plan','talent-ownership','--migration-inspection',inspection,'--preview')
            assert '"selected_rows": 0' in old.stdout
            preview = run(*plan,'--preview')
            review = json.loads(Path(preview.stdout.split('Details: ',1)[1].strip()).read_text())
            assert review['selected'] == expected, review
            if aura_aliases:
                assert review['summary']['reviewed_aura_alias_rows'] == 8
                assert review['summary']['enabled_rows_removed'] == 8
            else:
                assert review['summary']['restorable_disabled_prefix_rows'] == 8
                assert review['summary']['enabled_rows_removed'] == 4
            assert not (session/'active-batch.json').exists() and not list((session/'batches').iterdir())
            assert checksum() == baseline
            passed('default-policy control, explicit opt-in exact selection; selected/reset/foreign/unsupported stored helper cases deferred; source and active batch unchanged')
            run(*plan,'--expect-rows','3',code=2)
            # Even a deferred character belongs to the sealed planning scope.
            sql(f'UPDATE `{source}`.characters SET level=79 WHERE guid=4;')
            assert 'HISTORY_INPUT_DRIFT' in run(*plan,'--expect-rows',str(len(expected)),code=2).stderr
            sql(f'UPDATE `{source}`.characters SET level=80 WHERE guid=4;')
            run(*plan,'--expect-rows',str(len(expected)))
            package = session/'batches'/json.loads((session/'active-batch.json').read_text())['batch']
            manifest = json.loads((package/'manifest.json').read_text())
            archive = manifest['archive_schema']
            owned.append(archive)
            assert manifest['policy'] == ('tc-unselected-reviewed-aura-alias-retirement-v4' if aura_aliases else 'tc-selected-native-passive-prefix-repair-v3')
            assert manifest['numeric_fingerprint'] == 'EXACT_FRACTIONAL_V1'
            if aura_aliases:
                assert len(manifest['native_owner_proofs']) == 8
                assert all(p['contract']=='UNSELECTED_REVIEWED_AURA_ALIAS_V1' and not p['selected_spell_groups']
                           for p in manifest['native_owner_proofs'])
            else:
                assert [p['prefix_restore_anchors'] for p in manifest['native_owner_proofs'][:2]] == [
                    [[16952,[16954]],[16958,[16961]]], [[16952,[16954]],[16958,[16961]]]]
                assert len(manifest['native_owner_proofs']) == 3
            run('prepare');run('prepare')
            assert checksum() == baseline
            run('apply',code=2)  # No implicit source write grant.
            sql(f"GRANT INSERT,DELETE ON `{source}`.character_spell TO '{writer}'@'%';")
            passed('count/deferred-scope guards, sealed exact native proofs, full custom originals and repeatable read-only preparation; explicit write grants required')
            ack = "SET @talent_cleanup_ack='STOPPED_PREPARATION_COPY_ONLY';SET @talent_ownership_ack='SELECTED_TALENTS_AUTHORITATIVE';"

            def direct(extra=''):
                return subprocess.run(['mysql',*base,'--user='+writer],input=ack+extra+f'CALL `{archive}`.apply_batch();',text=True,capture_output=True)

            ack_variable = 'talent_aura_alias_ack' if aura_aliases else 'talent_native_prefix_ack'
            error_text = 'reviewed aura alias acknowledgement' if aura_aliases else 'native passive prefix acknowledgement'
            for extra in ('',f"SET @{ack_variable}='WRONG';"):
                denied = direct(extra)
                assert denied.returncode and error_text in denied.stderr,denied.stderr
                assert checksum() == baseline
            ack_value = 'UNSELECTED_REVIEWED_AURA_ALIASES_ONLY' if aura_aliases else 'RETAIN_AUTHORIZED_HIGHER_ANCHORS'
            extra = f"SET @{ack_variable}='{ack_value}';"
            affected_guid = 8 if aura_aliases else 1
            affected_spell = 20140 if aura_aliases else 16954
            for update, undo, error in (
                (f'UPDATE `{source}`.characters SET position_x=0.2 WHERE guid={affected_guid}',f'UPDATE `{source}`.characters SET position_x=0.1 WHERE guid={affected_guid}','full-row fingerprint'),
                (f'UPDATE `{source}`.character_spell SET custom_decimal=0.100002 WHERE guid={affected_guid} AND spell=6603',f'UPDATE `{source}`.character_spell SET custom_decimal=0.100001 WHERE guid={affected_guid} AND spell=6603','full-row fingerprint'),
                (f'UPDATE `{source}`.character_spell SET disabled=1 WHERE guid={affected_guid} AND spell={affected_spell}',f'UPDATE `{source}`.character_spell SET disabled=0 WHERE guid={affected_guid} AND spell={affected_spell}','full-row fingerprint'),
                (f'UPDATE `{world}`.spell_dbc SET EffectRealPointsPerLevel1=0.2 WHERE Id=900099',f'UPDATE `{world}`.spell_dbc SET EffectRealPointsPerLevel1=0.1 WHERE Id=900099','world content drift')):
                sql(update)
                changed = checksum()
                denied = direct(extra)
                assert denied.returncode and error in denied.stderr,denied.stderr
                assert checksum() == changed
                sql(undo)
            sql(f'ALTER TABLE `{world}`.spell_required ADD unexpected INT DEFAULT 0;')
            denied = direct(extra)
            assert denied.returncode and 'world layout' in denied.stderr,denied.stderr
            sql(f'ALTER TABLE `{world}`.spell_required DROP unexpected;')
            assert checksum() == baseline
            passed('direct SQL acknowledgement, same-count anchor/decimal/float source and world drift, and world-layout changes reject before deletion')
            sql(f"CREATE TRIGGER `{archive}`.fail_commit BEFORE UPDATE ON `{archive}`.batch FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='prefix-late-error';")
            run('apply',code=2)
            assert checksum() == baseline and sql(f'SELECT state FROM `{archive}`.batch;') == 'PREPARED'
            sql(f'DROP TRIGGER `{archive}`.fail_commit;')
            sql(f"CREATE TRIGGER `{archive}`.pause_commit BEFORE UPDATE ON `{archive}`.batch FOR EACH ROW BEGIN IF NEW.state='APPLIED' THEN DO SLEEP(30); END IF; END")
            worker = subprocess.Popen(command+['apply'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            deadline, connection = time.monotonic()+15, ''
            while time.monotonic() < deadline:
                if worker.poll() is not None:
                    raise AssertionError(worker.communicate())
                connection = sql(f"SELECT ID FROM information_schema.PROCESSLIST WHERE DB='{archive}' AND STATE='User sleep' LIMIT 1;")
                if connection:
                    break
                time.sleep(.1)
            assert connection, 'Fixture did not reach checkpoint'
            sql('KILL CONNECTION '+connection)
            worker.communicate(timeout=10)
            assert worker.returncode != 0
            worker = None
            assert checksum() == baseline and sql(f'SELECT state FROM `{archive}`.batch;') == 'PREPARED'
            sql(f'DROP TRIGGER `{archive}`.pause_commit;')
            passed('late checkpoint failure and interrupted connection roll back deletion and state atomically')
            retained_tables = [t for t in tables if t != f'`{source}`.`character_spell`']
            retained = sql('CHECKSUM TABLE '+','.join(retained_tables)+' EXTENDED;')
            run('apply');run('apply');run('status')
            if aura_aliases:
                assert sql(f'SELECT COUNT(*) FROM `{source}`.character_spell WHERE guid IN(8,13) AND spell IN(20140,20256,31869,53648);') == '0'
                assert sql(f'SELECT COUNT(*) FROM `{source}`.character_spell WHERE guid IN(9,10,11,12) AND spell IN(20140,20256,31869,53648);') == '16'
                assert sql(f'SELECT COUNT(*) FROM `{source}`.character_spell WHERE guid=11 AND spell IN(63510,63514,63531);') == '3'
                assert sql(f'SELECT COUNT(*) FROM `{source}`.character_spell WHERE guid IN(1,2);') == '14'
            else:
                assert sql(f'SELECT COUNT(*) FROM `{source}`.character_spell WHERE guid IN(1,2) AND spell IN(16952,16958);') == '0'
                assert sql(f'SELECT COUNT(*) FROM `{source}`.character_spell WHERE guid IN(1,2) AND spell IN(37116,37117,16954,16961,6603);') == '10'
                assert sql(f'SELECT COUNT(*) FROM `{source}`.character_spell WHERE guid=7 AND spell IN(50096,50108,61274,61275,50110,50111,61277,61278);') == '0'
                assert sql(f'SELECT COUNT(*) FROM `{source}`.character_spell WHERE guid=7 AND spell IN(61156,61154,50109,61276,6603);') == '5'
            assert sql('CHECKSUM TABLE '+','.join(retained_tables)+' EXTENDED;') == retained
            # Retained spell rows equal complete archived originals exactly.
            assert sql(f'''SELECT COUNT(*) FROM `{source}`.character_spell s JOIN `{archive}`.character_spell_before a
                ON s.guid=a.guid AND s.spell=a.spell WHERE NOT(s.active<=>a.active AND s.disabled<=>a.disabled
                AND BINARY s.custom_blob<=>BINARY a.custom_blob AND s.custom_decimal<=>a.custom_decimal);''') == '0'
            sql(f'UPDATE `{source}`.character_spell SET custom_decimal=0.100002 WHERE guid={affected_guid} AND spell=6603;')
            changed = checksum();run('restore',code=2);assert checksum() == changed
            sql(f'UPDATE `{source}`.character_spell SET custom_decimal=0.100001 WHERE guid={affected_guid} AND spell=6603;')
            run('restore');run('restore');assert checksum() == baseline
            run('apply',code=2)
            passed('committed apply/rerun, retained higher ranks and both talent builds/skills/worlds/unrelated state preserved; guarded exact full custom restore and rerun')
        label = 'reviewed aura alias' if aura_aliases else 'native passive prefix'
        print(f'MySQL {version}: {len(checks)} {label} check groups PASS; native gameplay NOT TESTED.',flush=True)
    finally:
        if worker is not None and worker.poll() is None:
            worker.terminate();worker.wait()
        for schema in reversed(owned):
            sql(f'DROP DATABASE `{schema}`;')
        for user in users:
            sql(f"DROP USER '{user}'@'%';")


if __name__ == '__main__':
    main(aura_aliases='--aura-aliases' in sys.argv[1:])
