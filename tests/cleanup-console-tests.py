#!/usr/bin/env python3
"""Fast cleanup console configuration, secret and workspace boundary tests."""
from contextlib import redirect_stderr
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'lib'))
import cleanup_console as console


class ConsoleTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.config=self.root/'cleanup.ini'
        self.secret='literal%password;#"\\value'
        self.config.write_text(f'''[workspace]
directory=work
[source]
characters=tc_chars
auth=tc_auth
world=tc_world
[paths]
tc_dbc=dbc
tc_source=tc
[mysql]
user=test_writer
password={self.secret}
[safety]
preparation_copy=yes
writers_stopped=yes
backup_reference=verified-backup-01
''')
        self.config.chmod(0o600)

    def tearDown(self):
        self.temp.cleanup()

    def settings(self):
        return console.Settings(self.config)

    def test_relative_paths_and_literal_password(self):
        settings=self.settings()
        self.assertEqual(settings.workspace,self.root/'work')
        self.assertEqual(settings.paths['tc_dbc'],self.root/'dbc')
        self.assertEqual(settings.get('mysql','password'),self.secret)

    def test_private_config_required(self):
        self.config.chmod(0o644)
        with self.assertRaisesRegex(console.CleanupError,'private file'):
            self.settings()

    def test_unknown_settings_do_not_silently_disable_guards(self):
        with self.config.open('a') as stream:
            stream.write('writers_stoped=yes\n')
        with self.assertRaisesRegex(console.CleanupError,'Unknown setting'):
            self.settings()

    def test_bad_ini_never_echoes_password_line(self):
        self.config.write_text('[mysql]\npassword=first\npassword=SECRET-HIDDEN\n')
        errors=io.StringIO()
        with redirect_stderr(errors):
            self.assertEqual(console.main(['--config',str(self.config),'init']),2)
        self.assertNotIn('SECRET-HIDDEN',errors.getvalue())
        self.assertIn('CONFIG_SYNTAX',errors.getvalue())

    def test_credentials_are_private_temporary_files_and_not_arguments(self):
        settings=self.settings()
        console.private_dir(settings.workspace)
        with settings.client('write') as args:
            self.assertNotIn(self.secret,' '.join(args))
            filename=Path(args[0].split('=',1)[1])
            self.assertEqual(filename.stat().st_mode&0o777,0o600)
            self.assertIn('password="literal%password;#\\"\\\\value"',filename.read_text())
        self.assertFalse(filename.exists())

    def test_role_passwords_are_not_inherited(self):
        with self.config.open('a') as stream:
            stream.write('[mysql_audit]\nuser=reader\npassword=read-only-secret\n')
        settings=self.settings()
        console.private_dir(settings.workspace)
        with settings.client('audit') as args:
            text=Path(args[0].split('=',1)[1]).read_text()
            self.assertIn('read-only-secret',text)
            self.assertNotIn(self.secret,text)

    def test_missing_safety_assertions_block_mutating_workflow(self):
        self.config.write_text(self.config.read_text().replace('writers_stopped=yes','writers_stopped=no'))
        with self.assertRaisesRegex(console.CleanupError,'writers_stopped'):
            self.settings().safety()

    def test_external_client_file_secrets_and_empty_password_redaction(self):
        client=self.root/'client.cnf'
        client.write_text('[client]\nuser=reader\npassword="external-secret"\n')
        client.chmod(0o600)
        with self.config.open('a') as stream:
            stream.write('[mysql_audit]\ndefaults_file=client.cnf\n')
        settings=self.settings()
        console.private_dir(settings.workspace)
        with settings.client('audit'):
            self.assertNotIn('external-secret',settings.redact('external-secret'))
        client.write_text('[client]\nuser=reader\npassword=""\n')
        settings=self.settings()
        with settings.client('audit'):
            self.assertEqual(settings.redact('ordinary report'),'ordinary report')
            self.assertEqual(settings.redact('{"value":""}'),'{"value":""}')

    def test_mysql_errors_are_redacted_and_reported_without_inline_credentials(self):
        settings=self.settings()
        console.private_dir(settings.workspace)
        failure=subprocess.CompletedProcess([],1,'','Access denied '+self.secret)
        with patch.object(console.subprocess,'run',return_value=failure) as run:
            with self.assertRaises(console.CleanupError) as raised:
                settings.sql('SELECT 1;')
        self.assertNotIn(self.secret,str(raised.exception))
        self.assertIn('[REDACTED]',str(raised.exception))
        self.assertNotIn(self.secret,' '.join(run.call_args.args[0]))
        self.assertIn('--init-command=SET SESSION transaction_read_only=ON',run.call_args.args[0])

    def test_missing_mysql_client_has_actionable_error(self):
        settings=self.settings()
        with patch.object(console.shutil,'which',return_value=None):
            with self.assertRaises(console.CleanupError) as raised:
                settings.sql('SELECT 1;')
        self.assertEqual(raised.exception.code,'MYSQL_CLIENT_MISSING')

    def test_credential_redaction_does_not_corrupt_matching_query_data(self):
        self.config.write_text(self.config.read_text().replace(self.secret,'1'))
        settings=self.settings()
        console.private_dir(settings.workspace)
        result=subprocess.CompletedProcess([],0,'{"guid":1}\n','')
        with patch.object(console.subprocess,'run',return_value=result):
            self.assertEqual(settings.sql('SELECT JSON_OBJECT("guid",1);'),'{"guid":1}\n')

    def test_failed_operation_keeps_structured_redacted_evidence(self):
        failure=subprocess.CompletedProcess([],1,'','Rejected '+self.secret)
        errors=io.StringIO()
        with patch.object(console.Settings,'check_paths'),patch.object(console.subprocess,'run',return_value=failure),redirect_stderr(errors):
            result=console.main(['--config',str(self.config),'init'])
        self.assertEqual(result,2)
        report=next((self.root/'work/operations').glob('*/error.json'))
        self.assertEqual(json.loads(report.read_text())['code'],'MYSQL_FAILED')
        self.assertNotIn(self.secret,errors.getvalue()+report.read_text()+report.with_name('traceback.txt').read_text())
        self.assertEqual(json.loads(report.with_name('operation.json').read_text())['state'],'FAILED_OR_UNCERTAIN')

    def test_workspace_lock_rejects_parallel_commands(self):
        settings=self.settings()
        first,second=console.Workspace(settings),console.Workspace(settings)
        with first.locked():
            with self.assertRaisesRegex(console.CleanupError,'workspace lock'):
                with second.locked():
                    pass

    def test_missing_session_retains_an_early_error_report(self):
        with redirect_stderr(io.StringIO()):
            self.assertEqual(console.main(['--config',str(self.config),'apply']),2)
        report=next((self.root/'work/operations').glob('*/error.json'))
        self.assertEqual(json.loads(report.read_text())['code'],'SESSION_REQUIRED')

    def test_sealed_packages_reject_changes_extra_files_and_symlinks(self):
        package=self.root/'batch'
        package.mkdir()
        (package/'manifest.json').write_text('{}')
        console.seal(package)
        console.verify(package)
        (package/'manifest.json').write_text('changed')
        with self.assertRaises(console.CleanupError): console.verify(package)
        console.seal(package)
        (package/'extra.sql').write_text('SELECT 1')
        with self.assertRaises(console.CleanupError): console.verify(package)
        (package/'extra.sql').unlink()
        target=package/'manifest.json'
        target.unlink()
        target.symlink_to(self.config)
        with self.assertRaises(console.CleanupError): console.verify(package)

    def test_ids_and_schema_arguments_cannot_escape_workspace_or_sql(self):
        for text in ('../previous','a/b','a`; DROP DATABASE x;',''):
            with self.assertRaises(console.CleanupError): console.local_id(text)
            with self.assertRaises(console.CleanupError): console.identifier(text)

    def test_private_atomic_json_and_marker_refusal(self):
        path=self.root/'state.json'
        console.write_json(path,{'state':'COMPLETE'})
        self.assertEqual(path.stat().st_mode&0o777,0o600)
        package=self.root/'batch'
        package.mkdir()
        (package/'INCOMPLETE').touch()
        with self.assertRaisesRegex(console.CleanupError,'Incomplete'): console.verify(package)


if __name__=='__main__':
    unittest.main()
