"""Configuration, private workspaces and execution of reviewed cleanup batches."""
import argparse
import configparser
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import traceback
import uuid

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT/'compatibility/tc335-acwotlk-v2'


class CleanupError(Exception):
    def __init__(self, code, message, hint=''):
        super().__init__(message)
        self.code, self.hint = code, hint


def fail(code, message, hint=''):
    raise CleanupError(code, message, hint)


def now():
    return datetime.now(timezone.utc).isoformat()


def token(prefix):
    return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-')+prefix+'-'+uuid.uuid4().hex[:10]


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def toolkit_hashes():
    names=('console','lib/cleanup_console.py','lib/cleanup_plans.py','lib/spells.py',
           'tools/audit-tc-source.py','tools/plan-talent-cleanup.py',
           'tools/talent-cleanup.sql.in','tools/single-character-talent-reset.sql.in',
           'tools/container-recovery.sql.in')
    return {name:sha(ROOT/name) for name in names}


def identifier(value):
    if not re.fullmatch(r'[A-Za-z0-9_]{1,64}', str(value)):
        fail('INVALID_IDENTIFIER', 'Expected a 1-64 character ASCII SQL identifier')
    return str(value)


def local_id(value):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', value):
        fail('INVALID_ID', 'Invalid session, audit or batch ID')
    return value


