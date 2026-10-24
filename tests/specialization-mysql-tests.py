#!/usr/bin/env python3
"""Exercise specialization retirement/inverse through the console on disposable MySQL 8.4."""
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


def main(parent=False):
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
    prefix='specialty_'+uuid.uuid4().hex[:10]
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
        for table in ('characters','character_spell','character_talent','character_skills','character_inventory','item_instance'):
            sql(re.search(r'CREATE TABLE `'+table+r'` \(.*?\) ENGINE=[^;]+;',ddl,re.S)[0],source)
        sql(f'''ALTER TABLE `{source}`.characters ADD custom_decimal DECIMAL(18,6) NULL,
            ADD created TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP;
            ALTER TABLE `{source}`.character_spell ADD custom_blob VARBINARY(20) NULL, ADD custom_decimal DECIMAL(18,6) NULL;
            CREATE TABLE `{source}`.unrelated(id INT PRIMARY KEY,note TEXT);
            INSERT INTO `{source}`.unrelated VALUES(1,'Keep Ω');
            CREATE TABLE `{auth}`.account(id INT PRIMARY KEY);INSERT INTO `{auth}`.account VALUES(1);''')
        spec=importlib.util.spec_from_file_location('selected_assets',ROOT/'tests/specialization-fixtures.py')
        assets_module=importlib.util.module_from_spec(spec);spec.loader.exec_module(assets_module);assets=assets_module.base
        profile=json.loads((ROOT/'compatibility/tc335-acwotlk-v2/spell-metadata.json').read_text())
        assets.seed_worlds(sql,tc,ac,world,aworld,profile)
        sql('CREATE TABLE playercreateinfo_spell_custom(racemask INT UNSIGNED,classmask INT UNSIGNED,Spell INT UNSIGNED);',world)
        sql('INSERT INTO spell_dbc(Id,EffectRealPointsPerLevel1) VALUES(900099,0.1);',world)
        expected=[]
        weapon=[(17039,0,0),(17040,0,0),(17041,1,0),(9787,1,0),(51300,1,0)]
        cases={1:(weapon,[(164,441,450)],0),
               2:([(26797,0,0),(26798,1,0),(51309,1,0)],[(197,419,450)],0),
               3:(weapon,[(164,441,450)],4),
               4:([r for r in weapon if r[0]!=9787],[(164,441,450)],0),
               5:([(10656,0,0),(10660,1,0),(51302,1,0)],[(165,375,450)],0),
               6:([(20219,0,0),(20222,1,0),(51306,1,0)],[(202,375,450)],0),
               7:(weapon,[(164,441,450)],0),
               8:([(10656,0,0),(10660,1,0),(51302,1,0)],[(165,375,450)],0)}
        for g,(rows,skills,pending) in cases.items():
            sql(f"INSERT INTO `{source}`.characters(guid,account,name,taximask,race,class,level,online,activeTalentGroup,talentGroupsCount,at_login,position_x,custom_decimal,created) "
                f"VALUES({g},1,'Specialty{g}','',1,8,80,0,{int(g==2)},2,{pending or 32},0.1,0.100001,'2010-01-02 03:04:05');")
            for spell,a,d in rows+[(6603,1,0),(3275,1,0)]:
                sql(f'INSERT INTO `{source}`.character_spell VALUES({g},{spell},{a},{d},0x00ff,0.100001);')
                if g in (1,2,8) and a==0:expected.append([g,spell,a,d])
            for sk,v,cap in skills:sql(f'INSERT INTO `{source}`.character_skills VALUES({g},{sk},{v},{cap});')
        if parent:
            sql(f'ALTER TABLE `{source}`.character_spell DROP COLUMN custom_blob, DROP COLUMN custom_decimal')
            sql(f'TRUNCATE TABLE `{source}`.character_spell')
            expected=[]
            for g in range(1,9):
                rows=[(9788,0,0),(17039,0,0),(17040,0,0),(17041,1,0),(51300,1,0),(6603,1,0),(3275,1,0)]
                if g==5:rows=[(s,1 if s==17039 else a,d)for s,a,d in rows]
                for spell,a,d in rows:sql(f'INSERT INTO `{source}`.character_spell VALUES({g},{spell},{a},{d})')
                sql(f'DELETE FROM `{source}`.character_skills WHERE guid={g}')
                sql(f'INSERT INTO `{source}`.character_skills VALUES({g},164,{1 if g==4 else 441},450)')
                if g in (1,2,8):expected += [[g,spell,0,0]for spell in (9788,17039,17040)]
        expected.sort()
        # Use each real stock CREATE TABLE, not a synthetic C++ member name.
        # Native DDL spells the database column `requiredspell` in lowercase.
        for schema,definition in ((world,tc/'sql/base/dev/world_database.sql'),
                                  (aworld,ac/'data/sql/base/db_world/item_template.sql')):
            native=re.search(r'CREATE TABLE `item_template` \(.*?\) ENGINE=[^;]+;',definition.read_text(),re.S)[0]
            assert '`requiredspell`'in native and '`RequiredSpell`'not in native
            sql(native,schema)
            sql('ALTER TABLE item_template ADD custom_decimal DECIMAL(18,6) NULL;',schema)
        for g,slot,tc_req,ac_req in ((1,15,17041,17041),(5,15,10656,0),(6,15,0,20219),(7,15,0,None),(8,30,10656,10656)):
            item,entry=100+g,10000+g
            sql(f"INSERT INTO `{source}`.item_instance(guid,itemEntry,owner_guid,enchantments) VALUES({item},{entry},{g},'');")
            sql(f'INSERT INTO `{source}`.character_inventory(guid,bag,slot,item) VALUES({g},0,{slot},{item});')
            sql(f'INSERT INTO `{world}`.item_template(entry,requiredspell,custom_decimal) VALUES({entry},{tc_req},0.100001);')
            if ac_req is not None:sql(f'INSERT INTO `{aworld}`.item_template(entry,requiredspell,custom_decimal) VALUES({entry},{ac_req},0.100001);')
        if parent:
            sql(f'UPDATE `{aworld}`.item_template SET requiredspell=9788 WHERE entry=10006')
        for user in (writer,reader):
            sql(f"CREATE USER '{user}'@'%' IDENTIFIED BY '';");users.append(user)
            for schema in (source,auth,world,aworld):sql(f"GRANT SELECT ON `{schema}`.* TO '{user}'@'%';")
        tables=sql("SELECT CONCAT('`',TABLE_SCHEMA,'`.`',TABLE_NAME,'`') FROM information_schema.TABLES "
                   f"WHERE TABLE_SCHEMA IN ('{source}','{auth}','{world}','{aworld}') AND TABLE_TYPE='BASE TABLE' ORDER BY 1").splitlines()

        def checksum():return sql('CHECKSUM TABLE '+','.join(tables)+' EXTENDED;')

        baseline=checksum()
        with tempfile.TemporaryDirectory() as temp:
            work=Path(temp);assets.write_assets(work,profile)
            config=work/'cleanup.ini'
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
backup_reference=dedicated-disposable-specialization-fixture
''');config.chmod(0o600)
            command=['python3',str(ROOT/'console'),'--config',str(config)]

            def run(*args,code=0):
                r=subprocess.run(command+list(args),text=True,capture_output=True)
                assert r.returncode==code,r.stdout+r.stderr
                return r

            run('init','--label','specialization-retirement')
            session=work/'workspace/sessions'/json.loads((work/'workspace/current.json').read_text())['session']
            report=work/'blockers.tsv'
            report.write_text('guid\tspell\treason_code\tdetail\n'+''.join(f'{g}\t*\tUNAUTHORIZED_TALENT_SPELL\t12677\n' for g in range(1,9)))
            result=run('inspect-migration-blockers','--report',str(report))
            inspection=Path(result.stdout.split('Reports: ',1)[1].strip()).name

            if parent:
                sql(f'ALTER TABLE `{source}`.character_spell ADD custom_spell_state INT NOT NULL DEFAULT 0')
                result=run('inspect-migration-blockers','--report',str(report))
                custom_inspection=Path(result.stdout.split('Reports: ',1)[1].strip()).name
                error=run('plan','specialization-parent','--migration-inspection',custom_inspection,'--preview',code=2)
                assert 'UNSUPPORTED_PARENT_COLUMNS' in error.stderr,error.stderr
                sql(f'ALTER TABLE `{source}`.character_spell DROP COLUMN custom_spell_state')
                result=run('inspect-migration-blockers','--report',str(report))
                inspection=Path(result.stdout.split('Reports: ',1)[1].strip()).name
            plan=['plan','specialization-parent' if parent else 'specialization-retirement','--migration-inspection',inspection]
            old=run('plan','talent-ownership','--migration-inspection',inspection,'--preview')
            assert '"selected_rows": 0' in old.stdout
            preview=run(*plan,'--preview')
            review=json.loads(Path(preview.stdout.split('Details: ',1)[1].strip()).read_text())
            assert review['selected']==expected,review
            assert review['summary']['selected_characters']==3 and len(expected)==(9 if parent else 4)
            assert review['summary']['spell_rows_inserted']==(3 if parent else 0) and review['summary']['skill_rows_changed']==0
            assert not (session/'active-batch.json').exists() and not list((session/'batches').iterdir())
            assert checksum()==baseline
            run(*plan,'--expect-rows','3',code=2)
            sql(f'UPDATE `{source}`.characters SET level=79 WHERE guid=5;')
            drift = run(*plan,'--expect-rows','9' if parent else '4',code=2)
            assert 'HISTORY_INPUT_DRIFT' in drift.stderr,drift.stdout+drift.stderr
            sql(f'UPDATE `{source}`.characters SET level=80 WHERE guid=5;')
            passed('explicit parent restoration under retained Master Axesmith; pending-reset, low skill, ambiguous choice and TC/AC required or unknown equipped items defer' if parent else 'active choices with ordinary rank-prefix anchors; no-op preview; source unchanged; pending-reset, missing Weaponsmith, TC/AC required equipment and unknown custom templates defer')
            run(*plan,'--expect-rows','9' if parent else '4')
            package=session/'batches'/json.loads((session/'active-batch.json').read_text())['batch']
            manifest=json.loads((package/'manifest.json').read_text());archive=manifest['archive_schema'];owned.append(archive)
            assert manifest['policy']==('tc-reviewed-weaponsmith-parent-repair-v2' if parent else 'tc-inactive-competing-specialization-retirement-v1')
            assert manifest['selected_rows']==(9 if parent else 4) and manifest['spell_rows_inserted']==(3 if parent else 0)
            run('prepare');run('prepare');assert checksum()==baseline
            denied=run('apply',code=2)
            assert 'DELETE' in denied.stderr,denied.stderr
            sql(f"GRANT INSERT,DELETE ON `{source}`.character_spell TO '{writer}'@'%';")
            passed('stock spell and full custom character originals archived; source-unchanged preparation; paired DELETE/INSERT grants; no UPDATE privilege' if parent else 'full custom spell/binary/decimal originals archived; repeatable source-unchanged preparation; source writes require explicit DELETE/INSERT grants; no UPDATE privilege')
            ack="SET @talent_cleanup_ack='STOPPED_PREPARATION_COPY_ONLY';SET @talent_ownership_ack='SELECTED_TALENTS_AUTHORITATIVE';SET @eligibility_tc_all_spells=0;SET @eligibility_ac_custom_spells=0;"
            extra=("SET @specialization_retirement_ack='RESTORE_WEAPONSMITH_RETAIN_MASTER_AXESMITH_RETIRE_INACTIVE_COMPETITORS';" if parent else "SET @specialization_retirement_ack='RETIRE_INACTIVE_COMPETITORS_RETAIN_VERIFIED_ACTIVE_CHOICE';")

            def direct(extra=''):
                return subprocess.run(['mysql',*base,'--user='+writer],input=ack+extra+f'CALL `{archive}`.apply_batch();',text=True,capture_output=True)

            if parent:
                old_ack=direct("SET @specialization_retirement_ack='RETIRE_INACTIVE_COMPETITORS_RETAIN_VERIFIED_ACTIVE_CHOICE';")
                assert old_ack.returncode and checksum()==baseline
                sql(f'INSERT INTO `{source}`.character_spell VALUES(1,9787,1,0)')
                changed=checksum();denied=direct(extra)
                assert denied.returncode and 'full-row fingerprint' in denied.stderr
                assert checksum()==changed
                sql(f'DELETE FROM `{source}`.character_spell WHERE guid=1 AND spell=9787')
            for wrong in ('',"SET @specialization_retirement_ack='WRONG';"):
                denied=direct(wrong);assert denied.returncode and 'Explicit eligibility repair' in denied.stderr
                assert checksum()==baseline
            for update,undo,error in (
                (f'UPDATE `{source}`.characters SET custom_decimal=0.100002 WHERE guid=1',f'UPDATE `{source}`.characters SET custom_decimal=0.100001 WHERE guid=1','full-row fingerprint'),
                (f'UPDATE `{source}`.character_spell SET disabled=1 WHERE guid=1 AND spell=17039',f'UPDATE `{source}`.character_spell SET disabled=0 WHERE guid=1 AND spell=17039','full-row fingerprint'),
                (f'UPDATE `{world}`.spell_dbc SET EffectRealPointsPerLevel1=0.2 WHERE Id=900099',f'UPDATE `{world}`.spell_dbc SET EffectRealPointsPerLevel1=0.1 WHERE Id=900099','world content drift')):
                sql(update);changed=checksum();denied=direct(extra)
                assert denied.returncode and error in denied.stderr,denied.stderr
                assert checksum()==changed;sql(undo)
            for update,undo in (
                (f"INSERT INTO `{source}`.item_instance(guid,itemEntry,owner_guid,enchantments) VALUES(102,10001,2,''); INSERT INTO `{source}`.character_inventory(guid,bag,slot,item) VALUES(2,0,20,102)",
                 f'DELETE FROM `{source}`.character_inventory WHERE item=102; DELETE FROM `{source}`.item_instance WHERE guid=102'),
                (f'UPDATE `{world}`.item_template SET requiredspell=17039 WHERE entry=10001',f'UPDATE `{world}`.item_template SET requiredspell=17041 WHERE entry=10001'),
                (f'UPDATE `{aworld}`.item_template SET requiredspell=17040 WHERE entry=10001',f'UPDATE `{aworld}`.item_template SET requiredspell=17041 WHERE entry=10001'),
                (f'UPDATE `{source}`.character_inventory SET slot=16 WHERE guid=1 AND item=101',f'UPDATE `{source}`.character_inventory SET slot=15 WHERE guid=1 AND item=101'),
                (f'UPDATE `{source}`.character_inventory SET slot=67 WHERE guid=1 AND item=101',f'UPDATE `{source}`.character_inventory SET slot=15 WHERE guid=1 AND item=101'),
                (f'UPDATE `{source}`.item_instance SET itemEntry=10005 WHERE guid=101',f'UPDATE `{source}`.item_instance SET itemEntry=10001 WHERE guid=101')):
                sql(update);changed=checksum();denied=direct(extra)
                assert denied.returncode and 'Specialization equipped item' in denied.stderr,denied.stderr
                assert checksum()==changed
                assert 'SPECIALIZATION_EQUIPMENT_DRIFT' in run('apply',code=2).stderr
                sql(undo)
            # Resolution is case insensitive at planning, but a prepared batch
            # must still reject ANY change to its exact recorded column names.
            sql(f'ALTER TABLE `{world}`.item_template CHANGE COLUMN requiredspell RequiredSpell INT UNSIGNED NOT NULL DEFAULT 0;')
            denied=direct(extra);assert denied.returncode and 'Specialization equipment/item layout' in denied.stderr
            assert 'SPECIALIZATION_EQUIPMENT_DRIFT' in run('apply',code=2).stderr
            sql(f'ALTER TABLE `{world}`.item_template CHANGE COLUMN RequiredSpell requiredspell INT UNSIGNED NOT NULL DEFAULT 0;')
            sql(f'ALTER TABLE `{world}`.item_template ADD extra INT NOT NULL DEFAULT 0;')
            denied=direct(extra);assert denied.returncode and 'Specialization equipment/item layout' in denied.stderr
            sql(f'ALTER TABLE `{world}`.item_template DROP COLUMN extra;')
            passed('direct SQL and console reject inventory slot/instance changes, TC/AC RequiredSpell drift and item-template schema drift')
            sql(f'UPDATE `{archive}`.expected_spells SET active=1 WHERE guid=1 AND spell=17039;')
            denied=direct(extra);assert denied.returncode and 'fingerprints' in denied.stderr
            sql(f'UPDATE `{archive}`.expected_spells SET active=0 WHERE guid=1 AND spell=17039;')
            sql(f'INSERT INTO `{aworld}`.trainer_spell VALUES(99,19902);')
            denied=direct(extra);assert denied.returncode and 'world content drift' in denied.stderr
            sql(f'DELETE FROM `{aworld}`.trainer_spell WHERE TrainerId=99;')
            assert checksum()==baseline
            passed('direct SQL ACK, exact sealed selection, full source decimal and both-world/trainer drift guards reject before specialization removal')
            sql(f"CREATE TRIGGER `{archive}`.fail_commit BEFORE UPDATE ON `{archive}`.batch FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='passive-late-error';")
            run('apply',code=2);assert checksum()==baseline and sql(f'SELECT state FROM `{archive}`.batch;')=='PREPARED'
            sql(f'DROP TRIGGER `{archive}`.fail_commit;')
            sql(f"CREATE TRIGGER `{archive}`.pause_commit BEFORE UPDATE ON `{archive}`.batch FOR EACH ROW BEGIN IF NEW.state='APPLIED' THEN DO SLEEP(30); END IF; END")
            worker=subprocess.Popen(command+['apply'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            deadline,connection=time.monotonic()+15,''
            while time.monotonic()<deadline:
                if worker.poll() is not None:raise AssertionError(worker.communicate())
                connection=sql(f"SELECT ID FROM information_schema.PROCESSLIST WHERE DB='{archive}' AND STATE='User sleep' LIMIT 1;")
                if connection:break
                time.sleep(.1)
            assert connection,'Fixture did not reach checkpoint'
            if parent:
                blocked=subprocess.run(['mysql',*base,'--user=root'],input=f'SET SESSION innodb_lock_wait_timeout=1; UPDATE `{world}`.item_template SET requiredspell=9788 WHERE entry=10001;',text=True,capture_output=True)
                assert blocked.returncode and '1205' in blocked.stderr,blocked.stderr
            sql('KILL CONNECTION '+connection);worker.communicate(timeout=10);assert worker.returncode!=0;worker=None
            assert checksum()==baseline and sql(f'SELECT state FROM `{archive}`.batch;')=='PREPARED'
            sql(f'DROP TRIGGER `{archive}`.pause_commit;')
            passed('late checkpoint failure and killed connection roll back specialization removal and checkpoint atomically')
            retained=[t for t in tables if t!=f'`{source}`.`character_spell`']
            retained_hash=sql('CHECKSUM TABLE '+','.join(retained)+' EXTENDED;')
            run('apply');run('apply');status=run('status','--batch',package.name)
            assert 'APPLIED' in status.stdout
            assert ('9\t0\t9' if parent else '4\t0\t4') in status.stdout,status.stdout
            if parent:
                assert sql(f'SELECT COUNT(*) FROM `{source}`.character_spell WHERE guid IN (1,2,8) AND spell=9787 AND active=1 AND disabled=0')=='3'
                assert sql(f'SELECT COUNT(*) FROM `{source}`.character_spell WHERE spell=17041 AND active=1 AND disabled=0')=='8'
            for g,spell,_,_ in expected:
                assert sql(f'SELECT COUNT(*) FROM `{source}`.character_spell WHERE guid={g} AND spell={spell};')=='0'
            assert sql(f'SELECT COUNT(*) FROM `{source}`.character_spell WHERE spell=6603;')=='8'
            assert sql(f'SELECT COUNT(*) FROM `{source}`.character_spell WHERE spell=3275;')=='8'
            assert sql('CHECKSUM TABLE '+','.join(retained)+' EXTENDED;')==retained_hash
            assert sql(f'SELECT COUNT(*) FROM `{source}`.character_spell WHERE guid=5;')==('7' if parent else '5')
            for g,(_,skills,_) in (() if parent else cases.items()):
                for sk,v,cap in skills:
                    assert sql(f'SELECT value, max FROM `{source}`.character_skills WHERE guid={g} AND skill={sk};')==f'{v}\t{cap}'
            assert sql(f'SELECT COUNT(*) FROM `{source}`.character_spell WHERE guid=1 AND spell=3104;')=='0'
            if not parent:assert sql(f'SELECT active FROM `{source}`.character_spell WHERE guid=5 AND spell=10656;')=='0'
            sql(f'UPDATE `{source}`.characters SET custom_decimal=0.100002 WHERE guid=1;' if parent else f'UPDATE `{source}`.character_spell SET custom_decimal=0.100002 WHERE guid=1 AND spell=6603;')
            changed=checksum();run('restore',code=2);assert checksum()==changed
            sql(f'UPDATE `{source}`.characters SET custom_decimal=0.100001 WHERE guid=1;' if parent else f'UPDATE `{source}`.character_spell SET custom_decimal=0.100001 WHERE guid=1 AND spell=6603;')
            sql(f'UPDATE `{aworld}`.item_template SET requiredspell=17039 WHERE entry=10001;')
            changed=checksum();run('restore',code=2);assert checksum()==changed
            sql(f'UPDATE `{aworld}`.item_template SET requiredspell=17041 WHERE entry=10001;')
            run('restore');run('restore');assert checksum()==baseline
            run('apply',code=2)
            passed('committed rerun, only inactive competitors removed; active choices, ranks/recipes, both builds, every skill/cap, professions, worlds and unrelated state preserved; guarded full custom inverse and restore rerun')
        print(f'MySQL {version}: {len(checks)} specialization {"parent repair" if parent else "retirement"} check groups PASS; native gameplay NOT TESTED.',flush=True)
    finally:
        if worker is not None and worker.poll() is None:worker.terminate();worker.wait()
        for schema in reversed(owned):sql(f'DROP DATABASE `{schema}`;')
        for user in users:sql(f"DROP USER '{user}'@'%';")


if __name__=='__main__':
    assert sys.argv[1:] in ([],['--parent'])
    main(parent=sys.argv[1:]==['--parent'])
