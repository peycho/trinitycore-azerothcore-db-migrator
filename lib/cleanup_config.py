"""Configuration validation and role-scoped MySQL client access."""

from __future__ import annotations

from collections.abc import Iterator
import configparser
from contextlib import contextmanager
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import uuid

from cleanup_errors import fail
from cleanup_files import PROFILE, identifier, private_dir, private_file, sha
from cleanup_types import Evidence


class Settings:
    """Validated operator configuration and role-scoped database access."""

    compatibility: Evidence
    connection: dict[str, str]
    file: Path
    ini: configparser.ConfigParser
    paths: dict[str, Path | None]
    schemas: dict[str, str]
    secrets: list[str]
    workspace: Path

    def __init__(self, filename: str | Path) -> None:
        self.file = Path(filename).expanduser().absolute()
        private_file(self.file)
        self.ini = configparser.ConfigParser(interpolation=None)
        try:
            self.ini.read_string(self.file.read_text())
        except configparser.Error as error:
            # Parser exception strings include raw input, which may contain
            # passwords.
            line = getattr(error, 'lineno', None)
            location = f' at line {line}' if isinstance(line, int) else ''
            section = getattr(error, 'section', None)
            option = getattr(error, 'option', None)
            safe_sections = {'workspace', 'source', 'target', 'paths',
                'safety', 'mysql', 'mysql_audit', 'mysql_admin'}
            safe_options = {'socket', 'host', 'port', 'user', 'password',
                'defaults_file'}
            if isinstance(error, configparser.DuplicateSectionError):
                label = f' [{section}]' if section in safe_sections else ''
                message = 'Duplicate INI section' + label + location
                hint = (
                    'Edit the existing section instead of appending a second '
                    'copy.')
            elif isinstance(error, configparser.DuplicateOptionError):
                label = f' {option}' if option in safe_options else ''
                group = f' in [{section}]' if section in safe_sections else ''
                message = 'Duplicate INI setting' + label + group + location
                hint = (
                    'Keep one entry for each setting in a section; '
                    'remove the obsolete entry.'
                )
            else:
                if not location:
                    lines = ([number for number, _ in getattr(error, 'errors',
                        []) if isinstance(number, int)])
                    if lines:
                        location = ' at line(s) ' + ', '.join(map(str, lines))
                message = ('Invalid INI configuration' + location
                    + '; values were omitted to protect credentials')
                hint = 'Use config/cleanup.ini.example as the format.'
            fail('CONFIG_SYNTAX', message, hint)
        allowed = {'workspace', 'source', 'target', 'paths', 'safety', 'mysql',
            'mysql_audit', 'mysql_admin'}
        if set(self.ini.sections()) - allowed:
            fail('CONFIG_UNKNOWN_SECTION', 'Unknown configuration section: '
                + ','.join(sorted(set(self.ini.sections()) - allowed)))
        fields = {
            'workspace': {'directory'}, 'source': {'core', 'characters',
                'auth', 'world', 'player_start_all_spells'},
            'target': {'world', 'player_start_custom_spells'},
            'paths': {'tc_dbc', 'ac_dbc', 'tc_source', 'ac_source'},
            'safety': {'preparation_copy', 'writers_stopped',
                'backup_reference'},
            'mysql': {'host', 'port', 'socket', 'user', 'password',
                'defaults_file', 'ssl_mode', 'connect_timeout'},
            'mysql_audit': {'user', 'password', 'defaults_file'},
            'mysql_admin': {'user', 'password', 'defaults_file'}}
        for section in self.ini.sections():
            unknown = set(self.ini[section]) - fields[section]
            if unknown:
                fail('CONFIG_UNKNOWN_SETTING',
                    f'Unknown setting in [{section}]: ' + ','.join(sorted(
                        unknown)))
        self.workspace = self.path('workspace', 'directory', required=True)
        self.schemas = ({key: identifier(self.get('source', key,
            required=True)) for key in ('characters', 'auth', 'world')})
        if len(set(self.schemas.values())) != 3:
            fail('CONFIG_SCHEMAS',
                'Auth, characters and world must be distinct schemas')
        if self.get('source', 'core', 'tc') != 'tc':
            fail('UNSUPPORTED_SOURCE',
                'Preparation cleanup currently supports TrinityCore '
                'sources only; AC paths are compatibility inputs, not an '
                'AC cleanup policy')
        if self.get('source', 'player_start_all_spells') not in ('', '0', '1'):
            fail('CONFIG_VALUE',
                '[source] player_start_all_spells must be blank, 0 or 1')
        self.paths = ({key: self.path('paths', key, required=key in ('tc_dbc',
            'tc_source')) for key in ('tc_dbc', 'ac_dbc', 'tc_source',
                'ac_source')})
        self.secrets = ([self.ini[s].get('password', '') for s in ('mysql',
            'mysql_audit', 'mysql_admin') if s in self.ini])
        self.secrets = [s for s in self.secrets if s]
        self.compatibility = {}
        self.connection = {'host': self.get('mysql', 'host', '127.0.0.1'),
            'port': self.get('mysql', 'port', '3306'), 'socket': self.get(
                'mysql', 'socket', '')}
        try:
            if not 1 <= int(self.connection['port']) <= 65535:
                raise ValueError()
        except ValueError:
            fail('CONFIG_PORT', 'MySQL port must be between 1 and 65535')
        if (self.connection['socket'] and self.connection['host'] not in (
            'localhost', '127.0.0.1', '::1')):
            fail('CONFIG_SOCKET_HOST',
                'A Unix socket requires a local MySQL host',
                'Use [mysql] host=localhost with the socket path, or '
                'clear socket to use TCP to the configured host.')

    def get(
        self,
        section: str,
        key: str,
        default: str = '',
        required: bool = False,
    ) -> str:
        value = self.ini.get(section, key, fallback=default)
        if required and not value:
            fail('CONFIG_MISSING', f'Missing [{section}] {key}')
        if '\x00' in value:
            fail('CONFIG_VALUE', 'NUL bytes are not supported in settings')
        return value

    def path(
        self,
        section: str,
        key: str,
        required: bool = False,
    ) -> Path | None:
        value = self.get(section, key, required=required)
        if not value:
            return None
        path = Path(os.path.expandvars(value)).expanduser()
        return ((self.file.parent / path).absolute() if not path.is_absolute()
            else path)

    def redact(self, value: str) -> str:
        for secret in self.secrets:
            value = value.replace(secret, '[REDACTED]')
        return value

    def safety(self) -> None:
        for key in ('preparation_copy', 'writers_stopped'):
            if self.get('safety', key).lower() not in ('yes', 'true', '1'):
                fail('PREPARATION_ACK_REQUIRED',
                    f'[safety] {key}=yes is required',
                    'Use only a stopped restored preparation copy; this '
                    'setting is your assertion, not service detection.')
        if not self.get('safety', 'backup_reference'):
            fail('BACKUP_REFERENCE_REQUIRED',
                'Set [safety] backup_reference to the retained verified '
                'backup identifier')

    def check_paths(self) -> None:
        for key, path in self.paths.items():
            if path and not path.is_dir():
                fail('PATH_MISSING',
                    f'Configured directory does not exist: {key}: {path}')
        for prefix, key in (('trinitycore', 'tc_source'), ('azerothcore',
            'ac_source')):
            base = self.paths[key]
            if base is None:
                continue
            manifests = {}
            for kind in ('sql', 'semantic'):
                manifest = PROFILE / (prefix + '-' + kind + '.sha256')
                manifests[manifest.name] = sha(manifest)
                for line in manifest.read_text().splitlines():
                    expected, relative = line.split(None, 1)
                    target = base / relative.strip()
                    if not target.is_file() or sha(target) != expected:
                        fail('CORE_PROFILE_MISMATCH',
                            f'{key}: protected content differs: '
                            f'{relative}',
                            'Use the reviewed checkout or establish '
                            'compatibility; pins and release approval '
                            'are not changed by this tool.')
            revision = None
            if shutil.which('git'):
                result = subprocess.run(['git', '--no-optional-locks', '-C',
                    str(base), 'rev-parse', 'HEAD'], text=True,
                    capture_output=True)
                if (result.returncode == 0 and re.fullmatch('[0-9a-f]{40,64}',
                    result.stdout.strip())):
                    revision = result.stdout.strip()
            self.compatibility[key] = {'path': str(base),
                'actual_revision': revision,
                'protected_content': 'MATCH', 'manifest_sha256': manifests}

    @contextmanager
    def client(self, role: str) -> Iterator[list[str]]:
        """Yield role-specific arguments backed by a private temporary
        option file.
        """
        section = ({'audit': 'mysql_audit', 'admin': 'mysql_admin',
            'write': 'mysql'} [role])
        selected = section if section in self.ini else 'mysql'
        defaults = self.get(selected, 'defaults_file')
        # A separately configured role does not accidentally inherit the main
        # password.
        if defaults:
            source = self.path(selected, 'defaults_file')
            private_file(source)
            content = source.read_text()
            for line in content.splitlines():
                match = re.match('\\s*password\\s*=\\s*(.*)', line, re.I)
                if match and match[1].strip('"\''):
                    self.secrets.extend((match[1], match[1].strip('"\'')))
        else:
            def quote(value: str) -> str:
                return ('"' + value.replace('\\', '\\\\').replace('"',
                    '\\"').replace('\n', '\\n').replace('\r', '\\r').replace(
                        '\t', '\\t') + '"')
            user = self.get(selected, 'user', required=True)
            content = ('[client]\nuser=' + quote(user) + '\npassword=' + quote(
                self.get(selected, 'password')) + '\n')
        secrets_dir = self.workspace / '.credentials'
        private_dir(secrets_dir)
        fd, filename = tempfile.mkstemp(prefix='mysql-', suffix='.cnf',
            dir=secrets_dir)
        try:
            with os.fdopen(fd, 'w') as stream:
                stream.write(content)
            args = ['--defaults-file=' + filename,
                '--connect-timeout=' + self.get('mysql', 'connect_timeout',
                    '10')]
            if self.connection['socket']:
                # libmysql rejects SOCKET with a numeric host as error 2047.
                args += ['--host=localhost', '--socket=' + self.connection[
                    'socket'], '--protocol=SOCKET']
            else:
                args += ['--host=' + self.connection['host'],
                    '--port=' + str(int(self.connection['port'])),
                    '--protocol=TCP']
            mode = self.get('mysql', 'ssl_mode')
            if mode:
                args += ['--ssl-mode=' + mode]
            yield args
        finally:
            Path(filename).unlink(missing_ok=True)

    def sql(
        self,
        query: str,
        role: str = 'audit',
        headers: bool = False,
    ) -> str:
        if not shutil.which('mysql'):
            fail('MYSQL_CLIENT_MISSING',
                'mysql executable is not available in PATH',
                'Install MySQL 8 client tools, then retry this command.')
        with self.client(role) as args:
            args += ['--batch', '--raw', '--skip-force',
                '--default-character-set=utf8mb4']
            if not headers:
                args += ['--skip-column-names']
            if role == 'audit':
                args += ['--init-command=SET SESSION transaction_read_only=ON']
            environment = os.environ.copy()
            environment.pop('MYSQL_PWD', None)
            result = subprocess.run(['mysql', *args], input=query, text=True,
                capture_output=True, env=environment)
            if result.returncode:
                fail('MYSQL_FAILED', self.redact(result.stderr.strip()),
                    'No automatic retry or guard bypass was attempted. '
                    'Check grants, endpoint and batch state; status can '
                    'reconcile a disconnected operation.')
            # These statements never select credentials. Redacting ordinary
            # query data could change GUIDs/JSON when a short password happens
            # to match a data value. Only diagnostics are secret-redacted.
            return result.stdout

    def identity(self, role: str = 'audit') -> Evidence:
        row = self.sql('SELECT @@server_uuid,@@version;', role).strip().split(
            '\t')
        if len(row) != 2 or not row[1].startswith('8.4.'):
            fail('MYSQL_VERSION', 'Cleanup requires MySQL 8.4.x')
        return {'uuid': str(uuid.UUID(row[0])), 'version': row[1],
            'schemas': self.schemas, 'connection': self.connection}

    def validate_schemas(self) -> None:
        names = ','.join("'" + name + "'" for name in self.schemas.values())
        visible = set(self.sql(
            'SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE '
            f'SCHEMA_NAME IN ({names});').splitlines())
        missing = sorted(set(self.schemas.values()) - visible)
        if missing:
            fail('CONFIG_SCHEMA_UNAVAILABLE',
                'Configured schemas are missing or inaccessible: ' + ', '.join(
                    missing),
                'Check [source] spelling and the audit account SELECT '
                'grants. After changing schemas, run init for a new '
                'session.')
