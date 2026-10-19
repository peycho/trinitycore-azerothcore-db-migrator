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
            # Real Fiery Payback roots/children and Holy Shock trained ranks.
            # Enabled children, inactive-but-enabled ranks, inactive selected
            # ownership and pending resets must survive the wider v3 policy.
            sql(f'''INSERT INTO `{source}`.characters(guid,account,name,taximask,race,class,level,online,activeTalentGroup,talentGroupsCount,at_login)
              VALUES(11,1,'FieryHistory','',1,8,80,0,0,2,0),(12,1,'FieryEnabled','',1,8,80,0,0,2,0),
                    (13,1,'ShockHistory','',1,2,80,0,0,2,0),(14,1,'ShockEnabled','',1,2,80,0,0,2,0),
                    (15,1,'FieryLower','',1,8,80,0,0,1,0),(16,1,'FSelected','',1,8,80,0,0,2,0),
                    (17,1,'FieryPending','',1,8,80,0,0,1,4);
              INSERT INTO `{source}`.character_spell VALUES(11,64357,1,1,NULL),(11,44441,0,1,0x00af),(11,64349,1,1,NULL),
                (12,64357,1,1,NULL),(12,44441,1,0,NULL),(13,20473,1,1,NULL),(13,48825,0,1,0xaabb),
                (14,20473,1,1,NULL),(14,48825,0,0,NULL),(15,64353,1,1,NULL),(15,64350,0,1,NULL),
                (16,64357,1,1,NULL),(16,44441,1,1,NULL),(17,64357,1,1,NULL);
              INSERT INTO `{source}`.character_talent VALUES(16,64357,1);
              INSERT INTO `{world}`.spell_learn_spell VALUES(64357,44441,1);''')
            sql(f'INSERT INTO `{world}`.spell_ranks VALUES '+','.join(f'(20473,{s},{i+1})' for i,s in enumerate(assets.CHAINS[7])))
            relation_baseline=checksum()
            other_tables=[t for t in tables if t!=f'`{source}`.`character_spell`']
            other_before=sql('CHECKSUM TABLE '+','.join(other_tables)+' EXTENDED;')
            run('audit','--scope','all',code=1)
            result=run('inspect-spell-history');inspection=Path(result.stdout.split('Reports: ',1)[1].strip()).name
            relation_plan=('plan','disabled-talent-history','--inspection',inspection,'--expect-review-rows','12')
            run(*relation_plan,'--include-inert-relations')
            data=json.loads((package()/'manifest.json').read_text());relation_archive=data['archive_schema'];owned.append(relation_archive)
            assert data['policy']=='tc-disabled-unselected-talent-closure-v3',data
            assert (data['selected_root_rows'],data['selected_related_rows'],data['selected_rows'])==(6,4,10),data
            assert data['excluded_reason_counts']['DEFER_ENABLED_RELATED_SPELL']==3,data
            report=(package()/'relationship-review.tsv').read_text()
            assert '11\t2001\t44440\tRANK_OR_DEPENDENT\tABSENT_NO_GRANT' in report,report
            assert '13\t3\t48825\tRANK_OR_DEPENDENT\tSELECTED_DISABLED\t0\t1' in report,report
            assert checksum()==relation_baseline
            run('prepare');run('prepare');assert checksum()==relation_baseline
            sql(f'UPDATE `{source}`.character_spell SET disabled=0 WHERE guid=11 AND spell=44441')
            drift=checksum();run('apply',code=2);assert checksum()==drift
            sql(f'UPDATE `{source}`.character_spell SET disabled=1 WHERE guid=11 AND spell=44441')
            sql(f'UPDATE `{world}`.spell_learn_spell SET entry=900002 WHERE entry=64357')
            drift=checksum();assert 'HISTORY_METADATA_DRIFT' in run('apply',code=2).stderr;assert checksum()==drift
            direct=subprocess.run(['mysql',*base,'--user='+writer],input=
                f"SET @talent_cleanup_ack='STOPPED_PREPARATION_COPY_ONLY'; CALL `{relation_archive}`.apply_batch();",text=True,capture_output=True)
            assert direct.returncode!=0 and 'World metadata content changed' in direct.stderr,direct.stderr
            sql(f'UPDATE `{world}`.spell_learn_spell SET entry=64357 WHERE entry=900002')
            sql(f"CREATE TRIGGER `{relation_archive}`.fail_commit BEFORE UPDATE ON `{relation_archive}`.batch FOR EACH ROW BEGIN IF NEW.state='APPLIED' THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='relation-late-error'; END IF; END")
            assert 'relation-late-error' in run('apply',code=2).stderr
            assert checksum()==relation_baseline
            sql(f'DROP TRIGGER `{relation_archive}`.fail_commit')
            passed('v3 full related-state review: real Fiery Payback children/Holy Shock ranks, enabled and inactive-spec preservation, absent ranks never granted, child/world drift and late rollback')
            sql(f"CREATE TRIGGER `{relation_archive}`.pause_commit BEFORE UPDATE ON `{relation_archive}`.batch FOR EACH ROW BEGIN IF NEW.state='APPLIED' THEN DO SLEEP(30); END IF; END")
            worker=subprocess.Popen(command+['apply'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            connection='';deadline=time.monotonic()+25
            while time.monotonic()<deadline:
                if worker.poll() is not None:
                    stdout,stderr=worker.communicate();raise AssertionError(stdout+stderr)
                connection=sql("SELECT ID FROM information_schema.PROCESSLIST WHERE DB='"+relation_archive+"' AND STATE='User sleep' LIMIT 1")
                if connection:break
                time.sleep(0.2)
            assert connection,'Timed out waiting for v3 disposable transaction pause'
            sql('KILL CONNECTION '+connection);worker.communicate(timeout=10);assert worker.returncode!=0;worker=None
            assert checksum()==relation_baseline and sql(f'SELECT state FROM `{relation_archive}`.batch')=='PREPARED'
            sql(f'DROP TRIGGER `{relation_archive}`.pause_commit')
            run('apply');run('apply');run('status')
            assert sql(f'SELECT COUNT(*) FROM `{source}`.character_spell')=='19'
            assert sql('CHECKSUM TABLE '+','.join(other_tables)+' EXTENDED;')==other_before
            assert sql(f'SELECT disabled FROM `{source}`.character_spell WHERE guid=14 AND spell=48825')=='0'
            assert sql(f'SELECT COUNT(*) FROM `{source}`.character_spell WHERE guid IN (12,14,16,17)')=='7'
            run('restore');run('restore');assert checksum()==relation_baseline
            passed('v3 interrupted transaction rollback, apply/rerun and exact complete restore including child binary fields; enabled spells/ownership/skills/auth/world and unrelated data unchanged')
            sql(f'DELETE FROM `{source}`.character_spell WHERE guid BETWEEN 11 AND 17; DELETE FROM `{source}`.character_talent WHERE guid=16; DELETE FROM `{source}`.characters WHERE guid BETWEEN 11 AND 17; DELETE FROM `{world}`.spell_ranks WHERE first_spell_id=20473; DELETE FROM `{world}`.spell_learn_spell WHERE entry=64357;')
            assert checksum()==baseline
            def route_stores(profile):
                data=history_stores(profile)
                for spell in (50334,51266,50321,11113,1831):
                    row=[0]*len(profile['stores']['Spell']['columns']);row[0]=spell;data['Spell'][spell]=row
                for family,root,cls in ((1927,50334,11),(32,11113,8)):
                    tab=[0]*len(profile['stores']['TalentTab']['columns']);tab[0]=family;tab[20]=1<<(cls-1)
                    data['TalentTab'][family]=tab
                    talent=[0]*len(profile['stores']['Talent']['columns']);talent[0]=family;talent[1]=family;talent[4]=root
                    data['Talent'][family]=talent
                data['Spell'][51266][71:74]=[36,36,0];data['Spell'][51266][116:119]=[50321,50334,0]
                data['Spell'][1831][71]=36;data['Spell'][1831][116]=11113
                return data
            assets.stores=route_stores
            for name in ('tc-dbc','ac-dbc'):shutil.rmtree(work/name)
            assets.write_assets(work,profile)
            sql(f'''INSERT INTO `{source}`.characters(guid,account,name,taximask,race,class,level,online,activeTalentGroup,talentGroupsCount,at_login)
              VALUES(21,1,'BerserkOld','',4,11,80,0,0,2,0),(22,1,'BerserkTeach','',4,11,80,0,0,2,0),
                    (23,1,'BlastOld','',1,8,80,0,0,2,0),(24,1,'BlastTeach','',1,8,80,0,0,2,0),
                    (25,1,'DualEnabled','',2,7,80,0,0,2,0),(26,1,'DualSelected','',2,7,80,0,0,2,0),
                    (27,1,'DualAbsent','',2,7,80,0,0,1,0),(28,1,'DualDisabled','',2,7,80,0,0,1,0),
                    (29,1,'WarriorDual','',1,1,80,0,0,1,0);
              INSERT INTO `{source}`.character_spell VALUES(21,50334,1,1,NULL),(21,51266,1,1,0x00af),(21,50321,0,1,NULL),
                (22,50334,1,1,NULL),(22,51266,1,0,NULL),(23,11113,1,1,NULL),(23,1831,0,1,0xff00),
                (24,11113,1,1,NULL),(24,1831,1,0,NULL),(25,30798,1,1,0xaa00),(25,674,1,0,0xbb00),
                (26,30798,1,1,NULL),(26,674,1,0,NULL),(27,30798,0,1,NULL),
                (28,30798,1,1,NULL),(28,674,0,1,0x00cc),(29,30798,1,1,NULL),(29,674,1,0,NULL);
              INSERT INTO `{source}`.character_talent VALUES(26,30798,1);
              INSERT INTO `{source}`.character_skills VALUES(25,118,1,1),(28,118,1,1),(29,118,1,1);''')
            route_baseline=checksum()
            other_before=sql('CHECKSUM TABLE '+','.join(other_tables)+' EXTENDED;')
            shared_before=sql(f'SELECT guid,spell,active,disabled,HEX(custom_blob) FROM `{source}`.character_spell WHERE spell=674 ORDER BY guid')
            run('audit','--scope','all',code=1)
            result=run('inspect-spell-history');inspection=Path(result.stdout.split('Reports: ',1)[1].strip()).name
            route_plan=('plan','disabled-talent-history','--inspection',inspection,'--expect-review-rows','14')
            run(*route_plan,'--include-inert-relations')
            old=json.loads((package()/'manifest.json').read_text())
            assert old['selected_rows']==3 and old['excluded_rows']==11,old
            audit_id=json.loads((session()/'inspections'/inspection/'inspection.json').read_text())['audit']
            run('plan','disabled-talent-history','--audit',audit_id,'--expect-review-rows','14','--include-reviewed-routes')
            data=json.loads((package()/'manifest.json').read_text());route_archive=data['archive_schema'];owned.append(route_archive)
            assert data['inspection_id']!=inspection
            assert data['policy']=='tc-disabled-reviewed-talent-routes-v4',data
            assert (data['selected_root_rows'],data['selected_related_rows'],data['selected_rows'])==(8,3,11),data
            assert data['preserved_shared_route_rows']==2,data
            report=(package()/'relationship-review.tsv').read_text()
            assert '25\t1690\t674\tRANK_OR_DEPENDENT\tPRESERVED_SHARED_SKILL_ROUTE\t1\t0' in report,report
            assert '23\t32\t1831\tREVIEWED_TEACHER\tSELECTED_DISABLED' in report,report
            assert checksum()==route_baseline
            run('prepare');run('prepare');assert checksum()==route_baseline
            sql(f'UPDATE `{source}`.character_spell SET active=0 WHERE guid=25 AND spell=674')
            drift=checksum();run('apply',code=2);assert checksum()==drift
            sql(f'UPDATE `{source}`.character_spell SET active=1 WHERE guid=25 AND spell=674')
            sql(f'UPDATE `{source}`.character_skills SET max=2 WHERE guid=25 AND skill=118')
            drift=checksum();run('apply',code=2);assert checksum()==drift
            sql(f'UPDATE `{source}`.character_skills SET max=1 WHERE guid=25 AND skill=118')
            sql(f"CREATE TRIGGER `{route_archive}`.fail_commit BEFORE UPDATE ON `{route_archive}`.batch FOR EACH ROW BEGIN IF NEW.state='APPLIED' THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='route-late-error'; END IF; END")
            assert 'route-late-error' in run('apply',code=2).stderr
            assert checksum()==route_baseline
            sql(f'DROP TRIGGER `{route_archive}`.fail_commit')
            run('apply');run('apply');run('status')
            assert sql(f'SELECT COUNT(*) FROM `{source}`.character_spell')=='22'
            assert sql(f'SELECT guid,spell,active,disabled,HEX(custom_blob) FROM `{source}`.character_spell WHERE spell=674 ORDER BY guid')==shared_before
            assert sql('CHECKSUM TABLE '+','.join(other_tables)+' EXTENDED;')==other_before
            assert sql(f'SELECT COUNT(*) FROM `{source}`.character_spell WHERE guid IN (22,24,26,29)')=='8'
            run('restore');run('restore');assert checksum()==route_baseline
            passed('v4 exact teacher contracts and shaman root-only cleanup: enabled teachers, inactive selected build and other classes preserved; every 674 field/skill 118/cap retained; source drift, late rollback, rerun and exact restore')
            sql(f'DELETE FROM `{source}`.character_spell WHERE guid BETWEEN 21 AND 29; DELETE FROM `{source}`.character_skills WHERE guid BETWEEN 21 AND 29; DELETE FROM `{source}`.character_talent WHERE guid=26; DELETE FROM `{source}`.characters WHERE guid BETWEEN 21 AND 29;')
            assert checksum()==baseline
            valid_route_stores=route_stores
            def missing_route_stores(profile):
                data=valid_route_stores(profile);del data['Spell'][50321];return data
            assets.stores=missing_route_stores
            for name in ('tc-dbc','ac-dbc'):shutil.rmtree(work/name)
            assets.write_assets(work,profile)
            sql(f'''INSERT INTO `{source}`.characters(guid,account,name,taximask,race,class,level,online,activeTalentGroup,talentGroupsCount,at_login)
              VALUES(30,1,'OldBerserk','',4,11,80,0,0,1,0),(31,1,'BadTeacher','',4,11,80,0,0,1,0);
              INSERT INTO `{source}`.character_spell VALUES(30,50334,1,1,0xff00),(31,50334,1,1,NULL),(31,51266,0,1,NULL);''')
            missing_baseline=checksum()
            run('audit','--scope','all',code=1)
            audit_id=max((session()/'audits').iterdir()).name
            run('plan','disabled-talent-history','--audit',audit_id,'--expect-review-rows','9','--include-reviewed-routes')
            data=json.loads((package()/'manifest.json').read_text());missing_archive=data['archive_schema'];owned.append(missing_archive)
            assert data['selected_rows']==4 and data['selected_root_rows']==4 and data['selected_related_rows']==0,data
            assert data['rejected_missing_target_teachers']==[[50334,51266,50321]],data
            assert data['excluded_reason_counts']['DEFER_INVALID_TEACHER_STORED']==1,data
            assert 'ABSENT_INVALID_TEACHER' in (package()/'relationship-review.tsv').read_text()
            assert checksum()==missing_baseline
            run('prepare');run('apply');run('apply')
            assert sql(f'SELECT COUNT(*) FROM `{source}`.character_spell WHERE guid=31')=='2'
            assert sql(f'SELECT COUNT(*) FROM `{source}`.character_spell WHERE guid=30')=='0'
            run('restore');assert checksum()==missing_baseline
            passed('v4 stock missing-50321 branch: exact invalid wrapper/native-rejection evidence; only absent wrapper qualifies; present invalid teacher retained; no grant; prepare/apply/rerun/exact restore')
            sql(f'DELETE FROM `{source}`.character_spell WHERE guid IN (30,31); DELETE FROM `{source}`.characters WHERE guid IN (30,31);')
            assert checksum()==baseline
            sql(f'''INSERT INTO `{source}`.characters(guid,account,name,taximask,race,class,level,online,activeTalentGroup,talentGroupsCount,at_login)
              VALUES(40,1,'BothRanks','',1,1,80,0,0,2,0),(41,1,'LowerOld','',1,1,80,0,1,2,0),
                    (42,1,'HigherOld','',1,1,80,0,0,1,0),(43,1,'EnabledOld','',1,1,80,0,0,1,0),
                    (44,1,'ResetRanks','',1,1,80,0,0,2,4),(45,1,'BadRankMap','',1,1,80,0,0,1,0),
                    (46,1,'ForeignRank','',1,9,80,0,0,1,0);
              INSERT INTO `{source}`.character_talent VALUES(40,12282,0),(40,12664,1),(41,12664,1),(42,12282,0),
                    (43,12282,0),(44,12663,1),(45,12282,0),(45,12664,0),(46,17877,0);
              INSERT INTO `{source}`.character_spell VALUES(40,12282,1,0,0x00aa),(40,12663,1,1,0x00bb),(40,12664,1,1,0x00cc),
                (41,12282,1,1,NULL),(41,12663,0,1,NULL),(41,12664,1,0,NULL),(42,12664,1,1,NULL),
                (43,12663,1,1,NULL),(43,12664,1,0,0xaaee),(44,12282,1,1,NULL),(44,12663,1,1,NULL),
                (45,12663,1,1,NULL),(46,12663,1,1,NULL);
              INSERT INTO `{source}`.character_skills VALUES(40,171,450,450);''')
            rank_baseline=checksum()
            other_before=sql('CHECKSUM TABLE '+','.join(other_tables)+' EXTENDED;')
            owned_sql=f'SELECT s.guid,s.spell,s.active,s.disabled,HEX(s.custom_blob) FROM `{source}`.character_spell s JOIN `{source}`.character_talent t ON t.guid=s.guid AND t.spell=s.spell ORDER BY s.guid,s.spell,t.talentGroup'
            selected_before=sql(owned_sql)
            run('audit','--scope','all',code=1);audit_id=max((session()/'audits').iterdir()).name
            conflict=run('plan','disabled-talent-history','--audit',audit_id,'--expect-review-rows','6','--selected-rank-history','--include-reviewed-routes',code=2)
            assert 'HISTORY_POLICY_CONFLICT' in conflict.stderr
            run('plan','disabled-talent-history','--audit',audit_id,'--expect-review-rows','6','--selected-rank-history')
            data=json.loads((package()/'manifest.json').read_text());rank_archive=data['archive_schema'];owned.append(rank_archive)
            assert data['policy']=='tc-disabled-other-selected-talent-rank-v5',data
            assert data['selected_rows']==5 and data['excluded_rows']==1,data
            assert data['excluded_reason_counts']=={'DEFER_ENABLED_UNSELECTED_FAMILY_RANK':1},data
            report=(package()/'selected-rank-review.tsv').read_text()
            assert '[[12282,0,1],[12664,1,3]]' in report,report
            assert '[[12282,null,null]]' in report,report
            assert checksum()==rank_baseline
            run('prepare');run('prepare');assert checksum()==rank_baseline
            for update,restore in (
                (f'UPDATE `{source}`.character_spell SET disabled=0 WHERE guid=40 AND spell=12664',f'UPDATE `{source}`.character_spell SET disabled=1 WHERE guid=40 AND spell=12664'),
                (f'UPDATE `{source}`.character_talent SET talentGroup=0 WHERE guid=40 AND spell=12664',f'UPDATE `{source}`.character_talent SET talentGroup=1 WHERE guid=40 AND spell=12664')):
                sql(update);drift=checksum();run('apply',code=2);assert checksum()==drift;sql(restore)
            sql(f"INSERT INTO `{world}`.spell_script_names VALUES(12663,'spell_dk_mark_of_blood');")
            drift=checksum();assert 'HISTORY_METADATA_DRIFT' in run('apply',code=2).stderr;assert checksum()==drift
            sql(f'DELETE FROM `{world}`.spell_script_names WHERE spell_id=12663')
            sql(f"CREATE TRIGGER `{rank_archive}`.fail_commit BEFORE UPDATE ON `{rank_archive}`.batch FOR EACH ROW BEGIN IF NEW.state='APPLIED' THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='rank-late-error'; END IF; END")
            assert 'rank-late-error' in run('apply',code=2).stderr;assert checksum()==rank_baseline
            sql(f'DROP TRIGGER `{rank_archive}`.fail_commit')
            run('apply');run('apply');run('status')
            assert sql(f'SELECT COUNT(*) FROM `{source}`.character_spell')=='23'
            assert sql(owned_sql)==selected_before
            assert sql('CHECKSUM TABLE '+','.join(other_tables)+' EXTENDED;')==other_before
            assert sql(f'SELECT COUNT(*) FROM `{source}`.character_spell WHERE guid=43')=='2'
            run('audit','--scope','all',code=1)
            reviewed=run('inspect-spell-history');assert 'REVIEW_DISABLED_OTHER_SELECTED_RANK\t1' in reviewed.stdout,reviewed.stdout
            sql(f'UPDATE `{source}`.character_spell SET custom_blob=0x9999 WHERE guid=40 AND spell=12282')
            drift=checksum();run('restore',code=2);assert checksum()==drift
            sql(f'UPDATE `{source}`.character_spell SET custom_blob=0x00aa WHERE guid=40 AND spell=12282')
            run('restore');run('restore');assert checksum()==rank_baseline
            passed('v5 selected-rank authority: both specs/different ranks and flags retained, lower/higher stale disabled rows only; enabled conflicts/pending/foreign/invalid owners excluded; source/world drift, late rollback, rerun, fresh audit and exact restore')
            sql(f'DELETE FROM `{source}`.character_spell WHERE guid BETWEEN 40 AND 46; DELETE FROM `{source}`.character_skills WHERE guid=40; DELETE FROM `{source}`.character_talent WHERE guid BETWEEN 40 AND 46; DELETE FROM `{source}`.characters WHERE guid BETWEEN 40 AND 46;')
            assert checksum()==baseline
            saved_report=work/'migration-blockers.tsv'
            saved_report.write_text('guid\tspell\treason_code\tdetail\n1\t*\tUNAUTHORIZED_TALENT_SPELL\t12282: stored_flags=(1, 1)\n2\t*\tUNSUPPORTED_DEPENDENT_LEARN\t33943:34090: no verified native AC dependency\n')
            active_before=(session()/'active-batch.json').read_bytes() if (session()/'active-batch.json').exists() else None
            captured=run('inspect-migration-blockers','--report',str(saved_report),'--bundle')
            evidence=Path(captured.stdout.split('Reports: ',1)[1].splitlines()[0].strip())
            assert Path(captured.stdout.split('Bundle: ',1)[1].strip()).is_file()
            details=json.loads((evidence/'inspection.json').read_text())
            state=json.loads((evidence/'source-state.json').read_text())['rows']
            assert details['reported_characters']==2 and details['cleanup_approval']=='NOT_GRANTED',details
            assert details['migration_approval']=='UNREVIEWED' and details['dbc_sha256'],details
            for table in ('characters','character_spell','character_talent','character_skills'):
                assert len(state.get(table,[]))==int(sql(f'SELECT COUNT(*) FROM `{source}`.`{table}` WHERE guid IN (1,2)')),table
            assert (evidence/'tc-world.json').exists() and (evidence/'SHA256SUMS').exists()
            assert not list(evidence.glob('*.sql')) and not (evidence/'INCOMPLETE').exists()
            assert checksum()==baseline
            assert ((session()/'active-batch.json').read_bytes() if (session()/'active-batch.json').exists() else None)==active_before
            passed('saved migration blocker context with SELECT-only credentials: complete ordinary/direct spell, both-spec talent and skill rows; TC world/DBC fingerprints; source/auth/world and active batch unchanged; no executable cleanup')
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
