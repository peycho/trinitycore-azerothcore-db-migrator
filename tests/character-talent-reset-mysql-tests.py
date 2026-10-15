#!/usr/bin/env python3
"""Rehearse the reviewed single-character pending reset policy on disposable fixtures."""
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('talent_cleanup',ROOT/'tools/plan-talent-cleanup.py')
planner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(planner)
TEMPLATE = ROOT/'tools/single-character-talent-reset.sql.in'


def render(source, archive, server_uuid):
    rows = [(1,11189,1),(1,11247,1),(1,11426,1)]
    ranks = [(11189,),(11247,),(11426,),(12296,),(12469,),(12472,)]
    values = {'SOURCE':source,'ARCHIVE':archive,'UUID':server_uuid,
        'BATCH':'b'*64,'AUDIT':'a'*64,'EXPECTED_HASH':planner.key_hash(rows),
        'RANK_HASH':planner.key_hash(ranks),'COUNT':'3','SOURCE_COUNT':'6','AFTER_COUNT':'3',
        'RANK_COUNT':str(len(ranks)),'EXPECTED_INSERT':planner.insert_values('expected',rows),
        'RANK_INSERT':planner.insert_values('valid_rank_spell',ranks),
        'GUID':'1','ACCOUNT':'1','NAME':'FixtureOne','LEVEL':'80','CLASS':'8','ACTIVE_GROUP':'0','SPEC_COUNT':'1',
        'REMOVE_GROUP':'1','RETAINED_ROWS':'2'}
    text = TEMPLATE.read_text()
    for key,value in values.items():
        text = text.replace('@'+key+'@',value)
    assert not re.search(r'@[A-Z_]+@',text)
    return text


