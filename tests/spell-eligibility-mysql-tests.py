#!/usr/bin/env python3
"""Eligibility policy through the real console and isolated MySQL 8.4 transactions."""
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]


def main():
    port = os.environ.get('REHEARSAL_MYSQL_PORT', '33317')
    if (os.environ.get('MIGRATOR_DISPOSABLE_MYSQL') != '1' or not port.isascii() or not port.isdigit()
            or not 1 <= int(port) <= 65535 or int(port) == 3306):
        raise SystemExit('Requires dedicated disposable localhost MySQL on a non-production port')
    defaults = os.environ.get('REHEARSAL_MYSQL_DEFAULTS_FILE', '')
    base = (['--defaults-extra-file='+defaults] if defaults else ['--no-defaults']) + [
        '--host=127.0.0.1', '--port='+str(int(port)), '--protocol=TCP', '--batch', '--raw',
        '--skip-column-names', '--skip-force', '--default-character-set=utf8mb4']
    def sql(query, user='root', ok=True):
        if query.startswith('CREATE TRIGGER '):
            query = 'DELIMITER //\n'+query+'//\nDELIMITER ;\n'
        result = subprocess.run(['mysql', *base, '--user='+user], input=query, text=True, capture_output=True)
        if ok:
            assert result.returncode == 0, result.stderr
        else:
            assert result.returncode != 0, result.stdout
        return result.stdout.strip() if ok else result.stderr
    version = sql('SELECT @@version;')
    assert version.startswith('8.4.'), version
    prefix = 'eligibility_'+uuid.uuid4().hex[:10]
    source, auth, tcworld, acworld = [prefix+s for s in ('_chars','_auth','_tc','_ac')]
    writer, reader = prefix+'_w', prefix+'_r'
    owned, users, worker = [], [], None
    tc = Path(os.environ.get('TRINITYCORE_DIR', ROOT.parent/'TrinityCore'))
    ac = Path(os.environ.get('AZEROTHCORE_DIR', ROOT.parent/'azerothcore-wotlk'))
    profile = json.loads((ROOT/'compatibility/tc335-acwotlk-v2/spell-metadata.json').read_text())
    try:
        for schema in (source, auth, tcworld, acworld):
            sql(f'CREATE DATABASE `{schema}`;')
            owned.append(schema)
        sql(f'USE `{source}`;'+(tc/'sql/base/characters_database.sql').read_text())
        world_sql = (tc/'sql/base/dev/world_database.sql').read_text()
        for table in ('spell_dbc','spell_ranks','spell_required','spell_learn_spell','spell_script_names',
                      'spell_custom_attr','playercreateinfo_spell_custom'):
            ddl = re.search(r'CREATE TABLE `'+table+r'` \(.*?\) ENGINE=[^;]+;', world_sql, re.S)[0]
            sql(f'USE `{tcworld}`;'+ddl)
        target_tables = sorted({s['table'] for s in profile['stores'].values()} |
                               {'spell_ranks','spell_required','spell_script_names','spell_custom_attr','trainer_spell'})
        for table in target_tables:
            text = (ac/'data/sql/base/db_world'/f'{table}.sql').read_text()
            ddl = re.search(r'CREATE TABLE `'+table+r'` \(.*?\) ENGINE=[^;]+;', text, re.S)[0]
            sql(f'USE `{acworld}`;'+ddl)
        sql(f'''ALTER TABLE `{source}`.character_spell ADD custom_blob VARBINARY(20) NULL,
                ADD custom_decimal DECIMAL(18,6) NULL;
            ALTER TABLE `{source}`.characters ADD legacy_note TEXT NULL;
            CREATE TABLE `{auth}`.account(id INT PRIMARY KEY); INSERT INTO `{auth}`.account VALUES(1);
            INSERT INTO `{source}`.characters(guid,account,name,taximask,race,class,level,online,activeTalentGroup,talentGroupsCount,at_login,legacy_note)
            VALUES(1,1,'ForeignChain','',1,1,80,0,0,2,32,'Retain Ω'),
                  (2,1,'EligibleCtrl','',1,2,80,0,1,2,0,NULL),
                  (3,1,'ResetDefer','',1,1,80,0,0,1,4,NULL),
                  (4,1,'SkillDefer','',1,1,80,0,0,1,0,NULL),
                  (5,1,'UpperOnly','',1,1,80,0,1,2,0,NULL);
            INSERT INTO `{source}`.character_spell(guid,spell,active,disabled,custom_blob) VALUES
                (1,465,0,0,0x00ff),(1,48942,1,0,0xff00),(1,6603,1,0,0x1234),
                (2,48942,1,0,NULL),(3,48942,1,0,NULL),(4,48942,1,0,NULL),(5,48942,1,0,0x1122);
            INSERT INTO `{source}`.character_talent VALUES(1,12282,0),(1,12664,1);
            INSERT INTO `{source}`.character_skills VALUES(1,171,375,450),(4,267,1,400);
            INSERT INTO `{source}`.character_action(guid,spec,button,action,type) VALUES(1,0,1,465,0);
            INSERT INTO `{source}`.item_instance(guid,itemEntry,owner_guid,enchantments) VALUES(700,10000022,1,'Keep custom item');
            INSERT INTO `{acworld}`.trainer_spell(TrainerId,SpellId) VALUES(1,6603);
            UPDATE `{source}`.characters SET position_x=0.1 WHERE guid=1;
            UPDATE `{source}`.character_spell SET custom_decimal=0.100001 WHERE guid=1 AND spell=6603;
            INSERT INTO `{tcworld}`.spell_dbc(Id,EffectRealPointsPerLevel1) VALUES(900099,0.1);
            INSERT INTO `{acworld}`.spell_dbc(ID,Speed) VALUES(900099,0.1);''')
        spec = importlib.util.spec_from_file_location('assets', ROOT/'tests/spell-fixtures.py')
        assets = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(assets)
        values = ','.join(f'(465,{s},{n})' for n,s in enumerate(assets.CHAINS[0],1))
        for schema in (tcworld, acworld):
            sql(f'INSERT INTO `{schema}`.spell_ranks VALUES '+values)
        for user in (writer, reader):
            sql(f"CREATE USER '{user}'@'%' IDENTIFIED BY '';")
            users.append(user)
            for schema in (source, auth, tcworld, acworld):
                sql(f"GRANT SELECT ON `{schema}`.* TO '{user}'@'%';")
        tables = sql("SELECT CONCAT('`',TABLE_SCHEMA,'`.`',TABLE_NAME,'`') FROM information_schema.TABLES "
                     f"WHERE TABLE_SCHEMA IN ('{source}','{auth}','{tcworld}','{acworld}') AND TABLE_TYPE='BASE TABLE' ORDER BY 1").splitlines()
        checksum = lambda: sql('CHECKSUM TABLE '+','.join(tables)+' EXTENDED;')
        unrelated = [t for t in tables if t != f'`{source}`.`character_spell`']
        baseline = checksum()
        preserved = sql('CHECKSUM TABLE '+','.join(unrelated)+' EXTENDED;')
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            assets.write_assets(work, profile)
            config = work/'cleanup.ini'
            text = f'''[workspace]
directory=workspace
[source]
characters={source}
auth={auth}
world={tcworld}
player_start_all_spells=0
[target]
world={acworld}
player_start_custom_spells=0
[paths]
tc_dbc=tc-dbc
ac_dbc=ac-dbc
tc_source={tc}
ac_source={ac}
[mysql]
host=127.0.0.1
port={port}
user={writer}
password=
[mysql_audit]
user={reader}
password=
[mysql_admin]
user=root
password=
defaults_file={defaults}
[safety]
preparation_copy=yes
writers_stopped=yes
backup_reference=disposable-synthetic-fixture
'''
            config.write_text(text)
            config.chmod(0o600)
            command = ['python3', str(ROOT/'console'), '--config', str(config)]
            def run(*args, code=0):
                result = subprocess.run(command+list(args), text=True, capture_output=True)
                assert result.returncode == code, result.stdout+result.stderr
                return result
            run('init', '--label', 'eligibility')
            session = work/'workspace/sessions'/json.loads((work/'workspace/current.json').read_text())['session']
            report = work/'blockers.tsv'
            report.write_text('guid\tspell\treason_code\tdetail\n'+''.join(
                f'{g}\t*\tAC_WOULD_DELETE_SPELL\t48942: captured fixture scope\n' for g in range(1,6)))
            run('inspect-migration-blockers', '--report', str(report))
            plan = ('plan','spell-eligibility','--migration-inspection','latest')
            config.write_text(text.replace('[target]\nworld='+acworld, '[target]\nworld='+source))
            assert 'ELIGIBILITY_TARGET_OVERLAP' in run(*plan,'--preview',code=2).stderr
            config.write_text(text.replace('[target]\nworld='+acworld+'\nplayer_start_custom_spells=0',
                                           '[target]\nworld='+acworld+'\nplayer_start_custom_spells='))
            assert 'ELIGIBILITY_CONFIG_REQUIRED' in run(*plan,'--preview',code=2).stderr
            config.write_text(text)
            run(*plan, '--preview')
            assert not (session/'active-batch.json').exists() and not list((session/'batches').glob('*'))
            assert checksum() == baseline
            run(*plan,'--expect-rows','2',code=2)
            sql(f'UPDATE `{source}`.characters SET level=79 WHERE guid=2')
            changed=checksum()
            assert 'HISTORY_INPUT_DRIFT' in run(*plan,'--expect-rows','3',code=2).stderr
            assert checksum()==changed
            sql(f'UPDATE `{source}`.characters SET level=80 WHERE guid=2')
            run(*plan,'--expect-rows','3')
            package=session/'batches'/json.loads((session/'active-batch.json').read_text())['batch']
            manifest=json.loads((package/'manifest.json').read_text())
            archive=manifest['archive_schema'];owned.append(archive)
            assert manifest['selected_rows']==3 and manifest['enabled_rows_removed']==3
            assert manifest['excluded_reason_counts']=={'DEFER_PENDING_NATIVE_RESET':1,'DEFER_EXISTING_ASSOCIATED_SKILL':1}
            assert json.loads((package/'eligibility-native-proof.json').read_text())
            run('prepare');run('prepare');assert checksum()==baseline
            assert 'DELETE on character_spell' in run('apply',code=2).stderr
            sql(f"GRANT DELETE,INSERT ON `{source}`.character_spell TO '{writer}'@'%';")
            ack="SET @talent_cleanup_ack='STOPPED_PREPARATION_COPY_ONLY'; SET @spell_eligibility_ack='RETIRE_VERIFIED_INELIGIBLE_SPELLS'; SET @eligibility_tc_all_spells=0;SET @eligibility_ac_custom_spells=0;"
            error=sql(f"SET @talent_cleanup_ack='STOPPED_PREPARATION_COPY_ONLY';CALL `{archive}`.apply_batch();",writer,False)
            assert 'Explicit eligibility repair' in error
            for variable in ('eligibility_tc_all_spells','eligibility_ac_custom_spells'):
                error=sql(ack+f"SET @{variable}='UNKNOWN'; CALL `{archive}`.apply_batch();",writer,False)
                assert 'Explicit eligibility repair' in error
            # Failing control: historical HEX(number) collapses these changes.
            assert sql('SELECT HEX(0.1)=HEX(0.2),HEX(0.100001)=HEX(0.100002)')=='1\t1'
            for update, restore in (
                    (f'UPDATE `{source}`.characters SET position_x=0.2 WHERE guid=1',
                     f'UPDATE `{source}`.characters SET position_x=0.1 WHERE guid=1'),
                    (f'UPDATE `{source}`.character_spell SET custom_decimal=0.100002 WHERE guid=1 AND spell=6603',
                     f'UPDATE `{source}`.character_spell SET custom_decimal=0.100001 WHERE guid=1 AND spell=6603')):
                sql(update);changed=checksum()
                error=sql(ack+f'CALL `{archive}`.apply_batch();',writer,False)
                assert 'full-row fingerprint differs' in error,error
                assert checksum()==changed;sql(restore)
            for schema in (tcworld,acworld):
                field='EffectRealPointsPerLevel1' if schema==tcworld else 'Speed'
                sql(f'UPDATE `{schema}`.spell_dbc SET `{field}`=0.2 WHERE Id=900099')
                changed=checksum()
                error=sql(ack+f'CALL `{archive}`.apply_batch();',writer,False)
                assert 'world content drift' in error,error
                assert checksum()==changed
                sql(f'UPDATE `{schema}`.spell_dbc SET `{field}`=0.1 WHERE Id=900099')
            for schema in (tcworld, acworld):
                sql(f'UPDATE `{schema}`.spell_ranks SET `rank`=11 WHERE spell_id=48942')
                changed=checksum();run('apply',code=2)
                assert 'world content drift' in sql(ack+f'CALL `{archive}`.apply_batch();',writer,False)
                assert checksum()==changed
                sql(f'UPDATE `{schema}`.spell_ranks SET `rank`=10 WHERE spell_id=48942')
            sql(f'UPDATE `{acworld}`.trainer_spell SET ReqLevel=1 WHERE TrainerId=1')
            assert 'ELIGIBILITY_TARGET_DRIFT' in run('apply',code=2).stderr
            assert 'world content drift' in sql(ack+f'CALL `{archive}`.apply_batch();',writer,False)
            sql(f'UPDATE `{acworld}`.trainer_spell SET ReqLevel=0 WHERE TrainerId=1')
            sql(f'ALTER TABLE `{acworld}`.spell_ranks MODIFY `rank` TINYINT UNSIGNED NOT NULL DEFAULT 0 FIRST')
            assert 'Eligibility world layout' in sql(ack+f'CALL `{archive}`.apply_batch();',writer,False)
            sql(f'ALTER TABLE `{acworld}`.spell_ranks MODIFY `rank` TINYINT UNSIGNED NOT NULL DEFAULT 0 AFTER spell_id')
            sql(f"CREATE TRIGGER `{archive}`.late_error BEFORE UPDATE ON `{archive}`.batch FOR EACH ROW BEGIN IF NEW.state='APPLIED' THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='eligibility-late-error';END IF;END")
            run('apply',code=2);assert checksum()==baseline
            sql(f'DROP TRIGGER `{archive}`.late_error')
            sql(f"CREATE TRIGGER `{archive}`.pause_commit BEFORE UPDATE ON `{archive}`.batch FOR EACH ROW BEGIN IF NEW.state='APPLIED' THEN DO SLEEP(30);END IF;END")
            worker=subprocess.Popen(command+['apply'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            deadline=time.monotonic()+10;connection=''
            while time.monotonic()<deadline:
                if worker.poll() is not None:
                    raise AssertionError(worker.communicate())
                connection=sql(f"SELECT ID FROM information_schema.PROCESSLIST WHERE DB='{archive}' AND STATE='User sleep' LIMIT 1")
                if connection:break
                time.sleep(.1)
            assert connection,'Apply did not reach the uncommitted checkpoint'
            sql('KILL CONNECTION '+connection);worker.communicate(timeout=10)
            assert worker.returncode!=0;worker=None
            assert checksum()==baseline and sql(f'SELECT state FROM `{archive}`.batch')=='PREPARED'
            sql(f'DROP TRIGGER `{archive}`.pause_commit')
            run('status');run('apply');run('apply');run('status')
            assert sql(f'SELECT COUNT(*) FROM `{source}`.character_spell WHERE guid=1')=='1'
            assert sql(f'SELECT COUNT(*) FROM `{source}`.character_spell WHERE guid=5')=='0'
            assert sql('CHECKSUM TABLE '+','.join(unrelated)+' EXTENDED;')==preserved
            sql(f'UPDATE `{source}`.character_spell SET custom_blob=0x99 WHERE guid=1 AND spell=6603')
            changed=checksum();run('restore',code=2);assert checksum()==changed
            sql(f'UPDATE `{source}`.character_spell SET custom_blob=0x1234 WHERE guid=1 AND spell=6603')
            run('restore');run('restore');assert checksum()==baseline;run('apply',code=2)
        print(f'MySQL {version}: eligibility preview/config/count/full-scope drift, native catalogs, direct SQL guards, rollback/disconnect/reruns/exact custom restore PASS; gameplay NOT TESTED',flush=True)
    finally:
        if worker is not None and worker.poll() is None:
            worker.terminate();worker.wait()
        for schema in reversed(owned):sql(f'DROP DATABASE IF EXISTS `{schema}`;')
        for user in users:sql(f"DROP USER IF EXISTS '{user}'@'%';")


if __name__ == '__main__':
    main()
