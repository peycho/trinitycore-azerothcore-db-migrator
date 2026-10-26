#!/usr/bin/env python3
"""Equipment-aware paired retirement, guarded inventory moves and exact inverse on isolated MySQL."""
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
    prefix='shaman_gear_'+uuid.uuid4().hex[:10]
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
        for table in ('characters','character_spell','character_talent','character_skills','character_inventory','item_instance','mail_items','guild_bank_item','auctionhouse','character_aura'):
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
        profile=json.loads((ROOT/'compatibility/tc335-acwotlk-v2/spell-metadata.json').read_text())
        assets.seed_worlds(sql,tc,ac,world,aworld,profile)
        sql('CREATE TABLE playercreateinfo_spell_custom(racemask INT UNSIGNED,classmask INT UNSIGNED,Spell INT UNSIGNED);',world)
        sql('INSERT INTO spell_dbc(Id,EffectRealPointsPerLevel1) VALUES(900099,0.1);',world)
        for schema in (world,aworld):
            sql('CREATE TABLE playercreateinfo_skills(raceMask INT UNSIGNED,classMask INT UNSIGNED,skill SMALLINT UNSIGNED,`rank` SMALLINT UNSIGNED,comment TEXT) ENGINE=InnoDB;',schema)
            sql("INSERT INTO playercreateinfo_skills VALUES(0,40,118,0,'ordinary classes');",schema)
        for schema in (world,aworld):
            sql('CREATE TABLE item_template(entry MEDIUMINT UNSIGNED PRIMARY KEY,class TINYINT UNSIGNED,subclass TINYINT UNSIGNED,InventoryType TINYINT UNSIGNED,RequiredSkill SMALLINT UNSIGNED,requiredspell MEDIUMINT UNSIGNED) ENGINE=InnoDB;',schema)
            sql('INSERT INTO item_template VALUES(100,2,13,22,0,0),(101,4,6,14,0,0);',schema)
        for g in range(1,8):
            sql(f"INSERT INTO `{source}`.characters(guid,account,name,taximask,race,class,level,online,activeTalentGroup,talentGroupsCount,at_login,custom_decimal) VALUES({g},1,'Gear{g}','',11,7,55,0,0,2,{36 if g==1 else 32},0.100001);")
            sql(f'INSERT INTO `{source}`.character_spell VALUES({g},674,1,0,0x00ff,0.100001),({g},6603,1,0,0x00aa,0.100002);')
            sql(f'INSERT INTO `{source}`.character_skills VALUES({g},118,1,275,0x0001,0.100001),({g},171,375,450,0x0002,0.100002);')
            if g!=7:
                sql(f'INSERT INTO `{source}`.character_inventory VALUES({g},0,16,{g*100});')
                sql(f"INSERT INTO `{source}`.item_instance(guid,owner_guid,itemEntry,enchantments,text) VALUES({g*100},{g if g!=6 else 1},{101 if g==2 else 100},'exact enchantments','exact item text Ω');")
        sql(f'INSERT INTO `{source}`.character_skills VALUES(2,433,1,1,0x0003,0.100003);')
        sql(f'INSERT INTO `{source}`.character_talent VALUES(5,30798,1);')
        for g,end in ((3,39),(4,67)):
            for slot in range(23,end):sql(f'INSERT INTO `{source}`.character_inventory VALUES({g},0,{slot},{g*10000+slot});')
        for user in (writer,reader):
            sql(f"CREATE USER '{user}'@'%' IDENTIFIED BY '';");users.append(user)
            for schema in (source,auth,world,aworld):sql(f"GRANT SELECT ON `{schema}`.* TO '{user}'@'%';")
        for table in ('character_spell','character_skills'):sql(f"GRANT INSERT,DELETE ON `{source}`.{table} TO '{writer}'@'%';")
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
backup_reference=dedicated-disposable-shaman-equipment-fixture
''');config.chmod(0o600)
            command=['python3',str(ROOT/'console'),'--config',str(config)]
            def run(*args,code=0):
                r=subprocess.run(command+list(args),text=True,capture_output=True)
                assert r.returncode==code,r.stdout+r.stderr
                return r
            run('init','--label','shaman-offhand')
            session=work/'workspace/sessions'/json.loads((work/'workspace/current.json').read_text())['session']
            report=work/'blockers.tsv';report.write_text('guid\tspell\treason_code\tdetail\n'+''.join(f'{g}\t*\tUNAUTHORIZED_TALENT_SPELL\t674\n'for g in range(1,8)))
            result=run('inspect-migration-blockers','--report',str(report));inspection=Path(result.stdout.split('Reports: ',1)[1].strip()).name
            plan=['plan','talent-ownership','--migration-inspection',inspection,'--reconcile-shaman-offhand']
            preview=run(*plan,'--preview');review=json.loads(Path(preview.stdout.split('Details: ',1)[1].strip()).read_text())
            assert review['selected']==[[g,674,1,0]for g in(1,2,3,7)],review
            assert review['summary']['inventory_moves']==[[1,100,16,23],[3,300,16,39]],review
            assert checksum()==baseline and not(session/'active-batch.json').exists()
            run(*plan,'--expect-rows','4');package=session/'batches'/json.loads((session/'active-batch.json').read_text())['batch']
            manifest=json.loads((package/'manifest.json').read_text());archive=manifest['archive_schema'];owned.append(archive)
            assert manifest['policy']=='tc-unselected-shaman-offhand-reconciliation-v2'
            run('prepare');run('prepare');assert checksum()==baseline
            denied=run('apply',code=2);assert 'UPDATE' in denied.stderr and checksum()==baseline,denied.stderr
            sql(f"GRANT UPDATE(slot) ON `{source}`.character_inventory TO '{writer}'@'%';")
            passed('preview chooses native backpack/bank moves and retains shield/empty hand; full storage, invalid ownership and selected talents defer; preparation unchanged and explicit inventory grant required')
            ack="SET @talent_cleanup_ack='STOPPED_PREPARATION_COPY_ONLY';SET @eligibility_tc_all_spells=0;SET @eligibility_ac_custom_spells=0;"
            extra="SET @shaman_dual_wield_ack='RETIRE_UNSELECTED_DUAL_WIELD_STOW_WEAPON_RETAIN_SHIELD';"
            def direct(extra=''):
                return subprocess.run(['mysql',*base,'--user='+writer],input=ack+extra+f'CALL `{archive}`.apply_batch();',text=True,capture_output=True)
            denied=direct();assert denied.returncode and 'Explicit eligibility repair' in denied.stderr
            drifts=[
                (f'UPDATE `{source}`.item_instance SET owner_guid=2 WHERE guid=100',f'UPDATE `{source}`.item_instance SET owner_guid=1 WHERE guid=100','hand item'),
                (f'UPDATE `{source}`.character_inventory SET slot=24 WHERE item=100',f'UPDATE `{source}`.character_inventory SET slot=16 WHERE item=100','inventory fingerprint'),
                (f'INSERT INTO `{source}`.character_inventory VALUES(1,0,23,9999)',f'DELETE FROM `{source}`.character_inventory WHERE item=9999','inventory fingerprint'),
                (f'INSERT INTO `{source}`.mail_items(mail_id,item_guid,receiver) VALUES(1,100,1)',f'DELETE FROM `{source}`.mail_items WHERE item_guid=100','hand item'),
                (f'INSERT INTO `{source}`.character_aura(guid,casterGuid,itemGuid,spell) VALUES(1,1,4611686018427388004,6603)',f'DELETE FROM `{source}`.character_aura WHERE guid=1','hand item'),
                (f'UPDATE `{world}`.item_template SET requiredspell=674 WHERE entry=100',f'UPDATE `{world}`.item_template SET requiredspell=0 WHERE entry=100','hand item'),
                (f'UPDATE `{aworld}`.item_template SET RequiredSkill=118 WHERE entry=100',f'UPDATE `{aworld}`.item_template SET RequiredSkill=0 WHERE entry=100','hand item'),
                (f'UPDATE `{source}`.characters SET at_login=32 WHERE guid=1',f'UPDATE `{source}`.characters SET at_login=36 WHERE guid=1','full-row fingerprint'),
                (f'UPDATE `{archive}`.expected_moves SET new_slot=24 WHERE guid=1',f'UPDATE `{archive}`.expected_moves SET new_slot=23 WHERE guid=1','move keys'),
            ]
            for change,undo,error in drifts:
                sql(change);changed=checksum();denied=direct(extra)
                assert denied.returncode and error in denied.stderr,denied.stderr
                assert checksum()==changed;sql(undo)
            assert checksum()==baseline
            passed('direct SQL rejects missing ACK, changed item owner/template/aura/placement, occupied destination, reset flags and tampered move mapping')
            sql(f"CREATE TRIGGER `{archive}`.late_fail BEFORE UPDATE ON `{archive}`.batch FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='late-checkpoint';")
            run('apply',code=2);assert checksum()==baseline and sql(f'SELECT state FROM `{archive}`.batch')=='PREPARED'
            sql(f'DROP TRIGGER `{archive}`.late_fail;')
            sql(f"CREATE TRIGGER `{archive}`.pause_commit BEFORE UPDATE ON `{archive}`.batch FOR EACH ROW BEGIN IF NEW.state='APPLIED' THEN DO SLEEP(30); END IF; END")
            worker=subprocess.Popen(command+['apply'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            deadline=time.monotonic()+15;connection=''
            while time.monotonic()<deadline:
                if worker.poll()is not None:raise AssertionError(worker.communicate())
                connection=sql(f"SELECT ID FROM information_schema.PROCESSLIST WHERE DB='{archive}' AND STATE='User sleep' LIMIT 1")
                if connection:break
                time.sleep(.1)
            assert connection,'Checkpoint not reached'
            blocked=subprocess.run(['mysql',*base,'--user=root'],input=f'SET SESSION innodb_lock_wait_timeout=1; INSERT INTO `{source}`.character_inventory VALUES(1,0,23,9999);',text=True,capture_output=True)
            assert blocked.returncode and ('1205'in blocked.stderr or'1213'in blocked.stderr),blocked.stderr
            sql('KILL CONNECTION '+connection);worker.communicate(timeout=10);assert worker.returncode!=0;worker=None
            assert checksum()==baseline and sql(f'SELECT state FROM `{archive}`.batch')=='PREPARED'
            sql(f'DROP TRIGGER `{archive}`.pause_commit;')
            passed('late checkpoint error and disconnected transaction roll back both retired rows and moved items; SERIALIZABLE protects destination slot')
            unchanged=[t for t in tables if not any(t==f'`{source}`.`{name}`'for name in('character_spell','character_skills','character_inventory'))]
            stable=sql('CHECKSUM TABLE '+','.join(unchanged)+' EXTENDED;')
            run('apply');run('apply');assert 'APPLIED'in run('status').stdout
            assert sql(f'SELECT slot FROM `{source}`.character_inventory WHERE item=100')=='23'
            assert sql(f'SELECT slot FROM `{source}`.character_inventory WHERE item=300')=='39'
            assert sql(f'SELECT slot FROM `{source}`.character_inventory WHERE item=200')=='16'
            assert sql(f'SELECT at_login FROM `{source}`.characters WHERE guid=1')=='36'
            assert sql('CHECKSUM TABLE '+','.join(unchanged)+' EXTENDED;')==stable
            assert sql(f'SELECT COUNT(*) FROM `{source}`.character_skills WHERE skill=118')=='3'
            # Live and archived placement changes invalidate restoration.
            for change,undo in ((f'UPDATE `{source}`.character_inventory SET slot=24 WHERE item=100',f'UPDATE `{source}`.character_inventory SET slot=23 WHERE item=100'),(f'UPDATE `{archive}`.inventory_before SET slot=17 WHERE item=100',f'UPDATE `{archive}`.inventory_before SET slot=16 WHERE item=100')):
                sql(change);changed=checksum();run('restore',code=2);assert checksum()==changed;sql(undo)
            run('restore');run('restore');assert checksum()==baseline
            passed('guarded apply/restore reruns preserve full custom main-table and item data, shield and pending flags; exact original inventory/source checksums restored')
        print(str(len(checks))+' equipment-aware Shaman MySQL test groups passed',flush=True)
    finally:
        if worker is not None and worker.poll()is None:worker.kill();worker.communicate()
        for schema in reversed(owned):sql('DROP DATABASE IF EXISTS `'+schema+'`;')
        for user in users:sql("DROP USER IF EXISTS '"+user+"'@'%';")

if __name__=='__main__':main()