def main():
    port = os.environ.get('REHEARSAL_MYSQL_PORT','33317')
    if (os.environ.get('MIGRATOR_DISPOSABLE_MYSQL')!='1' or not port.isascii()
            or not port.isdigit() or not 1<=int(port)<=65535 or int(port)==3306):
        raise SystemExit('Requires dedicated disposable localhost MySQL on a non-production port')
    defaults = os.environ.get('REHEARSAL_MYSQL_DEFAULTS_FILE','')
    base = ([f'--defaults-extra-file={defaults}'] if defaults else ['--no-defaults']) + [
        '--host=127.0.0.1',f'--port={int(port)}','--protocol=TCP','--batch',
        '--skip-column-names','--skip-force','--unbuffered','--default-character-set=utf8mb4']
    def client(query,user='root',okay=True):
        result = subprocess.run(['mysql',*base,'--user='+user],input=query,text=True,capture_output=True)
        assert (result.returncode==0 if okay else result.returncode!=0 and 'ERROR' in result.stderr), result.stdout+result.stderr
        return result
    def sql(query,user='root'):
        if query.startswith('CREATE TRIGGER '):
            query='DELIMITER //\n'+query+'//\nDELIMITER ;\n'
        return client(query,user).stdout.strip()
    version = sql('SELECT @@version;')
    assert version.startswith('8.4.'),version
    server_uuid = sql('SELECT @@server_uuid;')
    prefix='group_prep_'+uuid.uuid4().hex[:10]
    source,auth,world,archive=[prefix+s for s in ('_chars','_auth','_world','_archive')]
    owned=[]
    owned_user=False
    worker=None
    checks=[]
    def passed(label):
        checks.append(label)
        print('PASS '+label,flush=True)
    try:
        for schema in (source,auth,world):
            sql(f'CREATE DATABASE `{schema}`;')
            owned.append(schema)
        tc=Path(os.environ.get('TRINITYCORE_DIR',ROOT.parent/'TrinityCore'))
        sql(f'USE `{source}`;'+(tc/'sql/base/characters_database.sql').read_text())
        sql(f'''ALTER TABLE `{source}`.characters ADD createDate TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
              ADD legacy_note TEXT NULL;
            ALTER TABLE `{source}`.item_instance ADD transmog INT UNSIGNED NOT NULL DEFAULT 0;
            INSERT INTO `{source}`.characters(guid,account,name,taximask,race,class,level,online,
              activeTalentGroup,talentGroupsCount,at_login,createDate,legacy_note)
              VALUES(1,1,'FixtureOne','',1,8,80,0,0,1,32,'2010-03-04 05:06:07','Original Case Ω'),
                    (2,1,'FixtureTwo','',1,1,80,0,0,1,0,NULL,NULL);
            INSERT INTO `{source}`.character_talent VALUES
              (1,11189,1),(1,11247,1),(1,11426,1),(1,12469,0),(1,12472,0),(2,12296,0);
            INSERT INTO `{source}`.character_spell VALUES(1,6603,1,0),(1,11189,1,1),(1,11426,1,0);
            INSERT INTO `{source}`.character_skills VALUES(1,43,400,400);
            INSERT INTO `{source}`.character_glyphs(guid,talentGroup,glyph1) VALUES(1,0,123),(1,1,456);
            INSERT INTO `{source}`.character_action(guid,spec,button,action,type) VALUES(1,0,1,6603,0),(1,1,2,11426,0);
            INSERT INTO `{source}`.item_instance(guid,itemEntry,owner_guid,enchantments,transmog)
              VALUES(700,10000022,1,'Retain enchants',123);
            INSERT INTO `{source}`.mail(id,receiver,subject,body) VALUES(800,1,'Earlier recovery','Retain body');
            INSERT INTO `{source}`.mail_items VALUES(800,700,1);
            CREATE TABLE `{auth}`.account(id INT PRIMARY KEY);
            INSERT INTO `{auth}`.account VALUES(1);
            CREATE TABLE `{world}`.item_template(entry INT PRIMARY KEY);
            INSERT INTO `{world}`.item_template VALUES(10000022);''')
        sql(f"CREATE USER '{prefix}'@'%' IDENTIFIED BY ''; GRANT SELECT ON `{source}`.* TO '{prefix}'@'%';")
        owned_user=True
        tables=sql("SELECT CONCAT('`',TABLE_SCHEMA,'`.`',TABLE_NAME,'`') FROM information_schema.TABLES "
            f"WHERE TABLE_SCHEMA IN ('{source}','{auth}','{world}') AND TABLE_TYPE='BASE TABLE' ORDER BY 1").splitlines()
        def checksum(selected=tables):
            return sql('CHECKSUM TABLE '+','.join(selected)+' EXTENDED;')
        baseline=checksum()
        setup=render(source,archive,server_uuid)
        sql(setup)
        owned.append(archive)
        sql(f"GRANT ALL ON `{archive}`.* TO '{prefix}'@'%';")
        ack="SET @talent_cleanup_ack='STOPPED_PREPARATION_COPY_ONLY';\n"
        def action(name,okay=True,with_ack=True):
            return client((ack if with_ack else '')+f'CALL `{archive}`.{name}_batch();',prefix,okay)
        archive_tables=sql("SELECT CONCAT('`',TABLE_SCHEMA,'`.`',TABLE_NAME,'`') FROM information_schema.TABLES "
            f"WHERE TABLE_SCHEMA='{archive}' AND TABLE_TYPE='BASE TABLE' ORDER BY 1").splitlines()
        client(setup,okay=False)
        action('prepare',False,False)
        assert checksum()==baseline
        passed('fresh archive and explicit stopped-copy acknowledgement required; source unchanged')
        for assignment,undo in [('online=1','online=0'),('class=1','class=8'),
                ('account=2','account=1'),("name='Different'","name='FixtureOne'"),('level=70','level=80'),
                ('talentGroupsCount=2','talentGroupsCount=1'),('activeTalentGroup=1','activeTalentGroup=0')]:
            sql(f'UPDATE `{source}`.characters SET {assignment} WHERE guid=1;')
            current=checksum()
            action('prepare',False)
            assert checksum()==current and sql(f'SELECT state FROM `{archive}`.batch')=='NEW'
            sql(f'UPDATE `{source}`.characters SET {undo} WHERE guid=1;')
        passed('online, account/name/level/class, enabled second spec and changed active spec blocked before preparation')
        action('prepare')
        assert checksum()==baseline
        assert sql(f'SELECT COUNT(*) FROM `{archive}`.character_before')=='1'
        assert sql(f'SELECT COUNT(*) FROM `{archive}`.talent_before')=='5'
        assert sql(f'SELECT COUNT(*) FROM `{archive}`.talent_removed')=='3'
        assert sql(f"SELECT createDate FROM `{archive}`.character_before WHERE guid=1")=='2010-03-04 05:06:07'
        prepared=checksum(archive_tables)
        action('prepare')
        action('apply',False)
        assert checksum()==baseline and checksum(archive_tables)==prepared
        passed('SELECT-only preparation, full build/custom/timestamp snapshots, prepare rerun, DELETE privilege refusal')
        sql(f"GRANT DELETE,INSERT ON `{source}`.character_talent TO '{prefix}'@'%';")
        action('apply',False)
        assert checksum()==baseline and checksum(archive_tables)==prepared
        passed('missing login-flag UPDATE grant rolls back the preceding talent deletion')
        sql(f"GRANT UPDATE(at_login) ON `{source}`.characters TO '{prefix}'@'%';")
        def blocked(change,undo,label):
            sql(change)
            before=checksum()
            action('apply',False)
            assert checksum()==before and checksum(archive_tables)==prepared
            sql(undo)
            assert checksum()==baseline
            passed(label)
        blocked(f'UPDATE `{source}`.character_talent SET spell=11958 WHERE guid=1 AND spell=11189;',
            f'UPDATE `{source}`.character_talent SET spell=11189 WHERE guid=1 AND spell=11958;',
            'same-count unavailable build drift rejected')
        blocked(f'UPDATE `{source}`.character_talent SET spell=12571 WHERE guid=1 AND spell=12469;',
            f'UPDATE `{source}`.character_talent SET spell=12469 WHERE guid=1 AND spell=12571;',
            'same-count active build drift rejected')
        blocked(f"UPDATE `{source}`.characters SET legacy_note=LOWER(legacy_note) WHERE guid=1;",
            f"UPDATE `{source}`.characters SET legacy_note='Original Case Ω' WHERE guid=1;",
            'byte-sensitive full custom character drift rejected')
        blocked(f'ALTER TABLE `{source}`.characters ADD unexpected INT DEFAULT 0;',
            f'ALTER TABLE `{source}`.characters DROP unexpected;', 'source schema drift rejected')
        blocked(f'UPDATE `{source}`.characters SET at_login=33 WHERE guid=1;',
            f'UPDATE `{source}`.characters SET at_login=32 WHERE guid=1;', 'other login-flag drift rejected')
        sql(f'UPDATE `{archive}`.expected SET talentGroup=0 WHERE spell=11189;')
        action('apply',False)
        sql(f'UPDATE `{archive}`.expected SET talentGroup=1 WHERE spell=11189;')
        sql(f'DELETE FROM `{archive}`.valid_rank_spell WHERE spell=11189;')
        action('apply',False)
        sql(f'INSERT INTO `{archive}`.valid_rank_spell VALUES(11189);')
        assert checksum(archive_tables)==prepared
        passed('available-group selection and catalog tampering rejected')
        sql(f'CREATE TRIGGER `{source}`.unreviewed BEFORE DELETE ON `{source}`.character_talent FOR EACH ROW SET @fixture_ran=1;')
        assert 'Source triggers require separate review' in action('apply',False).stderr
        sql(f'DROP TRIGGER `{source}`.unreviewed;')
        sql(f'''CREATE TABLE `{source}`.fk_fixture(guid INT UNSIGNED,spell MEDIUMINT UNSIGNED,talentGroup TINYINT UNSIGNED,
          FOREIGN KEY(guid,spell,talentGroup) REFERENCES `{source}`.character_talent(guid,spell,talentGroup) ON DELETE CASCADE) ENGINE=InnoDB;
          INSERT INTO `{source}`.fk_fixture VALUES(1,11189,1);''')
        assert 'Talent foreign keys require separate review' in action('apply',False).stderr
        sql(f'DROP TABLE `{source}`.fk_fixture;')
        assert checksum()==baseline
        passed('hidden source triggers and foreign-key cascades blocked')
        sql(f"CREATE TRIGGER `{archive}`.late_failure BEFORE UPDATE ON `{archive}`.batch FOR EACH ROW BEGIN "
            "IF NEW.state='APPLIED' THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Injected late error'; END IF; END;")
        action('apply',False)
        assert checksum()==baseline and checksum(archive_tables)==prepared
        sql(f'DROP TRIGGER `{archive}`.late_failure;')
        passed('late apply failure rolls back deletion and state atomically')
        sql(f"CREATE TRIGGER `{archive}`.pause BEFORE UPDATE ON `{archive}`.batch FOR EACH ROW BEGIN "
            "IF NEW.state='APPLIED' THEN DO SLEEP(30); END IF; END;")
        worker=subprocess.Popen(['mysql',*base,'--user='+prefix],stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        worker.stdin.write(ack+f'SELECT CONNECTION_ID(); CALL `{archive}`.apply_batch();\n')
        worker.stdin.close()
        worker_id=worker.stdout.readline().strip()
        assert worker_id.isdigit()
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            if worker.poll() is not None:
                raise AssertionError(worker.stderr.read())
            if sql(f"SELECT ID FROM information_schema.PROCESSLIST WHERE ID={worker_id} AND STATE='User sleep'"):
                break
            time.sleep(.1)
        else:
            raise AssertionError('Interruption boundary not reached')
        sql('KILL CONNECTION '+worker_id)
        assert worker.wait(timeout=10)!=0
        assert checksum()==baseline and checksum(archive_tables)==prepared
        sql(f'DROP TRIGGER `{archive}`.pause;')
        passed('interruption after DELETE rolls back source and checkpoint')
        protected=[t for t in tables if t!=f'`{source}`.`character_talent`']
        sql(f'UPDATE `{source}`.characters SET at_login=36 WHERE guid=1;')
        expected_protected=checksum(protected)
        sql(f'UPDATE `{source}`.characters SET at_login=32 WHERE guid=1;')
        action('apply')
        assert sql(f'SELECT at_login FROM `{source}`.characters WHERE guid=1')=='36'
        assert sql(f'SELECT COUNT(*) FROM `{source}`.character_talent')=='3'
        assert sql(f'SELECT COUNT(*) FROM `{source}`.character_talent WHERE guid=1 AND talentGroup=0')=='2'
        applied,applied_archive=checksum(),checksum(archive_tables)
        action('apply')
        assert checksum()==applied and checksum(archive_tables)==applied_archive
        protected=[t for t in tables if t!=f'`{source}`.`character_talent`']
        assert checksum(protected)==expected_protected
        passed('apply/rerun queue reset bit 4, preserve other flags and active ownership for native reset, one-spec state, glyphs, action bars, spell flags, skills, items, recovery mail, auth/world')
        sql(f'UPDATE `{source}`.character_talent SET spell=12571 WHERE guid=1 AND spell=12469;')
        changed=checksum()
        action('restore',False)
        assert checksum()==changed
        sql(f'UPDATE `{source}`.character_talent SET spell=12469 WHERE guid=1 AND spell=12571;')
        passed('restore refuses changed active build')
        sql(f"CREATE TRIGGER `{archive}`.restore_failure BEFORE UPDATE ON `{archive}`.batch FOR EACH ROW BEGIN "
            "IF NEW.state='RESTORED' THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Injected late restore error'; END IF; END;")
        action('restore',False)
        assert checksum()==applied and checksum(archive_tables)==applied_archive
        sql(f'DROP TRIGGER `{archive}`.restore_failure;')
        passed('late restore error rolls back reinsertions and checkpoint')
        action('restore')
        assert checksum()==baseline
        restored=checksum(archive_tables)
        action('restore')
        action('apply',False)
        assert checksum()==baseline and checksum(archive_tables)==restored
        passed('exact restoration, rerun, retained archive and apply-after-restore refusal')
        sql(f'UPDATE `{source}`.characters SET at_login=36 WHERE guid=1;')
        queued_baseline=checksum()
        other=archive+'_queued'
        sql(render(source,other,server_uuid))
        owned.append(other)
        sql(f"GRANT ALL ON `{other}`.* TO '{prefix}'@'%';")
        for name in ('prepare','apply','apply','restore','restore'):
            client(ack+f'CALL `{other}`.{name}_batch();',prefix)
            assert sql(f'SELECT at_login FROM `{source}`.characters WHERE guid=1')=='36'
        assert checksum()==queued_baseline
        sql(f'UPDATE `{source}`.characters SET at_login=32 WHERE guid=1;')
        assert checksum()==baseline
        passed('already queued reset is idempotent; restore preserves an originally set reset flag')
        for suffix,definition in [('virtual','INT GENERATED ALWAYS AS (`level`+1) VIRTUAL'),
                ('stored','INT GENERATED ALWAYS AS (`level`+1) STORED'),('invisible','INT DEFAULT 9 INVISIBLE')]:
            sql(f'ALTER TABLE `{source}`.characters ADD unsupported {definition};')
            current=checksum()
            other=archive+'_'+suffix
            sql(render(source,other,server_uuid))
            owned.append(other)
            sql(f"GRANT ALL ON `{other}`.* TO '{prefix}'@'%';")
            rejected=client(ack+f'CALL `{other}`.prepare_batch();',prefix,False)
            assert 'unsupported generated/invisible fields' in rejected.stderr,rejected.stderr
            assert checksum()==current and sql(f'SELECT state FROM `{other}`.batch')=='NEW'
            assert sql(f'SELECT COUNT(*) FROM `{other}`.character_before')=='0'
            sql(f'ALTER TABLE `{source}`.characters DROP unsupported;')
            assert checksum()==baseline
            passed(suffix+' columns rejected even when present at setup')
        print(f'MySQL {version}: {len(checks)} single-character pending reset check groups PASS; native gameplay NOT TESTED.')
    finally:
        if worker is not None and worker.poll() is None:
            worker.kill(); worker.wait()
        if owned_user:
            sql(f"DROP USER '{prefix}'@'%';")
        for schema in reversed(owned):
            sql(f'DROP DATABASE `{schema}`;')


if __name__=='__main__':
    main()
