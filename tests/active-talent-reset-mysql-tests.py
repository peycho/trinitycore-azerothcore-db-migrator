#!/usr/bin/env python3
"""End-to-end pending native reset through console; dedicated disposable MySQL only."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import struct
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
        '--skip-column-names','--skip-force','--unbuffered','--default-character-set=utf8mb4']
    def sql(query):
        if query.startswith('CREATE TRIGGER '):query='DELIMITER //\n'+query+'//\nDELIMITER ;\n'
        result=subprocess.run(['mysql',*base,'--user=root'],input=query,text=True,capture_output=True)
        assert result.returncode==0,result.stderr
        return result.stdout.strip()
    version=sql('SELECT @@version;');assert version.startswith('8.4.'),version
    prefix='active_reset_'+uuid.uuid4().hex[:10]
    source,auth,world=[prefix+s for s in ('_chars','_auth','_world')]
    writer=prefix+'_writer'
    owned=[];user_created=False;worker=None;checks=[]
    def passed(text):checks.append(text);print('PASS '+text,flush=True)
    try:
        for schema in (source,auth,world):
            sql(f'CREATE DATABASE `{schema}`;');owned.append(schema)
        tc=Path(os.environ.get('TRINITYCORE_DIR',ROOT.parent/'TrinityCore'))
        ac=Path(os.environ.get('AZEROTHCORE_DIR',ROOT.parent/'azerothcore-wotlk'))
        sql(f'USE `{source}`;'+(tc/'sql/base/characters_database.sql').read_text())
        sql(f'''ALTER TABLE `{source}`.characters ADD legacy_note TEXT NULL,
            ADD created TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP;
            ALTER TABLE `{source}`.character_spell ADD custom_blob VARBINARY(20) NULL;
            ALTER TABLE `{source}`.character_talent ADD legacy_value INT DEFAULT 17;
            INSERT INTO `{source}`.characters(guid,account,name,taximask,race,class,level,online,activeTalentGroup,talentGroupsCount,at_login,legacy_note,created)
            VALUES(1,1,'FixtureLock','',5,9,80,0,0,2,32,'Case Ω','2010-03-04 05:06:07'),
            (2,1,'OtherLock','',1,9,80,0,0,2,0,NULL,NULL);
            INSERT INTO `{source}`.character_talent(guid,spell,talentGroup) VALUES(1,17877,0),(1,54349,0),(2,17877,1);
            INSERT INTO `{source}`.character_spell(guid,spell,active,disabled,custom_blob) VALUES
            (1,12284,1,0,0x00ff),(1,17877,1,0,NULL),(1,54349,1,0,0xabc0),(1,6603,1,0,NULL),(2,12284,1,0,0xff00);
            INSERT INTO `{source}`.character_skills VALUES(1,171,375,450);
            INSERT INTO `{source}`.character_glyphs(guid,talentGroup,glyph1) VALUES(1,0,123),(1,1,456);
            INSERT INTO `{source}`.character_action(guid,spec,button,action,type) VALUES(1,0,1,17877,0),(1,1,1,6603,0);
            INSERT INTO `{source}`.item_instance(guid,itemEntry,owner_guid,enchantments) VALUES(700,10000022,1,'Retain');
            INSERT INTO `{source}`.mail(id,receiver,subject) VALUES(800,1,'Earlier recovery');
            INSERT INTO `{source}`.mail_items VALUES(800,700,1);
            CREATE TABLE `{auth}`.account(id INT PRIMARY KEY); INSERT INTO `{auth}`.account VALUES(1);
            CREATE TABLE `{world}`.marker(id INT PRIMARY KEY); INSERT INTO `{world}`.marker VALUES(1);
            CREATE USER '{writer}'@'%' IDENTIFIED BY '';
            GRANT SELECT ON `{source}`.* TO '{writer}'@'%';
            GRANT SELECT ON `{auth}`.* TO '{writer}'@'%';
            GRANT SELECT ON `{world}`.* TO '{writer}'@'%';''')
        user_created=True
        tables=sql("SELECT CONCAT('`',TABLE_SCHEMA,'`.`',TABLE_NAME,'`') FROM information_schema.TABLES "
            f"WHERE TABLE_SCHEMA IN ('{source}','{auth}','{world}') AND TABLE_TYPE='BASE TABLE' ORDER BY 1").splitlines()
        def checksum():return sql('CHECKSUM TABLE '+','.join(tables)+' EXTENDED;')
        baseline=checksum()
        with tempfile.TemporaryDirectory() as directory:
            work=Path(directory)
            spec=importlib.util.spec_from_file_location('fixtures',ROOT/'tests/spell-fixtures.py')
            fixtures=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixtures)
            profile=json.loads((ROOT/'compatibility/tc335-acwotlk-v2/spell-metadata.json').read_text())
            stores=fixtures.stores(profile)
            row=[0]*len(profile['stores']['Spell']['formats']['tc']);row[0]=12284;row[4]=464;row[71]=6;row[95]=280
            stores['Spell'][12284]=row
            tab=[0]*len(profile['stores']['TalentTab']['formats']['tc']);tab[0]=125;tab[20]=1
            stores['TalentTab'][125]=tab
            talent=[0]*len(profile['stores']['Talent']['formats']['tc']);talent[0:2]=[125,125];talent[4]=12284
            stores['Talent'][125]=talent
            (work/'tc-dbc').mkdir()
            for name,data in stores.items():
                fields=len(profile['stores'][name]['formats']['tc'])
                body=b''.join(struct.pack('<'+'I'*fields,*row) for _,row in sorted(data.items()))
                (work/'tc-dbc'/(name+'.dbc')).write_bytes(struct.pack('<4s4I',b'WDBC',len(data),fields,fields*4,1)+body+b'\0')
            config=work/'cleanup.ini'
            config.write_text(f'''[workspace]
directory={work}/workspace
[source]
characters={source}
auth={auth}
world={world}
[paths]
tc_dbc={work}/tc-dbc
tc_source={tc}
ac_source={ac}
[mysql]
host=127.0.0.1
port={port}
user={writer}
password=
[mysql_admin]
user=root
password=
defaults_file={defaults}
[safety]
preparation_copy=yes
writers_stopped=yes
backup_reference=disposable-synthetic-fixture
''')
            config.chmod(0o600)
            def cli(*arguments,okay=True):
                result=subprocess.run(['python3',str(ROOT/'console'),'--config',str(config),*arguments],text=True,capture_output=True)
                assert (result.returncode==0 if okay else result.returncode!=0),result.stdout+result.stderr
                return result
            cli('init','--label','active-reset')
            command=('plan','reset-active-talents','--guid','1','--remove-spells','12284','--expect-talent-rows','2')
            sql(f'INSERT INTO `{source}`.character_talent(guid,spell,talentGroup) VALUES(1,17877,1)')
            cli(*command,okay=False)
            sql(f'DELETE FROM `{source}`.character_talent WHERE guid=1 AND talentGroup=1')
            assert checksum()==baseline
            cli(*command)
            session=(work/'workspace/sessions'/json.loads((work/'workspace/current.json').read_text())['session'])
            batch=json.loads((session/'active-batch.json').read_text())['batch']
            package=session/'batches'/batch
            manifest=json.loads((package/'manifest.json').read_text())
            archive=manifest['archive_schema'];owned.append(archive)
            assert manifest['selected_talent_points']==4
            assert manifest['retained_pending_native_reset']==2
            assert checksum()==baseline
            passed('SELECT-only planning rejects populated inactive build, seals exact foreign row and retains active ownership')
            sql(f"UPDATE `{source}`.characters SET legacy_note=LOWER(legacy_note) WHERE guid=1")
            cli('prepare',okay=False)
            assert sql(f'SELECT state FROM `{archive}`.batch')=='NEW'
            assert sql(f'SELECT COUNT(*) FROM `{archive}`.characters_before')=='0'
            sql(f"UPDATE `{source}`.characters SET legacy_note='Case Ω' WHERE guid=1")
            cli('prepare');cli('prepare')
            assert checksum()==baseline
            assert sql(f'SELECT HEX(custom_blob) FROM `{archive}`.character_spell_before WHERE guid=1 AND spell=12284')=='00FF'
            passed('planned full-state drift rejected; archive-only preparation and rerun preserve timestamp/binary/custom data')
            cli('apply',okay=False)
            assert checksum()==baseline and sql(f'SELECT state FROM `{archive}`.batch')=='PREPARED'
            sql(f"GRANT DELETE,INSERT ON `{source}`.character_spell TO '{writer}'@'%'")
            cli('apply',okay=False)
            assert checksum()==baseline
            sql(f"GRANT UPDATE(at_login) ON `{source}`.characters TO '{writer}'@'%'")
            passed('SELECT-only writer denied; missing flag UPDATE rolls back foreign spell deletion')
            for change,undo in [
                (f'UPDATE `{source}`.character_spell SET active=0 WHERE guid=1 AND spell=6603',f'UPDATE `{source}`.character_spell SET active=1 WHERE guid=1 AND spell=6603'),
                (f'UPDATE `{source}`.character_talent SET legacy_value=18 WHERE guid=1',f'UPDATE `{source}`.character_talent SET legacy_value=17 WHERE guid=1'),
                (f'UPDATE `{source}`.character_skills SET value=374 WHERE guid=1',f'UPDATE `{source}`.character_skills SET value=375 WHERE guid=1'),
                (f'UPDATE `{source}`.characters SET online=1 WHERE guid=1',f'UPDATE `{source}`.characters SET online=0 WHERE guid=1')]:
                sql(change);changed=checksum();cli('apply',okay=False);assert checksum()==changed;sql(undo)
            assert checksum()==baseline
            passed('same-count spell/talent/skill drift and online state blocked before writes')
            sql(f'UPDATE `{archive}`.expected_spells SET active=0')
            cli('apply',okay=False);assert checksum()==baseline
            sql(f'UPDATE `{archive}`.expected_spells SET active=1')
            sql(f'UPDATE `{archive}`.character_spell_before SET custom_blob=0xff00 WHERE spell=12284')
            cli('apply',okay=False);assert checksum()==baseline
            sql(f'UPDATE `{archive}`.character_spell_before SET custom_blob=0x00ff WHERE spell=12284')
            sql(f'ALTER TABLE `{source}`.character_spell ADD unexpected INT DEFAULT 0')
            changed=checksum();cli('apply',okay=False);assert checksum()==changed
            sql(f'ALTER TABLE `{source}`.character_spell DROP unexpected')
            sql(f'CREATE TABLE `{source}`.reset_fk(guid INT UNSIGNED,spell MEDIUMINT UNSIGNED, FOREIGN KEY(guid,spell) REFERENCES `{source}`.character_spell(guid,spell) ON DELETE CASCADE) ENGINE=InnoDB')
            cli('apply',okay=False)
            sql(f'DROP TABLE `{source}`.reset_fk')
            assert checksum()==baseline
            passed('archive selection/snapshot tampering, source DDL drift and hidden cascade foreign keys blocked')
            sql(f"CREATE TRIGGER `{source}`.unreviewed BEFORE DELETE ON `{source}`.character_spell FOR EACH ROW SET @changed=1;")
            cli('apply',okay=False);sql(f'DROP TRIGGER `{source}`.unreviewed')
            sql(f"CREATE TRIGGER `{archive}`.late_failure BEFORE UPDATE ON `{archive}`.batch FOR EACH ROW BEGIN IF NEW.state='APPLIED' THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Late error'; END IF; END;")
            cli('apply',okay=False)
            assert checksum()==baseline and sql(f'SELECT state FROM `{archive}`.batch')=='PREPARED'
            sql(f'DROP TRIGGER `{archive}`.late_failure')
            passed('hidden source triggers blocked; late checkpoint error rolls back deletion and flags')
            sql(f"CREATE TRIGGER `{archive}`.pause BEFORE UPDATE ON `{archive}`.batch FOR EACH ROW BEGIN IF NEW.state='APPLIED' THEN DO SLEEP(30); END IF; END;")
            worker=subprocess.Popen(['mysql',*base,'--user='+writer],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            worker.stdin.write(f"SET @talent_cleanup_ack='STOPPED_PREPARATION_COPY_ONLY'; SELECT CONNECTION_ID(); CALL `{archive}`.apply_batch();\n")
            worker.stdin.close();worker_id=worker.stdout.readline().strip();assert worker_id.isdigit()
            deadline=time.monotonic()+15
            while time.monotonic()<deadline:
                if sql(f"SELECT ID FROM information_schema.PROCESSLIST WHERE ID={worker_id} AND STATE='User sleep'"):break
                assert worker.poll() is None;time.sleep(.1)
            else:raise AssertionError('Interruption boundary not reached')
            sql('KILL CONNECTION '+worker_id);assert worker.wait(timeout=10)!=0
            assert checksum()==baseline and sql(f'SELECT state FROM `{archive}`.batch')=='PREPARED'
            sql(f'DROP TRIGGER `{archive}`.pause')
            passed('interrupted transaction rolls back source and checkpoint')
            cli('apply');cli('apply');cli('status')
            assert sql(f'SELECT at_login FROM `{source}`.characters WHERE guid=1')=='36'
            assert sql(f'SELECT COUNT(*) FROM `{source}`.character_spell WHERE guid=1 AND spell=12284')=='0'
            assert sql(f'SELECT COUNT(*) FROM `{source}`.character_talent WHERE guid=1')=='2'
            # Calculate the exact intended full-schema result, including other characters and untouched tables.
            sql(f'INSERT INTO `{source}`.character_spell SELECT * FROM `{archive}`.character_spell_before WHERE spell=12284')
            sql(f'UPDATE `{source}`.characters SET at_login=32 WHERE guid=1')
            assert checksum()==baseline
            sql(f'DELETE FROM `{source}`.character_spell WHERE guid=1 AND spell=12284')
            sql(f'UPDATE `{source}`.characters SET at_login=36 WHERE guid=1')
            applied=checksum()
            passed('apply/rerun removes only reviewed foreign row, queues bit 4, preserves ownership, specs, skills/caps, glyphs/actions, items/mail, auth/world and other characters')
            sql(f'DELETE FROM `{source}`.character_talent WHERE guid=1 AND spell=17877')
            changed=checksum();cli('restore',okay=False);assert checksum()==changed
            sql(f'INSERT INTO `{source}`.character_talent SELECT * FROM `{archive}`.character_talent_before WHERE spell=17877')
            assert checksum()==applied
            sql(f"CREATE TRIGGER `{archive}`.restore_error BEFORE UPDATE ON `{archive}`.batch FOR EACH ROW BEGIN IF NEW.state='RESTORED' THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Restore error'; END IF; END;")
            cli('restore',okay=False);assert checksum()==applied
            sql(f'DROP TRIGGER `{archive}`.restore_error')
            cli('restore');cli('restore');cli('apply',okay=False)
            assert checksum()==baseline
            passed('restore refuses native-reset/changed ownership, rolls back late errors, reinstates exact full foreign row and flags, retains archive and is idempotent')
            # Originally queued flags must survive exact restoration.
            sql(f'UPDATE `{source}`.characters SET at_login=36 WHERE guid=1')
            cli(*command)
            new_batch=json.loads((session/'active-batch.json').read_text())['batch']
            new_manifest=json.loads((session/'batches'/new_batch/'manifest.json').read_text())
            owned.append(new_manifest['archive_schema'])
            queued=checksum()
            for action in ('prepare','apply','restore'):cli(action)
            assert checksum()==queued
            passed('original reset flag preserved; fresh batches coexist with retained archive')
            print(f'MySQL {version}: {len(checks)} active-build pending-reset groups PASS; native gameplay NOT TESTED.',flush=True)
    finally:
        if worker is not None and worker.poll() is None:worker.kill();worker.wait()
        if user_created:sql(f"DROP USER '{writer}'@'%'")
        for schema in reversed(owned):sql(f'DROP DATABASE IF EXISTS `{schema}`')

if __name__=='__main__':main()
