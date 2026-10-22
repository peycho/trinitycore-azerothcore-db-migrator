#!/usr/bin/env python3
"""Missing native skill plans and exact inverse through the real MySQL console."""
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import uuid
ROOT=Path(__file__).resolve().parents[1]
def main():
    port=os.environ.get('REHEARSAL_MYSQL_PORT','33317')
    if os.environ.get('MIGRATOR_DISPOSABLE_MYSQL')!='1' or not port.isascii() or not port.isdigit() or not 1<=int(port)<=65535 or int(port)==3306:
        raise SystemExit('Requires dedicated disposable localhost MySQL on a non-production port')
    defaults=os.environ.get('REHEARSAL_MYSQL_DEFAULTS_FILE','')
    base=([f'--defaults-extra-file={defaults}']if defaults else['--no-defaults'])+['--host=127.0.0.1','--port='+str(int(port)),'--protocol=TCP','--batch','--raw','--skip-column-names','--skip-force','--default-character-set=utf8mb4']
    def sql(query,database=None):
        result=subprocess.run(['mysql',*base,'--user=root',*([database]if database else[])],input=query,text=True,capture_output=True)
        assert result.returncode==0,result.stderr
        return result.stdout.strip()
    version=sql('SELECT @@version;');assert version.startswith('8.4.'),version
    prefix='native_'+uuid.uuid4().hex[:10];source,auth,world,aworld=[prefix+s for s in ('_chars','_auth','_world','_acworld')];writer=prefix+'_w';reader=prefix+'_r';owned=[];users=[];worker=None;checks=[]
    def passed(text):checks.append(text);print('PASS '+text,flush=True)
    try:
        for schema in (source,auth,world,aworld):sql(f'CREATE DATABASE `{schema}`;');owned.append(schema)
        tc=Path(os.environ.get('TRINITYCORE_DIR',ROOT.parent/'TrinityCore'));ac=Path(os.environ.get('AZEROTHCORE_DIR',ROOT.parent/'azerothcore-wotlk'))
        ddl=(tc/'sql/base/characters_database.sql').read_text()
        for table in ('characters','character_spell','character_talent','character_skills'):
            sql(re.search(r'CREATE TABLE `'+table+r'` \(.*?\) ENGINE=[^;]+;',ddl,re.S)[0],source)
        sql(f'''ALTER TABLE `{source}`.characters ADD legacy_note TEXT NULL,ADD created TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP;
          ALTER TABLE `{source}`.character_spell ADD custom_blob VARBINARY(20) NULL;
          CREATE TABLE `{source}`.unrelated(id INT PRIMARY KEY,custom_value TEXT);INSERT INTO `{source}`.unrelated VALUES(1,'Keep Ω');
          CREATE TABLE `{auth}`.account(id INT PRIMARY KEY);INSERT INTO `{auth}`.account VALUES(1);''')
        values=[]
        for g in range(1,11):
            cls=6 if g in (2,7,10)else 1;level=1 if g==8 else 70 if g==2 else 80;groups=1 if g==6 else 2;login=4 if g==5 else 32
            values.append(f"({g},1,'Native{g}','',1,{cls},{level},0,0,{groups},{login},'Original Ω','2010-01-02 03:04:05')")
        sql('INSERT INTO characters(guid,account,name,taximask,race,class,level,online,activeTalentGroup,talentGroupsCount,at_login,legacy_note,created) VALUES'+','.join(values)+';',source)
        sql('''INSERT INTO character_spell VALUES(1,63644,1,0,0xabc0),(2,53428,1,0,NULL),(3,63644,1,0,NULL),
          (4,63644,1,1,NULL),(5,63644,1,0,NULL),(6,63644,1,0,NULL),(7,53428,1,0,NULL),
          (8,2382,1,0,NULL),(9,6603,1,0,NULL),(10,53428,1,0,NULL);
          INSERT INTO character_skills VALUES(1,171,375,450),(2,183,350,350),(3,183,1,400),(7,776,5,5),(10,776,1,1);
          INSERT INTO character_talent VALUES(1,12282,0);''',source)
        spec=importlib.util.spec_from_file_location('native_skill_fixture',ROOT/'tests/native-skill-fixtures.py');assets=importlib.util.module_from_spec(spec);spec.loader.exec_module(assets)
        profile=json.loads((ROOT/'compatibility/tc335-acwotlk-v2/spell-metadata.json').read_text());assets.base.seed_worlds(sql,tc,ac,world,aworld,profile)
        sql('CREATE TABLE playercreateinfo_spell_custom(racemask INT UNSIGNED,classmask INT UNSIGNED,Spell INT UNSIGNED);',world)
        for user in (writer,reader):
            sql(f"CREATE USER '{user}'@'%' IDENTIFIED BY '';");users.append(user)
            for schema in (source,auth,world):sql(f"GRANT SELECT ON `{schema}`.* TO '{user}'@'%';")
        tables=sql("SELECT CONCAT('`',TABLE_SCHEMA,'`.`',TABLE_NAME,'`') FROM information_schema.TABLES "+f"WHERE TABLE_SCHEMA IN ('{source}','{auth}','{world}','{aworld}') AND TABLE_TYPE='BASE TABLE' ORDER BY 1").splitlines()
        def checksum():return sql('CHECKSUM TABLE '+','.join(tables)+' EXTENDED;')
        baseline=checksum()
        with tempfile.TemporaryDirectory()as temp:
            work=Path(temp);assets.base.write_assets(work,profile)
            config=work/'cleanup.ini';config.write_text(f'''[workspace]
directory={work/'workspace'}
[source]
core=tc
characters={source}
auth={auth}
world={world}
[paths]
tc_dbc={work/'tc-dbc'}
ac_dbc={work/'ac-dbc'}
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
backup_reference=dedicated-disposable-native-skill-fixture
''');config.chmod(0o600)
            command=['python3',str(ROOT/'console'),'--config',str(config)]
            def run(*args,code=0):
                r=subprocess.run(command+list(args),text=True,capture_output=True);assert r.returncode==code,r.stdout+r.stderr;return r
            run('init','--label','native-skills')
            session=work/'workspace/sessions'/json.loads((work/'workspace/current.json').read_text())['session']
            report=work/'blockers.tsv';report.write_text('guid\tspell\treason_code\tdetail\n'+''.join(f'{g}\t*\tSPELL_WOULD_ADD_SKILL\t63644: skill=183\n'for g in range(1,11)))
            result=run('inspect-migration-blockers','--report',str(report));inspection=Path(result.stdout.split('Reports: ',1)[1].strip()).name
            preview=run('plan','native-skills','--preview')
            assert 'PREVIEW: captured evidence only' in preview.stdout and inspection in preview.stdout
            assert not (session/'active-batch.json').exists() and not list((session/'batches').iterdir())
            plan=['plan','native-skills','--migration-inspection',inspection,'--expect-rows','3']
            denied=run(*plan[:-1],'99',code=2);assert 'NATIVE_SKILL_SELECTION_MISMATCH'in denied.stderr
            sql(f'UPDATE `{source}`.character_spell SET active=0 WHERE guid=9;')
            assert 'NATIVE_SKILL_INPUT_DRIFT'in run(*plan,code=2).stderr
            sql(f'UPDATE `{source}`.character_spell SET active=1 WHERE guid=9;')
            run(*plan);package=session/'batches'/json.loads((session/'active-batch.json').read_text())['batch'];manifest=json.loads((package/'manifest.json').read_text());archive=manifest['archive_schema'];owned.append(archive)
            assert manifest['selected_rows']==3 and manifest['skill_counts']=={'183':2,'776':1},manifest
            sql(f'ALTER TABLE `{source}`.character_skills ADD custom_skill TINYINT NOT NULL DEFAULT 0;')
            changed=run('inspect-migration-blockers','--report',str(report));changed_id=Path(changed.stdout.split('Reports: ',1)[1].strip()).name
            assert 'NATIVE_SKILL_SCHEMA_UNSUPPORTED'in run('plan','native-skills','--migration-inspection',changed_id,'--expect-rows','3',code=2).stderr
            sql(f'ALTER TABLE `{source}`.character_skills DROP COLUMN custom_skill;')
            assert checksum()==baseline
            passed('read-only exact three-row candidate; source context drift and wrong count refused; existing skills and pending/single-spec/disabled/no-anchor cases excluded')
            run('prepare');run('prepare');assert checksum()==baseline
            assert 'INSERT on character_skills'in run('apply',code=2).stderr
            sql(f"GRANT INSERT,DELETE ON `{source}`.character_skills TO '{writer}'@'%';")
            passed('complete original custom/binary/timestamp snapshots; prepare/rerun unchanged; source INSERT/DELETE required explicitly')
            for update,inverse in (
                (f"UPDATE `{source}`.characters SET legacy_note='Changed' WHERE guid=1",f"UPDATE `{source}`.characters SET legacy_note='Original Ω' WHERE guid=1"),
                (f'UPDATE `{source}`.character_spell SET custom_blob=0xffff WHERE guid=1',f'UPDATE `{source}`.character_spell SET custom_blob=0xabc0 WHERE guid=1'),
                (f'UPDATE `{source}`.character_talent SET talentGroup=1 WHERE guid=1',f'UPDATE `{source}`.character_talent SET talentGroup=0 WHERE guid=1'),
                (f'UPDATE `{source}`.character_skills SET value=374 WHERE guid=1',f'UPDATE `{source}`.character_skills SET value=375 WHERE guid=1'),
                (f'UPDATE `{world}`.spell_custom_attr SET attributes=1 WHERE entry=6603',f'UPDATE `{world}`.spell_custom_attr SET attributes=0 WHERE entry=6603')):
                sql(update);run('apply',code=2);sql(inverse);assert checksum()==baseline
            passed('same-count character/spell/talent/skill and world drift refused before apply')
            sql(f"CREATE TRIGGER `{archive}`.late_error BEFORE UPDATE ON `{archive}`.batch FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='fixture late error';")
            run('apply',code=2);assert checksum()==baseline;assert sql(f'SELECT state FROM `{archive}`.batch')=='PREPARED'
            sql(f'DROP TRIGGER `{archive}`.late_error;')
            passed('late checkpoint failure rolls back all inserted skills atomically')
            sql(f"CREATE TRIGGER `{archive}`.pause_commit BEFORE UPDATE ON `{archive}`.batch FOR EACH ROW DO SLEEP(30);")
            worker=subprocess.Popen(command+['apply'],text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            killed=False
            for _ in range(400):
                if worker.poll() is not None:
                    stdout,stderr=worker.communicate();raise AssertionError(stdout+stderr)
                row=sql(f"SELECT ID FROM information_schema.PROCESSLIST WHERE DB='{archive}' AND STATE='User sleep' LIMIT 1;")
                if row:sql('KILL CONNECTION '+row+';');killed=True;break
                time.sleep(0.05)
            assert killed,'Did not reach late transaction pause';worker.communicate(timeout=20);worker=None
            assert checksum()==baseline;assert sql(f'SELECT state FROM `{archive}`.batch')=='PREPARED'
            sql(f'DROP TRIGGER `{archive}`.pause_commit;')
            run('apply');applied=checksum();run('apply');assert checksum()==applied
            assert sql(f'SELECT value,max FROM `{source}`.character_skills WHERE guid=1 AND skill=183')=='400\t400'
            assert sql(f'SELECT value,max FROM `{source}`.character_skills WHERE guid=8 AND skill=183')=='5\t5'
            assert sql(f'SELECT value,max FROM `{source}`.character_skills WHERE guid=2 AND skill=776')=='1\t1'
            passed('interrupted transaction rolls back; resume and completed rerun insert exact 400/400, 5/5 and 1/1 rows')
            sql(f'UPDATE `{source}`.character_skills SET value=399 WHERE guid=1 AND skill=183;');run('restore',code=2)
            sql(f'UPDATE `{source}`.character_skills SET value=400 WHERE guid=1 AND skill=183;')
            run('restore');assert checksum()==baseline;run('restore');assert checksum()==baseline
            assert sql(f'SELECT state FROM `{archive}`.batch')=='RESTORED'
            passed('guarded exact inverse removes only inserted rows; original absences, full unrelated data, custom fields and worlds restored/preserved; restore rerun passes')
            # V2 is explicit and separate from the still-restorable v1 archive.
            for g in range(11,19):
                level=1 if g==18 else 80;groups=1 if g==14 else 2;login=4 if g==15 else 32
                sql(f"INSERT INTO `{source}`.characters(guid,account,name,taximask,race,class,level,talentGroupsCount,at_login) VALUES({g},1,'Generic{g}','',1,1,{level},{groups},{login});")
                sql(f"INSERT INTO `{source}`.character_spell(guid,spell,active,disabled) VALUES({g},63680,1,{1 if g==16 else 0});")
            sql(f"INSERT INTO `{source}`.character_skills VALUES(12,183,5,350),(13,183,400,400),(17,183,0,400),(18,183,400,400);")
            v2baseline=checksum()
            report.write_text('guid\tspell\treason_code\tdetail\n'+''.join(f'{g}\t*\tSPELL_WOULD_CHANGE_SKILL\t63680: skill=183\n'for g in range(1,19)))
            captured=run('inspect-migration-blockers','--report',str(report));v2inspection=Path(captured.stdout.split('Reports: ',1)[1].strip()).name
            v2plan=['plan','native-skills','--migration-inspection',v2inspection,'--skills','generic','--normalize-generic']
            assert 'NATIVE_SKILL_POLICY_SCOPE' in run('plan','native-skills','--normalize-generic','--preview',code=2).stderr
            preview=run(*v2plan,'--preview');assert '"normalized_rows": 3' in preview.stdout and '"inserted_rows": 3' in preview.stdout,preview.stdout
            run(*v2plan,'--expect-rows','6')
            v2package=session/'batches'/json.loads((session/'active-batch.json').read_text())['batch']
            v2manifest=json.loads((v2package/'manifest.json').read_text());v2archive=v2manifest['archive_schema'];owned.append(v2archive)
            assert v2manifest['policy']=='tc-native-generic-skills-v2' and v2manifest['normalized_rows']==3
            assert checksum()==v2baseline
            run('prepare');run('prepare');assert checksum()==v2baseline
            assert 'UPDATE(value,max)' in run('apply',code=2).stderr
            sql(f"GRANT UPDATE(value,max) ON `{source}`.character_skills TO '{writer}'@'%';")
            for update,inverse in (
                (f'UPDATE `{source}`.characters SET level=79 WHERE guid=12',f'UPDATE `{source}`.characters SET level=80 WHERE guid=12'),
                (f'UPDATE `{source}`.character_skills SET max=349 WHERE guid=12 AND skill=183',f'UPDATE `{source}`.character_skills SET max=350 WHERE guid=12 AND skill=183'),
                (f'UPDATE `{source}`.character_spell SET disabled=1 WHERE guid=11',f'UPDATE `{source}`.character_spell SET disabled=0 WHERE guid=11'),
                (f'UPDATE `{world}`.spell_custom_attr SET attributes=1 WHERE entry=6603',f'UPDATE `{world}`.spell_custom_attr SET attributes=0 WHERE entry=6603')):
                sql(update);run('apply',code=2)
                denied=subprocess.run(['mysql',*base,'--user=root'],input=f"SET @skill_cleanup_ack='STOPPED_PREPARATION_COPY_ONLY';CALL `{v2archive}`.apply_batch();",text=True,capture_output=True)
                assert denied.returncode!=0,denied.stdout
                sql(inverse);assert checksum()==v2baseline
            for alteration,inverse in (
                (f'ALTER TABLE `{world}`.spell_custom_attr ADD fixture_extra INT',f'ALTER TABLE `{world}`.spell_custom_attr DROP COLUMN fixture_extra'),
                (f'ALTER TABLE `{world}`.spell_custom_attr ENGINE=MyISAM',f'ALTER TABLE `{world}`.spell_custom_attr ENGINE=InnoDB')):
                sql(alteration);run('apply',code=2)
                denied=subprocess.run(['mysql',*base,'--user=root'],input=f"SET @skill_cleanup_ack='STOPPED_PREPARATION_COPY_ONLY';CALL `{v2archive}`.apply_batch();",text=True,capture_output=True)
                assert denied.returncode!=0 and 'world layout or engine drift' in denied.stderr,denied.stderr
                sql(inverse);assert checksum()==v2baseline
            sql(f"CREATE TRIGGER `{v2archive}`.late_error BEFORE UPDATE ON `{v2archive}`.batch FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='fixture late error';")
            run('apply',code=2);assert checksum()==v2baseline and sql(f'SELECT state FROM `{v2archive}`.batch')=='PREPARED'
            sql(f'DROP TRIGGER `{v2archive}`.late_error;')
            sql(f"CREATE TRIGGER `{v2archive}`.pause_commit BEFORE UPDATE ON `{v2archive}`.batch FOR EACH ROW DO SLEEP(30);")
            worker=subprocess.Popen(command+['apply'],text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            killed=False
            for _ in range(400):
                if worker.poll() is not None:
                    stdout,stderr=worker.communicate();raise AssertionError(stdout+stderr)
                row=sql(f"SELECT ID FROM information_schema.PROCESSLIST WHERE DB='{v2archive}' AND STATE='User sleep' LIMIT 1;")
                if row:sql('KILL CONNECTION '+row+';');killed=True;break
                time.sleep(0.05)
            assert killed;worker.communicate(timeout=20);worker=None
            assert checksum()==v2baseline and sql(f'SELECT state FROM `{v2archive}`.batch')=='PREPARED'
            sql(f'DROP TRIGGER `{v2archive}`.pause_commit;')
            run('apply');v2applied=checksum();run('apply');assert checksum()==v2applied
            assert sql(f'SELECT value,max FROM `{source}`.character_skills WHERE guid=11 AND skill=183')=='400\t400'
            assert sql(f'SELECT value,max FROM `{source}`.character_skills WHERE guid=12 AND skill=183')=='400\t400'
            assert sql(f'SELECT value,max FROM `{source}`.character_skills WHERE guid=18 AND skill=183')=='5\t5'
            assert sql(f'SELECT value,max FROM `{source}`.character_skills WHERE guid=17 AND skill=183')=='0\t400'
            assert sql(f'SELECT COUNT(*) FROM `{source}`.character_skills WHERE skill=183 AND guid IN (14,15,16)')=='0'
            passed('v2 explicit teacher-derived insertions plus native Generic updates; zero/single-spec/reset/disabled excluded; same-count source/world/direct-SQL drift and both late-error/disconnect rollback; commit/rerun exact')
            sql(f'UPDATE `{source}`.character_skills SET value=399 WHERE guid=12 AND skill=183;');run('restore',code=2)
            sql(f'UPDATE `{source}`.character_skills SET value=400 WHERE guid=12 AND skill=183;')
            run('restore');run('restore');assert checksum()==v2baseline
            assert sql(f'SELECT value,max FROM `{source}`.character_skills WHERE guid=12 AND skill=183')=='5\t350'
            assert sql(f'SELECT value,max FROM `{source}`.character_skills WHERE guid=18 AND skill=183')=='400\t400'
            assert sql(f'SELECT COUNT(*) FROM `{source}`.character_skills WHERE guid=11 AND skill=183')=='0'
            passed('v2 exact inverse restores old Generic values/caps and original absences; all other custom state, skills, ownership and worlds preserved; old v1 archive retained')
            # Update-only packages need neither source INSERT nor DELETE.
            update_report=work/'update-only.tsv';update_report.write_text('guid\tspell\treason_code\tdetail\n3\t*\tSPELL_WOULD_CHANGE_SKILL\t63644: skill=183\n')
            captured=run('inspect-migration-blockers','--report',str(update_report));update_id=Path(captured.stdout.split('Reports: ',1)[1].strip()).name
            run('plan','native-skills','--migration-inspection',update_id,'--skills','generic','--normalize-generic','--expect-rows','1')
            update_package=session/'batches'/json.loads((session/'active-batch.json').read_text())['batch'];owned.append(json.loads((update_package/'manifest.json').read_text())['archive_schema'])
            sql(f"REVOKE INSERT,DELETE ON `{source}`.character_skills FROM '{writer}'@'%';")
            run('prepare');run('apply');run('restore');assert checksum()==v2baseline
            passed('update-only v2 package works with SELECT plus UPDATE(value,max), no source INSERT/DELETE')
            # Insert-only v2 packages have an empty expected_prior and no source UPDATE.
            insert_report=work/'insert-only.tsv';insert_report.write_text('guid\tspell\treason_code\tdetail\n11\t*\tSPELL_WOULD_ADD_SKILL\t63680: skill=183\n')
            captured=run('inspect-migration-blockers','--report',str(insert_report));insert_id=Path(captured.stdout.split('Reports: ',1)[1].strip()).name
            run('plan','native-skills','--migration-inspection',insert_id,'--skills','generic','--normalize-generic','--expect-rows','1')
            insert_package=session/'batches'/json.loads((session/'active-batch.json').read_text())['batch'];owned.append(json.loads((insert_package/'manifest.json').read_text())['archive_schema'])
            sql(f"REVOKE UPDATE(value,max) ON `{source}`.character_skills FROM '{writer}'@'%';")
            sql(f"GRANT INSERT,DELETE ON `{source}`.character_skills TO '{writer}'@'%';")
            run('prepare');run('apply');run('restore');assert checksum()==v2baseline
            passed('insert-only v2 package with empty prior set works with SELECT plus INSERT/DELETE, no source UPDATE')
            # V3 corrects only the old spec-count restriction on native
            # Generic acquisition, without buying a spec or normalizing skills.
            for g in range(20,26):
                level=48 if g==20 else 80;cls=6 if g==21 else 1;groups=2 if g==23 else 1;active=1 if g==23 else 0;login=4 if g==24 else 0
                sql(f"INSERT INTO `{source}`.characters(guid,account,name,taximask,race,class,level,activeTalentGroup,talentGroupsCount,at_login) VALUES({g},1,'Switch{g}','',1,{cls},{level},{active},{groups},{login})")
            sql(f"INSERT INTO `{source}`.character_spell(guid,spell,active,disabled,custom_blob) VALUES(20,63645,1,0,0xff00),(21,53323,1,0,NULL),(22,63680,1,0,NULL),(23,63644,1,0,NULL),(23,12282,1,0,NULL),(24,63644,1,0,NULL),(25,63644,1,1,NULL)")
            sql(f"INSERT INTO `{source}`.character_skills VALUES(20,171,375,450),(21,776,5,5),(23,183,1,400)")
            sql(f"INSERT INTO `{source}`.character_talent VALUES(23,12282,1)")
            sql(f"ALTER TABLE `{source}`.character_spell ADD custom_decimal DECIMAL(12,6) NOT NULL DEFAULT 0.100001")
            sql(f"UPDATE `{source}`.characters SET position_x=0.1 WHERE guid=6")
            sql(f"INSERT INTO `{world}`.spell_dbc(Id,EffectRealPointsPerLevel1) VALUES(900088,0.1)")
            v3baseline=checksum();other_tables=[t for t in tables if t!=f'`{source}`.`character_skills`'];v3other=sql('CHECKSUM TABLE '+','.join(other_tables)+' EXTENDED;')
            v3report=work/'known-switch.tsv';v3report.write_text('guid\tspell\treason_code\tdetail\n'+''.join(f'{g}\t*\tSPELL_WOULD_ADD_SKILL\t63644: skill=183\n'for g in (6,20,21,22,23,24,25)))
            captured=run('inspect-migration-blockers','--report',str(v3report));v3inspection=Path(captured.stdout.split('Reports: ',1)[1].strip()).name
            old=run('plan','native-skills','--migration-inspection',v3inspection,'--skills','generic','--preview')
            assert '"selected_rows": 0' in old.stdout,old.stdout
            v3plan=['plan','native-skills','--migration-inspection',v3inspection,'--skills','generic','--known-generic-switch']
            assert 'NATIVE_SKILL_POLICY_SCOPE' in run('plan','native-skills','--known-generic-switch','--preview',code=2).stderr
            pointer=(session/'active-batch.json').read_bytes();batches=set((session/'batches').iterdir())
            preview=run(*v3plan,'--preview');assert '"selected_rows": 2' in preview.stdout and '"normalized_rows": 0' in preview.stdout,preview.stdout
            assert checksum()==v3baseline and pointer==(session/'active-batch.json').read_bytes()and batches==set((session/'batches').iterdir())
            run(*v3plan,'--expect-rows','1',code=2)
            sql(f'UPDATE `{source}`.characters SET level=79 WHERE guid=23')
            changed=checksum();assert 'NATIVE_SKILL_INPUT_DRIFT' in run(*v3plan,'--expect-rows','2',code=2).stderr;assert checksum()==changed
            sql(f'UPDATE `{source}`.characters SET level=80 WHERE guid=23')
            run(*v3plan,'--expect-rows','2');v3package=session/'batches'/json.loads((session/'active-batch.json').read_text())['batch']
            v3manifest=json.loads((v3package/'manifest.json').read_text());v3archive=v3manifest['archive_schema'];owned.append(v3archive)
            assert v3manifest['policy']=='tc-known-generic-switch-skill-v3'and v3manifest['numeric_fingerprint']=='EXACT_FRACTIONAL_V1'
            assert v3manifest['normalized_rows']==0 and v3manifest['inserted_rows']==2
            assert all(p['talent_groups']==1 and p['spec_ownership_change']==0 for p in v3manifest['native_skill_proofs'])
            assert json.loads((v3package/'native-skill-proof.json').read_text())==v3manifest['native_skill_proofs']
            run('prepare');run('prepare');assert checksum()==v3baseline
            def direct_switch(extra):
                return subprocess.run(['mysql',*base,'--user='+writer],text=True,capture_output=True,input="SET @skill_cleanup_ack='STOPPED_PREPARATION_COPY_ONLY';"+extra+f'CALL `{v3archive}`.apply_batch();')
            for extra in ('',"SET @native_generic_switch_ack='WRONG';"):
                denied=direct_switch(extra);assert denied.returncode!=0 and 'Explicit known Generic switch-skill' in denied.stderr,denied.stderr
                assert checksum()==v3baseline
            extra="SET @native_generic_switch_ack='KNOWN_SWITCH_SKILL_ONLY';"
            for update,inverse,expected in (
                (f'UPDATE `{source}`.characters SET position_x=0.2 WHERE guid=6',f'UPDATE `{source}`.characters SET position_x=0.1 WHERE guid=6','full-row fingerprint differs'),
                (f'UPDATE `{source}`.character_spell SET custom_decimal=0.100002 WHERE guid=20 AND spell=63645',f'UPDATE `{source}`.character_spell SET custom_decimal=0.100001 WHERE guid=20 AND spell=63645','full-row fingerprint differs'),
                (f'UPDATE `{world}`.spell_dbc SET EffectRealPointsPerLevel1=0.2 WHERE Id=900088',f'UPDATE `{world}`.spell_dbc SET EffectRealPointsPerLevel1=0.1 WHERE Id=900088','world content drift')):
                sql(update);changed=checksum();denied=direct_switch(extra)
                assert denied.returncode!=0 and expected in denied.stderr,denied.stderr
                assert checksum()==changed;sql(inverse)
            sql(f'ALTER TABLE `{world}`.spell_required ADD unexpected INT DEFAULT 0')
            denied=direct_switch(extra);assert denied.returncode!=0 and 'world layout' in denied.stderr,denied.stderr
            sql(f'ALTER TABLE `{world}`.spell_required DROP unexpected')
            sql(f"CREATE TRIGGER `{v3archive}`.late_error BEFORE UPDATE ON `{v3archive}`.batch FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='v3 late failure'")
            run('apply',code=2);assert checksum()==v3baseline and sql(f'SELECT state FROM `{v3archive}`.batch')=='PREPARED'
            sql(f'DROP TRIGGER `{v3archive}`.late_error')
            sql(f"CREATE TRIGGER `{v3archive}`.pause_commit BEFORE UPDATE ON `{v3archive}`.batch FOR EACH ROW DO SLEEP(30)")
            worker=subprocess.Popen(command+['apply'],text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            connection='';deadline=time.monotonic()+10
            while time.monotonic()<deadline:
                if worker.poll()is not None:raise AssertionError(worker.communicate())
                connection=sql(f"SELECT ID FROM information_schema.PROCESSLIST WHERE DB='{v3archive}' AND STATE='User sleep' LIMIT 1")
                if connection:break
                time.sleep(.1)
            assert connection;sql('KILL CONNECTION '+connection);worker.communicate(timeout=10);assert worker.returncode!=0;worker=None
            assert checksum()==v3baseline and sql(f'SELECT state FROM `{v3archive}`.batch')=='PREPARED';sql(f'DROP TRIGGER `{v3archive}`.pause_commit')
            run('status');run('apply');applied=checksum();run('apply');run('status');assert checksum()==applied
            assert sql(f'SELECT guid,value,max FROM `{source}`.character_skills WHERE skill=183 AND guid IN(6,20)ORDER BY guid')=='6\t400\t400\n20\t240\t240'
            assert sql(f'SELECT talentGroupsCount FROM `{source}`.characters WHERE guid=6')=='1'
            assert sql(f'SELECT value,max FROM `{source}`.character_skills WHERE guid=23 AND skill=183')=='1\t400'
            assert sql('CHECKSUM TABLE '+','.join(other_tables)+' EXTENDED;')==v3other
            sql(f'UPDATE `{source}`.character_skills SET value=399 WHERE guid=6 AND skill=183');changed=checksum();run('restore',code=2);assert checksum()==changed
            sql(f'UPDATE `{source}`.character_skills SET value=400 WHERE guid=6 AND skill=183')
            run('restore');run('restore');assert checksum()==v3baseline;run('apply',code=2)
            passed('v3 explicit known-switch Generic insertion independent of spec count; old-policy rejecting control, no second spec, existing skills/spells/talents unchanged; fractional source/world/layout drift, direct SQL acknowledgement, deferred-scope drift, late/disconnect rollback, reruns and exact full restore')
            original=(package/'02-apply.sql').read_text();(package/'02-apply.sql').write_text(original+'SELECT 1;\n')
            assert 'PACKAGE_CHANGED'in run('apply','--batch',package.name,code=2).stderr
            passed('sealed-package tampering rejected; archives retained until owned-fixture teardown')
    finally:
        if worker:
            worker.terminate();worker.communicate(timeout=20)
        for user in reversed(users):sql(f"DROP USER IF EXISTS '{user}'@'%';")
        for schema in reversed(owned):sql(f'DROP DATABASE IF EXISTS `{schema}`;')
    print(f'MySQL {version}: {len(checks)} native-skill repair groups PASS; gameplay NOT TESTED.',flush=True)
if __name__=='__main__':main()
