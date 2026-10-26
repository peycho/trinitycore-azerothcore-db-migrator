#!/usr/bin/env python3
"""Exercise the complete paired repair and its inverse on owned MySQL fixtures."""
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


def main():
    horse='--horse'in sys.argv[1:]
    legacy_spell,legacy_skill=(824,148)if horse else(825,149)
    invalid_items = horse or '--native-invalid-items' in sys.argv[1:]
    if any(a not in('--native-invalid-items','--horse') for a in sys.argv[1:]): raise SystemExit('Unknown test mode')
    port = os.environ.get('REHEARSAL_MYSQL_PORT','33317')
    if (os.environ.get('MIGRATOR_DISPOSABLE_MYSQL') != '1' or not port.isascii()
            or not port.isdigit() or not 1 <= int(port) <= 65535 or int(port) == 3306):
        raise SystemExit('Requires dedicated disposable localhost MySQL on a non-production port')
    defaults = os.environ.get('REHEARSAL_MYSQL_DEFAULTS_FILE','')
    options = (['--defaults-extra-file='+defaults] if defaults else ['--no-defaults'])+[
        '--host=127.0.0.1','--port='+port,'--protocol=TCP','--batch','--raw','--skip-column-names',
        '--skip-force','--default-character-set=utf8mb4']
    def sql(query,schema=None):
        if query.startswith('CREATE TRIGGER '): query = 'DELIMITER //\n'+query+'//\nDELIMITER ;\n'
        r = subprocess.run(['mysql',*options,'--user=root',*([schema] if schema else [])],
                           input=query,text=True,capture_output=True)
        assert r.returncode == 0, r.stderr
        return r.stdout.strip()
    assert sql('SELECT @@version').startswith('8.4.')
    prefix = 'riding_pair_'+uuid.uuid4().hex[:10]
    source,auth,world,aworld = [prefix+s for s in ('_chars','_auth','_world','_ac')]
    writer,reader = prefix+'_w',prefix+'_r'
    owned,users,worker = [],[],None
    try:
        for schema in (source,auth,world,aworld): sql(f'CREATE DATABASE `{schema}`'); owned.append(schema)
        tc = Path(os.environ.get('TRINITYCORE_DIR',ROOT.parent/'TrinityCore'))
        ac = Path(os.environ.get('AZEROTHCORE_DIR',ROOT.parent/'azerothcore-wotlk'))
        ddl = (tc/'sql/base/characters_database.sql').read_text()
        for table in ('characters','character_spell','character_talent','character_skills','character_inventory','item_instance','mail','mail_items'):
            sql(re.search(r'CREATE TABLE `'+table+r'` \(.*?\) ENGINE=[^;]+;',ddl,re.S)[0],source)
        sql(f'''ALTER TABLE `{source}`.characters ADD custom_decimal DECIMAL(18,6) NULL,
            ADD created TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP;
            ALTER TABLE `{source}`.character_spell ADD custom_blob VARBINARY(20) NULL, ADD custom_decimal DECIMAL(18,6) NULL;
            ALTER TABLE `{source}`.character_skills ADD custom_blob VARBINARY(20) NULL, ADD custom_decimal DECIMAL(18,6) NULL;
            CREATE TABLE `{source}`.unrelated(id INT PRIMARY KEY,note TEXT);
            INSERT INTO `{source}`.unrelated VALUES(1,'Keep Ω');
            CREATE TABLE `{auth}`.account(id INT PRIMARY KEY); INSERT INTO `{auth}`.account VALUES(1);''')
        spec = importlib.util.spec_from_file_location('riding_assets',ROOT/('tests/obsolete-horse-fixtures.py'if horse else'tests/obsolete-riding-fixtures.py'))
        assets = importlib.util.module_from_spec(spec); spec.loader.exec_module(assets)
        profile = json.loads((ROOT/'compatibility/tc335-acwotlk-v2/spell-metadata.json').read_text())
        assets.seed(sql,tc,ac,world,aworld,profile)
        sql('CREATE TABLE playercreateinfo_spell_custom(racemask INT UNSIGNED,classmask INT UNSIGNED,Spell INT UNSIGNED);',world)
        sql('INSERT INTO spell_dbc(Id,EffectRealPointsPerLevel1) VALUES(900099,0.1);',world)
        for schema in (world,aworld):
            sql('CREATE TABLE playercreateinfo_skills(raceMask INT UNSIGNED,classMask INT UNSIGNED,skill SMALLINT UNSIGNED,`rank` SMALLINT UNSIGNED,comment TEXT) ENGINE=InnoDB;',schema)
            sql('CREATE TABLE item_template(entry INT UNSIGNED PRIMARY KEY,RequiredSkill INT UNSIGNED,RequiredSkillRank INT UNSIGNED,requiredspell INT UNSIGNED,description TEXT) ENGINE=InnoDB;',schema)
            sql(f"INSERT INTO item_template VALUES(10001,762,300,0,'mount'),(10002,{legacy_skill},1,0,'legacy requirement');",schema)
        for g in range(1,6):
            sql(f"INSERT INTO `{source}`.characters(guid,account,name,taximask,race,class,level,online,activeTalentGroup,talentGroupsCount,at_login,position_x,custom_decimal,created) "
                f"VALUES({g},1,'Rider{g}','',{2 if g==4 else 10},5,{20 if g==5 else 80},0,1,2,{4 if g==5 else 32},0.1,0.100001,'2010-01-02 03:04:05');")
            sql(f'INSERT INTO `{source}`.character_spell VALUES({g},{legacy_spell},1,0,0x00ff,0.100001),({g},34091,1,0,0x00ff,0.100001),({g},6603,1,0,0x00ff,0.100001);')
            sql(f'INSERT INTO `{source}`.character_skills VALUES({g},{legacy_skill},1,75,0x0001,0.100001),({g},762,300,300,0x0002,0.100002),({g},171,375,450,0x0003,0.100003);')
        sql(f"INSERT INTO `{source}`.item_instance(guid,itemEntry,owner_guid,enchantments) VALUES(101,10001,1,''),(102,10001,0,''),(103,10002,3,'');")
        sql(f'INSERT INTO `{source}`.character_inventory VALUES(1,0,23,101),(3,0,23,103);')
        sql(f"INSERT INTO `{source}`.mail(id,receiver,subject,body) VALUES(1,2,'retained mount','');")
        sql(f'INSERT INTO `{source}`.mail_items VALUES(1,102,0);')
        if invalid_items:
            sql(f"INSERT INTO `{source}`.item_instance(guid,itemEntry,owner_guid,enchantments) VALUES(104,0,1,'retained zero');")
            sql(f'INSERT INTO `{source}`.character_inventory VALUES(1,0,24,104),(1,0,25,999998);')
            sql(f"INSERT INTO `{source}`.mail(id,receiver,subject,body) VALUES(2,2,'retained missing attachment','');")
            sql(f'INSERT INTO `{source}`.mail_items VALUES(2,999997,0);')
        for user in (writer,reader):
            sql(f"CREATE USER '{user}'@'%' IDENTIFIED BY ''"); users.append(user)
            for schema in (source,auth,world,aworld): sql(f"GRANT SELECT ON `{schema}`.* TO '{user}'@'%'")
        tables = sql("SELECT CONCAT('`',TABLE_SCHEMA,'`.`',TABLE_NAME,'`') FROM information_schema.TABLES "
                     f"WHERE TABLE_SCHEMA IN ('{source}','{auth}','{world}','{aworld}') AND TABLE_TYPE='BASE TABLE' ORDER BY 1").splitlines()
        def checksum(): return sql('CHECKSUM TABLE '+','.join(tables)+' EXTENDED')
        baseline = checksum()
        with tempfile.TemporaryDirectory() as temp:
            work = Path(temp); assets.base.write_assets(work,profile)
            config = work/'cleanup.ini'
            config.write_text(f'''[workspace]
directory={work/'workspace'}
[source]
core=tc
characters={source}
auth={auth}
world={world}
player_start_all_spells=0
[target]
world={aworld}
player_start_custom_spells=0
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
backup_reference=disposable-obsolete-riding-fixture
'''); config.chmod(0o600)
            command = ['python3',str(ROOT/'console'),'--config',str(config)]
            def run(*args,code=0):
                r = subprocess.run(command+list(args),text=True,capture_output=True)
                assert r.returncode == code, r.stdout+r.stderr
                return r
            run('init','--label','obsolete-riding')
            session = work/'workspace/sessions'/json.loads((work/'workspace/current.json').read_text())['session']
            report = work/'blockers.tsv'
            report.write_text('guid\tspell\treason_code\tdetail\n'+''.join(f'{g}\t*\tAC_WOULD_DELETE_SPELL\t{legacy_spell}\n' for g in range(1,6)))
            result = run('inspect-migration-blockers','--report',str(report))
            inspection = Path(result.stdout.split('Reports: ',1)[1].strip()).name
            plan = ['plan','obsolete-riding','--migration-inspection',inspection]
            if invalid_items:
                control = run(*plan,'--preview')
                control_review = json.loads(Path(control.stdout.split('Details: ',1)[1].strip()).read_text())
                assert not control_review['selected'], control_review
                plan.append('--horse'if horse else'--native-invalid-items')
            preview = run(*plan,'--preview')
            review = json.loads(Path(preview.stdout.split('Details: ',1)[1].strip()).read_text())
            assert review['selected'] == [[1,legacy_spell,1,0],[2,legacy_spell,1,0]], review
            assert review['summary']['skill_rows_removed'] == 2
            assert {r[2] for r in review['excluded']} == {'DEFER_ITEM_REQUIRES_LEGACY_RIDING','DEFER_LEGACY_RIDING_ELIGIBLE','DEFER_PENDING_NATIVE_RESET'}
            assert not (session/'active-batch.json').exists() and checksum() == baseline
            run(*plan,'--expect-rows','3',code=2)
            run(*plan,'--expect-rows','2')
            package = session/'batches'/json.loads((session/'active-batch.json').read_text())['batch']
            manifest = json.loads((package/'manifest.json').read_text()); archive = manifest['archive_schema']; owned.append(archive)
            assert manifest['policy'] == ('tc-obsolete-horse-riding-native-invalid-items-v3'if horse else'tc-obsolete-wolf-riding-native-invalid-items-v2' if invalid_items else 'tc-obsolete-wolf-riding-spell-skill-retirement-v1')
            if invalid_items:
                assert manifest['native_invalid_items_retained'] == 3
                assert manifest['riding_items']['zero_template_counts'] == {'tc':0,'ac':0}
            run('prepare'); run('prepare'); assert checksum() == baseline
            denied = run('apply',code=2); assert 'DELETE' in denied.stderr
            sql(f"GRANT INSERT,DELETE ON `{source}`.character_spell TO '{writer}'@'%'")
            denied = run('apply',code=2); assert 'character_skills' in denied.stderr and 'DELETE/INSERT' in denied.stderr
            assert checksum() == baseline
            sql(f"GRANT INSERT,DELETE ON `{source}`.character_skills TO '{writer}'@'%'")
            ack = "SET @talent_cleanup_ack='STOPPED_PREPARATION_COPY_ONLY'; SET @eligibility_tc_all_spells=0; SET @eligibility_ac_custom_spells=0;"
            explicit = ("SET @obsolete_riding_ack='RETIRE_FORBIDDEN_HORSE_RIDING_PAIR_RETAIN_MODERN_RIDING';"if horse else "SET @obsolete_riding_ack='RETAIN_NATIVE_INVALID_ITEM_ROWS_CHECK_ALL_VALID_REQUIREMENTS';" if invalid_items
                        else "SET @obsolete_riding_ack='RETIRE_FORBIDDEN_WOLF_RIDING_PAIR_RETAIN_MODERN_RIDING';")
            def direct(extra=''):
                return subprocess.run(['mysql',*options,'--user='+writer],input=ack+extra+f'CALL `{archive}`.apply_batch();',text=True,capture_output=True)
            assert direct().returncode != 0 and checksum() == baseline
            if invalid_items:
                wrong = direct("SET @obsolete_riding_ack='RETIRE_FORBIDDEN_WOLF_RIDING_PAIR_RETAIN_MODERN_RIDING';")
                assert wrong.returncode and checksum() == baseline
                for schema in (world,aworld):
                    sql(f"INSERT INTO `{schema}`.item_template VALUES(0,0,0,0,'unexpected custom zero')")
                    changed = checksum(); denied = direct(explicit)
                    assert denied.returncode and 'no item template zero' in denied.stderr, denied.stderr
                    assert checksum() == changed
                    sql(f'DELETE FROM `{schema}`.item_template WHERE entry=0')
                for update,undo in (
                    (f'UPDATE `{source}`.item_instance SET itemEntry=777777 WHERE guid=104',f'UPDATE `{source}`.item_instance SET itemEntry=0 WHERE guid=104'),
                    (f"INSERT INTO `{source}`.item_instance(guid,itemEntry,owner_guid,enchantments) VALUES(999998,10001,0,'newly resolved')",f'DELETE FROM `{source}`.item_instance WHERE guid=999998')):
                    sql(update); changed = checksum(); denied = direct(explicit)
                    assert denied.returncode and checksum() == changed
                    sql(undo)
            for update,undo in (
                (f'UPDATE `{world}`.item_template SET RequiredSkill={legacy_skill} WHERE entry=10001',f'UPDATE `{world}`.item_template SET RequiredSkill=762 WHERE entry=10001'),
                (f'UPDATE `{aworld}`.item_template SET requiredspell={legacy_spell} WHERE entry=10001',f'UPDATE `{aworld}`.item_template SET requiredspell=0 WHERE entry=10001'),
                (f'UPDATE `{source}`.character_skills SET custom_decimal=0.100009 WHERE guid=1 AND skill={legacy_skill}',f'UPDATE `{source}`.character_skills SET custom_decimal=0.100001 WHERE guid=1 AND skill={legacy_skill}'),
                (f'INSERT INTO `{source}`.mail_items VALUES(3,103,1)',f'DELETE FROM `{source}`.mail_items WHERE mail_id=3 AND item_guid=103'),
                (f"INSERT INTO `{aworld}`.playercreateinfo_skills VALUES(0,0,{legacy_skill},0,'new route')",f'DELETE FROM `{aworld}`.playercreateinfo_skills'),
                (f'UPDATE `{world}`.spell_dbc SET EffectRealPointsPerLevel1=0.2 WHERE Id=900099',f'UPDATE `{world}`.spell_dbc SET EffectRealPointsPerLevel1=0.1 WHERE Id=900099')):
                sql(update); changed = checksum(); denied = direct(explicit)
                assert denied.returncode != 0, update
                assert checksum() == changed; sql(undo)
            assert checksum() == baseline
            sql(f"CREATE TRIGGER `{archive}`.fail_checkpoint BEFORE UPDATE ON `{archive}`.batch FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='fixture late failure'")
            run('apply',code=2); assert checksum() == baseline
            assert sql(f'SELECT state FROM `{archive}`.batch') == 'PREPARED'
            sql(f'DROP TRIGGER `{archive}`.fail_checkpoint')
            sql(f"CREATE TRIGGER `{archive}`.pause_checkpoint BEFORE UPDATE ON `{archive}`.batch FOR EACH ROW BEGIN IF NEW.state='APPLIED' THEN DO SLEEP(30); END IF; END")
            worker = subprocess.Popen(command+['apply'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            deadline,connection = time.monotonic()+15,''
            while time.monotonic() < deadline:
                if worker.poll() is not None: raise AssertionError(worker.communicate())
                connection = sql(f"SELECT ID FROM information_schema.PROCESSLIST WHERE DB='{archive}' AND STATE='User sleep' LIMIT 1")
                if connection: break
                time.sleep(.1)
            assert connection, 'Fixture did not reach atomic checkpoint'
            blocked = subprocess.run(['mysql',*options,'--user=root'],
                input=f'SET SESSION innodb_lock_wait_timeout=1; UPDATE `{aworld}`.item_template SET requiredspell={legacy_spell} WHERE entry=10001;',
                text=True,capture_output=True)
            assert blocked.returncode and ('1205' in blocked.stderr or '1213' in blocked.stderr), blocked.stderr
            sql('KILL CONNECTION '+connection); worker.communicate(timeout=10); assert worker.returncode != 0; worker = None
            assert checksum() == baseline and sql(f'SELECT state FROM `{archive}`.batch') == 'PREPARED'
            sql(f'DROP TRIGGER `{archive}`.pause_checkpoint')
            retained = [t for t in tables if t not in (f'`{source}`.`character_spell`',f'`{source}`.`character_skills`')]
            retained_hash = sql('CHECKSUM TABLE '+','.join(retained)+' EXTENDED')
            run('apply'); run('apply'); assert 'APPLIED' in run('status').stdout
            assert sql(f'SELECT COUNT(*) FROM `{source}`.character_spell WHERE guid IN (1,2) AND spell={legacy_spell}') == '0'
            assert sql(f'SELECT COUNT(*) FROM `{source}`.character_skills WHERE guid IN (1,2) AND skill={legacy_skill}') == '0'
            assert sql(f'SELECT COUNT(*) FROM `{source}`.character_skills WHERE skill=762 AND value=300 AND max=300') == '5'
            assert sql(f'SELECT COUNT(*) FROM `{source}`.character_spell WHERE spell=34091 AND active=1 AND disabled=0') == '5'
            assert sql('CHECKSUM TABLE '+','.join(retained)+' EXTENDED') == retained_hash
            sql(f'UPDATE `{source}`.character_skills SET value=299 WHERE guid=1 AND skill=762')
            changed = checksum(); run('restore',code=2); assert checksum() == changed
            sql(f'UPDATE `{source}`.character_skills SET value=300 WHERE guid=1 AND skill=762')
            run('restore'); run('restore'); assert checksum() == baseline
            run('apply',code=2)
        print('PASS obsolete riding MySQL '+('v3 Horse'if horse else'v2 native-invalid-items' if invalid_items else 'v1')+': full console preview/prepare/apply/status/restore; item and mail requirements in both worlds; missing grants; direct SQL acknowledgement and source/world/default drift; late failure and disconnected transaction rollback; concurrent item requirement write blocked; paired reruns and exact custom inverse; modern riding and all unrelated tables preserved; '+('invalid references/zero instances retained, zero-template and resolved-reference drift rejected. ' if invalid_items else '')+'Gameplay NOT TESTED.',flush=True)
    finally:
        if worker is not None and worker.poll() is None: worker.terminate(); worker.wait()
        for schema in reversed(owned): sql(f'DROP DATABASE `{schema}`')
        for user in users: sql(f"DROP USER '{user}'@'%'")


if __name__ == '__main__': main()
