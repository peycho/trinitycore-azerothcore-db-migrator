#!/usr/bin/env python3
"""Real recipe sequencing/counts/archives/fixed point and missing-auth gating."""
import importlib.util,json,os,re,shlex,subprocess,sys,tempfile,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def main():
 port=os.environ.get('REHEARSAL_MYSQL_PORT','33317')
 if os.environ.get('MIGRATOR_DISPOSABLE_MYSQL')!='1' or not port.isdigit()or int(port)==3306:
  raise SystemExit('Requires explicitly disposable local MySQL on a non-production port')
 defaults=os.environ.get('REHEARSAL_MYSQL_DEFAULTS_FILE','')
 mysql=([f'--defaults-extra-file={defaults}']if defaults else ['--no-defaults'])+['--host=127.0.0.1',f'--port={int(port)}','--protocol=TCP','--user=root','--batch','--skip-column-names']
 def sql(q):
  p=subprocess.run(['mysql',*mysql],input=q,text=True,capture_output=True)
  assert not p.returncode,p.stderr
  return p.stdout.strip()
 prefix='recipe_'+uuid.uuid4().hex[:10];chars,auth,world,missing=[prefix+s for s in ('_chars','_auth','_world','_missing')];owned=[];users=[]
 tc=Path(os.environ.get('TRINITYCORE_DIR',ROOT.parent/'TrinityCore'));ac=Path(os.environ.get('AZEROTHCORE_DIR',ROOT.parent/'azerothcore-wotlk'))
 try:
  for name in (chars,auth,world,missing):sql(f'CREATE DATABASE `{name}`');owned.append(name)
  sql(f'USE `{chars}`;'+(tc/'sql/base/characters_database.sql').read_text())
  sql(f'USE `{auth}`;'+(tc/'sql/base/auth_database.sql').read_text()+(ROOT/'tests/fixtures/auth-data.sql').read_text())
  text=(tc/'sql/base/dev/world_database.sql').read_text();ddl=re.search(r'CREATE TABLE `spell_dbc` \(.*?\) ENGINE=[^;]+;',text,re.S)[0]
  sql(f'USE `{world}`;'+ddl+';CREATE TABLE item_template(entry INT PRIMARY KEY);CREATE TABLE quest_template(ID INT PRIMARY KEY)')
  sql(f'''INSERT INTO `{chars}`.characters(guid,account,name,taximask,race,class,level,talentGroupsCount,activeTalentGroup) VALUES(1,1,'RecipeCase','',1,1,80,1,0);
  INSERT INTO `{chars}`.character_talent VALUES(1,27,0),(1,130,0);
  INSERT INTO `{chars}`.character_spell VALUES(1,6603,1,0);
  INSERT INTO `{chars}`.character_skills VALUES(1,183,500,400);
  ALTER TABLE `{chars}`.characters ADD custom_blob BLOB; UPDATE `{chars}`.characters SET custom_blob=0x00ff;
  ''')
  reader=prefix+'_reader';writer=prefix+'_writer'
  for user in (reader,writer):
   sql(f"CREATE USER '{user}'@'%' IDENTIFIED BY ''");users.append(user)
   for schema in (chars,auth,world,missing):sql(f"GRANT SELECT ON `{schema}`.* TO '{user}'@'%'")
  sql(f"GRANT INSERT,DELETE ON `{chars}`.character_talent TO '{writer}'@'%'; GRANT UPDATE(value) ON `{chars}`.character_skills TO '{writer}'@'%'")
  tables=sql("SELECT CONCAT('`',TABLE_SCHEMA,'`.`',TABLE_NAME,'`') FROM information_schema.TABLES WHERE TABLE_SCHEMA IN ('"+chars+"','"+auth+"','"+world+"') ORDER BY 1").splitlines()
  check='CHECKSUM TABLE '+','.join(tables)+' EXTENDED';baseline=sql(check)
  with tempfile.TemporaryDirectory()as d:
   p=Path(d);spec=importlib.util.spec_from_file_location('replay_assets',ROOT/'tests/spell-fixtures.py');assets=importlib.util.module_from_spec(spec);spec.loader.exec_module(assets)
   profile=json.loads((ROOT/'compatibility/tc335-acwotlk-v2/spell-metadata.json').read_text());original=assets.stores
   def stores(profile):
    data=original(profile);row=[0]*len(profile['stores']['SkillLine']['columns']);row[0]=183;row[1]=7;data['SkillLine'][183]=row
    # A native ranked-language row must stay known with its skill absent.
    lang=[0]*len(profile['stores']['Spell']['columns']);lang[0]=900090;lang[4]=192;lang[71]=39;data['Spell'][900090]=lang
    line=[0]*len(profile['stores']['SkillLine']['columns']);line[0]=109;line[1]=10;data['SkillLine'][109]=line
    data['SkillLineAbility'][9999]=[9999,109,900090,0,0,0,0,1,0,2,0,0,0,0]
    data['SkillRaceClassInfo'][9999]=[9999,109,1,1,160,0,21,0]
    data['SkillTiers'][21]=[21]+[0]*16+[300]*16
    return data
   assets.stores=stores;assets.write_assets(p,profile)
   recipe=p/'recipe.json';recipe.write_text('{"version":1,"policies":["invalid-talents","skill-caps"]}')
   config=p/'cleanup.ini';client=f'defaults_file={defaults}'if defaults else ''
   def configuration(auth_schema):
    config.write_text(f'''[workspace]
directory={p/'workspace'}
[source]
characters={chars}
auth={auth_schema}
world={world}
[paths]
tc_dbc={p/'tc-dbc'}
ac_dbc={p/'ac-dbc'}
tc_source={tc}
ac_source={ac}
[mysql]
host=127.0.0.1
port={port}
user={writer}
password=
{client}
[mysql_audit]
user={reader}
password=
{client}
[mysql_admin]
user=root
password=
{client}
[safety]
preparation_copy=yes
writers_stopped=yes
backup_reference=retained-original-synthetic-snapshot
''');config.chmod(0o600)
   for label,source_auth,expected in [('complete',auth,'COMPLETE'),('missing-auth',missing,'COMPLETE_WITH_LIMITATIONS')]:
    configuration(source_auth);out=p/label
    command=[sys.executable,str(ROOT/'tools/replay-source-preparation.py'),'--config',str(config),'--recipe',str(recipe),'--output',str(out),'--apply-reviewed-recipe']
    if source_auth==missing:command+=['--migration-config',str(p/'must-never-be-used.env')]
    result=subprocess.run(command,text=True,capture_output=True)
    assert result.returncode==2,result.stdout+result.stderr
    report=json.loads((out/'replay.json').read_text());assert report['status']=='POLICY_FIXED_POINT',(report,[(f.name,f.read_text())for f in out.glob('*.stderr')if f.stat().st_size])
    assert report['final_audit']['status']==expected,report
    assert report['migration']=='BLOCKED_PENDING_FULL_REHEARSAL' and report['gameplay']=='NOT_TESTED'
    assert not (out/'migration.env').exists()
    applied=[r for r in report['steps']if r['state']=='APPLIED'];assert len(applied)==2,report
    assert [r['summary']['selected_rows']for r in applied]==[2,1]
    assert sql(f'SELECT COUNT(*) FROM `{chars}`.character_talent')=='0'
    assert sql(f'SELECT value FROM `{chars}`.character_skills WHERE guid=1 AND skill=183')=='400'
    assert all(r['state']=='NO_SELECTION'for r in report['steps']if r['pass']==2)
    session=p/'workspace/sessions'/report['session']
    for entry in reversed(applied):
     manifest=json.loads((session/'batches'/entry['batch']/'manifest.json').read_text());owned.append(manifest['archive_schema'])
     r=subprocess.run([sys.executable,str(ROOT/'console'),'--config',str(config),'restore','--batch',entry['batch']],text=True,capture_output=True)
     assert r.returncode==0,r.stdout+r.stderr
    assert sql(check)==baseline,'Recipe restore did not recover exact original data'
   # A third original-state replay must reach READY through the real migrator,
   # with fresh targets/control and all source worlds retained unchanged.
   aworld=prefix+'_acworld';sql(f'CREATE DATABASE `{aworld}`');owned.append(aworld)
   sql(f'DROP TABLE `{world}`.spell_dbc')
   assets.seed_worlds(lambda q,db:sql('USE `'+db+'`;'+q),tc,ac,world,aworld,profile)
   sql(f'CREATE TABLE `{world}`.playercreateinfo_spell_custom(racemask INT UNSIGNED,classmask INT UNSIGNED,Spell INT UNSIGNED)')
   for user in (writer,reader):sql(f"GRANT SELECT ON `{aworld}`.* TO '{user}'@'%'")
   configuration(auth)
   sql(f'INSERT INTO `{chars}`.character_spell VALUES(1,900090,1,0)')
   with config.open('a')as f:f.write(f'\n[target]\nworld={aworld}\nplayer_start_custom_spells=0\n')
   targets=[prefix+s for s in ('_mauth','_mchars','_mcontrol')];owned+=targets
   migration=p/'migration-config.env'
   values={'MYSQL_HOST':'127.0.0.1','MYSQL_PORT':port,'MYSQL_USER':'root','MYSQL_SOCKET':'','MYSQL_DEFAULTS_FILE':defaults,
    'MIGRATION_DIRECTION':'tc-to-ac','SOURCE_AUTH_SCHEMA':auth,'SOURCE_CHARACTERS_SCHEMA':chars,'SOURCE_WORLD_SCHEMA':world,'TARGET_WORLD_SCHEMA':aworld,
    'TARGET_AUTH_SCHEMA':targets[0],'TARGET_CHARACTERS_SCHEMA':targets[1],'CONTROL_SCHEMA':targets[2], 'REALM_ID':'1',
    'TRINITYCORE_DIR':str(tc),'AZEROTHCORE_DIR':str(ac),'TRINITYCORE_DBC_DIR':str(p/'tc-dbc'),'AZEROTHCORE_DBC_DIR':str(p/'ac-dbc'),
    'COMPATIBILITY_PROFILE':'tc335-acwotlk-v2','LOAD_CHUNK_SIZE':'1000','CLEANUP_CHUNK_SIZE':'1000','LARGE_TABLE_ROWS':'1000','DEFER_SECONDARY_INDEXES':'1',
    'REQUIRE_QUIESCENT':'0','ALLOW_SOURCE_ARCHIVE':'1','ALLOW_GAMEPLAY_ARCHIVE':'1','ARCHIVE_DIR':str(p/'archives')}
   migration.write_text(''.join(k+'='+shlex.quote(str(v))+'\n'for k,v in values.items()));migration.chmod(0o600)
   # Approval is enabled only inside the established /tmp test-toolkit copy.
   test_toolkit=p/'toolkit'
   script='set -Eeuo pipefail; ROOT=$1; COMPATIBILITY_PROFILE=tc335-acwotlk-v2; source "$1/tests/test-support.sh"; prepare_test_toolkit "$2"'
   subprocess.run(['bash','-c',script,'bash',str(ROOT),str(test_toolkit)],check=True)
   result=subprocess.run([sys.executable,str(test_toolkit/'tools/replay-source-preparation.py'),'--config',str(config),'--recipe',str(recipe),'--output',str(p/'with-migration'),'--apply-reviewed-recipe','--migration-config',str(migration)],text=True,capture_output=True)
   report=json.loads((p/'with-migration/replay.json').read_text())
   # Register archives even when a later migration gate fails.
   assert 'session' in report,(report.get('status'),report.get('error'),result.stdout,result.stderr,[(f.name,f.read_text()[-1000:])for f in (p/'with-migration').glob('*.stderr')if f.stat().st_size])
   session=p/'workspace/sessions'/report['session']
   for entry in report['steps']:
    if entry.get('batch'):owned.append(json.loads((session/'batches'/entry['batch']/'manifest.json').read_text())['archive_schema'])
   assert result.returncode==0,(report.get('status'),report.get('error'),result.stdout,result.stderr,[(f.name,f.read_text()[-2000:])for f in (p/'with-migration').glob('*.stderr')if f.stat().st_size and not f.name[0].isdigit()])
   assert report['status']=='DATABASE_REHEARSAL_READY' and report['migration']=='READY' and report['gameplay']=='NOT_TESTED'
   assert report['migration_phases']==['preflight','archive-unsupported','assemble','load-auth','load-characters','sanitize-target','validate','report']
   assert sql(f"SELECT status FROM `{targets[2]}`.migration_run WHERE run_id='{report['migration_run_id']}'")=='READY'
   assert sql(f'SELECT value FROM `{targets[1]}`.character_skills WHERE guid=1 AND skill=183')=='400'
   assert sql(f'SELECT specMask FROM `{targets[1]}`.character_spell WHERE guid=1 AND spell=900090')=='3'
   assert sql(f'SELECT COUNT(*) FROM `{targets[1]}`.character_skills WHERE guid=1 AND skill=109')=='0'
   assert sql(f"SELECT JSON_EXTRACT(provenance,'$.authorization.absent_ranked_language_skill[0].skill_granted') FROM `{targets[2]}`.spell_expected WHERE guid=1 AND spell=900090")=='false'
  print('MySQL recipe replay: original -> guarded repairs/fixed point -> real TC-to-AC database READY; missing-auth stop; exact custom restore PASS; gameplay NOT TESTED')
 finally:
  for schema in reversed(list(dict.fromkeys(owned))):sql(f'DROP DATABASE IF EXISTS `{schema}`')
  for user in users:sql(f"DROP USER '{user}'@'%'")

if __name__=='__main__':main()
