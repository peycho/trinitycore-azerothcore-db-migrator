#!/usr/bin/env python3
"""Exercise complete foreign skill-family retirement/inverse through the console on disposable MySQL 8.4."""
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
    training='--training-actions'in sys.argv[1:]
    if any(v!='--training-actions'for v in sys.argv[1:]):raise SystemExit('Unknown family fixture mode')
    port = os.environ.get('REHEARSAL_MYSQL_PORT','33317')
    if (os.environ.get('MIGRATOR_DISPOSABLE_MYSQL')!='1' or not port.isascii()
            or not port.isdigit() or not 1<=int(port)<=65535 or int(port)==3306):
        raise SystemExit('Requires dedicated disposable localhost MySQL on a non-production port')
    defaults = os.environ.get('REHEARSAL_MYSQL_DEFAULTS_FILE','')
    base = (['--defaults-extra-file='+defaults] if defaults else ['--no-defaults'])+[
        '--host=127.0.0.1','--port='+port,'--protocol=TCP','--batch','--raw',
        '--skip-column-names','--skip-force','--default-character-set=utf8mb4']

    def sql(query,database=None):
        if query.startswith('CREATE TRIGGER '):query='DELIMITER //\n'+query+'//\nDELIMITER ;\n'
        r=subprocess.run(['mysql',*base,'--user=root',*([database] if database else [])],input=query,text=True,capture_output=True)
        assert r.returncode==0,r.stderr
        return r.stdout.strip()

    version=sql('SELECT @@version;')
    assert version.startswith('8.4.'),version
    prefix='foreign_skills_'+uuid.uuid4().hex[:10]
    source,auth,world,aworld=[prefix+s for s in ('_chars','_auth','_world','_ac')]
    writer,reader=prefix+'_w',prefix+'_r'
    owned,users,checks,worker=[],[],[],None

    def passed(text):
        checks.append(text);print('PASS '+text,flush=True)

    try:
        for schema in (source,auth,world,aworld):
            sql(f'CREATE DATABASE `{schema}`;');owned.append(schema)
        tc=Path(os.environ.get('TRINITYCORE_DIR',ROOT.parent/'TrinityCore'))
        ac=Path(os.environ.get('AZEROTHCORE_DIR',ROOT.parent/'azerothcore-wotlk'))
        ddl=(tc/'sql/base/characters_database.sql').read_text()
        for table in ('characters','character_spell','character_talent','character_skills','character_inventory','item_instance','mail','mail_items','guild_bank_item','auctionhouse','character_aura'):
            sql(re.search(r'CREATE TABLE `'+table+r'` \(.*?\) ENGINE=[^;]+;',ddl,re.S)[0],source)
        sql(f'''ALTER TABLE `{source}`.characters ADD custom_decimal DECIMAL(18,6) NULL,
            ADD created TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP;
            ALTER TABLE `{source}`.character_spell ADD custom_blob VARBINARY(20) NULL, ADD custom_decimal DECIMAL(18,6) NULL;
            ALTER TABLE `{source}`.character_skills ADD custom_blob VARBINARY(20) NULL, ADD custom_decimal DECIMAL(18,6) NULL;
            CREATE TABLE `{source}`.unrelated(id INT PRIMARY KEY,note TEXT);
            INSERT INTO `{source}`.unrelated VALUES(1,'Keep Ω');
            CREATE TABLE `{auth}`.account(id INT PRIMARY KEY);INSERT INTO `{auth}`.account VALUES(1);''')
        spec=importlib.util.spec_from_file_location('selected_assets',ROOT/'tests/shaman-dual-wield-fixtures.py')
        assets_module=importlib.util.module_from_spec(spec);spec.loader.exec_module(assets_module);assets=assets_module.base
        if training:
            original_stores=assets.stores
            def training_stores(profile):
                data=original_stores(profile);row=[0]*len(profile['stores']['Spell']['columns']);row[0]=900098;row[4]=256;row[71]=36;row[74]=1;row[86]=25;row[116]=465;data['Spell'][900098]=row;return data
            assets.stores=training_stores
        profile=json.loads((ROOT/'compatibility/tc335-acwotlk-v2/spell-metadata.json').read_text())
        assets.seed_worlds(sql,tc,ac,world,aworld,profile)
        sql('CREATE TABLE playercreateinfo_spell_custom(racemask INT UNSIGNED,classmask INT UNSIGNED,Spell INT UNSIGNED);',world)
        sql('INSERT INTO spell_dbc(Id,EffectRealPointsPerLevel1) VALUES(900099,0.1);',world)
        for schema in (world,aworld):
            sql('CREATE TABLE playercreateinfo_skills(raceMask INT UNSIGNED,classMask INT UNSIGNED,skill SMALLINT UNSIGNED,`rank` SMALLINT UNSIGNED,comment TEXT) ENGINE=InnoDB;',schema)
            sql("INSERT INTO playercreateinfo_skills VALUES(0,40,118,0,'ordinary classes');",schema)
        for schema in(world,aworld):
            sql('CREATE TABLE item_template(entry INT UNSIGNED PRIMARY KEY,class TINYINT UNSIGNED,subclass TINYINT UNSIGNED,InventoryType TINYINT UNSIGNED,RequiredSkill INT UNSIGNED,RequiredSkillRank INT UNSIGNED,requiredspell INT UNSIGNED) ENGINE=InnoDB;',schema)
            sql('INSERT INTO item_template VALUES(1000,15,0,0,0,0,0),(1001,15,0,0,267,1,0);',schema)
        for g in range(1,7):
            sql(f"INSERT INTO `{source}`.characters(guid,account,name,taximask,race,class,level,online,activeTalentGroup,talentGroupsCount,at_login,custom_decimal) VALUES({g},1,'Family{g}','',1,{2 if g==2 else 1},80,0,0,2,{4 if g==3 else 0},0.100001);")
            sql(f'INSERT INTO `{source}`.character_spell VALUES({g},465,1,0,0x00ff,0.100001),({g},6603,1,0,0x00aa,0.100002);')
            if g!=4:sql(f'INSERT INTO `{source}`.character_skills VALUES({g},267,400,400,0x0001,0.100001);')
        sql(f'INSERT INTO `{source}`.character_spell VALUES(1,48942,1,0,0x00ff,0.100001);')
        sql(f'INSERT INTO `{source}`.character_skills VALUES(1,171,375,450,0x0002,0.100002);')
        sql(f'INSERT INTO `{source}`.character_talent VALUES(1,12282,0),(1,12664,1),(6,1234567,0);')
        sql(f"INSERT INTO `{source}`.item_instance(guid,itemEntry,owner_guid,enchantments) VALUES(100,1000,1,'preserve'),(101,1001,5,'must defer');")
        if training:
            sql(f'DELETE FROM `{source}`.character_spell WHERE guid=1 AND spell IN(465,48942);')
            sql(f'INSERT INTO `{source}`.character_spell VALUES(1,900098,1,0,0x00ff,0.100001);')
        for user in(writer,reader):
            sql(f"CREATE USER '{user}'@'%' IDENTIFIED BY '';");users.append(user)
            for schema in(source,auth,world,aworld):sql(f"GRANT SELECT ON `{schema}`.* TO '{user}'@'%';")
        tables=sql("SELECT CONCAT('`',TABLE_SCHEMA,'`.`',TABLE_NAME,'`') FROM information_schema.TABLES "+f"WHERE TABLE_SCHEMA IN ('{source}','{auth}','{world}','{aworld}') AND TABLE_TYPE='BASE TABLE' ORDER BY 1").splitlines()
        def checksum():return sql('CHECKSUM TABLE '+','.join(tables)+' EXTENDED;')
        baseline=checksum()
        with tempfile.TemporaryDirectory()as temp:
            work=Path(temp);assets.write_assets(work,profile);config=work/'cleanup.ini'
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
backup_reference=dedicated-disposable-foreign-skill-family-fixture
''');config.chmod(0o600)
            command=['python3',str(ROOT/'console'),'--config',str(config)]
            def run(*args,code=0):
                r=subprocess.run(command+list(args),text=True,capture_output=True);assert r.returncode==code,r.stdout+r.stderr;return r
            run('init','--label','foreign-skill-families');session=work/'workspace/sessions'/json.loads((work/'workspace/current.json').read_text())['session']
            report=work/'blockers.tsv';report.write_text('guid\tspell\treason_code\tdetail\n'+''.join(f'{g}\t*\tAC_WOULD_DELETE_SPELL\t465\n'for g in range(1,7)))
            result=run('inspect-migration-blockers','--report',str(report));inspection=Path(result.stdout.split('Reports: ',1)[1].strip()).name
            plan=['plan','foreign-skill-families','--migration-inspection',inspection]+(['--absent-training-actions']if training else[])
            preview=run(*plan,'--preview');review=json.loads(Path(preview.stdout.split('Details: ',1)[1].strip()).read_text())
            expected=([[1,900098,1,0]]if training else[[1,465,1,0],[1,48942,1,0]])+[[3,465,1,0],[4,465,1,0]]
            assert review['selected']==expected,review
            assert review['summary']['retired_skills']==[[1,267,400,400],[3,267,400,400]],review
            assert {r[2]for r in review['excluded']}=={'DEFER_OWNED_ITEM_REQUIRES_FAMILY','DEFER_INVALID_SELECTED_TALENT'},review
            assert checksum()==baseline and not(session/'active-batch.json').exists()
            run(*plan,'--expect-rows',str(len(expected)));package=session/'batches'/json.loads((session/'active-batch.json').read_text())['batch'];manifest=json.loads((package/'manifest.json').read_text());archive=manifest['archive_schema'];owned.append(archive)
            assert manifest['policy']==('tc-forbidden-player-training-family-retirement-v2'if training else'tc-forbidden-player-skill-family-retirement-v1')
            run('prepare');run('prepare');assert checksum()==baseline
            denied=run('apply',code=2);assert checksum()==baseline and 'DELETE'in denied.stderr
            for table in('character_spell','character_skills'):sql(f"GRANT INSERT,DELETE ON `{source}`.{table} TO '{writer}'@'%';")
            passed('complete forbidden rank families and exact stored skill keys; native eligible control, valid selected talents, absent-skill and pending-reset cases; owned item and invalid ownership defer')
            ack="SET @talent_cleanup_ack='STOPPED_PREPARATION_COPY_ONLY';SET @eligibility_tc_all_spells=0;SET @eligibility_ac_custom_spells=0;"
            extra=("SET @foreign_skill_family_ack='RETIRE_FOREIGN_FAMILIES_AND_VERIFIED_ABSENT_CHILD_TRAINING_ACTIONS';"if training else"SET @foreign_skill_family_ack='RETIRE_VERIFIED_FOREIGN_SKILL_AND_COMPLETE_PLAYERBOOK_FAMILY';")
            def direct(extra=''):
                return subprocess.run(['mysql',*base,'--user='+writer],input=ack+extra+f'CALL `{archive}`.apply_batch();',text=True,capture_output=True)
            assert direct().returncode and checksum()==baseline
            for change,undo in((f'UPDATE `{source}`.character_skills SET custom_decimal=0.100003 WHERE guid=1 AND skill=267',f'UPDATE `{source}`.character_skills SET custom_decimal=0.100001 WHERE guid=1 AND skill=267'),(f'UPDATE `{source}`.characters SET at_login=0 WHERE guid=3',f'UPDATE `{source}`.characters SET at_login=4 WHERE guid=3'),(f'INSERT INTO `{source}`.character_inventory VALUES(1,0,23,100)',f'DELETE FROM `{source}`.character_inventory WHERE item=100'),(f'UPDATE `{world}`.item_template SET RequiredSkill=267 WHERE entry=1000',f'UPDATE `{world}`.item_template SET RequiredSkill=0 WHERE entry=1000'),(f'DELETE FROM `{archive}`.expected_skills WHERE guid=1',f'INSERT INTO `{archive}`.expected_skills VALUES(1,267)')):
                sql(change);changed=checksum();denied=direct(extra);assert denied.returncode,denied.stdout;assert checksum()==changed;sql(undo)
            assert checksum()==baseline
            passed('direct SQL rejects missing family ACK, exact custom skill/source/reset drift, inventory/item requirement changes and tampered skill keys before mutation')
            sql(f"CREATE TRIGGER `{archive}`.late_fail BEFORE UPDATE ON `{archive}`.batch FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='late-checkpoint';")
            run('apply',code=2);assert checksum()==baseline and sql(f'SELECT state FROM `{archive}`.batch')=='PREPARED';sql(f'DROP TRIGGER `{archive}`.late_fail;')
            sql(f"CREATE TRIGGER `{archive}`.pause_commit BEFORE UPDATE ON `{archive}`.batch FOR EACH ROW BEGIN IF NEW.state='APPLIED' THEN DO SLEEP(30); END IF; END")
            worker=subprocess.Popen(command+['apply'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True);deadline=time.monotonic()+15;connection=''
            while time.monotonic()<deadline:
                if worker.poll()is not None:raise AssertionError(worker.communicate())
                connection=sql(f"SELECT ID FROM information_schema.PROCESSLIST WHERE DB='{archive}' AND STATE='User sleep' LIMIT 1")
                if connection:break
                time.sleep(.1)
            assert connection;blocked=subprocess.run(['mysql',*base,'--user=root'],input=f'SET SESSION innodb_lock_wait_timeout=1; UPDATE `{world}`.item_template SET RequiredSkill=267 WHERE entry=1000;',text=True,capture_output=True)
            assert blocked.returncode and('1205'in blocked.stderr or'1213'in blocked.stderr),blocked.stderr
            sql('KILL CONNECTION '+connection);worker.communicate(timeout=10);assert worker.returncode!=0;worker=None
            assert checksum()==baseline and sql(f'SELECT state FROM `{archive}`.batch')=='PREPARED';sql(f'DROP TRIGGER `{archive}`.pause_commit;')
            passed('late checkpoint and killed connection roll back every spell and skill deletion; SERIALIZABLE protects owned item requirements')
            stable=[t for t in tables if t not in(f'`{source}`.`character_spell`',f'`{source}`.`character_skills`')];stable_hash=sql('CHECKSUM TABLE '+','.join(stable)+' EXTENDED;')
            run('apply');run('apply');assert 'APPLIED'in run('status').stdout
            assert sql('CHECKSUM TABLE '+','.join(stable)+' EXTENDED;')==stable_hash
            assert sql(f'SELECT at_login FROM `{source}`.characters WHERE guid=3')=='4'
            assert sql(f'SELECT COUNT(*) FROM `{source}`.character_skills WHERE guid IN(1,3) AND skill=267')=='0'
            assert sql(f'SELECT COUNT(*) FROM `{source}`.character_skills WHERE guid=1 AND skill=171')=='1'
            assert sql(f'SELECT COUNT(*) FROM `{source}`.character_spell WHERE guid IN(2,5,6) AND spell=465')=='3'
            run('restore');run('restore');assert checksum()==baseline
            passed('apply/restore reruns and complete exact original checksums; eligible/deferred controls, selected talents, other skills, items and reset flags preserved')
        print(str(len(checks))+(' foreign training-action'if training else' complete foreign skill-family')+' MySQL test groups passed',flush=True)
    finally:
        if worker is not None and worker.poll()is None:worker.kill();worker.communicate()
        for schema in reversed(owned):sql('DROP DATABASE IF EXISTS `'+schema+'`;')
        for user in users:sql("DROP USER IF EXISTS '"+user+"'@'%';")
if __name__=='__main__':main()
