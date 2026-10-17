#!/usr/bin/env python3
"""Exact disabled-history transactions on dedicated disposable MySQL 8.4 only."""
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]


def main():
    port=os.environ.get('REHEARSAL_MYSQL_PORT','33317')
    if (os.environ.get('MIGRATOR_DISPOSABLE_MYSQL')!='1' or not port.isascii() or not port.isdigit()
            or not 1<=int(port)<=65535 or int(port)==3306):
        raise SystemExit('Requires dedicated disposable localhost MySQL on a non-production port')
    defaults=os.environ.get('REHEARSAL_MYSQL_DEFAULTS_FILE','')
    base=([f'--defaults-extra-file={defaults}'] if defaults else ['--no-defaults'])+[
        '--host=127.0.0.1','--port='+str(int(port)),'--protocol=TCP','--batch','--raw',
        '--skip-column-names','--skip-force','--default-character-set=utf8mb4']
    def sql(query):
        if query.startswith('CREATE TRIGGER '):query='DELIMITER //\n'+query+'//\nDELIMITER ;\n'
        result=subprocess.run(['mysql',*base,'--user=root'],input=query,text=True,capture_output=True)
        assert result.returncode==0,result.stderr
        return result.stdout.strip()
    version=sql('SELECT @@version;');assert version.startswith('8.4.'),version
    prefix='history_'+uuid.uuid4().hex[:10]
    source,auth,world=[prefix+s for s in ('_chars','_auth','_world')]
    writer,reader=prefix+'_w',prefix+'_r'
    owned=[];users=[];checks=[];worker=None
    def passed(text):checks.append(text);print('PASS '+text,flush=True)
    try:
        for schema in (source,auth,world):sql(f'CREATE DATABASE `{schema}`;');owned.append(schema)
        tc=Path(os.environ.get('TRINITYCORE_DIR',ROOT.parent/'TrinityCore'))
        ac=Path(os.environ.get('AZEROTHCORE_DIR',ROOT.parent/'azerothcore-wotlk'))
        sql(f'USE `{source}`;'+(tc/'sql/base/characters_database.sql').read_text())
        world_sql=(tc/'sql/base/dev/world_database.sql').read_text()
        for table in ('spell_dbc','spell_ranks','spell_required','spell_learn_spell','spell_script_names',
                      'spell_custom_attr','playercreateinfo_spell_custom','item_template','quest_template'):
            ddl=re.search(r'CREATE TABLE `'+table+r'` \(.*?\) ENGINE=[^;]+;',world_sql,re.S)[0]
            sql(f'USE `{world}`;'+ddl)
        # SQL column lookup is case-insensitive in the native TC reader.
        sql(f'ALTER TABLE `{world}`.spell_learn_spell RENAME COLUMN SpellID TO spellid;')
        sql(f'''ALTER TABLE `{source}`.character_spell ADD custom_blob VARBINARY(20) NULL;
            ALTER TABLE `{source}`.characters ADD legacy_note TEXT NULL, ADD created TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP;
            CREATE TABLE `{auth}`.account(id INT PRIMARY KEY);INSERT INTO `{auth}`.account VALUES(1);
            INSERT INTO `{source}`.characters(guid,account,name,taximask,race,class,level,online,activeTalentGroup,talentGroupsCount,at_login,legacy_note,created)
            VALUES(1,1,'HistoryOne','',1,1,80,0,0,2,32,'Case Ω','2010-01-02 03:04:05'),
                  (2,1,'OtherRank','',1,1,80,0,0,2,0,NULL,NULL),
                  (3,1,'ResetPending','',1,1,80,0,0,1,4,NULL,NULL),
                  (4,1,'Foreign','',1,9,80,0,0,1,0,NULL,NULL),
                  (5,1,'EnabledRank','',1,1,80,0,0,1,0,NULL,NULL),
                  (6,1,'Inactive','',1,1,80,0,0,1,0,NULL,NULL),
                  (7,1,'SkillRoute','',1,1,80,0,0,1,0,NULL,NULL),
                  (8,1,'LearnRoute','',1,1,80,0,0,1,0,NULL,NULL),
                  (9,1,'Enabled','',1,1,80,0,0,1,0,NULL,NULL),
                  (10,1,'EmptyAfter','',1,1,80,0,0,1,0,NULL,NULL);
            INSERT INTO `{source}`.character_talent VALUES(1,12282,0),(2,12664,1);
            INSERT INTO `{source}`.character_spell VALUES
              (1,12282,1,0,NULL),(1,12300,1,1,0x00ff),(1,12296,1,1,0xff00),(1,6603,1,0,0xabc0),
              (2,12282,1,1,NULL),(2,12664,1,1,NULL),(3,12296,1,1,NULL),(4,12296,1,1,NULL),
              (5,12282,1,1,NULL),(5,12664,1,0,NULL),(6,12296,0,1,NULL),(7,12308,1,1,NULL),
              (8,12301,1,1,NULL),(9,12296,1,0,NULL),(10,12296,1,1,0x01ab);
            INSERT INTO `{source}`.character_skills VALUES(1,171,375,450);
            INSERT INTO `{source}`.character_glyphs(guid,talentGroup,glyph1) VALUES(1,0,123),(1,1,456);
            INSERT INTO `{source}`.character_action(guid,spec,button,action,type) VALUES(1,0,1,12282,0);
            INSERT INTO `{source}`.item_instance(guid,itemEntry,owner_guid,enchantments) VALUES(700,10000022,1,'Retain');
            INSERT INTO `{source}`.mail(id,receiver,subject) VALUES(800,1,'Earlier recovery');
            INSERT INTO `{source}`.mail_items VALUES(800,700,1);''')
        for user in (writer,reader):
            sql(f"CREATE USER '{user}'@'%' IDENTIFIED BY '';")
            users.append(user)
            for schema in (source,auth,world):sql(f"GRANT SELECT ON `{schema}`.* TO '{user}'@'%';")
        tables=sql("SELECT CONCAT('`',TABLE_SCHEMA,'`.`',TABLE_NAME,'`') FROM information_schema.TABLES "
            f"WHERE TABLE_SCHEMA IN ('{source}','{auth}','{world}') AND TABLE_TYPE='BASE TABLE' ORDER BY 1").splitlines()
        def checksum():return sql('CHECKSUM TABLE '+','.join(tables)+' EXTENDED;')
        baseline=checksum()
        with tempfile.TemporaryDirectory() as temporary:
            work=Path(temporary)
            spec=importlib.util.spec_from_file_location('fixtures',ROOT/'tests/spell-fixtures.py')
            assets=importlib.util.module_from_spec(spec);spec.loader.exec_module(assets)
            profile=json.loads((ROOT/'compatibility/tc335-acwotlk-v2/spell-metadata.json').read_text())
            original=assets.stores
            def history_stores(profile):
                data=original(profile)
                data['Spell'][900010][71]=36;data['Spell'][900010][116]=12301
                ability=[0]*len(profile['stores']['SkillLineAbility']['columns'])
                ability[0:3]=[99999,183,12308];ability[9]=2
                data['SkillLineAbility'][99999]=ability
                return data
            assets.stores=history_stores;assets.write_assets(work,profile)
            config=work/'cleanup.ini'
            config.write_text(f'''[workspace]
directory=workspace
[source]
characters={source}
auth={auth}
world={world}
[paths]
tc_dbc=tc-dbc
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
''');config.chmod(0o600)
            command=['python3',str(ROOT/'console'),'--config',str(config)]
            def run(*args,code=0):
                result=subprocess.run(command+list(args),text=True,capture_output=True)
                assert result.returncode==code,result.stdout+result.stderr
                return result
            def session():return work/'workspace/sessions'/json.loads((work/'workspace/current.json').read_text())['session']
            def package():return session()/'batches'/json.loads((session()/'active-batch.json').read_text())['batch']
            run('init','--label','history')
            run('audit','--scope','all',code=1)
            result=run('inspect-spell-history')
            inspection=Path(result.stdout.split('Reports: ',1)[1].strip()).name
            plan=('plan','disabled-talent-history','--inspection',inspection,'--expect-review-rows','7')
            run(*plan[:-1],'6',code=2)
            result=run(*plan)
            manifest=json.loads((package()/'manifest.json').read_text());archive=manifest['archive_schema'];owned.append(archive)
            assert manifest['selected_rows']==3 and manifest['excluded_rows']==4,manifest
            assert manifest['excluded_reason_counts']=={'DEFER_ENABLED_FAMILY_SPELL':1,'DEFER_INDEPENDENT_LEARN_ROUTE':2,'DEFER_SKILL_REWARD_ROUTE':1}
            assert checksum()==baseline
            passed('sealed inspection reused; first plan read-only; both specs, pending reset, foreign/enabled ranks and independent learning routes excluded')
            run('prepare');run('prepare');assert checksum()==baseline
            timezone=subprocess.run(['mysql',*base,'--user='+writer],input=
                f"SET SESSION time_zone='+03:00'; SET @talent_cleanup_ack='STOPPED_PREPARATION_COPY_ONLY'; CALL `{archive}`.prepare_batch();",
                text=True,capture_output=True)
            assert timezone.returncode==0,timezone.stderr
            assert checksum()==baseline
            denied=run('apply',code=2);assert 'DELETE on character_spell' in denied.stderr
            assert checksum()==baseline
            sql(f"GRANT DELETE,INSERT ON `{source}`.character_spell TO '{writer}'@'%';")
            passed('prepare archives complete custom/binary/timestamp state without source writes; narrow source grants required')
            for update,restore in (
                (f"UPDATE `{source}`.characters SET legacy_note='Changed' WHERE guid=1",f"UPDATE `{source}`.characters SET legacy_note='Case Ω' WHERE guid=1"),
                (f"UPDATE `{source}`.character_spell SET custom_blob=0xffff WHERE guid=1 AND spell=6603",f"UPDATE `{source}`.character_spell SET custom_blob=0xabc0 WHERE guid=1 AND spell=6603"),
                (f'UPDATE `{source}`.character_talent SET talentGroup=1 WHERE guid=1',f'UPDATE `{source}`.character_talent SET talentGroup=0 WHERE guid=1'),
                (f'UPDATE `{source}`.character_skills SET value=374 WHERE guid=1',f'UPDATE `{source}`.character_skills SET value=375 WHERE guid=1'),
                (f'UPDATE `{source}`.characters SET at_login=36 WHERE guid=1',f'UPDATE `{source}`.characters SET at_login=32 WHERE guid=1')):
                sql(update);changed=checksum();run('apply',code=2);assert checksum()==changed;sql(restore)
            sql(f"INSERT INTO `{world}`.spell_script_names VALUES(12296,'unexpected_script');")
            drift=checksum();assert 'HISTORY_METADATA_DRIFT' in run('apply',code=2).stderr;assert checksum()==drift
            direct=subprocess.run(['mysql',*base,'--user='+writer],input=
                f"SET @talent_cleanup_ack='STOPPED_PREPARATION_COPY_ONLY'; CALL `{archive}`.apply_batch();",
                text=True,capture_output=True)
            assert direct.returncode!=0 and 'World metadata content changed' in direct.stderr,direct.stderr
            assert checksum()==drift
            sql(f'DELETE FROM `{world}`.spell_script_names WHERE spell_id=12296')
            assert checksum()==baseline
            passed('same-count character, spell, skill and ownership drift; pending reset; world metadata drift all rejected')
            sql(f"CREATE TRIGGER `{archive}`.fail_commit BEFORE UPDATE ON `{archive}`.batch FOR EACH ROW BEGIN IF NEW.state='APPLIED' THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='late-error'; END IF; END")
            failure=run('apply',code=2);assert 'late-error' in failure.stderr,failure.stderr
            assert checksum()==baseline
            assert sql(f'SELECT state FROM `{archive}`.batch')=='PREPARED'
            sql(f'DROP TRIGGER `{archive}`.fail_commit')
            passed('late error rolls back exact row deletion and checkpoint together')
            sql(f"CREATE TRIGGER `{archive}`.pause_commit BEFORE UPDATE ON `{archive}`.batch FOR EACH ROW BEGIN IF NEW.state='APPLIED' THEN DO SLEEP(30); END IF; END")
            worker=subprocess.Popen(command+['apply'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            connection=''
            deadline=time.monotonic()+25
            while time.monotonic()<deadline:
                if worker.poll() is not None:
                    stdout,stderr=worker.communicate()
                    raise AssertionError(stdout+stderr)
                connection=sql("SELECT ID FROM information_schema.PROCESSLIST WHERE DB='"+archive+"' AND STATE='User sleep' LIMIT 1")
                if connection:break
                time.sleep(0.2)
            assert connection,'Timed out waiting for disposable transaction pause: '+sql("SELECT USER,DB,STATE,LEFT(INFO,100) FROM information_schema.PROCESSLIST WHERE USER<>'system user'")
            sql('KILL CONNECTION '+connection);worker.communicate(timeout=10);assert worker.returncode!=0;worker=None
            assert checksum()==baseline and sql(f'SELECT state FROM `{archive}`.batch')=='PREPARED'
            sql(f'DROP TRIGGER `{archive}`.pause_commit')
            run('apply');run('apply');run('status')
            assert sql(f'SELECT state FROM `{archive}`.batch')=='APPLIED'
            assert sql(f'SELECT COUNT(*) FROM `{source}`.character_spell')=='12'
            passed('interruption rolls back; status/retry and committed rerun; only three selected rows removed')
            sql(f'UPDATE `{source}`.character_spell SET active=0 WHERE guid=1 AND spell=6603')
            changed=checksum();run('restore',code=2);assert checksum()==changed
            sql(f'UPDATE `{source}`.character_spell SET active=1 WHERE guid=1 AND spell=6603')
            run('restore');run('restore');assert checksum()==baseline
            run('apply',code=2)
            passed('exact restoration including custom binary fields; changed-state restore blocked; archive retained; apply-after-restore refused')
            # V2 must require an explicit option, preserve every old exclusion,
            # record the reviewed script contract, and use the same atomic SQL.
            sql(f"INSERT INTO `{world}`.spell_script_names VALUES(12296,'spell_dk_mark_of_blood');")
            scripted_baseline=checksum()
            run('audit','--scope','all',code=1)
            result=run('inspect-spell-history');inspection=Path(result.stdout.split('Reports: ',1)[1].strip()).name
            scripted_plan=('plan','disabled-talent-history','--inspection',inspection,'--expect-review-rows','7')
            assert 'HISTORY_NO_ELIGIBLE_ROWS' in run(*scripted_plan,code=2).stderr
            run(*scripted_plan,'--include-reviewed-scripts')
            data=json.loads((package()/'manifest.json').read_text());scripted_archive=data['archive_schema'];owned.append(scripted_archive)
            assert data['policy']=='tc-disabled-reviewed-script-talent-history-v2',data
            assert data['selected_rows']==3 and data['scripted_selected_rows']==3,data
            assert data['reviewed_script_bindings']==[[137,12296,'spell_dk_mark_of_blood']],data
            assert 'REVIEWED_NO_SPELLBOOK_MUTATION' in (package()/'scripted-family-review.tsv').read_text()
            assert checksum()==scripted_baseline
            run('prepare');assert checksum()==scripted_baseline
            sql(f"UPDATE `{world}`.spell_script_names SET ScriptName='unknown_script' WHERE spell_id=12296")
            drift=checksum();assert 'HISTORY_METADATA_DRIFT' in run('apply',code=2).stderr
            assert checksum()==drift
            direct=subprocess.run(['mysql',*base,'--user='+writer],input=
                f"SET @talent_cleanup_ack='STOPPED_PREPARATION_COPY_ONLY'; CALL `{scripted_archive}`.apply_batch();",
                text=True,capture_output=True)
            assert direct.returncode!=0 and 'World metadata content changed' in direct.stderr,direct.stderr
            sql(f"UPDATE `{world}`.spell_script_names SET ScriptName='spell_dk_mark_of_blood' WHERE spell_id=12296")
            assert checksum()==scripted_baseline
            sql(f"CREATE TRIGGER `{scripted_archive}`.fail_commit BEFORE UPDATE ON `{scripted_archive}`.batch FOR EACH ROW BEGIN IF NEW.state='APPLIED' THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='scripted-late-error'; END IF; END")
            assert 'scripted-late-error' in run('apply',code=2).stderr
            assert checksum()==scripted_baseline
            sql(f'DROP TRIGGER `{scripted_archive}`.fail_commit')
            run('apply');run('apply');run('status')
            assert sql(f'SELECT COUNT(*) FROM `{source}`.character_spell')=='12'
            run('restore');run('restore');assert checksum()==scripted_baseline
            passed('explicit reviewed-script v2: binding provenance, v1 exclusion, metadata drift (console/direct SQL), late rollback, apply/rerun/exact restore; unrelated source/world state retained')
            sql(f'DELETE FROM `{world}`.spell_script_names WHERE spell_id=12296')
            assert checksum()==baseline
            scale=int(os.environ.get('HISTORY_SCALE_ROWS','0'))
            if scale:
                assert 1<=scale<=200000
                spells=[12282,12663,12664,12300,12301,12296,12308,12810,12811]
                # Alter independent-route fixture metadata before the new audit.
                assets.stores=original
                for name in ('tc-dbc','ac-dbc'):shutil.rmtree(work/name)
                assets.write_assets(work,profile)
                count=(scale+8)//9
                for start in range(0,count,500):
                    values=','.join(f"({100+i},1,'H{100+i}','',1,1,80,0,0,1,0)" for i in range(start,min(start+500,count)))
                    sql(f'INSERT INTO `{source}`.characters(guid,account,name,taximask,race,class,level,online,activeTalentGroup,talentGroupsCount,at_login) VALUES '+values)
                    values=[]
                    for i in range(start,min(start+500,count)):
                        values.extend(f'({100+i},{spell},1,1,NULL)' for index,spell in enumerate(spells) if i*9+index<scale)
                    sql(f'INSERT INTO `{source}`.character_spell VALUES '+','.join(values))
                scale_baseline=checksum()
                run('audit','--scope','all',code=1)
                result=run('inspect-spell-history');inspection=Path(result.stdout.split('Reports: ',1)[1].strip()).name
                # Existing small fixtures remain: the previous skill/learn route
                # rows now become eligible after the fixture DBC change.
                run('plan','disabled-talent-history','--inspection',inspection,'--expect-review-rows',str(scale+7))
                data=json.loads((package()/'manifest.json').read_text());owned.append(data['archive_schema'])
                assert data['selected_rows']==scale+6,data['selected_rows']
                run('prepare');assert checksum()==scale_baseline
                run('apply');run('apply');run('restore');assert checksum()==scale_baseline
                passed(f'{scale} additional history rows: bulk plan/prepare/apply/rerun/exact restore with bounded per-character digests')
        print(f'MySQL {version}: {len(checks)} disabled history check groups PASS; native gameplay NOT TESTED.',flush=True)
    finally:
        if worker is not None and worker.poll() is None:worker.terminate();worker.wait()
        for schema in reversed(owned):sql(f'DROP DATABASE `{schema}`;')
        for user in users:sql(f"DROP USER '{user}'@'%';")


if __name__=='__main__':main()
