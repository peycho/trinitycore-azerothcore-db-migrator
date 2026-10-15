#!/usr/bin/env python3
"""End-to-end CLI rehearsal; writes only owned disposable preparation fixtures."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]


def main():
    port=os.environ.get('REHEARSAL_MYSQL_PORT','33317')
    if (os.environ.get('MIGRATOR_DISPOSABLE_MYSQL')!='1' or not port.isascii()
            or not port.isdigit() or not 1<=int(port)<=65535 or int(port)==3306):
        raise SystemExit('Requires dedicated disposable localhost MySQL on a non-production port')
    defaults=os.environ.get('REHEARSAL_MYSQL_DEFAULTS_FILE','')
    mysql=([f'--defaults-extra-file={defaults}'] if defaults else ['--no-defaults'])+[
        '--host=127.0.0.1',f'--port={int(port)}','--protocol=TCP','--user=root','--batch','--skip-column-names','--skip-force']
    def sql(query):
        if query.startswith('CREATE TRIGGER '):
            query='DELIMITER //\n'+query+'//\nDELIMITER ;\n'
        result=subprocess.run(['mysql',*mysql],input=query,text=True,capture_output=True)
        assert result.returncode==0,result.stderr
        return result.stdout.strip()
    version=sql('SELECT @@version;')
    assert version.startswith('8.4.'),version
    socket_path=os.environ.get('REHEARSAL_MYSQL_SOCKET','')
    if socket_path:
        assert Path(socket_path).is_socket(),'Expected the dedicated disposable server socket'
        socket_args=([f'--defaults-extra-file={defaults}'] if defaults else ['--no-defaults'])+[
            '--host=localhost','--protocol=SOCKET','--socket='+socket_path,'--user=root',
            '--batch','--skip-column-names','--execute=SELECT @@server_uuid;']
        socket_server=subprocess.run(['mysql',*socket_args],text=True,capture_output=True)
        assert socket_server.returncode==0,socket_server.stderr
        assert socket_server.stdout.strip()==sql('SELECT @@server_uuid;'),'Socket does not belong to the dedicated TCP test server'
        print('Testing console roles through the verified disposable Unix socket',flush=True)
    prefix='console_'+uuid.uuid4().hex[:10]
    source,auth,world=[prefix+s for s in ('_chars','_auth','_world')]
    writer,reader=prefix+'_w',prefix+'_r'
    writer_password='private%#;writer'
    reader_password='private%#;reader'
    owned=[]
    users=[]
    checks=[]
    worker=None
    def passed(label):
        checks.append(label)
        print('PASS '+label,flush=True)
    with tempfile.TemporaryDirectory() as temporary:
        work=Path(temporary)
        try:
            for schema in (source,auth,world):
                sql(f'CREATE DATABASE `{schema}`;')
                owned.append(schema)
            tc=Path(os.environ.get('TRINITYCORE_DIR',ROOT.parent/'TrinityCore'))
            ac=Path(os.environ.get('AZEROTHCORE_DIR',ROOT.parent/'azerothcore-wotlk'))
            sql(f'USE `{source}`;'+(tc/'sql/base/characters_database.sql').read_text())
            sql(f'''ALTER TABLE `{source}`.characters ADD createDate TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
                ADD legacy_note TEXT;
              ALTER TABLE `{source}`.item_instance ADD transmog INT UNSIGNED DEFAULT 0,
                ADD enchant INT UNSIGNED DEFAULT 0;
              CREATE TABLE `{auth}`.account(id INT PRIMARY KEY,username VARCHAR(20));
              INSERT INTO `{auth}`.account VALUES(1,'FIXTURE');
              CREATE TABLE `{world}`.spell_dbc(Id INT PRIMARY KEY);
              CREATE TABLE `{world}`.item_template(entry INT PRIMARY KEY);
              CREATE TABLE `{world}`.quest_template(ID INT PRIMARY KEY);
              INSERT INTO `{world}`.item_template VALUES(6948);
              INSERT INTO `{source}`.characters(guid,account,name,taximask,race,class,level,online,
                activeTalentGroup,talentGroupsCount,at_login,createDate,legacy_note)
                VALUES(1,1,'Герой','',1,1,80,0,0,1,32,'2010-01-02 03:04:05','Original Case Ω'),
                      (2,1,'FixtureTwo','',1,1,80,0,0,1,0,NULL,NULL);
              INSERT INTO `{source}`.character_talent VALUES
                (1,12282,1),(1,12300,1),(1,12296,1),(1,12664,0),(2,130,0),(2,142,0),(2,12296,0);
              INSERT INTO `{source}`.character_spell VALUES(1,6603,1,0),(1,12296,1,1),(2,48942,1,0);
              INSERT INTO `{source}`.character_skills VALUES(1,43,400,400),(2,171,450,450);
              INSERT INTO `{source}`.character_glyphs(guid,talentGroup,glyph1) VALUES(1,0,123),(1,1,456);
              INSERT INTO `{source}`.item_instance(guid,itemEntry,owner_guid,enchantments,transmog,enchant)
                VALUES(100,0,1,'Container',123,456),(200,0,2,'Container two',789,987);
              INSERT INTO `{source}`.mail(id,receiver,subject,body) VALUES(800,1,'Earlier recovery','Preserve');
              INSERT INTO `{source}`.mail_items VALUES(900,99999,1);''')
            # 13 items for one owner exercises deterministic native 12+1 splitting;
            # one custom item for the other owner is absent from world templates.
            for index in range(14):
                owner,bag,slot=(1,100,index) if index<13 else (2,200,0)
                item=1000+index
                entry=6948 if index<13 else 10000022
                sql(f"INSERT INTO `{source}`.item_instance(guid,itemEntry,owner_guid,enchantments,transmog,enchant) VALUES({item},{entry},{owner},'Keep Case Ω',111,222);"
                    f'INSERT INTO `{source}`.character_inventory VALUES({owner},{bag},{slot},{item});')
            for user,password in ((writer,writer_password),(reader,reader_password)):
                sql(f"CREATE USER '{user}'@'%' IDENTIFIED BY '{password}';")
                users.append(user)
                for schema in (source,auth,world):
                    sql(f"GRANT SELECT ON `{schema}`.* TO '{user}'@'%';")
            sql(f"GRANT INSERT,DELETE ON `{source}`.character_talent TO '{writer}'@'%';"
                f"GRANT UPDATE(at_login) ON `{source}`.characters TO '{writer}'@'%';"
                f"GRANT INSERT,DELETE ON `{source}`.character_inventory TO '{writer}'@'%';"
                f"GRANT INSERT,DELETE ON `{source}`.mail TO '{writer}'@'%';"
                f"GRANT INSERT,DELETE ON `{source}`.mail_items TO '{writer}'@'%';")
            spec=importlib.util.spec_from_file_location('assets',ROOT/'tests/spell-fixtures.py')
            assets=importlib.util.module_from_spec(spec)
            spec.loader.exec_module(assets)
            profile=json.loads((ROOT/'compatibility/tc335-acwotlk-v2/spell-metadata.json').read_text())
            assets.write_assets(work,profile)
            config=work/'cleanup.ini'
            admin=(f'defaults_file={defaults}' if defaults else 'user=root\npassword=')
            config.write_text(f'''[workspace]
directory=workspace
[source]
core=tc
characters={source}
auth={auth}
world={world}
[paths]
tc_dbc=tc-dbc
ac_dbc=ac-dbc
tc_source={tc}
ac_source={ac}
[mysql]
host=127.0.0.1
port={port}
socket={socket_path}
user={writer}
password={writer_password}
[mysql_audit]
user={reader}
password={reader_password}
[mysql_admin]
{admin}
[safety]
preparation_copy=yes
writers_stopped=yes
backup_reference=synthetic-fixture-baseline
''')
            config.chmod(0o600)
            command=['python3',str(ROOT/'console'),'--config',str(config)]
            def run(*args,code=0):
                result=subprocess.run(command+list(args),cwd=work,text=True,capture_output=True)
                assert result.returncode==code,result.stdout+result.stderr
                assert writer_password not in result.stdout+result.stderr
                return result
            def session():
                return work/'workspace/sessions'/json.loads((work/'workspace/current.json').read_text())['session']
            def batch():
                return session()/'batches'/json.loads((session()/'active-batch.json').read_text())['batch']
            def manifest():
                return json.loads((batch()/'manifest.json').read_text())
            tables=sql("SELECT CONCAT('`',TABLE_SCHEMA,'`.`',TABLE_NAME,'`') FROM information_schema.TABLES "
                f"WHERE TABLE_SCHEMA IN ('{source}','{auth}','{world}') AND TABLE_TYPE='BASE TABLE' ORDER BY 1").splitlines()
            def checksum(selected=tables):
                return sql('CHECKSUM TABLE '+','.join(selected)+' EXTENDED;')
            baseline=checksum()
            dump_args=([f'--defaults-extra-file={defaults}'] if defaults else ['--no-defaults'])+[
                '--host=127.0.0.1',f'--port={int(port)}','--protocol=TCP','--user=root',
                '--default-character-set=utf8mb4','--set-gtid-purged=OFF','--databases',source,auth,world]
            dumped=subprocess.run(['mysqldump',*dump_args],text=True,capture_output=True)
            assert dumped.returncode==0,dumped.stderr
            run('init','--label','first-import')
            first_session=session()
            run('audit','--scope','all',code=1)
            assert checksum()==baseline
            passed('private configured session; real read-only full audit; finding exit 1; source/auth/world unchanged')
            run('plan','talents','--expect-rows','2')
            talent_batch=batch().name
            talent_archive=manifest()['archive_schema']
            run('prepare')
            assert checksum()==baseline
            dbc=work/'tc-dbc/Talent.dbc'
            original_dbc=dbc.read_bytes()
            changed_dbc=bytearray(original_dbc)
            changed_dbc[-1]^=1
            dbc.write_bytes(changed_dbc)
            assert 'DBC_DRIFT' in run('apply',code=2).stderr
            assert checksum()==baseline
            dbc.write_bytes(original_dbc)
            run('prepare')
            run('apply')
            applied=checksum()
            run('apply')
            assert checksum()==applied
            assert sql(f'SELECT COUNT(*) FROM `{source}`.character_talent')=='5'
            assert sql(f'SELECT COUNT(*) FROM `{source}`.character_talent WHERE guid=1')=='4'
            run('status','--batch',talent_batch)
            passed('non-rank batch creation, archive-only prepare, exact apply, status and idempotent reruns through restricted writer')
            run('audit','--scope','talents',code=1)
            run('plan','reset-talents','--guid','1')
            reset_batch=batch().name
            reset_archive=manifest()['archive_schema']
            run('prepare')
            run('apply')
            assert sql(f'SELECT at_login FROM `{source}`.characters WHERE guid=1')=='36'
            assert sql(f'SELECT COUNT(*) FROM `{source}`.character_talent WHERE guid=1 AND talentGroup=0')=='1'
            run('audit','--scope','talents')
            run('restore','--batch',talent_batch,code=2)
            run('restore')
            run('restore')
            run('restore','--batch',talent_batch)
            assert checksum()==baseline
            passed('UTF-8 character pending reset, flag preservation, clean talent audit, reverse-order restoration guards and exact full restoration')
            run('inspect-items')
            run('plan','items','--containers','100,200')
            recovery_batch=batch().name
            recovery_archive=manifest()['archive_schema']
            assert manifest()['mails']==3 and manifest()['selected_rows']==14
            run('prepare')
            assert checksum()==baseline
            assert sql(f'SELECT MAX(id) FROM `{recovery_archive}`.planned_mail')=='903'
            sql(f"UPDATE `{source}`.item_instance SET enchantments='changed' WHERE guid=1000;")
            changed=checksum()
            run('apply',code=2)
            assert checksum()==changed
            sql(f"UPDATE `{source}`.item_instance SET enchantments='Keep Case Ω' WHERE guid=1000;")
            assert checksum()==baseline
            passed('dynamic custom-field item snapshots and same-count item drift blocker')
            sql(f"CREATE TRIGGER `{recovery_archive}`.late_failure BEFORE UPDATE ON `{recovery_archive}`.batch FOR EACH ROW BEGIN "
                "IF NEW.state='APPLIED' THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Injected late failure'; END IF; END;")
            run('apply',code=2)
            assert checksum()==baseline
            sql(f'DROP TRIGGER `{recovery_archive}`.late_failure;')
            passed('mail/attachment/inventory/checkpoint late-error transaction rollback through console')
            sql(f"CREATE TRIGGER `{recovery_archive}`.pause BEFORE UPDATE ON `{recovery_archive}`.batch FOR EACH ROW BEGIN "
                "IF NEW.state='APPLIED' THEN DO SLEEP(30); END IF; END;")
            worker=subprocess.Popen(command+['apply'],cwd=work,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            deadline=time.monotonic()+20
            connection=''
            while time.monotonic()<deadline:
                if worker.poll() is not None:
                    raise AssertionError(worker.communicate())
                # A DEFINER trigger reports the definer while sleeping, so
                # locate the owned archive's boundary instead of filtering USER.
                connection=sql(f"SELECT ID FROM information_schema.PROCESSLIST WHERE DB='{recovery_archive}' AND STATE='User sleep'")
                if connection:
                    break
                time.sleep(.1)
            assert connection,'Interruption boundary not reached: '+sql("SELECT USER,STATE,LEFT(INFO,150) FROM information_schema.PROCESSLIST WHERE USER<>'system user'")
            sql('KILL CONNECTION '+connection)
            _,errors=worker.communicate(timeout=10)
            assert worker.returncode==2,errors
            assert checksum()==baseline
            sql(f'DROP TRIGGER `{recovery_archive}`.pause;')
            run('status','--batch',recovery_batch)
            run('apply')
            run('apply')
            assert sql(f'SELECT COUNT(*) FROM `{source}`.character_inventory')=='0'
            assert sql(f'SELECT COUNT(*) FROM `{source}`.mail_items WHERE mail_id BETWEEN 901 AND 903')=='14'
            assert sql(f'SELECT MAX(n) FROM (SELECT COUNT(*) n FROM `{source}`.mail_items WHERE mail_id BETWEEN 901 AND 903 GROUP BY mail_id) q')=='12'
            protected=[table for table in tables if table not in [f'`{source}`.`'+t+'`' for t in ('character_inventory','mail','mail_items')]]
            expected='\n'.join(line for line in baseline.splitlines() if not any(line.startswith(source+'.'+t+'\t') for t in ('character_inventory','mail','mail_items')))
            assert checksum(protected)==expected
            passed('interruption reconciliation/resume; deterministic 12+1+1 native mail; custom items, all item attributes and unrelated data preserved')
            sql(f'INSERT INTO `{source}`.character_inventory VALUES(1,100,0,100);')
            changed=checksum()
            run('restore',code=2)
            assert checksum()==changed
            sql(f'DELETE FROM `{source}`.character_inventory WHERE item=100;')
            run('restore')
            run('restore')
            assert checksum()==baseline
            passed('occupied-slot restoration blocker, exact mail inverse, archive retention and restore rerun')
            # Reject edited generated SQL before any DB statement executes.
            setup=batch()/'02-apply.sql'
            original=setup.read_text()
            setup.write_text('SELECT 1;')
            result=run('apply',code=2)
            assert 'PACKAGE_CHANGED' in result.stderr and checksum()==baseline
            setup.write_text(original)
            passed('SQL package tampering rejected with structured private error report')
            run('plan','items','--containers','100')
            partial=manifest()['archive_schema']
            sql(f'CREATE DATABASE `{partial}`;')
            run('prepare',code=2)
            assert checksum()==baseline
            passed('partial setup retained and refused; no implicit DROP or source writes')
            # Reimport the original fixture databases while old archives remain.
            # This exercises same-UUID restarts rather than merely a new label.
            run('audit','--scope','talents',code=1)
            run('plan','talents','--expect-rows','2')
            run('prepare')
            run('apply')
            old_applied=batch().name
            for schema in (source,auth,world):
                sql(f'DROP DATABASE `{schema}`;')
            sql(dumped.stdout)
            assert checksum()==baseline
            run('init','--label','fresh-import')
            assert session()!=first_session and first_session.is_dir()
            run('sessions')
            run('audit','--scope','talents',code=1)
            run('plan','talents','--expect-rows','2')
            assert manifest()['archive_schema']!=talent_archive
            run('prepare')
            run('apply')
            run('restore')
            assert checksum()==baseline
            passed('actual dump/reimport with same UUID/config and old APPLIED archives; new session and archives; old evidence retained')
            second_session=session()
            run('sessions','--use',first_session.name)
            run('apply','--batch',old_applied,code=2)
            assert checksum()==baseline
            run('sessions','--use',second_session.name)
            passed('explicit old-session selection cannot apply a stale APPLIED batch to freshly imported source data')
            session_file=session()/'session.json'
            original=session_file.read_text()
            data=json.loads(original)
            data['identity']['uuid']='12345678-1234-1234-1234-123456789abc'
            session_file.write_text(json.dumps(data))
            assert 'SESSION_ENDPOINT_CHANGED' in run('status',code=2).stderr
            session_file.write_text(original)
            passed('endpoint/session identity drift rejected before cleanup')
            for path in (work/'workspace').rglob('*'):
                assert path.stat().st_mode&0o077==0,path
                if path.is_file():
                    assert writer_password not in path.read_text(errors='replace'),path
            assert not list((work/'workspace/.credentials').iterdir())
            passed('private workspace, journal and packages contain no passwords; temporary client files removed')
            print(f'MySQL {version}: {len(checks)} cleanup console check groups PASS; native gameplay NOT TESTED.')
        finally:
            if worker is not None and worker.poll() is None:
                worker.kill(); worker.wait()
            archives=[]
            for path in (work/'workspace').glob('sessions/*/batches/*/manifest.json'):
                manifest_data=json.loads(path.read_text())
                archives.append(manifest_data['archive_schema'])
            for schema in archives:
                sql(f'DROP DATABASE IF EXISTS `{schema}`;')
            for user in users:
                sql(f"DROP USER '{user}'@'%';")
            for schema in reversed(owned):
                sql(f'DROP DATABASE `{schema}`;')


if __name__=='__main__':
    main()
