#!/usr/bin/env python3
"""Exercise redundant skill-teaching retirement/inverse through the console on disposable MySQL 8.4."""
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
    prefix='skill_teaching_'+uuid.uuid4().hex[:10]
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
        for table in ('characters','character_spell','character_talent','character_skills'):
            sql(re.search(r'CREATE TABLE `'+table+r'` \(.*?\) ENGINE=[^;]+;',ddl,re.S)[0],source)
        sql(f'''ALTER TABLE `{source}`.characters ADD custom_decimal DECIMAL(18,6) NULL,
            ADD created TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP;
            ALTER TABLE `{source}`.character_spell ADD custom_blob VARBINARY(20) NULL, ADD custom_decimal DECIMAL(18,6) NULL;
            CREATE TABLE `{source}`.unrelated(id INT PRIMARY KEY,note TEXT);
            INSERT INTO `{source}`.unrelated VALUES(1,'Keep Ω');
            CREATE TABLE `{auth}`.account(id INT PRIMARY KEY);INSERT INTO `{auth}`.account VALUES(1);''')
        spec=importlib.util.spec_from_file_location('selected_assets',ROOT/'tests/skill-teaching-fixtures.py')
        assets_module=importlib.util.module_from_spec(spec);spec.loader.exec_module(assets_module);assets=assets_module.base
        profile=json.loads((ROOT/'compatibility/tc335-acwotlk-v2/spell-metadata.json').read_text())
        assets.seed_worlds(sql,tc,ac,world,aworld,profile)
        sql('CREATE TABLE playercreateinfo_spell_custom(racemask INT UNSIGNED,classmask INT UNSIGNED,Spell INT UNSIGNED);',world)
        sql('INSERT INTO spell_dbc(Id,EffectRealPointsPerLevel1) VALUES(900099,0.1);',world)
        expected=[]
        cases=[(1,8,19902,45542,129,450,450,False),(2,9,5785,33391,762,150,150,False),
               (3,5,65286,51311,755,450,450,False),(4,9,5785,33388,762,75,75,False),
               (5,9,5785,33388,762,75,75,True),(6,8,19902,27028,129,1,375,False),
               (7,8,65286,51311,755,450,450,False)]
        for g,cls,teacher,child,skill,value,cap,pending in cases:
            sql(f"INSERT INTO `{source}`.characters(guid,account,name,taximask,race,class,level,online,activeTalentGroup,talentGroupsCount,at_login,position_x,custom_decimal,created) "
                f"VALUES({g},1,'Teacher{g}','',1,{cls},80,0,{int(g==2)},2,{4 if pending else 32},0.1,0.100001,'2010-01-02 03:04:05');")
            rows=[(teacher,1,0),(6603,1,0),(3275,1,0)]
            if g!=4:rows.append((child,1,int(g==7)))
            if cls==9:rows.append((5784,1,0))
            if g==2:rows.append((1710,1,0))
            for spell,a,d in rows:
                sql(f'INSERT INTO `{source}`.character_spell VALUES({g},{spell},{a},{d},0x00ff,0.100001);')
                if g in (1,2,3,6) and spell in (1710,5785,19902,65286):expected.append([g,spell,a,d])
            sql(f'INSERT INTO `{source}`.character_skills VALUES({g},{skill},{value},{cap}),({g},171,375,450);')
        expected.sort()
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
backup_reference=dedicated-disposable-skill-teaching-fixture
''');config.chmod(0o600)
            command=['python3',str(ROOT/'console'),'--config',str(config)]

            def run(*args,code=0):
                r=subprocess.run(command+list(args),text=True,capture_output=True)
                assert r.returncode==code,r.stdout+r.stderr
                return r

            run('init','--label','skill-teaching')
            session=work/'workspace/sessions'/json.loads((work/'workspace/current.json').read_text())['session']
            report=work/'blockers.tsv'
            report.write_text('guid\tspell\treason_code\tdetail\n'+''.join(f'{g}\t*\tUNAUTHORIZED_TALENT_SPELL\t12677\n' for g in range(1,8)))
            result=run('inspect-migration-blockers','--report',str(report))
            inspection=Path(result.stdout.split('Reports: ',1)[1].strip()).name
            plan=['plan','skill-teaching','--migration-inspection',inspection]
            old=run('plan','talent-ownership','--migration-inspection',inspection,'--preview')
            assert '"selected_rows": 0' in old.stdout
            preview=run(*plan,'--preview')
            review=json.loads(Path(preview.stdout.split('Details: ',1)[1].strip()).read_text())
            assert review['selected']==expected,review
            assert review['summary']['selected_characters']==4 and len(expected)==5
            assert review['summary']['spell_rows_inserted']==0 and review['summary']['skill_rows_changed']==0
            assert not (session/'active-batch.json').exists() and not list((session/'batches').iterdir())
            assert checksum()==baseline
            run(*plan,'--expect-rows','3',code=2)
            sql(f'UPDATE `{source}`.characters SET level=79 WHERE guid=5;')
            drift = run(*plan,'--expect-rows','5',code=2)
            assert 'HISTORY_INPUT_DRIFT' in drift.stderr,drift.stdout+drift.stderr
            sql(f'UPDATE `{source}`.characters SET level=80 WHERE guid=5;')
            passed('known direct/higher taught anchors, both active specs, wrapper retirement with exact skill/cap preservation; default-policy control, pending-reset exclusions and deferred-scope/count guards')
            run(*plan,'--expect-rows','5')
            package=session/'batches'/json.loads((session/'active-batch.json').read_text())['batch']
            manifest=json.loads((package/'manifest.json').read_text());archive=manifest['archive_schema'];owned.append(archive)
            assert manifest['policy']=='tc-redundant-skill-teaching-wrapper-retirement-v1'
            assert manifest['selected_rows']==5 and manifest['spell_rows_inserted']==0
            run('prepare');run('prepare');assert checksum()==baseline
            denied=run('apply',code=2)
            assert 'DELETE' in denied.stderr,denied.stderr
            sql(f"GRANT INSERT,DELETE ON `{source}`.character_spell TO '{writer}'@'%';")
            passed('full custom spell/binary/decimal originals archived; repeatable source-unchanged preparation; source writes require separate INSERT/DELETE grants')
            ack="SET @talent_cleanup_ack='STOPPED_PREPARATION_COPY_ONLY';SET @talent_ownership_ack='SELECTED_TALENTS_AUTHORITATIVE';SET @eligibility_tc_all_spells=0;SET @eligibility_ac_custom_spells=0;"
            extra="SET @skill_teaching_ack='RETIRE_ONLY_REDUNDANT_KNOWN_SKILL_TEACHERS';"

            def direct(extra=''):
                return subprocess.run(['mysql',*base,'--user='+writer],input=ack+extra+f'CALL `{archive}`.apply_batch();',text=True,capture_output=True)

            for wrong in ('',"SET @skill_teaching_ack='WRONG';"):
                denied=direct(wrong);assert denied.returncode and 'Explicit eligibility repair' in denied.stderr
                assert checksum()==baseline
            for update,undo,error in (
                (f'UPDATE `{source}`.characters SET custom_decimal=0.100002 WHERE guid=1',f'UPDATE `{source}`.characters SET custom_decimal=0.100001 WHERE guid=1','full-row fingerprint'),
                (f'UPDATE `{source}`.character_spell SET disabled=1 WHERE guid=1 AND spell=19902',f'UPDATE `{source}`.character_spell SET disabled=0 WHERE guid=1 AND spell=19902','full-row fingerprint'),
                (f'UPDATE `{world}`.spell_dbc SET EffectRealPointsPerLevel1=0.2 WHERE Id=900099',f'UPDATE `{world}`.spell_dbc SET EffectRealPointsPerLevel1=0.1 WHERE Id=900099','world content drift')):
                sql(update);changed=checksum();denied=direct(extra)
                assert denied.returncode and error in denied.stderr,denied.stderr
                assert checksum()==changed;sql(undo)
            sql(f'UPDATE `{archive}`.expected_spells SET active=0 WHERE guid=1 AND spell=19902;')
            denied=direct(extra);assert denied.returncode and 'fingerprints' in denied.stderr
            sql(f'UPDATE `{archive}`.expected_spells SET active=1 WHERE guid=1 AND spell=19902;')
            sql(f'INSERT INTO `{aworld}`.trainer_spell VALUES(99,19902);')
            denied=direct(extra);assert denied.returncode and 'world content drift' in denied.stderr
            sql(f'DELETE FROM `{aworld}`.trainer_spell WHERE TrainerId=99;')
            assert checksum()==baseline
            passed('direct SQL ACK, exact sealed selection, full source decimal and both-world/trainer drift guards reject before deletion')
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
            sql('KILL CONNECTION '+connection);worker.communicate(timeout=10);assert worker.returncode!=0;worker=None
            assert checksum()==baseline and sql(f'SELECT state FROM `{archive}`.batch;')=='PREPARED'
            sql(f'DROP TRIGGER `{archive}`.pause_commit;')
            passed('late checkpoint failure and killed connection roll back deletion and checkpoint atomically')
            retained=[t for t in tables if t!=f'`{source}`.`character_spell`']
            retained_hash=sql('CHECKSUM TABLE '+','.join(retained)+' EXTENDED;')
            run('apply');run('apply');status=run('status')
            assert 'APPLIED' in status.stdout
            for g,spell,_,_ in expected:
                assert sql(f'SELECT COUNT(*) FROM `{source}`.character_spell WHERE guid={g} AND spell={spell};')=='0'
            assert sql(f'SELECT COUNT(*) FROM `{source}`.character_spell WHERE spell=6603;')=='7'
            assert sql(f'SELECT COUNT(*) FROM `{source}`.character_spell WHERE spell=3275;')=='7'
            assert sql('CHECKSUM TABLE '+','.join(retained)+' EXTENDED;')==retained_hash
            assert sql(f'SELECT COUNT(*) FROM `{source}`.character_spell WHERE guid=5;')=='5'
            for g,cls,teacher,child,skill,value,cap,pending in cases:
                assert sql(f'SELECT value, max FROM `{source}`.character_skills WHERE guid={g} AND skill={skill};')==f'{value}\t{cap}'
            sql(f'UPDATE `{source}`.character_spell SET custom_decimal=0.100002 WHERE guid=1 AND spell=6603;')
            changed=checksum();run('restore',code=2);assert checksum()==changed
            sql(f'UPDATE `{source}`.character_spell SET custom_decimal=0.100001 WHERE guid=1 AND spell=6603;')
            run('restore');run('restore');assert checksum()==baseline
            run('apply',code=2)
            passed('committed rerun, only redundant wrappers removed; taught spells/recipes, both builds, every skill/cap, professions, worlds and unrelated state preserved; guarded full custom inverse and restore rerun')
        print(f'MySQL {version}: {len(checks)} redundant skill-teaching check groups PASS; native gameplay NOT TESTED.',flush=True)
    finally:
        if worker is not None and worker.poll() is None:worker.terminate();worker.wait()
        for schema in reversed(owned):sql(f'DROP DATABASE `{schema}`;')
        for user in users:sql(f"DROP USER '{user}'@'%';")


if __name__=='__main__':main()
