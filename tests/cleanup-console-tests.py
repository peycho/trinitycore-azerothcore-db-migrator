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

    def test_duplicate_socket_reports_setting_section_and_line_without_connecting(self):
        self.config.write_text('[mysql]\nsocket=/var/run/mysqld/mysqld.sock\nsocket=\n')
        errors=io.StringIO()
        with patch.object(console.subprocess,'run') as run,redirect_stderr(errors):
            self.assertEqual(console.main(['--config',str(self.config),'prepare']),2)
        run.assert_not_called()
        report=json.loads(errors.getvalue().removeprefix('ERROR '))
        self.assertEqual(report['code'],'CONFIG_SYNTAX')
        self.assertEqual(report['message'],'Duplicate INI setting socket in [mysql] at line 3')
        self.assertIn('Keep one entry',report['hint'])

    def test_duplicate_section_is_identified_without_values(self):
        self.config.write_text('[mysql_admin]\npassword=SECRET-HIDDEN\n[mysql_admin]\n')
        with self.assertRaises(console.CleanupError) as raised:
            self.settings()
        self.assertEqual(str(raised.exception),'Duplicate INI section [mysql_admin] at line 3')
        self.assertNotIn('SECRET-HIDDEN',str(raised.exception)+raised.exception.hint)

    def test_ini_syntax_errors_never_echo_unrecognized_names_or_input(self):
        cases=(
            ('[SECRET-HIDDEN]\n[SECRET-HIDDEN]\n','Duplicate INI section at line 2'),
            ('[mysql]\nSECRET-HIDDEN=one\nSECRET-HIDDEN=two\n','Duplicate INI setting in [mysql] at line 3'),
            ('[mysql]\nSECRET-HIDDEN\n','at line(s) 2'),
            ('SECRET-HIDDEN\n','at line 1'),
        )
        for text,expected in cases:
            with self.subTest(text=text):
                self.config.write_text(text)
                with self.assertRaises(console.CleanupError) as raised:
                    self.settings()
                self.assertEqual(raised.exception.code,'CONFIG_SYNTAX')
                self.assertIn(expected,str(raised.exception))
                self.assertNotIn('SECRET-HIDDEN',str(raised.exception)+raised.exception.hint)

    def test_single_socket_entry_selects_socket_for_all_roles(self):
        with self.config.open('a') as stream:
            stream.write('[mysql_admin]\nuser=root\npassword=\n')
        self.config.write_text(self.config.read_text().replace('[mysql]\n','[mysql]\nsocket=/var/run/mysqld/mysqld.sock\n'))
        settings=self.settings()
        console.private_dir(settings.workspace)
        for role in ('write','audit','admin'):
            with self.subTest(role=role),settings.client(role) as args:
                self.assertIn('--socket=/var/run/mysqld/mysqld.sock',args)
                self.assertIn('--host=localhost',args)
                self.assertEqual([arg for arg in args if arg.startswith('--protocol=')],['--protocol=SOCKET'])
                self.assertFalse(any(arg.startswith('--port=') for arg in args))

    def test_tcp_arguments_retain_host_and_port(self):
        settings=self.settings()
        console.private_dir(settings.workspace)
        with settings.client('write') as args:
            self.assertIn('--host=127.0.0.1',args)
            self.assertIn('--port=3306',args)
            self.assertEqual([arg for arg in args if arg.startswith('--protocol=')],['--protocol=TCP'])
            self.assertFalse(any(arg.startswith('--socket=') for arg in args))

    def test_socket_with_remote_host_is_rejected_before_connecting(self):
        self.config.write_text(self.config.read_text().replace('[mysql]\n',
            '[mysql]\nhost=database.example.invalid\nsocket=/tmp/local.sock\n'))
        with self.assertRaises(console.CleanupError) as raised:
            self.settings()
        self.assertEqual(raised.exception.code,'CONFIG_SOCKET_HOST')

    @unittest.skipUnless(console.shutil.which('mysql'),'MySQL client is not installed')
    def test_real_client_uses_missing_local_socket_instead_of_error_2047(self):
        # This path cannot be an operator socket; no server is needed or contacted.
        sock=self.root/'absent.sock'
        self.config.write_text(self.config.read_text().replace('[mysql]\n',f'[mysql]\nsocket={sock}\n'))
        settings=self.settings()
        console.private_dir(settings.workspace)
        with settings.client('write') as args:
            result=subprocess.run(['mysql',*args,'--execute=SELECT 1;'],capture_output=True,text=True,timeout=5)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('ERROR 2002',result.stderr)
        self.assertNotIn('ERROR 2047',result.stderr)

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

    def test_connection_change_reports_fields_and_keeps_session_guard(self):
        settings=self.settings()
        work=console.Workspace(settings)
        expected={'uuid':'test-uuid','version':'8.4.10','schemas':settings.schemas,
                  'connection':dict(settings.connection)}
        actual={**expected,'connection':{**expected['connection'],'host':'localhost','socket':'/tmp/test.sock'}}
        session={'identity':expected}
        with patch.object(work,'current',return_value=session),patch.object(settings,'identity',return_value=actual):
            with self.assertRaises(console.CleanupError) as raised:
                work.check_identity()
        self.assertEqual(raised.exception.code,'SESSION_ENDPOINT_CHANGED')
        self.assertEqual(str(raised.exception),'Session identity changed: connection.host, connection.socket')
        self.assertIn('console init',raised.exception.hint)
        self.assertIn('does not require a database reimport',raised.exception.hint)
        self.assertEqual(session['identity']['connection']['socket'],'')

    def test_matching_session_identity_is_accepted(self):
        settings=self.settings()
        work=console.Workspace(settings)
        session={'identity':{'uuid':'test-uuid','version':'8.4.10','schemas':settings.schemas,
                            'connection':settings.connection}}
        with patch.object(work,'current',return_value=session),patch.object(settings,'identity',return_value=session['identity']):
            self.assertIs(work.check_identity(),session)

    def test_missing_session_retains_an_early_error_report(self):
        with redirect_stderr(io.StringIO()):
            self.assertEqual(console.main(['--config',str(self.config),'apply']),2)
        report=next((self.root/'work/operations').glob('*/error.json'))
        self.assertEqual(json.loads(report.read_text())['code'],'SESSION_REQUIRED')

    def test_missing_toolkit_template_has_precise_persisted_error_before_mysql(self):
        original=Path.is_file
        missing=console.ROOT/'tools/skill-cleanup.sql.in'
        errors=io.StringIO()
        with patch.object(Path,'is_file',lambda path:False if path==missing else original(path)), \
                patch.object(console.subprocess,'run') as run,redirect_stderr(errors):
            self.assertEqual(console.main(['--config',str(self.config),'init']),2)
        run.assert_not_called()
        report=json.loads(errors.getvalue().removeprefix('ERROR '))
        self.assertEqual(report['code'],'TOOLKIT_INCOMPLETE')
        self.assertIn('tools/skill-cleanup.sql.in',report['message'])
        self.assertNotIn('report_error',report)
        saved=Path(report['report'])
        self.assertEqual(json.loads(saved.read_text())['code'],'TOOLKIT_INCOMPLETE')
        self.assertEqual(json.loads(saved.with_name('operation.json').read_text())['state'],'FAILED_OR_UNCERTAIN')
        self.assertNotIn(self.secret,errors.getvalue()+saved.with_name('traceback.txt').read_text())

    def test_unreadable_toolkit_template_reports_file_without_raw_error_details(self):
        original=console.sha
        unreadable=console.ROOT/'tools/skill-cleanup.sql.in'
        def read(path):
            if path==unreadable:
                raise PermissionError('Do not echo arbitrary error context '+self.secret)
            return original(path)
        errors=io.StringIO()
        with patch.object(console,'sha',side_effect=read),redirect_stderr(errors):
            self.assertEqual(console.main(['--config',str(self.config),'init']),2)
        report=json.loads(errors.getvalue().removeprefix('ERROR '))
        self.assertEqual(report['code'],'TOOLKIT_FILE_UNREADABLE')
        self.assertNotIn('report_error',report)
        self.assertIn('tools/skill-cleanup.sql.in',report['message'])
        self.assertNotIn(self.secret,errors.getvalue()+Path(report['report']).with_name('traceback.txt').read_text())

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