def private_file(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_uid != os.getuid() or stat.S_IMODE(path.stat().st_mode)&0o077:
        fail('PRIVATE_FILE_REQUIRED', f'Expected an operator-owned private file: {path}', 'Use chmod 600; do not put credentials in command arguments.')


def private_dir(path):
    if path.is_symlink():
        fail('SYMLINK_REFUSED', f'Workspace directory cannot be a symlink: {path}')
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.stat().st_uid != os.getuid() or stat.S_IMODE(path.stat().st_mode)&0o077:
        fail('PRIVATE_DIRECTORY_REQUIRED', f'Workspace directory must be operator-owned and private: {path}', 'Use chmod 700.')


def write_json(path, value):
    temporary = path.with_name(path.name+'.tmp-'+uuid.uuid4().hex)
    with temporary.open('x') as stream:
        temporary.chmod(0o600)
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def seal(directory):
    paths = sorted(p for p in directory.iterdir() if p.is_file() and p.name not in ('SHA256SUMS','INCOMPLETE'))
    (directory/'SHA256SUMS').write_text(''.join(sha(p)+'  '+p.name+'\n' for p in paths))
    for path in paths+[directory/'SHA256SUMS']:
        path.chmod(0o600)


def verify(directory):
    if directory.is_symlink() or (directory/'INCOMPLETE').exists():
        fail('INCOMPLETE_PACKAGE', 'Incomplete or symlinked package cannot be executed')
    manifest = directory/'SHA256SUMS'
    if manifest.is_symlink():
        fail('PACKAGE_CHANGED', 'Symlinked checksum manifest refused')
    names = set()
    contents = {}
    for line in manifest.read_text().splitlines():
        match = re.fullmatch(r'([0-9a-f]{64})  ([A-Za-z0-9_.-]+)', line)
        if not match or match[2] in names or match[2] in ('SHA256SUMS','INCOMPLETE'):
            fail('PACKAGE_CHANGED', 'Invalid or duplicate package checksum entry')
        name = match[2]
        path = directory/name
        if path.is_symlink() or not path.is_file():
            fail('PACKAGE_CHANGED', f'Package member is missing or symlinked: {name}')
        data=path.read_bytes()
        if hashlib.sha256(data).hexdigest()!=match[1]:
            fail('PACKAGE_CHANGED', f'Package checksum differs: {name}', 'Keep the evidence; generate a new batch rather than editing SQL.')
        names.add(name)
        contents[name]=data
    if names != {p.name for p in directory.iterdir() if p.name!='SHA256SUMS'}:
        fail('PACKAGE_CHANGED', 'Unsealed or missing files in package')
    return contents


class Settings:
    def __init__(self, filename):
        self.file = Path(filename).expanduser().absolute()
        private_file(self.file)
        self.ini = configparser.ConfigParser(interpolation=None)
        try:
            self.ini.read_string(self.file.read_text())
        except configparser.Error as error:
            # Parser exception strings include raw input, which may contain passwords.
            line=getattr(error,'lineno',None)
            location=f' at line {line}' if isinstance(line,int) else ''
            section=getattr(error,'section',None)
            option=getattr(error,'option',None)
            safe_sections={'workspace','source','paths','safety','mysql','mysql_audit','mysql_admin'}
            safe_options={'socket','host','port','user','password','defaults_file'}
            if isinstance(error,configparser.DuplicateSectionError):
                label=f' [{section}]' if section in safe_sections else ''
                message='Duplicate INI section'+label+location
                hint='Edit the existing section instead of appending a second copy.'
            elif isinstance(error,configparser.DuplicateOptionError):
                label=f' {option}' if option in safe_options else ''
                group=f' in [{section}]' if section in safe_sections else ''
                message='Duplicate INI setting'+label+group+location
                hint='Keep one entry for each setting in a section; remove the obsolete entry.'
            else:
                if not location:
                    lines=[number for number,_ in getattr(error,'errors',[]) if isinstance(number,int)]
                    if lines:
                        location=' at line(s) '+', '.join(map(str,lines))
                message='Invalid INI configuration'+location+'; values were omitted to protect credentials'
                hint='Use config/cleanup.ini.example as the format.'
            fail('CONFIG_SYNTAX',message,hint)
        allowed = {'workspace','source','paths','safety','mysql','mysql_audit','mysql_admin'}
        if set(self.ini.sections())-allowed:
            fail('CONFIG_UNKNOWN_SECTION', 'Unknown configuration section: '+','.join(sorted(set(self.ini.sections())-allowed)))
        fields = {
            'workspace':{'directory'}, 'source':{'core','characters','auth','world'},
            'paths':{'tc_dbc','ac_dbc','tc_source','ac_source'},
            'safety':{'preparation_copy','writers_stopped','backup_reference'},
            'mysql':{'host','port','socket','user','password','defaults_file','ssl_mode','connect_timeout'},
            'mysql_audit':{'user','password','defaults_file'},'mysql_admin':{'user','password','defaults_file'}}
        for section in self.ini.sections():
            unknown = set(self.ini[section])-fields[section]
            if unknown:
                fail('CONFIG_UNKNOWN_SETTING', f'Unknown setting in [{section}]: '+','.join(sorted(unknown)))
        self.workspace = self.path('workspace','directory',required=True)
        self.schemas = {key:identifier(self.get('source',key,required=True)) for key in ('characters','auth','world')}
        if len(set(self.schemas.values()))!=3:
            fail('CONFIG_SCHEMAS', 'Auth, characters and world must be distinct schemas')
        if self.get('source','core','tc')!='tc':
            fail('UNSUPPORTED_SOURCE', 'Preparation cleanup currently supports TrinityCore sources only; AC paths are compatibility inputs, not an AC cleanup policy')
        self.paths = {key:self.path('paths',key,required=key in ('tc_dbc','tc_source')) for key in ('tc_dbc','ac_dbc','tc_source','ac_source')}
        self.secrets = [self.ini[s].get('password','') for s in ('mysql','mysql_audit','mysql_admin') if s in self.ini]
        self.secrets = [s for s in self.secrets if s]
        self.compatibility = {}
        self.connection = {'host':self.get('mysql','host','127.0.0.1'),
            'port':self.get('mysql','port','3306'),'socket':self.get('mysql','socket','')}
        try:
            if not 1<=int(self.connection['port'])<=65535:
                raise ValueError()
        except ValueError:
            fail('CONFIG_PORT','MySQL port must be between 1 and 65535')
        if self.connection['socket'] and self.connection['host'] not in ('localhost','127.0.0.1','::1'):
            fail('CONFIG_SOCKET_HOST','A Unix socket requires a local MySQL host',
                 'Use [mysql] host=localhost with the socket path, or clear socket to use TCP to the configured host.')

    def get(self, section, key, default='', required=False):
        value = self.ini.get(section,key,fallback=default)
        if required and not value:
            fail('CONFIG_MISSING', f'Missing [{section}] {key}')
        if '\0' in value:
            fail('CONFIG_VALUE','NUL bytes are not supported in settings')
        return value

    def path(self, section, key, required=False):
        value = self.get(section,key,required=required)
        if not value:
            return None
        path = Path(os.path.expandvars(value)).expanduser()
        return (self.file.parent/path).absolute() if not path.is_absolute() else path

    def redact(self, value):
        for secret in self.secrets:
            value=value.replace(secret,'[REDACTED]')
        return value

    def safety(self):
        for key in ('preparation_copy','writers_stopped'):
            if self.get('safety',key).lower() not in ('yes','true','1'):
                fail('PREPARATION_ACK_REQUIRED', f'[safety] {key}=yes is required', 'Use only a stopped restored preparation copy; this setting is your assertion, not service detection.')
        if not self.get('safety','backup_reference'):
            fail('BACKUP_REFERENCE_REQUIRED','Set [safety] backup_reference to the retained verified backup identifier')

    def check_paths(self):
        for key,path in self.paths.items():
            if path and not path.is_dir():
                fail('PATH_MISSING', f'Configured directory does not exist: {key}: {path}')
        for prefix,key in (('trinitycore','tc_source'),('azerothcore','ac_source')):
            base=self.paths[key]
            if base is None:
                continue
            manifests={}
            for kind in ('sql','semantic'):
                manifest=PROFILE/(prefix+'-'+kind+'.sha256')
                manifests[manifest.name]=sha(manifest)
                for line in manifest.read_text().splitlines():
                    expected,relative=line.split(None,1)
                    target=base/relative.strip()
                    if not target.is_file() or sha(target)!=expected:
                        fail('CORE_PROFILE_MISMATCH', f'{key}: protected content differs: {relative}', 'Use the reviewed checkout or establish compatibility; pins and release approval are not changed by this tool.')
            revision=None
            if shutil.which('git'):
                result=subprocess.run(['git','--no-optional-locks','-C',str(base),'rev-parse','HEAD'],text=True,capture_output=True)
                if result.returncode==0 and re.fullmatch(r'[0-9a-f]{40,64}',result.stdout.strip()):
                    revision=result.stdout.strip()
            self.compatibility[key]={'path':str(base),'actual_revision':revision,
                'protected_content':'MATCH','manifest_sha256':manifests}

    @contextmanager
    def client(self, role):
        section={'audit':'mysql_audit','admin':'mysql_admin','write':'mysql'}[role]
        selected=section if section in self.ini else 'mysql'
        defaults=self.get(selected,'defaults_file')
        # A separately configured role does not accidentally inherit the main password.
        if defaults:
            source=self.path(selected,'defaults_file')
            private_file(source)
            content=source.read_text()
            for line in content.splitlines():
                match=re.match(r'\s*password\s*=\s*(.*)',line,re.I)
                if match and match[1].strip('\"\''):
                    self.secrets.extend((match[1],match[1].strip('\"\'')))
        else:
            def quote(value):
                return '"'+value.replace('\\','\\\\').replace('"','\\"').replace('\n','\\n').replace('\r','\\r').replace('\t','\\t')+'"'
            user=self.get(selected,'user',required=True)
            content='[client]\nuser='+quote(user)+'\npassword='+quote(self.get(selected,'password'))+'\n'
        secrets_dir=self.workspace/'.credentials'
        private_dir(secrets_dir)
        fd,filename=tempfile.mkstemp(prefix='mysql-',suffix='.cnf',dir=secrets_dir)
        try:
            with os.fdopen(fd,'w') as stream:
                stream.write(content)
            args=['--defaults-file='+filename,
                '--connect-timeout='+self.get('mysql','connect_timeout','10')]
            if self.connection['socket']:
                # libmysql rejects SOCKET with a numeric host as error 2047.
                args+=['--host=localhost','--socket='+self.connection['socket'],'--protocol=SOCKET']
            else:
                args+=['--host='+self.connection['host'],
                       '--port='+str(int(self.connection['port'])),'--protocol=TCP']
            mode=self.get('mysql','ssl_mode')
            if mode:
                args+=['--ssl-mode='+mode]
            yield args
        finally:
            Path(filename).unlink(missing_ok=True)

    def sql(self, query, role='audit', headers=False):
        if not shutil.which('mysql'):
            fail('MYSQL_CLIENT_MISSING','mysql executable is not available in PATH','Install MySQL 8 client tools, then retry this command.')
        with self.client(role) as args:
            args+=['--batch','--raw','--skip-force','--default-character-set=utf8mb4']
            if not headers:
                args+=['--skip-column-names']
            if role=='audit':
                args+=['--init-command=SET SESSION transaction_read_only=ON']
            environment=os.environ.copy()
            environment.pop('MYSQL_PWD',None)
            result=subprocess.run(['mysql',*args],input=query,text=True,capture_output=True,env=environment)
            if result.returncode:
                fail('MYSQL_FAILED',self.redact(result.stderr.strip()),
                     'No automatic retry or guard bypass was attempted. Check grants, endpoint and batch state; status can reconcile a disconnected operation.')
            # These statements never select credentials. Redacting ordinary
            # query data could change GUIDs/JSON when a short password happens
            # to match a data value. Only diagnostics are secret-redacted.
            return result.stdout

    def identity(self, role='audit'):
        row=self.sql('SELECT @@server_uuid,@@version;',role).strip().split('\t')
        if len(row)!=2 or not row[1].startswith('8.4.'):
            fail('MYSQL_VERSION','Cleanup requires MySQL 8.4.x')
        return {'uuid':str(uuid.UUID(row[0])),'version':row[1],'schemas':self.schemas,'connection':self.connection}

    def validate_schemas(self):
        names=','.join("'"+name+"'" for name in self.schemas.values())
        visible=set(self.sql('SELECT SCHEMA_NAME FROM information_schema.SCHEMATA '
                             f'WHERE SCHEMA_NAME IN ({names});').splitlines())
        missing=sorted(set(self.schemas.values())-visible)
        if missing:
            fail('CONFIG_SCHEMA_UNAVAILABLE','Configured schemas are missing or inaccessible: '+', '.join(missing),
                 'Check [source] spelling and the audit account SELECT grants. After changing schemas, run init for a new session.')


class Workspace:
    def __init__(self, settings):
        self.settings=settings
        self.root=settings.workspace
        self.session=None
        self.operation=None

    @contextmanager
    def locked(self):
        private_dir(self.root)
        lock=self.root/'.lock'
        if lock.is_symlink():
            fail('SYMLINK_REFUSED','Workspace lock cannot be a symlink')
        with lock.open('a') as stream:
            lock.chmod(0o600)
            try:
                fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:
                fail('WORKSPACE_BUSY','Another cleanup command holds this workspace lock')
            yield

    def current(self):
        pointer=json.loads((self.root/'current.json').read_text()) if (self.root/'current.json').exists() else None
        if not pointer:
            fail('SESSION_REQUIRED','No cleanup session is selected','Run console init after importing the stopped preparation databases.')
        self.session=self.root/'sessions'/local_id(pointer['session'])
        if not self.session.is_dir():
            fail('SESSION_MISSING','Selected session directory is missing; evidence was not recreated')
        private_dir(self.session)
        return json.loads((self.session/'session.json').read_text())

    def begin(self, command):
        base=(self.session/'operations') if self.session else self.root/'operations'
        private_dir(base)
        self.operation=base/token(command)
        private_dir(self.operation)
        write_json(self.operation/'operation.json',{'command':command,'state':'STARTED','started_utc':now(),
                   'toolkit_sha256':toolkit_hashes()})

    def finish(self, state, **details):
        if self.operation:
            item=json.loads((self.operation/'operation.json').read_text())
            item.update(state=state,finished_utc=now(),**details)
            write_json(self.operation/'operation.json',item)

    def check_identity(self, role='audit'):
        session=self.current()
        actual=self.settings.identity(role)
        if actual!=session['identity']:
            expected=session['identity']
            changed=[key for key in ('uuid','version') if actual.get(key)!=expected.get(key)]
            for group,keys in (('schemas',('characters','auth','world')),('connection',('host','port','socket'))):
                changed.extend(group+'.'+key for key in keys
                               if actual.get(group,{}).get(key)!=expected.get(group,{}).get(key))
            fail('SESSION_ENDPOINT_CHANGED','Session identity changed: '+', '.join(changed or ['identity fields']),
                 'Restore the original settings, or run console init followed by a fresh audit and plan after an intentional connection change or database import. A connection-only change does not require a database reimport.')
        return session

    def batch(self, batch_id):
        if not batch_id:
            pointer=self.session/'active-batch.json'
            if not pointer.exists():
                fail('BATCH_REQUIRED','No batch is selected','Generate a plan or pass --batch ID.')
            batch_id=json.loads(pointer.read_text())['batch']
        path=self.session/'batches'/local_id(batch_id)
        if not path.is_dir():
            fail('BATCH_MISSING',f'Batch is not in this session: {batch_id}')
        contents=verify(path)
        manifest=json.loads(contents['manifest.json'])
        if manifest.get('cleanup_session')!=self.session.name:
            fail('SESSION_BATCH_MISMATCH','Batch belongs to another cleanup session')
        return path,manifest


def command_init(settings, work, args):
    settings.safety()
    settings.check_paths()
    identity=settings.identity()
    settings.validate_schemas()
    private_dir(work.root/'sessions')
    session_id=token('session')
    work.session=work.root/'sessions'/session_id
    private_dir(work.session)
    for folder in ('audits','batches','inspections','operations'):
        private_dir(work.session/folder)
    write_json(work.session/'session.json',{'session':session_id,'label':args.label,'created_utc':now(),
        'identity':identity,'backup_reference':settings.get('safety','backup_reference'),
        'paths':{key:str(value) if value else None for key,value in settings.paths.items()},
        'core_compatibility':settings.compatibility,
        'profile':'tc335-acwotlk-v2','profile_approval':'UNREVIEWED'})
    write_json(work.root/'current.json',{'session':session_id})
    print('SESSION '+session_id+'\nWorkspace: '+str(work.session))


def check_audit_result(settings, work, output, returncode, stderr):
    """Classify the child result before treating its progress stream as errors."""
    report=output/'audit.json'
    status=None
    invalid_report=False
    if report.exists():
        try:
            status=json.loads(report.read_text())
            if not isinstance(status,dict):
                invalid_report=True
                status=None
        except (OSError,ValueError):
            invalid_report=True
    details={'child_exit_code':returncode,'reports':str(output),'audit_status':status.get('status') if status else None,
             'limitations':status.get('limitations') if status else None,
             'audit_error':settings.redact(str(status.get('error',''))) if status else None}
    write_json(work.operation/'audit-result.json',details)
    hint='Inspect '+str(report)+' and '+str(work.operation/'audit.stderr.txt')+'. No cleanup was performed.'
    if returncode<0:
        try:
            name=signal.Signals(-returncode).name
        except ValueError:
            name='signal '+str(-returncode)
        fail('AUDIT_PROCESS_TERMINATED',f'Audit child terminated by {name}; its report is not accepted.',hint)
    if invalid_report:
        fail('AUDIT_REPORT_INVALID','Audit child produced an unreadable or malformed audit.json',hint)
    if status is not None:
        limitations=status.get('limitations')
        if isinstance(limitations,list) and limitations:
            description='; '.join(settings.redact(str(value)) for value in limitations[:8])
            fail('AUDIT_COVERAGE_INCOMPLETE',f'Audit finished with {len(limitations)} coverage limitation(s): '+description,
                 'Inspect '+str(report)+' and coverage.tsv. Correct missing inputs/grants; initialize a new session if schema names change. No cleanup was performed.')
        if status.get('status')!='COMPLETE' or limitations!=[]:
            message=status.get('error') or 'Audit status is '+str(status.get('status'))
            fail('AUDIT_INCOMPLETE',settings.redact(str(message)),hint)
        if returncode in (0,1):
            return status
    diagnostic=[line for line in stderr.splitlines() if line and not line.startswith(('Auditing ','Audited '))]
    message=f'Audit child exited with status {returncode}'+(' without audit.json' if status is None else ' despite its report status')
    if diagnostic:
        message+=': '+'\n'.join(diagnostic[-8:])[-2048:]
    fail('AUDIT_INCOMPLETE',settings.redact(message),hint)


def command_audit(settings, work, args):
    settings.validate_schemas()
    audit_id=token(args.scope)
    output=work.session/'audits'/audit_id
    with settings.client('audit') as connection:
        command=[sys.executable,str(ROOT/'tools/audit-tc-source.py'),
            '--characters-schema',settings.schemas['characters'],'--auth-schema',settings.schemas['auth'],
            '--world-schema',settings.schemas['world'],'--tc-dbc',str(settings.paths['tc_dbc']),
            '--scope',args.scope,'--output',str(output),'--mysql',*connection]
        environment=os.environ.copy()
        environment.pop('MYSQL_PWD',None)
        print('Running read-only '+args.scope+' audit; reports: '+str(output),flush=True)
        with tempfile.TemporaryFile(mode='w+') as captured:
            process=subprocess.Popen(command,text=True,stdout=captured,stderr=subprocess.PIPE,env=environment)
            errors=[]
            try:
                for line in process.stderr:
                    safe=settings.redact(line)
                    errors.append(safe)
                    print(safe.rstrip(),file=sys.stderr,flush=True)
                returncode=process.wait()
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait()
            captured.seek(0)
            stdout=settings.redact(captured.read())
    (work.operation/'audit.stdout.txt').write_text(stdout)
    (work.operation/'audit.stderr.txt').write_text(''.join(errors))
    check_audit_result(settings,work,output,returncode,''.join(errors))
    write_json(work.session/'latest-audit.json',{'audit':audit_id})
    print('AUDIT '+audit_id+'\n'+(output/'summary.tsv').read_text().rstrip()+'\nReports: '+str(output))
    return returncode


def command_sessions(settings,work,args):
    if args.use:
        session=work.root/'sessions'/local_id(args.use)
        if not session.is_dir() or session.is_symlink():
            fail('SESSION_MISSING','Requested session does not exist')
        data=json.loads((session/'session.json').read_text())
        if data['identity']!=settings.identity():
            fail('SESSION_ENDPOINT_CHANGED','Requested session does not match the configured server and schemas')
        write_json(work.root/'current.json',{'session':session.name})
    base=work.root/'sessions'
    current=json.loads((work.root/'current.json').read_text())['session'] if (work.root/'current.json').exists() else ''
    if base.exists():
        for session in sorted(base.iterdir()):
            if session.is_dir() and not session.is_symlink():
                data=json.loads((session/'session.json').read_text())
                print(('* ' if session.name==current else '  ')+session.name+'\t'+data.get('label',''))


def command_plan(settings, work, args):
    from cleanup_plans import plan
    settings.safety()
    settings.check_paths()
    batch_id=token(args.kind)
    output=work.session/'batches'/batch_id
    plan(settings,work,args,output)
    write_json(work.session/'active-batch.json',{'batch':batch_id})
    manifest=json.loads((output/'manifest.json').read_text())
    print('CANDIDATE '+batch_id+'\nArchive: '+manifest['archive_schema']+'\nReview: '+str(output/'README.md'))


def command_action(settings, work, args):
    path,manifest=work.batch(args.batch)
    settings.safety()
    for name,expected_hash in manifest.get('dbc_sha256',{}).items():
        if not re.fullmatch(r'[A-Za-z0-9]+\.dbc',name) or sha(settings.paths['tc_dbc']/name)!=expected_hash:
            fail('DBC_DRIFT','DBC assets differ from the reviewed batch','Keep the original metadata or generate a new audit and batch.')
    work.check_identity('admin' if args.command=='prepare' else 'write')
    archive=identifier(manifest['archive_schema'])
    # Snapshot the verified SQL before invoking mysql, so replacing a file after
    # checksum verification cannot change the statement executed by this call.
    contents=verify(path)
    scripts={name:contents[name].decode() for name in ('00-setup.sql','01-prepare.sql','02-apply.sql','03-restore.sql')}
    exists=settings.sql("SELECT COUNT(*) FROM information_schema.SCHEMATA WHERE SCHEMA_NAME='"+archive+"';",'admin').strip()=='1'
    if args.command=='prepare' and not exists:
        settings.sql(scripts['00-setup.sql'],'admin')
        exists=True
    if not exists:
        fail('BATCH_NOT_PREPARED','Archive does not exist yet','Run prepare first; it creates only the new archive and captures originals.')
    # Reject partial DDL, a foreign schema, or a mismatched control record.
    procedures=set(settings.sql("SELECT ROUTINE_NAME FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA='"+archive+"';",'admin').splitlines())
    expected=set(re.findall(r'CREATE PROCEDURE ([A-Za-z0-9_]+)\(',scripts['00-setup.sql']))
    if procedures!=expected:
        fail('PARTIAL_ARCHIVE','Archive procedures are incomplete or changed','Retain and inspect the partial archive; never drop/reuse it automatically. Generate a new batch if needed.')
    header=settings.sql(f'SELECT batch_key,source_schema,source_uuid FROM `{archive}`.batch WHERE id=1;','admin').strip().split('\t')
    if header!=[manifest['batch_key'],settings.schemas['characters'],manifest['source_uuid']]:
        fail('ARCHIVE_OWNERSHIP','Archive provenance differs from the selected batch')
    # Archive permissions are limited to the newly owned schema. Source table
    # write privileges stay an operator decision and are never granted here.
    principal=settings.sql("SELECT QUOTE(SUBSTRING_INDEX(CURRENT_USER(),'@',1)),QUOTE(SUBSTRING_INDEX(CURRENT_USER(),'@',-1));",'write').strip().split('\t')
    if len(principal)!=2:
        fail('WRITER_IDENTITY','Cannot establish the authenticated writer account')
    settings.sql(f"GRANT SELECT,INSERT,UPDATE,DELETE,EXECUTE ON `{archive}`.* TO {principal[0]}@{principal[1]};",'admin')
    action={'prepare':'01-prepare.sql','apply':'02-apply.sql','restore':'03-restore.sql'}[args.command]
    ack=manifest.get('ack_variable','talent_cleanup_ack')
    if ack not in ('talent_cleanup_ack','recovery_ack'):
        fail('INVALID_POLICY','Unknown cleanup acknowledgement variable')
    result=settings.sql(f"SET @{ack}='STOPPED_PREPARATION_COPY_ONLY';\n"+scripts[action],'write',headers=True)
    (work.operation/'result.tsv').write_text(result)
    status=settings.sql(contents['04-status.sql'].decode(),'write',headers=True)
    (work.operation/'status.tsv').write_text(status)
    print(result.strip()+'\nStatus: '+str(work.operation/'status.tsv'))


def command_status(settings,work,args):
    if args.batch:
        path,manifest=work.batch(args.batch)
        result=settings.sql(verify(path)['04-status.sql'].decode(),'write',headers=True)
        (work.operation/'status.tsv').write_text(result)
        print(result.rstrip())
        return
    print('Session: '+work.session.name+'\nApproval: UNREVIEWED')
    for directory in sorted((work.session/'batches').iterdir()):
        if not directory.is_dir():
            continue
        try:
            _,manifest=work.batch(directory.name)
            archive=identifier(manifest['archive_schema'])
            exists=settings.sql("SELECT COUNT(*) FROM information_schema.SCHEMATA WHERE SCHEMA_NAME='"+archive+"';",'admin').strip()=='1'
            state=settings.sql(f'SELECT state FROM `{archive}`.batch WHERE id=1;','write').strip() if exists else 'CANDIDATE'
            print(directory.name+'\t'+manifest.get('policy','')+'\t'+state)
        except (CleanupError,OSError,ValueError) as error:
            print(directory.name+'\tERROR\t'+settings.redact(str(error)))


def parser():
    result=argparse.ArgumentParser(description='Audit and reviewed reversible cleanup of a stopped TrinityCore preparation copy.')
    result.add_argument('--config',default=os.environ.get('MIGRATOR_CLEANUP_CONFIG','cleanup.ini'),help='Private INI file (default: ./cleanup.ini)')
    commands=result.add_subparsers(dest='command',required=True)
    init=commands.add_parser('init',help='Start a NEW session after importing fresh preparation databases; retain old sessions')
    init.add_argument('--label',default='')
    sessions=commands.add_parser('sessions',help='List retained sessions or explicitly select one for inspection/restore')
    sessions.add_argument('--use',help='Session ID; must match the configured server and schemas')
    audit=commands.add_parser('audit',help='Run read-only source audit; exit 1 means findings, not a failed audit')
    audit.add_argument('--scope',choices=('talents','all'),default='all')
    inspect=commands.add_parser('inspect-items',help='Report zero-entry containers and their contents; no item deletion')
    plans=commands.add_parser('plan',help='Generate private SQL and a reviewable manifest; no source writes')
    types=plans.add_subparsers(dest='kind',required=True)
    talents=types.add_parser('talents',help='Only verified TALENT_VALUE_IS_NOT_RANK_SPELL rows')
    talents.add_argument('--audit',help='Audit ID in this session; defaults to latest completed audit')
    talents.add_argument('--expect-rows',type=int,required=True)
    reset=types.add_parser('reset-talents',help='One character: archive unavailable group 1 and queue free native reset')
    reset.add_argument('--guid',type=int,required=True)
    items=types.add_parser('items',help='Recover exact contents of selected zero-entry containers to native mail')
    items.add_argument('--containers',required=True,help='Comma-separated container GUIDs from inspect-items')
    for name in ('prepare','apply','restore','status'):
        action=commands.add_parser(name,help={'prepare':'Set up archive and snapshot originals; source unchanged',
            'apply':'Execute the selected reviewed batch transaction','restore':'Exact inverse before gameplay/further changes',
            'status':'Query authoritative archive states; --batch shows detailed status'}[name])
        action.add_argument('--batch',help='Batch ID in this session; prepare/apply/restore default to the selected plan')
    return result


def main(argv=None):
    args=parser().parse_args(argv)
    os.umask(0o077)
    settings=work=None
    try:
        settings=Settings(args.config)
        work=Workspace(settings)
        with work.locked():
            if args.command not in ('init','sessions'):
                try:
                    work.current()
                except Exception:
                    work.session=None
                    work.begin(args.command)
                    raise
            work.begin(args.command)
            if args.command=='init':
                command_init(settings,work,args)
            elif args.command=='sessions':
                command_sessions(settings,work,args)
            else:
                work.check_identity()
                if args.command=='audit':
                    exit_code=command_audit(settings,work,args)
                    work.finish('COMPLETE',exit_code=exit_code)
                    return exit_code
                elif args.command=='plan':
                    command_plan(settings,work,args)
                elif args.command=='inspect-items':
                    from cleanup_plans import inspect_items
                    inspect_items(settings,work)
                elif args.command=='status':
                    command_status(settings,work,args)
                else:
                    command_action(settings,work,args)
            work.finish('COMPLETE',exit_code=0)
        return 0
    except (Exception,KeyboardInterrupt) as error:
        code=error.code if isinstance(error,CleanupError) else ('INTERRUPTED' if isinstance(error,KeyboardInterrupt) else 'CLEANUP_FAILED')
        message=str(error) or 'Operation interrupted; inspect archive state before retrying'
        hint=error.hint if isinstance(error,CleanupError) else 'Inspect the private error report; existing evidence was retained.'
        if settings:
            message,hint=settings.redact(message),settings.redact(hint)
        report={'code':code,'message':message,'hint':hint,'time_utc':now()}
        if work and work.operation:
            trace=traceback.format_exc()
            try:
                write_json(work.operation/'error.json',report)
                (work.operation/'traceback.txt').write_text(settings.redact(trace))
                work.finish('FAILED_OR_UNCERTAIN',error=report)
                report['report']=str(work.operation/'error.json')
            except (OSError,ValueError):
                report['report_error']='Cannot persist the error journal; check workspace permissions and free disk space.'
        print('ERROR '+json.dumps(report,sort_keys=True),file=sys.stderr)
        return 130 if isinstance(error,KeyboardInterrupt) else 2
