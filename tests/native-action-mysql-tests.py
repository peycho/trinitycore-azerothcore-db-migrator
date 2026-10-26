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
    action=sys.argv[1]if len(sys.argv)>1 else'transient-combat'
    if action not in('forbidden-pairs-stowing','forbidden-pairs','redundant-teachers','obsolete-teachers','unusable-specializations','transient-combat'):raise SystemExit('Unknown native action fixture mode')
    sys.path.insert(0,str(ROOT/'lib'));import cleanup_native_actions as policy
    target,anchor,skill,value,cap,active={'forbidden-pairs-stowing':(42459,0,118,1,400,1),'forbidden-pairs':(42459,0,118,1,400,1),'redundant-teachers':(7415,28029,333,1,375,1),'obsolete-teachers':(6745,34091,762,300,300,1),'unusable-specializations':(9788,0,164,1,375,0),'transient-combat':(59888,0,267,400,400,1)}[action]
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
    prefix='native_actions_'+uuid.uuid4().hex[:10]
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
        spec=importlib.util.spec_from_file_location('selected_assets',ROOT/'tests/native-action-fixtures.py')
        assets_module=importlib.util.module_from_spec(spec);spec.loader.exec_module(assets_module);assets=assets_module.base
        profile=json.loads((ROOT/'compatibility/tc335-acwotlk-v2/spell-metadata.json').read_text())
        assets.seed_worlds(sql,tc,ac,world,aworld,profile)
        sql('CREATE TABLE playercreateinfo_spell_custom(racemask INT UNSIGNED,classmask INT UNSIGNED,Spell INT UNSIGNED);',world)
        sql('INSERT INTO spell_dbc(Id,EffectRealPointsPerLevel1) VALUES(900099,0.1);',world)
        for schema in (world,aworld):
            sql('CREATE TABLE playercreateinfo_skills(raceMask INT UNSIGNED,classMask INT UNSIGNED,skill SMALLINT UNSIGNED,`rank` SMALLINT UNSIGNED,comment TEXT) ENGINE=InnoDB;',schema)
            sql("INSERT INTO playercreateinfo_skills VALUES(0,40,118,0,'ordinary classes');",schema)
        for schema in(world,aworld):
            sql('CREATE TABLE item_template(entry INT UNSIGNED PRIMARY KEY,class TINYINT UNSIGNED,subclass TINYINT UNSIGNED,InventoryType TINYINT UNSIGNED,RequiredSkill INT UNSIGNED,RequiredSkillRank INT UNSIGNED,requiredspell INT UNSIGNED) ENGINE=InnoDB;',schema)
            sql(f'INSERT INTO item_template VALUES(1000,15,0,0,0,0,0),(1001,15,0,0,0,0,{target}),(1002,2,15,22,0,0,0);',schema)
        for g in range(1,7):
            sql(f"INSERT INTO `{source}`.characters(guid,account,name,taximask,race,class,level,online,activeTalentGroup,talentGroupsCount,at_login,custom_decimal) VALUES({g},1,'Action{g}','',1,{8 if action.startswith('forbidden-pairs')else 1},80,0,0,2,{4 if g==3 else 0},0.100001);")
            sql(f'INSERT INTO `{source}`.character_spell VALUES({g},6603,1,0,0x00aa,0.100002);')
            if g!=2:sql(f'INSERT INTO `{source}`.character_spell VALUES({g},{target},{active},0,0x00ff,0.100001);')
            if anchor:sql(f'INSERT INTO `{source}`.character_spell VALUES({g},{anchor},1,0,0x00cc,0.100003);')
            sql(f'INSERT INTO `{source}`.character_skills VALUES({g},{skill},{value},{cap},0x0001,0.100001);')
            if action=='obsolete-teachers':sql(f'INSERT INTO `{source}`.character_skills VALUES({g},150,1,300,0x0005,0.100005);')
        sql(f'INSERT INTO `{source}`.character_skills VALUES(1,171,375,450,0x0002,0.100002);')
        sql(f'INSERT INTO `{source}`.character_talent VALUES(6,1234567,0);')
        if not action.startswith('forbidden-pairs'):sql(f'INSERT INTO `{source}`.character_talent VALUES(1,12282,0),(1,12664,1);')
        sql(f"INSERT INTO `{source}`.item_instance(guid,itemEntry,owner_guid,enchantments) VALUES(100,1000,1,'preserve'),(101,1001,5,'must defer');")
        if action=='forbidden-pairs-stowing':
            sql(f"INSERT INTO `{source}`.item_instance(guid,itemEntry,owner_guid,enchantments) VALUES(102,1002,1,'preserve weapon');INSERT INTO `{source}`.character_inventory VALUES(1,0,16,102);")
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
            plan=['plan','native-actions','--action',action,'--migration-inspection',inspection]
            preview=run(*plan,'--preview');review=json.loads(Path(preview.stdout.split('Details: ',1)[1].strip()).read_text())
            expected=[[g,target,active,0]for g in(1,3,4)]
            assert review['selected']==expected,review
            assert review['summary']['retired_skills']==([[g,skill,value,cap]for g in(1,3,4)]if action.startswith('forbidden-pairs')else[]),review
            assert {r[2]for r in review['excluded']}=={'DEFER_OWNED_ITEM_REQUIRES_ACTION','DEFER_INVALID_SELECTED_TALENT'},review
            assert checksum()==baseline and not(session/'active-batch.json').exists()
            run(*plan,'--expect-rows',str(len(expected)));package=session/'batches'/json.loads((session/'active-batch.json').read_text())['batch'];manifest=json.loads((package/'manifest.json').read_text());archive=manifest['archive_schema'];owned.append(archive)
            assert manifest['policy']==policy.POLICIES[action][0]
            run('prepare');run('prepare');assert checksum()==baseline
            denied=run('apply',code=2);assert checksum()==baseline and 'DELETE'in denied.stderr
            for table in('character_spell','character_skills'):sql(f"GRANT INSERT,DELETE ON `{source}`.{table} TO '{writer}'@'%';")
            if action=='forbidden-pairs-stowing':sql(f"GRANT UPDATE(slot) ON `{source}`.character_inventory TO '{writer}'@'%';")
            passed('fixed native action selection with valid selected talents and pending-reset state; owned item and invalid ownership defer; every skill retained')
            ack="SET @talent_cleanup_ack='STOPPED_PREPARATION_COPY_ONLY';SET @eligibility_tc_all_spells=0;SET @eligibility_ac_custom_spells=0;"
            extra="SET @foreign_skill_family_ack='"+policy.POLICIES[action][1]+"';"
            def direct(extra=''):
                return subprocess.run(['mysql',*base,'--user='+writer],input=ack+extra+f'CALL `{archive}`.apply_batch();',text=True,capture_output=True)
            assert direct().returncode and checksum()==baseline
            if action=='forbidden-pairs-stowing':
                external=prefix+'_external';sql(f'CREATE DATABASE `{external}`');owned.append(external)
                sql(f'CREATE TABLE `{external}`.inventory_reference(guid INT UNSIGNED,bag INT UNSIGNED,slot TINYINT UNSIGNED,FOREIGN KEY(guid,bag,slot) REFERENCES `{source}`.character_inventory(guid,bag,slot) ON UPDATE CASCADE) ENGINE=InnoDB; INSERT INTO `{external}`.inventory_reference VALUES(1,0,16);')
                # Writer has no grant on this external schema. The DEFINER
                # environment guard must see inbound FKs outside its visibility.
                denied=direct(extra);assert denied.returncode and 'foreign keys'in denied.stderr,denied.stderr
                assert checksum()==baseline and sql(f'SELECT slot FROM `{external}`.inventory_reference')=='16'
                sql(f'DROP DATABASE `{external}`')
            for change,undo in((f'UPDATE `{source}`.character_skills SET custom_decimal=0.100003 WHERE guid=1 AND skill={skill}',f'UPDATE `{source}`.character_skills SET custom_decimal=0.100001 WHERE guid=1 AND skill={skill}'),(f'UPDATE `{source}`.characters SET at_login=0 WHERE guid=3',f'UPDATE `{source}`.characters SET at_login=4 WHERE guid=3'),(f'INSERT INTO `{source}`.character_inventory VALUES(1,0,23,100)',f'DELETE FROM `{source}`.character_inventory WHERE item=100'),(f'UPDATE `{world}`.item_template SET requiredspell={target} WHERE entry=1000',f'UPDATE `{world}`.item_template SET requiredspell=0 WHERE entry=1000'),((f'DELETE FROM `{archive}`.expected_skills WHERE guid=1',f'INSERT INTO `{archive}`.expected_skills VALUES(1,{skill})')if action.startswith('forbidden-pairs')else(f'INSERT INTO `{archive}`.expected_skills VALUES(1,{skill})',f'DELETE FROM `{archive}`.expected_skills WHERE guid=1'))):
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
            assert connection;blocked=subprocess.run(['mysql',*base,'--user=root'],input=f'SET SESSION innodb_lock_wait_timeout=1; UPDATE `{world}`.item_template SET requiredspell={target} WHERE entry=1000;',text=True,capture_output=True)
            assert blocked.returncode and('1205'in blocked.stderr or'1213'in blocked.stderr),blocked.stderr
            sql('KILL CONNECTION '+connection);worker.communicate(timeout=10);assert worker.returncode!=0;worker=None
            assert checksum()==baseline and sql(f'SELECT state FROM `{archive}`.batch')=='PREPARED';sql(f'DROP TRIGGER `{archive}`.pause_commit;')
            passed('late checkpoint and killed connection roll back every spell and skill deletion; SERIALIZABLE protects owned item requirements')
            stable=[t for t in tables if t not in(f'`{source}`.`character_spell`',f'`{source}`.`character_skills`',*( [f'`{source}`.`character_inventory`']if action=='forbidden-pairs-stowing'else[]))];stable_hash=sql('CHECKSUM TABLE '+','.join(stable)+' EXTENDED;')
            run('apply');run('apply');assert 'APPLIED'in run('status').stdout
            assert sql('CHECKSUM TABLE '+','.join(stable)+' EXTENDED;')==stable_hash
            assert sql(f'SELECT at_login FROM `{source}`.characters WHERE guid=3')=='4'
            assert sql(f'SELECT COUNT(*) FROM `{source}`.character_skills WHERE guid IN(1,3) AND skill={skill}')==('0'if action.startswith('forbidden-pairs')else'2')
            assert sql(f'SELECT COUNT(*) FROM `{source}`.character_skills WHERE guid=1 AND skill=171')=='1'
            assert sql(f'SELECT COUNT(*) FROM `{source}`.character_spell WHERE guid IN(1,3,4) AND spell={target}')=='0'
            assert sql(f'SELECT COUNT(*) FROM `{source}`.character_spell WHERE guid IN(5,6) AND spell={target}')=='2'
            if action=='forbidden-pairs-stowing':assert sql(f'SELECT slot FROM `{source}`.character_inventory WHERE guid=1 AND item=102')=='23'
            run('restore');run('restore');assert checksum()==baseline
            passed('apply/restore reruns and complete exact original checksums; selected talents, all skills, actual auras, items and reset flags preserved')
        print(str(len(checks))+' '+action+' MySQL test groups passed',flush=True)
    finally:
        if worker is not None and worker.poll()is None:worker.kill();worker.communicate()
        for schema in reversed(owned):sql('DROP DATABASE IF EXISTS `'+schema+'`;')
        for user in users:sql("DROP USER IF EXISTS '"+user+"'@'%';")
if __name__=='__main__':main()
