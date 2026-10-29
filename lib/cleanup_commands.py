"""Console command handlers for sessions, audits and planning."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
from typing import TYPE_CHECKING

from cleanup_errors import CleanupError, fail
from cleanup_files import (
    ROOT,
    identifier,
    local_id,
    now,
    private_dir,
    token,
    verify,
    write_json,
)
from cleanup_types import Evidence

if TYPE_CHECKING:
    from cleanup_config import Settings
    from cleanup_workspace import Workspace


def command_init(
    settings: Settings,
    work: Workspace,
    args: argparse.Namespace,
) -> None:
    settings.safety()
    settings.check_paths()
    identity = settings.identity()
    settings.validate_schemas()
    private_dir(work.root / 'sessions')
    session_id = token('session')
    work.session = work.root / 'sessions' / session_id
    private_dir(work.session)
    for folder in ('audits', 'batches', 'inspections', 'operations'):
        private_dir(work.session / folder)
    write_json(work.session / 'session.json', {'session': session_id,
        'label': args.label, 'created_utc': now(),
        'identity': identity, 'backup_reference': settings.get('safety',
            'backup_reference'),
        'paths': {key: str(value) if value else None for key, value
            in settings.paths.items()},
        'core_compatibility': settings.compatibility,
        'profile': 'tc335-acwotlk-v2', 'profile_approval': 'UNREVIEWED'})
    write_json(work.root / 'current.json', {'session': session_id})
    print('SESSION ' + session_id + '\nWorkspace: ' + str(work.session))


def check_audit_result(
    settings: Settings,
    work: Workspace,
    output: Path,
    returncode: int,
    stderr: str,
) -> Evidence:
    """Classify the child result before treating its progress stream as
    errors.
    """
    report = output / 'audit.json'
    status = None
    invalid_report = False
    if report.exists():
        try:
            status = json.loads(report.read_text())
            if not isinstance(status, dict):
                invalid_report = True
                status = None
        except (OSError, ValueError):
            invalid_report = True
    details = {'child_exit_code': returncode, 'reports': str(output),
        'audit_status': status.get('status') if status else None,
        'limitations': status.get('limitations') if status else None,
        'audit_error': settings.redact(str(status.get('error', '')))
        if status else None}
    write_json(work.operation / 'audit-result.json', details)
    hint = ('Inspect ' + str(report) + ' and ' + str(
        work.operation / 'audit.stderr.txt') + '. No cleanup was performed.')
    if returncode < 0:
        try:
            name = signal.Signals(-returncode).name
        except ValueError:
            name = 'signal ' + str(-returncode)
        fail('AUDIT_PROCESS_TERMINATED',
            f'Audit child terminated by {name}; its report is not '
            'accepted.',
            hint)
    if invalid_report:
        fail('AUDIT_REPORT_INVALID',
            'Audit child produced an unreadable or malformed audit.json', hint)
    if status is not None:
        limitations = status.get('limitations')
        if isinstance(limitations, list) and limitations:
            description = '; '.join(settings.redact(str(value)) for value
                in limitations[:8])
            fail('AUDIT_COVERAGE_INCOMPLETE',
                f'Audit finished with {len(limitations)} coverage '
                'limitation(s): ' + description,
                'Inspect ' + str(report)
                + ' and coverage.tsv. Correct missing inputs/grants; '
                'initialize a new session if schema names change. No '
                'cleanup was performed.')
        if status.get('status') != 'COMPLETE' or limitations != []:
            message = (status.get('error') or 'Audit status is ' + str(
                status.get('status')))
            fail('AUDIT_INCOMPLETE', settings.redact(str(message)), hint)
        if returncode in (0, 1):
            return status
    diagnostic = ([line for line in stderr.splitlines() if line
        and not line.startswith(('Auditing ', 'Audited '))])
    message = (f'Audit child exited with status {returncode}' + (
        ' without audit.json' if status is None
        else ' despite its report status'))
    if diagnostic:
        message += ': ' + '\n'.join(diagnostic[-8:])[-2048:]
    fail('AUDIT_INCOMPLETE', settings.redact(message), hint)


def command_audit(
    settings: Settings,
    work: Workspace,
    args: argparse.Namespace,
) -> int:
    settings.validate_schemas()
    audit_id = token(args.scope)
    output = work.session / 'audits' / audit_id
    with settings.client('audit') as connection:
        command = [sys.executable, str(ROOT / 'tools/audit-tc-source.py'),
            '--characters-schema', settings.schemas['characters'],
            '--auth-schema', settings.schemas['auth'],
            '--world-schema', settings.schemas['world'], '--tc-dbc', str(
                settings.paths['tc_dbc']),
            '--scope', args.scope, '--output', str(output), '--mysql',
            *connection]
        environment = os.environ.copy()
        environment.pop('MYSQL_PWD', None)
        print('Running read-only ' + args.scope + ' audit; reports: ' + str(
            output), flush=True)
        with tempfile.TemporaryFile(mode='w+') as captured:
            process = subprocess.Popen(command, text=True, stdout=captured,
                stderr=subprocess.PIPE, env=environment)
            errors = []
            try:
                for line in process.stderr:
                    safe = settings.redact(line)
                    errors.append(safe)
                    print(safe.rstrip(), file=sys.stderr, flush=True)
                returncode = process.wait()
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait()
            captured.seek(0)
            stdout = settings.redact(captured.read())
    (work.operation / 'audit.stdout.txt').write_text(stdout)
    (work.operation / 'audit.stderr.txt').write_text(''.join(errors))
    check_audit_result(settings, work, output, returncode, ''.join(errors))
    write_json(work.session / 'latest-audit.json', {'audit': audit_id})
    print('AUDIT ' + audit_id + '\n' + (output / 'summary.tsv').read_text(
    ).rstrip() + '\nReports: ' + str(output))
    return returncode


def command_sessions(
    settings: Settings,
    work: Workspace,
    args: argparse.Namespace,
) -> None:
    if args.use:
        session = work.root / 'sessions' / local_id(args.use)
        if not session.is_dir() or session.is_symlink():
            fail('SESSION_MISSING', 'Requested session does not exist')
        data = json.loads((session / 'session.json').read_text())
        if data['identity'] != settings.identity():
            fail('SESSION_ENDPOINT_CHANGED',
                'Requested session does not match the configured server '
                'and schemas')
        write_json(work.root / 'current.json', {'session': session.name})
    base = work.root / 'sessions'
    current = (json.loads((work.root / 'current.json').read_text())['session']
        if (work.root / 'current.json').exists() else '')
    if base.exists():
        for session in sorted(base.iterdir()):
            if session.is_dir() and not session.is_symlink():
                data = json.loads((session / 'session.json').read_text())
                print(('* ' if session.name == current else '  ')
                    + session.name + '\t' + data.get('label', ''))


def command_plan(
    settings: Settings,
    work: Workspace,
    args: argparse.Namespace,
) -> None:
    from cleanup_plans import plan
    settings.safety()
    settings.check_paths()
    batch_id = token(args.kind)
    output = work.session / 'batches' / batch_id
    if plan(settings, work, args, output) is False:
        # Explicit read-only preview creates no package or active-batch
        # pointer.
        return
    write_json(work.session / 'active-batch.json', {'batch': batch_id})
    manifest = json.loads((output / 'manifest.json').read_text())
    print('CANDIDATE ' + batch_id + '\nArchive: ' + manifest['archive_schema']
        + '\nReview: ' + str(output / 'README.md'))


def command_status(
    settings: Settings,
    work: Workspace,
    args: argparse.Namespace,
) -> None:
    if args.batch:
        path, manifest = work.batch(args.batch)
        result = settings.sql(verify(path)['04-status.sql'].decode(), 'write',
            headers=True)
        (work.operation / 'status.tsv').write_text(result)
        print(result.rstrip())
        return
    print('Session: ' + work.session.name + '\nApproval: UNREVIEWED')
    for directory in sorted((work.session / 'batches').iterdir()):
        if not directory.is_dir():
            continue
        try:
            _, manifest = work.batch(directory.name)
            archive = identifier(manifest['archive_schema'])
            exists = settings.sql(
                'SELECT COUNT(*) FROM information_schema.SCHEMATA WHERE '
                "SCHEMA_NAME='" + archive + "';", 'admin').strip(
                ) == '1'
            state = (settings.sql(
                f'SELECT state FROM `{archive}`.batch WHERE id=1;',
                'write').strip() if exists else 'CANDIDATE')
            print(directory.name + '\t' + manifest.get('policy', '') + '\t'
                + state)
        except (CleanupError, OSError, ValueError) as error:
            print(directory.name + '\tERROR\t' + settings.redact(str(error)))
