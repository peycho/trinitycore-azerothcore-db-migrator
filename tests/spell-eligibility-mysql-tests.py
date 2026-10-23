#!/usr/bin/env python3
"""Eligibility policy through the real console and isolated MySQL 8.4 transactions."""
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


def main(pet_teaching=False,reviewed_cower=False,absent_teachers=False,ordinary_training=False,reviewed_racials=False):
    assert not reviewed_racials or not(pet_teaching or absent_teachers or ordinary_training)
    assert not ordinary_training or not (pet_teaching or absent_teachers)
    assert not absent_teachers or not pet_teaching
    assert not reviewed_cower or pet_teaching
    port = os.environ.get('REHEARSAL_MYSQL_PORT', '33317')
    if (os.environ.get('MIGRATOR_DISPOSABLE_MYSQL') != '1' or not port.isascii() or not port.isdigit()
            or not 1 <= int(port) <= 65535 or int(port) == 3306):
        raise SystemExit('Requires dedicated disposable localhost MySQL on a non-production port')
    defaults = os.environ.get('REHEARSAL_MYSQL_DEFAULTS_FILE', '')
    base = (['--defaults-extra-file='+defaults] if defaults else ['--no-defaults']) + [
        '--host=127.0.0.1', '--port='+str(int(port)), '--protocol=TCP', '--batch', '--raw',
        '--skip-column-names', '--skip-force', '--default-character-set=utf8mb4']
    def sql(query, user='root', ok=True):
        if query.startswith('CREATE TRIGGER '):
            query = 'DELIMITER //\n'+query+'//\nDELIMITER ;\n'
        result = subprocess.run(['mysql', *base, '--user='+user], input=query, text=True, capture_output=True)
        if ok:
            assert result.returncode == 0, result.stderr
        else:
            assert result.returncode != 0, result.stdout
        return result.stdout.strip() if ok else result.stderr
    version = sql('SELECT @@version;')
    assert version.startswith('8.4.'), version
    kind = 'disabled-spell-history' if ordinary_training else 'pet-teaching' if pet_teaching else 'spell-eligibility'
    label = 'reviewed-racials' if reviewed_racials else 'training-prerequisites' if ordinary_training else 'absent-teachers' if absent_teachers else 'reviewed-cower' if reviewed_cower else 'pet-teaching' if pet_teaching else 'eligibility'
    prefix = 'eligibility_'+uuid.uuid4().hex[:10]
    source, auth, tcworld, acworld = [prefix+s for s in ('_chars','_auth','_tc','_ac')]
    writer, reader = prefix+'_w', prefix+'_r'
    owned, users, worker = [], [], None
    tc = Path(os.environ.get('TRINITYCORE_DIR', ROOT.parent/'TrinityCore'))
    ac = Path(os.environ.get('AZEROTHCORE_DIR', ROOT.parent/'azerothcore-wotlk'))
    profile = json.loads((ROOT/'compatibility/tc335-acwotlk-v2/spell-metadata.json').read_text())
    try:
        for schema in (source, auth, tcworld, acworld):
            sql(f'CREATE DATABASE `{schema}`;')
            owned.append(schema)
        sql(f'USE `{source}`;'+(tc/'sql/base/characters_database.sql').read_text())
        world_sql = (tc/'sql/base/dev/world_database.sql').read_text()
        for table in ('spell_dbc','spell_ranks','spell_required','spell_learn_spell','spell_script_names',
                      'spell_custom_attr','playercreateinfo_spell_custom'):
            ddl = re.search(r'CREATE TABLE `'+table+r'` \(.*?\) ENGINE=[^;]+;', world_sql, re.S)[0]
            sql(f'USE `{tcworld}`;'+ddl)
        target_tables = sorted({s['table'] for s in profile['stores'].values()} |
                               {'spell_ranks','spell_required','spell_script_names','spell_custom_attr','trainer_spell'})
        for table in target_tables:
            text = (ac/'data/sql/base/db_world'/f'{table}.sql').read_text()
            ddl = re.search(r'CREATE TABLE `'+table+r'` \(.*?\) ENGINE=[^;]+;', text, re.S)[0]
            sql(f'USE `{acworld}`;'+ddl)
        sql(f'''ALTER TABLE `{source}`.character_spell ADD custom_blob VARBINARY(20) NULL,
                ADD custom_decimal DECIMAL(18,6) NULL;
            ALTER TABLE `{source}`.characters ADD legacy_note TEXT NULL;
            CREATE TABLE `{auth}`.account(id INT PRIMARY KEY); INSERT INTO `{auth}`.account VALUES(1);
            INSERT INTO `{source}`.characters(guid,account,name,taximask,race,class,level,online,activeTalentGroup,talentGroupsCount,at_login,legacy_note)
            VALUES(1,1,'ForeignChain','',1,1,80,0,0,2,32,'Retain Ω'),
                  (2,1,'EligibleCtrl','',1,2,80,0,1,2,0,NULL),
                  (3,1,'ResetDefer','',1,1,80,0,0,1,4,NULL),
                  (4,1,'SkillDefer','',1,1,80,0,0,1,0,NULL),
                  (5,1,'UpperOnly','',1,1,80,0,1,2,0,NULL);
            INSERT INTO `{source}`.character_spell(guid,spell,active,disabled,custom_blob) VALUES
                (1,465,0,0,0x00ff),(1,48942,1,0,0xff00),(1,6603,1,0,0x1234),
                (2,48942,1,0,NULL),(3,48942,1,0,NULL),(4,48942,1,0,NULL),(5,48942,1,0,0x1122);
            INSERT INTO `{source}`.character_talent VALUES(1,12282,0),(1,12664,1);
            INSERT INTO `{source}`.character_skills VALUES(1,171,375,450),(4,267,1,400);
            INSERT INTO `{source}`.character_action(guid,spec,button,action,type) VALUES(1,0,1,465,0);
            INSERT INTO `{source}`.item_instance(guid,itemEntry,owner_guid,enchantments) VALUES(700,10000022,1,'Keep custom item');
            INSERT INTO `{acworld}`.trainer_spell(TrainerId,SpellId) VALUES(1,6603);
            UPDATE `{source}`.characters SET position_x=0.1 WHERE guid=1;
            UPDATE `{source}`.character_spell SET custom_decimal=0.100001 WHERE guid=1 AND spell=6603;
            INSERT INTO `{tcworld}`.spell_dbc(Id,EffectRealPointsPerLevel1) VALUES(900099,0.1);
            INSERT INTO `{acworld}`.spell_dbc(ID,Speed) VALUES(900099,0.1);''')
        if reviewed_racials:
            sql(f"UPDATE `{source}`.characters SET race=3 WHERE guid=2")
            sql(f"UPDATE `{source}`.characters SET race=2 WHERE guid=5")
            sql(f"UPDATE `{source}`.character_spell SET spell=28875 WHERE spell=465")
            sql(f"UPDATE `{source}`.character_spell SET spell=59224 WHERE spell=48942")
            sql(f"UPDATE `{source}`.character_spell SET spell=20597 WHERE guid=5 AND spell=59224")
            sql(f"UPDATE `{source}`.character_skills SET skill=101 WHERE guid=4")
        if ordinary_training:
            sql(f"UPDATE `{source}`.characters SET class=5 WHERE guid IN(1,2,3,4)")
            sql(f"UPDATE `{source}`.characters SET class=11 WHERE guid=5")
            sql(f"UPDATE `{source}`.character_spell SET spell=25312,disabled=IF(guid=2,0,1) WHERE spell=48942")
            sql(f"UPDATE `{source}`.character_spell SET spell=32999,disabled=1 WHERE spell=465")
            sql(f"UPDATE `{source}`.character_spell SET spell=16811 WHERE guid=5 AND spell=25312")
            sql(f"INSERT INTO `{source}`.character_spell(guid,spell,active,disabled) VALUES(4,14752,1,0)")
            sql(f"UPDATE `{source}`.character_talent SET spell=34914 WHERE spell=12282")
            sql(f"UPDATE `{source}`.character_talent SET spell=900000 WHERE spell=12664")
            sql(f"INSERT INTO `{tcworld}`.playercreateinfo_spell_custom(racemask,classmask,Spell) VALUES(0,16,48073),(0,16,48074),(0,1024,53308),(0,1024,53312),(0,0,6603)")
            sql(f"INSERT INTO `{source}`.character_spell(guid,spell,active,disabled) VALUES(4,6603,1,1)")
        if absent_teachers:
            sql(f"UPDATE `{source}`.character_spell SET spell=18540 WHERE guid=5 AND spell=48942")
            sql(f"INSERT INTO `{tcworld}`.spell_learn_spell VALUES(20700,18540,1)")
        if pet_teaching:
            sql(f"UPDATE `{source}`.characters SET class=3 WHERE guid IN (1,3,4,5);")
            sql(f"UPDATE `{source}`.character_spell SET spell=1747 WHERE spell=465;")
            sql(f"UPDATE `{source}`.character_spell SET spell=1749 WHERE spell=48942;")
            sql(f"UPDATE `{source}`.character_talent SET spell=900050 WHERE spell=12282;")
            sql(f"UPDATE `{source}`.character_talent SET spell=900051 WHERE spell=12664;")
            sql(f"INSERT INTO `{source}`.character_spell(guid,spell,active,disabled) VALUES(4,1754,1,0);")
            sql(f"INSERT INTO `{source}`.character_pet(id,entry,owner,PetType,level,abdata) VALUES(77,2850,1,1,80,'1754'),(78,2850,5,1,80,'27053');")
            sql(f"INSERT INTO `{source}`.pet_spell VALUES(77,1754,1),(78,27053,1);")
        spec = importlib.util.spec_from_file_location('assets', ROOT/'tests/spell-fixtures.py')
        assets = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(assets)
        if ordinary_training:
            sys.path.insert(0,str(ROOT/'lib'))
            training_spec=importlib.util.spec_from_file_location('training_assets',ROOT/'tests/ordinary-training-fixtures.py')
            training_assets=importlib.util.module_from_spec(training_spec);training_spec.loader.exec_module(training_assets)
            original_training=assets.stores
            assets.stores=lambda p:training_assets.extend(original_training(p),p)
        if reviewed_racials:
            racial_spec=importlib.util.spec_from_file_location('racial_assets',ROOT/'tests/racial-eligibility-fixtures.py')
            racial_assets=importlib.util.module_from_spec(racial_spec);racial_spec.loader.exec_module(racial_assets)
            original_racials=assets.stores
            assets.stores=lambda p:racial_assets.extend(original_racials(p),p)
        if absent_teachers:
            sys.path.insert(0,str(ROOT/'lib'))
            teacher_spec=importlib.util.spec_from_file_location('teacher_assets',ROOT/'tests/eligibility-teacher-fixtures.py')
            teacher_assets=importlib.util.module_from_spec(teacher_spec);teacher_spec.loader.exec_module(teacher_assets)
            original_teachers=assets.stores
            assets.stores=lambda p:teacher_assets.extend(original_teachers(p),p)
        if pet_teaching:
            sys.path.insert(0,str(ROOT/'lib'))
            pet_spec=importlib.util.spec_from_file_location('pet_assets',ROOT/'tests/pet-teaching-fixtures.py')
            pet_assets=importlib.util.module_from_spec(pet_spec);pet_spec.loader.exec_module(pet_assets)
            original=assets.stores
            assets.stores=lambda p:pet_assets.cower(pet_assets.extend(original(p),p)) if reviewed_cower else pet_assets.extend(original(p),p)
            from cleanup_pet_teaching import CONTRACTS
            values=','.join(f'({root},{spell},{rank})' for root,pairs in CONTRACTS.items()
                            for rank,(spell,_) in enumerate(pairs,1))
        else:
            values = ','.join(f'(465,{s},{n})' for n,s in enumerate(assets.CHAINS[0],1))
        if ordinary_training:
            from cleanup_ordinary_history import TRAINING_CHAINS
            values=','.join(f'({root},{spell},{rank})' for root,chain in TRAINING_CHAINS.items()for rank,spell in enumerate(chain,1))
        for schema in (tcworld, acworld):
            sql(f'INSERT INTO `{schema}`.spell_ranks VALUES '+values)
        if ordinary_training:
            for schema in (tcworld,acworld):
                sql(f'INSERT INTO `{schema}`.spell_required VALUES(27681,14752)')
                for parent,child in zip(TRAINING_CHAINS[339],TRAINING_CHAINS[16689]):
                    sql(f'INSERT INTO `{schema}`.spell_required VALUES({child},{parent})')
        if reviewed_cower:
            sql(f"INSERT INTO `{tcworld}`.spell_script_names VALUES(1742,'spell_hun_pet_cower');")
            sql(f"INSERT INTO `{acworld}`.spell_script_names VALUES(1742,'spell_hun_cower');")
        for user in (writer, reader):
            sql(f"CREATE USER '{user}'@'%' IDENTIFIED BY '';")
            users.append(user)
            for schema in (source, auth, tcworld, acworld):
                sql(f"GRANT SELECT ON `{schema}`.* TO '{user}'@'%';")
        tables = sql("SELECT CONCAT('`',TABLE_SCHEMA,'`.`',TABLE_NAME,'`') FROM information_schema.TABLES "
                     f"WHERE TABLE_SCHEMA IN ('{source}','{auth}','{tcworld}','{acworld}') AND TABLE_TYPE='BASE TABLE' ORDER BY 1").splitlines()
        checksum = lambda: sql('CHECKSUM TABLE '+','.join(tables)+' EXTENDED;')
        unrelated = [t for t in tables if t != f'`{source}`.`character_spell`']
        baseline = checksum()
        preserved = sql('CHECKSUM TABLE '+','.join(unrelated)+' EXTENDED;')
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            assets.write_assets(work, profile)
            config = work/'cleanup.ini'
            text = f'''[workspace]
directory=workspace
[source]
characters={source}
auth={auth}
world={tcworld}
player_start_all_spells=0
[target]
world={acworld}
player_start_custom_spells=0
[paths]
tc_dbc=tc-dbc
ac_dbc=ac-dbc
tc_source={tc}
ac_source={ac}
[mysql]
host=127.0.0.1
port={port}
user={writer}
password=
[mysql_audit]
user={reader}
password=
[mysql_admin]
user=root
password=
defaults_file={defaults}
[safety]
preparation_copy=yes
writers_stopped=yes
backup_reference=disposable-synthetic-fixture
'''
            config.write_text(text)
            config.chmod(0o600)
            command = ['python3', str(ROOT/'console'), '--config', str(config)]
            def run(*args, code=0):
                result = subprocess.run(command+list(args), text=True, capture_output=True)
                assert result.returncode == code, result.stdout+result.stderr
                return result
            run('init', '--label', label)
            session = work/'workspace/sessions'/json.loads((work/'workspace/current.json').read_text())['session']
            report = work/'blockers.tsv'
            report.write_text('guid\tspell\treason_code\tdetail\n'+''.join(
                f'{g}\t*\tAC_WOULD_DELETE_SPELL\t48942: captured fixture scope\n' for g in range(1,6)))
            run('inspect-migration-blockers', '--report', str(report))
            plan = ('plan',kind,'--migration-inspection','latest') + (('--reviewed-racials',) if reviewed_racials else ('--training-prerequisites',) if ordinary_training else ('--reviewed-cower',) if reviewed_cower else ('--absent-teachers',) if absent_teachers else ())
            if ordinary_training:
                for setting in ('','1'):
                    config.write_text(text.replace('player_start_all_spells=0','player_start_all_spells='+setting))
                    assert 'ORDINARY_HISTORY_CONFIG_REQUIRED' in run(*plan,'--preview',code=2).stderr
            else:
                config.write_text(text.replace('[target]\nworld='+acworld, '[target]\nworld='+source))
                assert 'ELIGIBILITY_TARGET_OVERLAP' in run(*plan,'--preview',code=2).stderr
                config.write_text(text.replace('[target]\nworld='+acworld+'\nplayer_start_custom_spells=0',
                                               '[target]\nworld='+acworld+'\nplayer_start_custom_spells='))
                assert 'ELIGIBILITY_CONFIG_REQUIRED' in run(*plan,'--preview',code=2).stderr
            config.write_text(text)
            if ordinary_training:
                control=run('plan','disabled-spell-history','--migration-inspection','latest','--preview')
                assert '"selected_rows": 0' in control.stdout
            if reviewed_racials:
                control=run('plan','spell-eligibility','--migration-inspection','latest','--preview')
                assert '"selected_rows": 0' in control.stdout
            if absent_teachers:
                control=run('plan','spell-eligibility','--migration-inspection','latest','--preview')
                assert '"selected_rows": 2' in control.stdout
            if reviewed_cower:
                control=run('plan','pet-teaching','--migration-inspection','latest','--preview')
                assert '"selected_rows": 0' in control.stdout
            preview=run(*plan, '--preview')
            if ordinary_training:
                assert '"selected_rows": 3' in preview.stdout
                assert '"selected_custom_default_rows": 3' in preview.stdout
                assert '"DEFER_CUSTOM_DEFAULT_ROUTE": 1' in preview.stdout
            assert not (session/'active-batch.json').exists() and not list((session/'batches').glob('*'))
            assert checksum() == baseline
            count_flag='--expect-review-rows' if ordinary_training else '--expect-rows'
            expected_count='6' if ordinary_training else '3'
            run(*plan,count_flag,'2',code=2)
            sql(f'UPDATE `{source}`.characters SET level=79 WHERE guid=2')
            changed=checksum()
            assert 'HISTORY_INPUT_DRIFT' in run(*plan,count_flag,expected_count,code=2).stderr
            assert checksum()==changed
            sql(f'UPDATE `{source}`.characters SET level=80 WHERE guid=2')
            run(*plan,count_flag,expected_count)
            package=session/'batches'/json.loads((session/'active-batch.json').read_text())['batch']
            manifest=json.loads((package/'manifest.json').read_text())
            archive=manifest['archive_schema'];owned.append(archive)
            if ordinary_training:
                assert manifest['policy']=='tc-disabled-ordinary-training-prerequisites-v4'
                assert manifest['numeric_fingerprint']=='EXACT_FRACTIONAL_V1'
                assert len(manifest['training_prerequisite_proofs'])==3
                assert manifest['selected_custom_default_rows']==3
                assert all(p['inactive_custom_default_spells'] for p in manifest['training_prerequisite_proofs'])
                assert json.loads((package/'ordinary-training-proof.json').read_text())==manifest['training_prerequisite_proofs']
            if reviewed_racials:
                assert manifest['policy']=='tc-ineligible-reviewed-racial-spell-repair-v3'
                assert manifest['racial_ack']=='RETIRE_ONLY_REVIEWED_WRONG_RACE_RACIALS'
                assert manifest['racial_catalog_sha256']
            if absent_teachers:
                assert manifest['policy']=='tc-ineligible-ordinary-absent-teacher-repair-v2'
                assert manifest['absent_teacher_ack']=='VERIFIED_TEACHERS_ABSENT'
            if reviewed_cower:
                assert manifest['policy']=='tc-pet-teaching-reviewed-cower-retirement-v2'
                assert json.loads((package/'cower-native-contract.json').read_text())==manifest['cower_native_contract']
            assert manifest['selected_rows']==3 and manifest['enabled_rows_removed']==(0 if ordinary_training else 3)
            assert manifest['excluded_reason_counts']==(
                {'DEFER_PENDING_NATIVE_RESET':1,'DEFER_PET_ABILITY_IN_PLAYER_BOOK':1,'DEFER_PET_TEACHER_CHARACTER_STATE':1}
                if pet_teaching else {'DEFER_PENDING_NATIVE_RESET':1,'DEFER_ENABLED_RELATED_SPELL':1,'DEFER_CUSTOM_DEFAULT_ROUTE':1}
                if ordinary_training else {'DEFER_PENDING_NATIVE_RESET':1,'DEFER_EXISTING_ASSOCIATED_SKILL':1})
            if not ordinary_training:
                assert json.loads((package/('pet-teaching-native-proof.json' if pet_teaching else 'eligibility-native-proof.json')).read_text())
            run('prepare');run('prepare');assert checksum()==baseline
            assert 'DELETE on character_spell' in run('apply',code=2).stderr
            sql(f"GRANT DELETE,INSERT ON `{source}`.character_spell TO '{writer}'@'%';")
            ack="SET @talent_cleanup_ack='STOPPED_PREPARATION_COPY_ONLY'; SET @spell_eligibility_ack='RETIRE_VERIFIED_INELIGIBLE_SPELLS'; SET @eligibility_tc_all_spells=0;SET @eligibility_ac_custom_spells=0;"
            if ordinary_training:
                ack="SET @talent_cleanup_ack='STOPPED_PREPARATION_COPY_ONLY'; SET @ordinary_history_all_spells=0;"
                for wrong in ('',"SET @ordinary_training_ack='UNKNOWN';"):
                    error=sql(ack+wrong+f'CALL `{archive}`.apply_batch();',writer,False)
                    assert 'Explicit reviewed ordinary training prerequisites' in error
                    assert checksum()==baseline
                ack+="SET @ordinary_training_ack='REVIEWED_TRAINING_PREREQUISITES_ONLY';"
            if reviewed_racials:
                without_racial_ack=ack
                ack+="SET @eligibility_racials_ack='RETIRE_ONLY_REVIEWED_WRONG_RACE_RACIALS';"
                for wrong in ('',"SET @eligibility_racials_ack='UNKNOWN';"):
                    error=sql(without_racial_ack+wrong+f'CALL `{archive}`.apply_batch();',writer,False)
                    assert 'Explicit reviewed racial retirement' in error
                    assert checksum()==baseline
                catalog=ROOT/'lib/cleanup_racial_catalog.json'
                original_catalog=catalog.read_bytes()
                try:
                    catalog.write_bytes(original_catalog+b' ')
                    assert 'RACIAL_POLICY_DRIFT' in run('apply',code=2).stderr
                    assert checksum()==baseline
                finally:catalog.write_bytes(original_catalog)
            if absent_teachers:
                without_teacher_ack=ack
                ack+="SET @eligibility_absent_teachers_ack='VERIFIED_TEACHERS_ABSENT';"
                for wrong in ('',"SET @eligibility_absent_teachers_ack='UNKNOWN';"):
                    error=sql(without_teacher_ack+wrong+f'CALL `{archive}`.apply_batch();',writer,False)
                    assert 'Explicit absent-teacher eligibility' in error
                    assert checksum()==baseline
            if pet_teaching:
                ack="SET @talent_cleanup_ack='STOPPED_PREPARATION_COPY_ONLY'; SET @pet_teaching_ack='RETIRE_VERIFIED_PET_TEACHERS'; SET @pet_teaching_tc_all_spells=0; SET @pet_teaching_ac_custom_spells=0;"
            if reviewed_cower:
                without_cower_ack=ack
                ack+="SET @pet_teaching_cower_ack='REVIEWED_COWER_CHILD_ONLY';"
                error=sql(without_cower_ack+f'CALL `{archive}`.apply_batch();',writer,False)
                assert 'Explicit reviewed Cower child' in error
                assert checksum()==baseline
                error=sql(ack+f"SET @pet_teaching_cower_ack='UNKNOWN';CALL `{archive}`.apply_batch();",writer,False)
                assert 'Explicit reviewed Cower child' in error
            ack_label='Explicit reviewed ordinary training prerequisites' if ordinary_training else 'Explicit pet-teaching repair' if pet_teaching else 'Explicit eligibility repair'
            error=sql(f"SET @talent_cleanup_ack='STOPPED_PREPARATION_COPY_ONLY';CALL `{archive}`.apply_batch();",writer,False)
            assert ('Explicit reviewed racial retirement' if reviewed_racials else 'Explicit reviewed Cower child' if reviewed_cower else 'Explicit absent-teacher eligibility' if absent_teachers else ack_label) in error
            for variable in (('ordinary_history_all_spells',) if ordinary_training else ('pet_teaching_tc_all_spells','pet_teaching_ac_custom_spells') if pet_teaching else ('eligibility_tc_all_spells','eligibility_ac_custom_spells')):
                error=sql(ack+f"SET @{variable}='UNKNOWN'; CALL `{archive}`.apply_batch();",writer,False)
                assert ('Explicit PlayerStart.AllSpells=0' if ordinary_training else ack_label) in error
            if reviewed_cower:
                sql(f"UPDATE `{acworld}`.spell_script_names SET ScriptName='spell_unknown' WHERE spell_id=1742")
                changed=checksum()
                assert 'ELIGIBILITY_TARGET_DRIFT' in run('apply',code=2).stderr
                assert 'world content drift' in sql(ack+f'CALL `{archive}`.apply_batch();',writer,False)
                assert checksum()==changed
                sql(f"UPDATE `{acworld}`.spell_script_names SET ScriptName='spell_hun_cower' WHERE spell_id=1742")
            if absent_teachers:
                # A newly stored disabled teacher invalidates the complete source proof.
                sql(f'INSERT INTO `{source}`.character_spell(guid,spell,active,disabled) VALUES(5,20700,1,1)')
                changed=checksum();run('apply',code=2)
                assert 'full-row fingerprint differs' in sql(ack+f'CALL `{archive}`.apply_batch();',writer,False)
                assert checksum()==changed
                sql(f'DELETE FROM `{source}`.character_spell WHERE guid=5 AND spell=20700')
                for schema,effect_field,child_field in ((tcworld,'Effect1','EffectTriggerSpell1'),
                                                        (acworld,'Effect_1','EffectTriggerSpell_1')):
                    sql(f'INSERT INTO `{schema}`.spell_dbc(Id,`{effect_field}`,`{child_field}`) VALUES(900098,36,20700)')
                    changed=checksum();run('apply',code=2)
                    assert 'world content drift' in sql(ack+f'CALL `{archive}`.apply_batch();',writer,False)
                    assert checksum()==changed
                    sql(f'DELETE FROM `{schema}`.spell_dbc WHERE Id=900098')
            # Failing control: historical HEX(number) collapses these changes.
            assert sql('SELECT HEX(0.1)=HEX(0.2),HEX(0.100001)=HEX(0.100002)')=='1\t1'
            for update, restore in (
                    (f'UPDATE `{source}`.characters SET position_x=0.2 WHERE guid=1',
                     f'UPDATE `{source}`.characters SET position_x=0.1 WHERE guid=1'),
                    (f'UPDATE `{source}`.character_spell SET custom_decimal=0.100002 WHERE guid=1 AND spell=6603',
                     f'UPDATE `{source}`.character_spell SET custom_decimal=0.100001 WHERE guid=1 AND spell=6603')):
                sql(update);changed=checksum()
                error=sql(ack+f'CALL `{archive}`.apply_batch();',writer,False)
                assert 'full-row fingerprint differs' in error,error
                assert checksum()==changed;sql(restore)
            for schema in ((tcworld,) if ordinary_training else (tcworld,acworld)):
                field='EffectRealPointsPerLevel1' if schema==tcworld else 'Speed'
                sql(f'UPDATE `{schema}`.spell_dbc SET `{field}`=0.2 WHERE Id=900099')
                changed=checksum()
                error=sql(ack+f'CALL `{archive}`.apply_batch();',writer,False)
                assert 'world content drift' in error,error
                assert checksum()==changed
                sql(f'UPDATE `{schema}`.spell_dbc SET `{field}`=0.1 WHERE Id=900099')
            changed_spell=16811 if ordinary_training else 1749 if pet_teaching else 48942
            original_rank=3 if pet_teaching or ordinary_training else 10
            for schema in ((tcworld,) if ordinary_training else (tcworld, acworld)):
                sql(f'UPDATE `{schema}`.spell_ranks SET `rank`=11 WHERE spell_id={changed_spell}')
                changed=checksum();run('apply',code=2)
                assert 'world content drift' in sql(ack+f'CALL `{archive}`.apply_batch();',writer,False)
                assert checksum()==changed
                sql(f'UPDATE `{schema}`.spell_ranks SET `rank`={original_rank} WHERE spell_id={changed_spell}')
            if ordinary_training:
                config.write_text(text.replace('player_start_all_spells=0','player_start_all_spells=1'))
                assert 'ORDINARY_HISTORY_CONFIG_REQUIRED' in run('apply',code=2).stderr
                assert checksum()==baseline
                config.write_text(text)
                sql(f'UPDATE `{tcworld}`.playercreateinfo_spell_custom SET Spell=14818 WHERE Spell=48073')
                changed=checksum();run('apply',code=2)
                assert 'world content drift' in sql(ack+f'CALL `{archive}`.apply_batch();',writer,False)
                assert checksum()==changed
                sql(f'UPDATE `{tcworld}`.playercreateinfo_spell_custom SET Spell=48073 WHERE Spell=14818')
                sql(f'UPDATE `{tcworld}`.spell_required SET req_spell=14818 WHERE spell_id=27681')
                changed=checksum();run('apply',code=2)
                assert 'world content drift' in sql(ack+f'CALL `{archive}`.apply_batch();',writer,False)
                assert checksum()==changed
                sql(f'UPDATE `{tcworld}`.spell_required SET req_spell=14752 WHERE spell_id=27681')
                sql(f'ALTER TABLE `{tcworld}`.spell_required ADD unexpected INT DEFAULT 0')
                assert 'world layout' in sql(ack+f'CALL `{archive}`.apply_batch();',writer,False)
                sql(f'ALTER TABLE `{tcworld}`.spell_required DROP unexpected')
            else:
                sql(f'UPDATE `{acworld}`.trainer_spell SET ReqLevel=1 WHERE TrainerId=1')
                assert 'ELIGIBILITY_TARGET_DRIFT' in run('apply',code=2).stderr
                assert 'world content drift' in sql(ack+f'CALL `{archive}`.apply_batch();',writer,False)
                sql(f'UPDATE `{acworld}`.trainer_spell SET ReqLevel=0 WHERE TrainerId=1')
                sql(f'ALTER TABLE `{acworld}`.spell_ranks MODIFY `rank` TINYINT UNSIGNED NOT NULL DEFAULT 0 FIRST')
                assert 'Eligibility world layout' in sql(ack+f'CALL `{archive}`.apply_batch();',writer,False)
                sql(f'ALTER TABLE `{acworld}`.spell_ranks MODIFY `rank` TINYINT UNSIGNED NOT NULL DEFAULT 0 AFTER spell_id')
            sql(f"CREATE TRIGGER `{archive}`.late_error BEFORE UPDATE ON `{archive}`.batch FOR EACH ROW BEGIN IF NEW.state='APPLIED' THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='eligibility-late-error';END IF;END")
            run('apply',code=2);assert checksum()==baseline
            sql(f'DROP TRIGGER `{archive}`.late_error')
            sql(f"CREATE TRIGGER `{archive}`.pause_commit BEFORE UPDATE ON `{archive}`.batch FOR EACH ROW BEGIN IF NEW.state='APPLIED' THEN DO SLEEP(30);END IF;END")
            worker=subprocess.Popen(command+['apply'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            deadline=time.monotonic()+10;connection=''
            while time.monotonic()<deadline:
                if worker.poll() is not None:
                    raise AssertionError(worker.communicate())
                connection=sql(f"SELECT ID FROM information_schema.PROCESSLIST WHERE DB='{archive}' AND STATE='User sleep' LIMIT 1")
                if connection:break
                time.sleep(.1)
            assert connection,'Apply did not reach the uncommitted checkpoint'
            sql('KILL CONNECTION '+connection);worker.communicate(timeout=10)
            assert worker.returncode!=0;worker=None
            assert checksum()==baseline and sql(f'SELECT state FROM `{archive}`.batch')=='PREPARED'
            sql(f'DROP TRIGGER `{archive}`.pause_commit')
            run('status');run('apply');run('apply');run('status')
            assert sql(f'SELECT COUNT(*) FROM `{source}`.character_spell WHERE guid=1')=='1'
            assert sql(f'SELECT COUNT(*) FROM `{source}`.character_spell WHERE guid=5')=='0'
            assert sql('CHECKSUM TABLE '+','.join(unrelated)+' EXTENDED;')==preserved
            sql(f'UPDATE `{source}`.character_spell SET custom_blob=0x99 WHERE guid=1 AND spell=6603')
            changed=checksum();run('restore',code=2);assert checksum()==changed
            sql(f'UPDATE `{source}`.character_spell SET custom_blob=0x1234 WHERE guid=1 AND spell=6603')
            run('restore');run('restore');assert checksum()==baseline;run('apply',code=2)
        print(f'MySQL {version}: {label} preview/config/count/full-scope drift, native catalogs, direct SQL guards, rollback/disconnect/reruns/exact custom restore PASS; gameplay NOT TESTED',flush=True)
    finally:
        if worker is not None and worker.poll() is None:
            worker.terminate();worker.wait()
        for schema in reversed(owned):sql(f'DROP DATABASE IF EXISTS `{schema}`;')
        for user in users:sql(f"DROP USER IF EXISTS '{user}'@'%';")


if __name__ == '__main__':
    assert sys.argv[1:] in ([],['--absent-teachers'],['--training-prerequisites'],['--reviewed-racials'])
    main(absent_teachers=sys.argv[1:]==['--absent-teachers'],ordinary_training=sys.argv[1:]==['--training-prerequisites'],reviewed_racials=sys.argv[1:]==['--reviewed-racials'])
