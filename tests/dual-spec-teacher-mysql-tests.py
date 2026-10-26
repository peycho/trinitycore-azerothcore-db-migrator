#!/usr/bin/env python3
"""Exercise unavailable dual-spec teacher retirement/inverse through the console on disposable MySQL 8.4."""
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
    prefix='dual_teacher_'+uuid.uuid4().hex[:10]
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
        for table in ('characters','character_spell','character_talent','character_skills','character_inventory'):
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
        for g in range(1,8):
            sql(f"INSERT INTO `{source}`.characters(guid,account,name,taximask,race,class,level,online,activeTalentGroup,talentGroupsCount,at_login,custom_decimal) VALUES({g},1,'Teacher{g}','',7,8,80,0,0,{2 if g==3 else 1},{0 if g==2 else 4},0.100001);")
            sql(f'INSERT INTO `{source}`.character_spell VALUES({g},63680,1,{1 if g==4 else 0},0x00ff,0.100001),({g},6603,1,0,0x00aa,0.100002);')
        sql(f'INSERT INTO `{source}`.character_spell VALUES(1,63706,1,0,0x00bb,0.100001),(1,63707,1,0,0x00cc,0.100001);')
        sql(f'INSERT INTO `{source}`.character_skills VALUES(5,183,400,400,0x00aa,0.100002);')
        sql(f'INSERT INTO `{source}`.character_spell VALUES(6,63644,1,0,0x00bb,0.100003);')
        sql(f'INSERT INTO `{source}`.character_talent VALUES(7,30798,0);')
        for user in(writer,reader):
            sql(f"CREATE USER '{user}'@'%' IDENTIFIED BY '';");users.append(user)
            for schema in(source,auth,world,aworld):sql(f"GRANT SELECT ON `{schema}`.* TO '{user}'@'%';")
        sql(f"GRANT INSERT,DELETE ON `{source}`.character_spell TO '{writer}'@'%';")
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
backup_reference=dedicated-disposable-dual-spec-teacher-fixture
''');config.chmod(0o600)
            command=['python3',str(ROOT/'console'),'--config',str(config)]
            def run(*args,code=0):
                r=subprocess.run(command+list(args),text=True,capture_output=True);assert r.returncode==code,r.stdout+r.stderr;return r
            run('init','--label','unavailable-dual-spec-teacher');session=work/'workspace/sessions'/json.loads((work/'workspace/current.json').read_text())['session']
            report=work/'blockers.tsv';report.write_text('guid\tspell\treason_code\tdetail\n'+''.join(f'{g}\t*\tUNREPRESENTABLE_TEACHER_STATE\t63680\n'for g in range(1,8)))
            result=run('inspect-migration-blockers','--report',str(report));inspection=Path(result.stdout.split('Reports: ',1)[1].strip()).name
            plan=['plan','dual-spec-teacher','--migration-inspection',inspection]
            preview=run(*plan,'--preview');review=json.loads(Path(preview.stdout.split('Details: ',1)[1].strip()).read_text())
            assert review['selected']==[[1,sp,1,0]for sp in(63680,63706,63707)],review
            assert checksum()==baseline and not(session/'active-batch.json').exists()
            run(*plan,'--expect-rows','3');package=session/'batches'/json.loads((session/'active-batch.json').read_text())['batch'];manifest=json.loads((package/'manifest.json').read_text());archive=manifest['archive_schema'];owned.append(archive)
            assert manifest['policy']=='tc-unavailable-dual-spec-teacher-retirement-v1'
            run('prepare');run('prepare');assert checksum()==baseline
            passed('only pending one-spec wrapper without Generic/buttons/invalid ownership qualifies; full original preparation does not change source')
            ack="SET @talent_cleanup_ack='STOPPED_PREPARATION_COPY_ONLY';SET @eligibility_tc_all_spells=0;SET @eligibility_ac_custom_spells=0;"
            extra="SET @spell_eligibility_ack='RETIRE_DUAL_SPEC_TEACHER_KEEP_ONE_SPEC_NO_BUTTON_GRANTS';"
            def direct(extra=''):
                return subprocess.run(['mysql',*base,'--user='+writer],input=ack+extra+f'CALL `{archive}`.apply_batch();',text=True,capture_output=True)
            denied=direct();assert denied.returncode and 'Explicit eligibility repair'in denied.stderr
            for change,undo in((f'UPDATE `{source}`.characters SET talentGroupsCount=2 WHERE guid=1',f'UPDATE `{source}`.characters SET talentGroupsCount=1 WHERE guid=1'),(f'UPDATE `{source}`.characters SET at_login=0 WHERE guid=1',f'UPDATE `{source}`.characters SET at_login=4 WHERE guid=1'),(f'INSERT INTO `{world}`.spell_learn_spell VALUES(63680,6603,1)',f'DELETE FROM `{world}`.spell_learn_spell WHERE entry=63680 AND SpellID=6603'),(f'UPDATE `{source}`.character_spell SET custom_decimal=0.100003 WHERE guid=1 AND spell=63680',f'UPDATE `{source}`.character_spell SET custom_decimal=0.100001 WHERE guid=1 AND spell=63680')):
                sql(change);changed=checksum();denied=direct(extra);assert denied.returncode;assert checksum()==changed;sql(undo)
            passed('separate direct ACK, spec/reset state, exact custom decimal and teacher dependency guards reject before mutation')
            sql(f"CREATE TRIGGER `{archive}`.late_fail BEFORE UPDATE ON `{archive}`.batch FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='late-checkpoint';")
            run('apply',code=2);assert checksum()==baseline and sql(f'SELECT state FROM `{archive}`.batch')=='PREPARED';sql(f'DROP TRIGGER `{archive}`.late_fail;')
            stable=[t for t in tables if t!=f'`{source}`.`character_spell`'];stable_hash=sql('CHECKSUM TABLE '+','.join(stable)+' EXTENDED;')
            run('apply');run('apply');assert 'APPLIED'in run('status').stdout
            assert sql('CHECKSUM TABLE '+','.join(stable)+' EXTENDED;')==stable_hash
            assert sql(f'SELECT COUNT(*) FROM `{source}`.character_spell WHERE guid=1 AND spell IN(63644,63645,63680,63706,63707)')=='0'
            assert sql(f'SELECT talentGroupsCount,at_login FROM `{source}`.characters WHERE guid=1')=='1\t4'
            run('restore');run('restore');assert checksum()==baseline
            passed('late checkpoint rollback, apply/restore reruns and full exact source inverse; no buttons, skill, second spec or completed reset introduced')
        print(str(len(checks))+' unavailable dual-spec teacher MySQL test groups passed',flush=True)
    finally:
        for schema in reversed(owned):sql('DROP DATABASE IF EXISTS `'+schema+'`;')
        for user in users:sql("DROP USER IF EXISTS '"+user+"'@'%';")
if __name__=='__main__':main()
