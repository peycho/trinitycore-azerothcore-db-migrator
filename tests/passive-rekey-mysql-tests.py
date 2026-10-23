#!/usr/bin/env python3
"""Exercise v5 key changes/inverse through the console on disposable MySQL 8.4."""
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
    prefix='rekey_'+uuid.uuid4().hex[:10]
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
            CREATE TABLE `{source}`.unrelated(id INT PRIMARY KEY,note TEXT);
            INSERT INTO `{source}`.unrelated VALUES(1,'Keep Ω');
            CREATE TABLE `{auth}`.account(id INT PRIMARY KEY);INSERT INTO `{auth}`.account VALUES(1);''')
        spec=importlib.util.spec_from_file_location('rekey_assets',ROOT/'tests/spell-fixtures.py')
        assets=importlib.util.module_from_spec(spec);spec.loader.exec_module(assets)
        profile=json.loads((ROOT/'compatibility/tc335-acwotlk-v2/spell-metadata.json').read_text())
        assets.seed_worlds(sql,tc,ac,world,aworld,profile)
        sql('CREATE TABLE playercreateinfo_spell_custom(racemask INT UNSIGNED,classmask INT UNSIGNED,Spell INT UNSIGNED);',world)
        sql('INSERT INTO spell_dbc(Id,EffectRealPointsPerLevel1) VALUES(900099,0.1);',world)
        expected,mappings=[],[]
        g=0
        for _,rule in sorted(profile['native_passive_ranks'].items(),key=lambda item:int(item[0])):
            for active in (0,1):
                g+=1
                lower,higher=rule['owners'][0],rule['owners'][-1]
                sql(f"INSERT INTO `{source}`.characters(guid,account,name,taximask,race,class,level,online,activeTalentGroup,talentGroupsCount,at_login,position_x,custom_decimal,created) "
                    f"VALUES({g},1,'Rekey{g}','',1,{rule['class']},80,0,{active},2,32,0.1,0.100001,'2010-01-02 03:04:05');")
                sql(f'INSERT INTO `{source}`.character_talent VALUES({g},{lower},{active}),({g},{higher},{1-active});')
                rows=[(lower,1,0),(6603,1,0)]+[(s,1,0) for s in rule['children'][-1]]
                for s,a,d in rows:sql(f'INSERT INTO `{source}`.character_spell VALUES({g},{s},{a},{d});')
                for old,new in zip(rule['children'][-1],rule['children'][0]):
                    expected.append([g,old,1,0]);mappings.append([g,old,new])
                sql(f'INSERT INTO `{source}`.character_skills VALUES({g},{134 if rule["class"]==11 else 770},400,400),({g},171,375,450);')
        expected.sort();mappings.sort()
        # Pending reset: full source scope is still guarded, but never changed.
        sql(f"INSERT INTO `{source}`.characters(guid,account,name,taximask,race,class,level,online,activeTalentGroup,talentGroupsCount,at_login) VALUES(9,1,'Pending','',1,11,80,0,0,2,4);")
        sql(f'INSERT INTO `{source}`.character_talent VALUES(9,37116,0);INSERT INTO `{source}`.character_spell VALUES(9,37116,1,0),(9,16954,1,0),(9,16961,1,0);')
        for user in (writer,reader):
            sql(f"CREATE USER '{user}'@'%' IDENTIFIED BY '';");users.append(user)
            for schema in (source,auth,world):sql(f"GRANT SELECT ON `{schema}`.* TO '{user}'@'%';")
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
[paths]
tc_dbc={work/'tc-dbc'}
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
backup_reference=dedicated-disposable-passive-rekey-fixture
''');config.chmod(0o600)
            command=['python3',str(ROOT/'console'),'--config',str(config)]

            def run(*args,code=0):
                r=subprocess.run(command+list(args),text=True,capture_output=True)
                assert r.returncode==code,r.stdout+r.stderr
                return r

            run('init','--label','passive-rekey')
            session=work/'workspace/sessions'/json.loads((work/'workspace/current.json').read_text())['session']
            report=work/'blockers.tsv'
            report.write_text('guid\tspell\treason_code\tdetail\n'+''.join(f'{g}\t*\tUNAUTHORIZED_TALENT_SPELL\t16954\n' for g in range(1,10)))
            result=run('inspect-migration-blockers','--report',str(report))
            inspection=Path(result.stdout.split('Reports: ',1)[1].strip()).name
            plan=['plan','talent-ownership','--migration-inspection',inspection,'--native-passive-rekey']
            old=run('plan','talent-ownership','--migration-inspection',inspection,'--preview')
            assert '"selected_rows": 0' in old.stdout
            preview=run(*plan,'--preview')
            review=json.loads(Path(preview.stdout.split('Details: ',1)[1].strip()).read_text())
            assert review['selected']==expected,review
            assert review['summary']['rekeys']==mappings
            assert review['summary']['selected_characters']==8 and len(expected)==14
            assert not (session/'active-batch.json').exists() and not list((session/'batches').iterdir())
            assert checksum()==baseline
            run(*plan,'--expect-rows','3',code=2)
            sql(f'UPDATE `{source}`.characters SET level=79 WHERE guid=9;')
            drift = run(*plan,'--expect-rows','14',code=2)
            assert 'HISTORY_INPUT_DRIFT' in drift.stderr,drift.stdout+drift.stderr
            sql(f'UPDATE `{source}`.characters SET level=80 WHERE guid=9;')
            passed('all four contracts, both active specs/inactive higher builds, exact known lower destinations, pending reset and deferred full-scope drift/count guards; old policy control fails')
            # A custom spell field cannot silently move to another spell ID.
            sql(f'ALTER TABLE `{source}`.character_spell ADD spell_specific_custom INT DEFAULT 0;')
            result=run('inspect-migration-blockers','--report',str(report))
            custom_inspection=Path(result.stdout.split('Reports: ',1)[1].strip()).name
            assert 'UNSUPPORTED_REKEY_COLUMNS' in run('plan','talent-ownership','--migration-inspection',custom_inspection,'--native-passive-rekey','--expect-rows','14',code=2).stderr
            sql(f'ALTER TABLE `{source}`.character_spell DROP spell_specific_custom;')
            run(*plan,'--expect-rows','14')
            package=session/'batches'/json.loads((session/'active-batch.json').read_text())['batch']
            manifest=json.loads((package/'manifest.json').read_text());archive=manifest['archive_schema'];owned.append(archive)
            assert manifest['policy']=='tc-selected-known-passive-rank-rekey-v5'
            assert manifest['rekeys']==mappings and manifest['spell_rows_rekeyed']==14
            run('prepare');run('prepare');assert checksum()==baseline
            denied=run('apply',code=2)
            assert 'UPDATE(spell)' in denied.stderr,denied.stderr
            sql(f"GRANT UPDATE (`spell`) ON `{source}`.character_spell TO '{writer}'@'%';")
            passed('custom spell columns rejected; sealed mappings, full fractional/custom character originals, repeatable preparation and column-specific UPDATE grant only')
            ack="SET @talent_cleanup_ack='STOPPED_PREPARATION_COPY_ONLY';SET @talent_ownership_ack='SELECTED_TALENTS_AUTHORITATIVE';"
            extra="SET @talent_native_rekey_ack='ONLY_ALREADY_KNOWN_SELECTED_LOWER_PASSIVES';"

            def direct(extra=''):
                return subprocess.run(['mysql',*base,'--user='+writer],input=ack+extra+f'CALL `{archive}`.apply_batch();',text=True,capture_output=True)

            for wrong in ('',"SET @talent_native_rekey_ack='WRONG';"):
                denied=direct(wrong);assert denied.returncode and 'already-known selected lower passive acknowledgement' in denied.stderr
                assert checksum()==baseline
            for update,undo,error in (
                (f'UPDATE `{source}`.characters SET custom_decimal=0.100002 WHERE guid=1',f'UPDATE `{source}`.characters SET custom_decimal=0.100001 WHERE guid=1','full-row fingerprint'),
                (f'UPDATE `{source}`.character_spell SET disabled=1 WHERE guid=1 AND spell=16954',f'UPDATE `{source}`.character_spell SET disabled=0 WHERE guid=1 AND spell=16954','full-row fingerprint'),
                (f'UPDATE `{world}`.spell_dbc SET EffectRealPointsPerLevel1=0.2 WHERE Id=900099',f'UPDATE `{world}`.spell_dbc SET EffectRealPointsPerLevel1=0.1 WHERE Id=900099','world content drift')):
                sql(update);changed=checksum();denied=direct(extra)
                assert denied.returncode and error in denied.stderr,denied.stderr
                assert checksum()==changed;sql(undo)
            sql(f'INSERT INTO `{source}`.character_spell VALUES(1,16952,1,0);')
            denied=direct(extra);assert denied.returncode and 'fingerprint' in denied.stderr
            sql(f'DELETE FROM `{source}`.character_spell WHERE guid=1 AND spell=16952;')
            sql(f'UPDATE `{archive}`.expected_rekeys SET to_spell=6603 WHERE guid=1 AND from_spell=16954;')
            denied=direct(extra);assert denied.returncode and 'mapping' in denied.stderr
            sql(f'UPDATE `{archive}`.expected_rekeys SET to_spell=16952 WHERE guid=1 AND from_spell=16954;')
            assert checksum()==baseline
            passed('direct SQL ACK, sealed mapping, destination collision, same-count source and fractional world drift guards reject before update')
            sql(f"CREATE TRIGGER `{archive}`.fail_commit BEFORE UPDATE ON `{archive}`.batch FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='rekey-late-error';")
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
            passed('late checkpoint failure and killed connection roll back key updates and state atomically')
            retained=[t for t in tables if t!=f'`{source}`.`character_spell`']
            retained_hash=sql('CHECKSUM TABLE '+','.join(retained)+' EXTENDED;')
            run('apply');run('apply');status=run('status')
            assert 'APPLIED' in status.stdout
            for g,old,new in mappings:
                assert sql(f'SELECT COUNT(*) FROM `{source}`.character_spell WHERE guid={g} AND spell={old};')=='0'
                assert sql(f'SELECT CONCAT_WS(":",active,disabled) FROM `{source}`.character_spell WHERE guid={g} AND spell={new};')=='1:0'
            assert sql('CHECKSUM TABLE '+','.join(retained)+' EXTENDED;')==retained_hash
            assert sql(f'SELECT COUNT(*) FROM `{source}`.character_spell WHERE guid=9;')=='3'
            sql(f'UPDATE `{source}`.character_spell SET active=0 WHERE guid=1 AND spell=16952;')
            changed=checksum();run('restore',code=2);assert checksum()==changed
            sql(f'UPDATE `{source}`.character_spell SET active=1 WHERE guid=1 AND spell=16952;')
            run('restore');run('restore');assert checksum()==baseline
            run('apply',code=2)
            passed('committed rerun, exact selected lower keys/flags, both builds/skills/professions/worlds/unrelated state preserved, guarded inverse and restore rerun')
        print(f'MySQL {version}: {len(checks)} passive rekey check groups PASS; native gameplay NOT TESTED.',flush=True)
    finally:
        if worker is not None and worker.poll() is None:worker.terminate();worker.wait()
        for schema in reversed(owned):sql(f'DROP DATABASE `{schema}`;')
        for user in users:sql(f"DROP USER '{user}'@'%';")


if __name__=='__main__':main()
