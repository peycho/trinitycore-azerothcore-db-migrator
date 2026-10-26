#!/usr/bin/env python3
"""Test source auditing against dirty native TC fixtures on disposable MySQL."""
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]


def main():
    port = os.environ.get('REHEARSAL_MYSQL_PORT','33317')
    if (os.environ.get('MIGRATOR_DISPOSABLE_MYSQL') != '1' or not port.isascii()
            or not port.isdigit() or not 1 <= int(port) <= 65535 or int(port) == 3306):
        raise SystemExit('Requires a dedicated disposable localhost MySQL and a non-production port')
    defaults = os.environ.get('REHEARSAL_MYSQL_DEFAULTS_FILE','')
    mysql = ([f'--defaults-extra-file={defaults}'] if defaults else ['--no-defaults']) + [
        '--host=127.0.0.1',f'--port={int(port)}','--protocol=TCP','--user=root','--batch','--skip-column-names']
    def sql(query):
        result = subprocess.run(['mysql',*mysql],input=query,text=True,capture_output=True)
        if result.returncode:
            raise AssertionError(result.stderr)
        return result.stdout.strip()
    version = sql('SELECT @@version;')
    assert version.startswith('8.4.'), version
    prefix = 'migrator_audit_' + uuid.uuid4().hex[:12]
    chars,auth,world = [prefix+suffix for suffix in ['_chars','_auth','_world']]
    owned,owned_user = [],False
    try:
        for schema in [chars,auth,world]:
            sql(f'CREATE DATABASE `{schema}`;')
            owned.append(schema)
        sql(f"CREATE USER '{prefix}'@'%' IDENTIFIED BY '';")
        owned_user=True
        for schema in owned:
            sql(f"GRANT SELECT ON `{schema}`.* TO '{prefix}'@'%';")
        tc = Path(os.environ.get('TRINITYCORE_DIR',ROOT.parent/'TrinityCore'))
        sql(f'USE `{chars}`;'+(tc/'sql/base/characters_database.sql').read_text())
        sql(f'USE `{auth}`;'+(tc/'sql/base/auth_database.sql').read_text())
        sql(f'USE `{auth}`;'+(ROOT/'tests/fixtures/auth-data.sql').read_text())
        source=(tc/'sql/base/dev/world_database.sql').read_text()
        ddl=re.search(r'CREATE TABLE `spell_dbc` \(.*?\) ENGINE=[^;]+;',source,re.S)[0]
        sql(f'USE `{world}`;'+ddl+';CREATE TABLE item_template(entry INT PRIMARY KEY);'
            'CREATE TABLE quest_template(ID INT PRIMARY KEY);INSERT INTO spell_dbc(Id) VALUES (900099);')
        sql(f'''USE `{chars}`;
            INSERT INTO characters(guid,account,name,taximask,race,class,talentGroupsCount,activeTalentGroup)
              VALUES(1,1,'AuditWarrior','',1,1,1,0),(2,1,'AuditDruid','',4,11,1,0);
            INSERT INTO character_talent VALUES(1,130,0),(1,442,0),(1,27,0),(1,12664,0),(999,12664,0);
            INSERT INTO character_spell VALUES(1,6603,1,0),(1,12296,1,1),(1,999999,1,0),
              (1,900099,1,0),(2,9634,1,0),(2,5209,1,0);
            INSERT INTO character_skills VALUES(1,183,500,400),(2,134,400,400);
            INSERT INTO character_inventory VALUES(999,0,23,1000),(1,0,23,2000);
            INSERT INTO item_instance(guid,itemEntry,owner_guid,enchantments) VALUES(2000,1001,1,'');
            INSERT INTO mail(id,receiver,subject,body) VALUES(1,1,'Keep this mail','Unrelated retained payload');
            INSERT INTO mail_items VALUES(1,2000,1);
        ''')
        tables = sql("SELECT CONCAT('`',TABLE_SCHEMA,'`.`',TABLE_NAME,'`') FROM information_schema.TABLES "
                     f"WHERE TABLE_SCHEMA IN ('{chars}','{auth}','{world}') AND TABLE_TYPE='BASE TABLE' ORDER BY 1").splitlines()
        checksum_query='CHECKSUM TABLE '+','.join(tables)+' EXTENDED;'
        before=sql(checksum_query)
        with tempfile.TemporaryDirectory() as directory:
            work=Path(directory)
            spec=importlib.util.spec_from_file_location('audit_fixture',ROOT/'tests/spell-fixtures.py')
            fixture=importlib.util.module_from_spec(spec); spec.loader.exec_module(fixture)
            profile=json.loads((ROOT/'compatibility/tc335-acwotlk-v2/spell-metadata.json').read_text())
            fixture.write_assets(work,profile)
            reader=['--no-defaults','--host=127.0.0.1',f'--port={int(port)}','--protocol=TCP',f'--user={prefix}']
            spec=importlib.util.spec_from_file_location('source_audit',ROOT/'tools/audit-tc-source.py')
            auditor=importlib.util.module_from_spec(spec); spec.loader.exec_module(auditor)
            # Interleave an administrator's fixture edit with two reads in
            # the audit's one transaction. The second read must see old data.
            db=auditor.AuditDatabase(auditor.mysql_arguments(reader))
            stream=db.rows('snapshot-test',f'''SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ;
                START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY;
                SELECT body FROM `{chars}`.mail WHERE id=1;
                DO SLEEP(1);
                SELECT body FROM `{chars}`.mail WHERE id=1;
                ROLLBACK;''')
            assert next(stream)==['Unrelated retained payload']
            sql(f"UPDATE `{chars}`.mail SET body='Concurrent fixture edit' WHERE id=1;")
            assert list(stream)==[['Unrelated retained payload']]
            sql(f"UPDATE `{chars}`.mail SET body='Unrelated retained payload' WHERE id=1;")
            def run(output,scope='all',world_schema=world,auth_schema=auth):
                return subprocess.run([sys.executable,str(ROOT/'tools/audit-tc-source.py'),
                    '--characters-schema',chars,'--auth-schema',auth_schema,'--world-schema',world_schema,
                    '--tc-dbc',str(work/'tc-dbc'),'--output',str(output),'--scope',scope,'--mysql',*reader],
                    text=True,capture_output=True)
            output=work/'full'
            result=run(output)
            assert result.returncode==1,result.stdout+result.stderr
            status=json.loads((output/'audit.json').read_text())
            assert status['status']=='COMPLETE',status
            assert status['cleanup_approval']==status['migration_approval']=='NOT_GRANTED'
            import csv
            with (output/'findings.tsv').open() as stream:
                rows=list(csv.DictReader(stream,delimiter='\t'))
            assert sum(row['reason_code']=='TALENT_VALUE_IS_NOT_RANK_SPELL' for row in rows)==3
            for reason in ['UNKNOWN_SPELL_ID','DISABLED_UNOWNED_TALENT_HISTORY','SKILL_VALUE_EXCEEDS_CAP',
                           'ITEM_MULTIPLE_ROOT_REFERENCES','CHILD_WITHOUT_CHARACTER','MISSING_PARENT','ITEM_TEMPLATE_MISSING']:
                assert any(row['reason_code']==reason for row in rows),reason
            assert not any(row['table']=='character_spell' and row['source_key'] in ['1:900099','2:9634','2:5209'] for row in rows)
            assert not any(row['reason_code'].startswith('UNSUPPORTED_') for row in rows)
            assert output.stat().st_mode & 0o777==0o700
            assert all(path.stat().st_mode & 0o077==0 for path in output.iterdir())
            assert subprocess.run(['sha256sum','--check','SHA256SUMS'],cwd=output,capture_output=True).returncode==0
            original=(output/'audit.json').read_bytes()
            assert run(output).returncode==2
            assert (output/'audit.json').read_bytes()==original
            partial=work/'partial'
            result=run(partial,world_schema=prefix+'_absent')
            assert result.returncode==2,result.stdout+result.stderr
            assert json.loads((partial/'audit.json').read_text())['status']=='COMPLETE_WITH_LIMITATIONS'
            assert 'UNKNOWN_SPELL_ID' not in (partial/'findings.tsv').read_text()
            sql(f'ALTER TABLE `{world}`.item_template ENGINE=MyISAM;')
            mixed=work/'mixed-engines'
            result=run(mixed)
            assert result.returncode==2,result.stdout+result.stderr
            assert any('Non-InnoDB input' in item for item in json.loads((mixed/'audit.json').read_text())['limitations'])
            sql(f'ALTER TABLE `{world}`.item_template ENGINE=InnoDB;')
            result=run(work/'talents',scope='talents')
            assert result.returncode==1,result.stdout+result.stderr
            assert 'UNKNOWN_SPELL_ID' not in (work/'talents/findings.tsv').read_text()
            # Character-state preparation must work without inventing auth rows;
            # the final all-scope audit still refuses this missing evidence.
            scoped=work/'character-state'
            result=run(scoped,scope='character-state',auth_schema=prefix+'_absent_auth')
            assert result.returncode==1,result.stdout+result.stderr
            state_status=json.loads((scoped/'audit.json').read_text())
            assert state_status['status']=='COMPLETE' and state_status['scope']=='character-state'
            assert set(state_status['audited_input_rows'])=={'characters','character_talent','character_spell','character_skills'}
            assert set(state_status['dbc_sha256'])=={'Spell.dbc','Talent.dbc','TalentTab.dbc','SkillLine.dbc'}
            scoped_findings=(scoped/'findings.tsv').read_text()
            assert 'SKILL_VALUE_EXCEEDS_CAP' in scoped_findings and 'UNKNOWN_SPELL_ID' in scoped_findings
            assert 'MISSING_PARENT' not in scoped_findings
            final=work/'full-missing-auth'
            assert run(final,auth_schema=prefix+'_absent_auth').returncode==2
            assert 'COMPLETE_WITH_LIMITATIONS'==json.loads((final/'audit.json').read_text())['status']
            result=subprocess.run(['mysql',*reader,'-e',f'DELETE FROM `{chars}`.character_spell;'],text=True,capture_output=True)
            assert result.returncode!=0 and '1142' in result.stderr
            assert sql(checksum_query)==before,'Auditing changed source/world data'
            assert sql(f'SELECT body FROM `{chars}`.mail WHERE id=1')=='Unrelated retained payload'
        print(f'MySQL {version}: full and focused source audits, all invalid talent rows, custom spells, missing coverage, private reports and immutability passed.')
    finally:
        for schema in owned:
            sql(f'DROP DATABASE `{schema}`;')
        if owned_user:
            sql(f"DROP USER '{prefix}'@'%';")


if __name__=='__main__':
    main()
