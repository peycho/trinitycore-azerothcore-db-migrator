#!/usr/bin/env python3
"""Rehearse generated talent cleanup on owned disposable preparation fixtures."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('talent_fixtures', ROOT/'tests/talent-cleanup-fixtures.py')
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)


def main():
    port = os.environ.get('REHEARSAL_MYSQL_PORT', '33317')
    if (os.environ.get('MIGRATOR_DISPOSABLE_MYSQL') != '1' or not port.isascii()
            or not port.isdigit() or not 1 <= int(port) <= 65535 or int(port) == 3306):
        raise SystemExit('Requires a dedicated disposable localhost MySQL on a non-production port')
    defaults = os.environ.get('REHEARSAL_MYSQL_DEFAULTS_FILE', '')
    base = ([f'--defaults-extra-file={defaults}'] if defaults else ['--no-defaults']) + [
        '--host=127.0.0.1', f'--port={int(port)}', '--protocol=TCP', '--batch',
        '--skip-column-names', '--skip-force', '--unbuffered', '--default-character-set=utf8mb4']
    def client(query, user='root', okay=True):
        result = subprocess.run(['mysql', *base, '--user='+user], input=query, text=True, capture_output=True)
        if okay:
            assert result.returncode == 0, result.stderr
        else:
            assert result.returncode and 'ERROR' in result.stderr, result.stdout+result.stderr
        return result
    def sql(query, user='root'):
        if query.startswith('CREATE TRIGGER '):
            query = 'DELIMITER //\n'+query+'//\nDELIMITER ;\n'
        return client(query, user).stdout.strip()
    version = sql('SELECT @@version;')
    assert version.startswith('8.4.'), version
    prefix = 'talent_prep_'+uuid.uuid4().hex[:10]
    source, auth, world, archive = [prefix+suffix for suffix in ('_chars','_auth','_world','_archive')]
    owned, owned_user = [], False
    checks = []
    worker = None
    def passed(label):
        checks.append(label)
        print('PASS '+label, flush=True)
    try:
        for schema in (source,auth,world):
            sql(f'CREATE DATABASE `{schema}`;')
            owned.append(schema)
        tc = Path(os.environ.get('TRINITYCORE_DIR',ROOT.parent/'TrinityCore'))
        sql(f'USE `{source}`;'+(tc/'sql/base/characters_database.sql').read_text())
        sql(f'''ALTER TABLE `{source}`.characters ADD legacy_note TEXT NULL,
                ADD createDate TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP;
            ALTER TABLE `{source}`.item_instance ADD transmog INT UNSIGNED NOT NULL DEFAULT 0,
                ADD enchant INT UNSIGNED NOT NULL DEFAULT 0;
            CREATE TABLE `{auth}`.account(id INT PRIMARY KEY,username VARCHAR(20));
            INSERT INTO `{auth}`.account VALUES(1,'FIXTURE');
            CREATE TABLE `{world}`.spell_dbc(Id INT PRIMARY KEY);
            CREATE TABLE `{world}`.item_template(entry INT PRIMARY KEY,name VARCHAR(20));
            INSERT INTO `{world}`.item_template VALUES(10000022,'Keep custom item');
            INSERT INTO `{source}`.characters(guid,account,name,taximask,race,class,level,online,
                activeTalentGroup,talentGroupsCount,legacy_note,createDate)
              VALUES(1,1,'FixtureOne','',1,1,80,0,0,1,'Original Case Ω','2011-02-03 04:05:06'),
                    (2,1,'FixtureTwo','',1,1,80,0,1,2,NULL,NULL);
            INSERT INTO `{source}`.character_talent VALUES
              (1,12296,0),(1,130,0),(1,142,0),(2,12282,0),(2,12300,0),
              (2,12664,1),(2,12296,3),(2,442,0),(999,27,0);
            INSERT INTO `{source}`.character_spell VALUES(1,6603,1,0),(1,130,1,0),(1,12296,1,1),(2,48942,1,0);
            INSERT INTO `{source}`.character_skills VALUES(1,43,400,400),(2,171,450,450);
            INSERT INTO `{source}`.character_glyphs(guid,talentGroup,glyph1) VALUES(1,0,123);
            INSERT INTO `{source}`.item_instance(guid,itemEntry,owner_guid,enchantments,transmog,enchant)
              VALUES(700,10000022,1,'Original enchantments',123,456);
            INSERT INTO `{source}`.mail(id,receiver,subject,body) VALUES(800,1,'Earlier recovery','Retain body');
            INSERT INTO `{source}`.mail_items VALUES(800,700,1);''')
        sql(f"CREATE USER '{prefix}'@'%' IDENTIFIED BY ''; GRANT SELECT ON `{source}`.* TO '{prefix}'@'%';"
            f"GRANT SELECT ON `{auth}`.* TO '{prefix}'@'%'; GRANT SELECT ON `{world}`.* TO '{prefix}'@'%';")
        owned_user = True
        tables = sql("SELECT CONCAT('`',TABLE_SCHEMA,'`.`',TABLE_NAME,'`') FROM information_schema.TABLES "
            f"WHERE TABLE_SCHEMA IN ('{source}','{auth}','{world}') AND TABLE_TYPE='BASE TABLE' ORDER BY 1").splitlines()
        def checksum(selected=tables):
            return sql('CHECKSUM TABLE '+','.join(selected)+' EXTENDED;')
        baseline = checksum()
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            profile = json.loads(fixtures.planner.PROFILE.read_text())
            fixtures.assets.write_assets(work, profile)
            reader = ['--no-defaults','--host=127.0.0.1',f'--port={int(port)}','--protocol=TCP','--user='+prefix]
            audit = work/'audit'
            result = subprocess.run(['python3',str(ROOT/'tools/audit-tc-source.py'),
                '--characters-schema',source,'--auth-schema',auth,'--world-schema',world,
                '--tc-dbc',str(work/'tc-dbc'),'--scope','talents','--output',str(audit),'--mysql',*reader],
                text=True,capture_output=True)
            assert result.returncode == 1, result.stdout+result.stderr
            candidate = work/'candidate'
            manifest = fixtures.planner.generate(audit,work/'tc-dbc',3,candidate,archive)
            assert manifest['selected_rows'] == 3 and manifest['affected_characters'] == 2
            assert checksum() == baseline
            setup = (candidate/'00-setup.sql').read_text()
            sql(setup)
            owned.append(archive)
            sql(f"GRANT ALL ON `{archive}`.* TO '{prefix}'@'%';")
            ack = "SET @talent_cleanup_ack='STOPPED_PREPARATION_COPY_ONLY';\n"
            def action(name, okay=True, with_ack=True):
                return client((ack if with_ack else '')+f'CALL `{archive}`.{name}_batch();',prefix,okay)
            archive_tables = sql("SELECT CONCAT('`',TABLE_SCHEMA,'`.`',TABLE_NAME,'`') FROM information_schema.TABLES "
                f"WHERE TABLE_SCHEMA='{archive}' AND TABLE_TYPE='BASE TABLE' ORDER BY 1").splitlines()
            # Regression: the historical predicate falsely rejects createDate,
            # even though it is ordinary stored data with a default expression.
            assert sql("SELECT COUNT(*) FROM information_schema.COLUMNS "
                f"WHERE TABLE_SCHEMA='{source}' AND TABLE_NAME='characters' AND COLUMN_NAME='createDate' "
                "AND EXTRA LIKE '%GENERATED%' AND GENERATION_EXPRESSION=''") == '1'
            action('prepare',False,False)
            client(setup,okay=False)
            assert checksum() == baseline and sql(f'SELECT state FROM `{archive}`.batch') == 'NEW'
            passed('real audit -> offline plan -> owned archive; setup reuse/acknowledgement refused')
            sql(f'UPDATE `{source}`.characters SET online=1 WHERE guid=1;')
            action('prepare',False)
            sql(f'UPDATE `{source}`.characters SET online=0 WHERE guid=1;')
            passed('online affected character rejected')
            action('prepare')
            assert checksum() == baseline
            assert sql(f'SELECT COUNT(*) FROM `{archive}`.talent_before') == '8'
            assert sql(f'SELECT COUNT(*) FROM `{archive}`.talent_removed') == '3'
            assert sql(f'SELECT COUNT(*) FROM `{archive}`.character_before') == '2'
            assert sql(f"SELECT CAST(createDate AS CHAR) FROM `{archive}`.character_before WHERE guid=1") == '2011-02-03 04:05:06'
            assert sql(f'SELECT COUNT(*) FROM `{archive}`.character_before WHERE guid=2 AND createDate IS NULL') == '1'
            passed('old predicate rejects DEFAULT_GENERATED timestamp; corrected prepare preserves historical and NULL values')
            prepared = checksum(archive_tables)
            action('prepare')
            action('apply',False)
            assert checksum() == baseline and checksum(archive_tables) == prepared
            passed('SELECT-only source preparation, full character/talent snapshots, prepare rerun and write privilege refusal')
            sql(f"GRANT INSERT,DELETE ON `{source}`.character_talent TO '{prefix}'@'%';")
            client(f'DELETE FROM `{source}`.character_spell WHERE guid=1;',prefix,False)
            client(f"UPDATE `{world}`.item_template SET name='changed';",prefix,False)
            def blocked_apply(change,undo,label):
                sql(change)
                before = checksum()
                action('apply',False)
                assert checksum() == before and sql(f'SELECT state FROM `{archive}`.batch') == 'PREPARED'
                sql(undo)
                assert checksum() == baseline
                passed(label)
            blocked_apply(f'UPDATE `{source}`.character_talent SET spell=131 WHERE guid=1 AND spell=130;',
                f'UPDATE `{source}`.character_talent SET spell=130 WHERE guid=1 AND spell=131;',
                'same-count invalid-key drift rejected')
            blocked_apply(f'UPDATE `{source}`.character_talent SET spell=12282 WHERE guid=2 AND spell=12664 AND talentGroup=1;',
                f'UPDATE `{source}`.character_talent SET spell=12664 WHERE guid=2 AND spell=12282 AND talentGroup=1;',
                'same-count retained talent ownership drift rejected')
            blocked_apply(f"UPDATE `{source}`.characters SET legacy_note=LOWER(legacy_note) WHERE guid=1;",
                f"UPDATE `{source}`.characters SET legacy_note='Original Case Ω' WHERE guid=1;",
                'byte-sensitive full custom character-state drift rejected')
            blocked_apply(f'UPDATE `{source}`.characters SET activeTalentGroup=0 WHERE guid=2;',
                f'UPDATE `{source}`.characters SET activeTalentGroup=1 WHERE guid=2;',
                'specialization drift rejected')
            blocked_apply(f'ALTER TABLE `{source}`.character_talent ADD custom_rank INT DEFAULT 0;',
                f'ALTER TABLE `{source}`.character_talent DROP custom_rank;', 'unsupported schema drift rejected')
            sql(f'UPDATE `{archive}`.expected SET spell=131 WHERE guid=1 AND spell=130;')
            action('apply',False)
            sql(f'UPDATE `{archive}`.expected SET spell=130 WHERE guid=1 AND spell=131;')
            sql(f'INSERT INTO `{archive}`.valid_rank_spell VALUES(130);')
            action('apply',False)
            sql(f'DELETE FROM `{archive}`.valid_rank_spell WHERE spell=130;')
            passed('expected-key and rank-catalog tampering rejected')
            sql(f"CREATE TRIGGER `{source}`.unreviewed BEFORE DELETE ON `{source}`.character_talent FOR EACH ROW SET @fixture_ran=1;")
            assert not sql(f"SELECT TRIGGER_NAME FROM information_schema.TRIGGERS WHERE EVENT_OBJECT_SCHEMA='{source}';",prefix)
            assert 'Source triggers require separate review' in action('apply',False).stderr
            sql(f'DROP TRIGGER `{source}`.unreviewed;')
            passed('complete definer metadata guard detects triggers hidden from restricted writer')
            sql(f'''CREATE TABLE `{source}`.cleanup_fk_fixture (
                guid INT UNSIGNED NOT NULL, spell MEDIUMINT UNSIGNED NOT NULL,
                talentGroup TINYINT UNSIGNED NOT NULL,
                FOREIGN KEY(guid,spell,talentGroup) REFERENCES `{source}`.character_talent(guid,spell,talentGroup)
                    ON DELETE CASCADE) ENGINE=InnoDB;
                INSERT INTO `{source}`.cleanup_fk_fixture VALUES(1,130,0);''')
            assert 'Talent foreign keys require separate review' in action('apply',False).stderr
            assert sql(f'SELECT COUNT(*) FROM `{source}`.cleanup_fk_fixture') == '1'
            sql(f'DROP TABLE `{source}`.cleanup_fk_fixture;')
            assert checksum() == baseline
            passed('foreign-key cascade rejected before deleting any dependent data')
            sql(f"CREATE TRIGGER `{archive}`.late_failure BEFORE UPDATE ON `{archive}`.batch FOR EACH ROW BEGIN "
                "IF NEW.state='APPLIED' THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Injected late failure'; END IF; END;")
            action('apply',False)
            assert checksum() == baseline and checksum(archive_tables) == prepared
            sql(f'DROP TRIGGER `{archive}`.late_failure;')
            passed('late error rolls back deletion and checkpoint atomically')
            sql(f"CREATE TRIGGER `{archive}`.pause BEFORE UPDATE ON `{archive}`.batch FOR EACH ROW BEGIN "
                "IF NEW.state='APPLIED' THEN DO SLEEP(30); END IF; END;")
            worker = subprocess.Popen(['mysql',*base,'--user='+prefix],stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            worker.stdin.write(ack+f'SELECT CONNECTION_ID(); CALL `{archive}`.apply_batch();\n')
            worker.stdin.close()
            worker_id = worker.stdout.readline().strip()
            assert worker_id.isdigit()
            deadline = time.monotonic()+15
            while time.monotonic() < deadline:
                if worker.poll() is not None:
                    raise AssertionError('Worker exited: '+worker.stderr.read())
                if sql(f"SELECT ID FROM information_schema.PROCESSLIST WHERE ID={worker_id} AND STATE='User sleep'"):
                    break
                time.sleep(.1)
            else:
                sql('KILL CONNECTION '+worker_id)
                raise AssertionError('Interruption boundary not reached')
            sql('KILL CONNECTION '+worker_id)
            assert worker.wait(timeout=10) != 0
            assert checksum() == baseline and checksum(archive_tables) == prepared
            sql(f'DROP TRIGGER `{archive}`.pause;')
            passed('killed connection after deletion rolls back all incomplete changes')
            action('apply')
            assert sql(f'SELECT COUNT(*) FROM `{source}`.character_talent') == '6'
            assert sql(f'SELECT GROUP_CONCAT(CONCAT(spell,":",talentGroup) ORDER BY talentGroup,spell) '
                       f'FROM `{source}`.character_talent WHERE guid=2 AND talentGroup IN (0,1)') == '12282:0,12300:0,12664:1'
            assert sql(f'SELECT COUNT(*) FROM `{source}`.character_talent WHERE guid=999 AND spell=27') == '1'
            assert sql(f'SELECT COUNT(*) FROM `{source}`.character_talent WHERE guid=2 AND spell=12296 AND talentGroup=3') == '1'
            applied, applied_archive = checksum(), checksum(archive_tables)
            action('apply')
            assert checksum() == applied and checksum(archive_tables) == applied_archive
            protected = [table for table in tables if table != f'`{source}`.`character_talent`']
            expected = '\n'.join(line for line in baseline.splitlines() if not line.startswith(source+'.character_talent\t'))
            assert checksum(protected) == expected
            passed('apply/rerun preserve selectable ranks in both groups, separate orphan/group conflicts, all unrelated source/auth/world data')
            sql(f'UPDATE `{source}`.characters SET money=money+1 WHERE guid=1;')
            changed = checksum()
            action('restore',False)
            assert checksum() == changed
            sql(f'UPDATE `{source}`.characters SET money=money-1 WHERE guid=1;')
            sql(f'UPDATE `{source}`.character_talent SET spell=12282 WHERE guid=2 AND spell=12664 AND talentGroup=1;')
            changed = checksum()
            action('restore',False)
            assert checksum() == changed
            sql(f'UPDATE `{source}`.character_talent SET spell=12664 WHERE guid=2 AND spell=12282 AND talentGroup=1;')
            passed('restore refuses changed character or legitimate talent state')
            sql(f"CREATE TRIGGER `{archive}`.restore_failure BEFORE UPDATE ON `{archive}`.batch FOR EACH ROW BEGIN "
                "IF NEW.state='RESTORED' THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Injected restore failure'; END IF; END;")
            action('restore',False)
            assert checksum() == applied and checksum(archive_tables) == applied_archive
            sql(f'DROP TRIGGER `{archive}`.restore_failure;')
            passed('late restore failure rolls back reinsertions and checkpoint')
            action('restore')
            assert checksum() == baseline
            restored_archive = checksum(archive_tables)
            action('restore')
            action('apply',False)
            assert checksum() == baseline and checksum(archive_tables) == restored_archive
            passed('exact full source restoration, restore rerun, retained archives and apply-after-restore refusal')
            # Use matching audits so these failures exercise column semantics,
            # rather than the simpler schema-drift guard.
            for suffix, definition in (
                    ('virtual', 'INT GENERATED ALWAYS AS (`level`+1) VIRTUAL'),
                    ('stored', 'INT GENERATED ALWAYS AS (`level`+1) STORED'),
                    ('invisible', 'INT NULL DEFAULT 9 INVISIBLE')):
                sql(f'ALTER TABLE `{source}`.characters ADD unsupported_field {definition};')
                current = checksum()
                next_audit, next_candidate = work/('audit-'+suffix), work/('candidate-'+suffix)
                result = subprocess.run(['python3',str(ROOT/'tools/audit-tc-source.py'),
                    '--characters-schema',source,'--auth-schema',auth,'--world-schema',world,
                    '--tc-dbc',str(work/'tc-dbc'),'--scope','talents','--output',str(next_audit),
                    '--mysql',*reader],text=True,capture_output=True)
                assert result.returncode == 1, result.stdout+result.stderr
                next_archive = archive+'_'+suffix
                fixtures.planner.generate(next_audit,work/'tc-dbc',3,next_candidate,next_archive)
                sql((next_candidate/'00-setup.sql').read_text())
                owned.append(next_archive)
                sql(f"GRANT ALL ON `{next_archive}`.* TO '{prefix}'@'%';")
                rejected = client(ack+f'CALL `{next_archive}`.prepare_batch();',prefix,False)
                assert 'unsupported generated/invisible fields' in rejected.stderr, rejected.stderr
                assert checksum() == current
                assert sql(f'SELECT state FROM `{next_archive}`.batch') == 'NEW'
                assert sql(f'SELECT COUNT(*) FROM `{next_archive}`.character_before') == '0'
                sql(f'ALTER TABLE `{source}`.characters DROP unsupported_field;')
                assert checksum() == baseline
                passed(f'matching audit with {suffix} column still rejected before snapshots or source changes')
        print(f'MySQL {version}: {len(checks)} talent cleanup check groups PASS; native gameplay NOT TESTED.')
    finally:
        if worker is not None and worker.poll() is None:
            worker.kill(); worker.wait()
        if owned_user:
            sql(f"DROP USER '{prefix}'@'%';")
        for schema in reversed(owned):
            sql(f'DROP DATABASE `{schema}`;')


if __name__ == '__main__':
    main()
