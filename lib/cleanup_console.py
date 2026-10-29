"""Compatibility facade and error boundary for the cleanup console."""

from __future__ import annotations

from collections.abc import Sequence
import json
import os
import shutil
import subprocess
import sys
import traceback

from cleanup_actions import command_action
from cleanup_arguments import parser
from cleanup_commands import (
    check_audit_result,
    command_audit,
    command_init,
    command_plan,
    command_sessions,
    command_status,
)
from cleanup_config import Settings
from cleanup_errors import CleanupError, fail
from cleanup_files import (
    PROFILE,
    ROOT,
    identifier,
    load_module,
    local_id,
    now,
    private_dir,
    private_file,
    seal,
    sha,
    token,
    toolkit_hashes,
    verify,
    write_json,
)
from cleanup_workspace import Workspace


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    os.umask(0o077)
    settings = work = None
    try:
        settings = Settings(args.config)
        work = Workspace(settings)
        with work.locked():
            if args.command not in ('init', 'sessions'):
                try:
                    work.current()
                except Exception:
                    work.session = None
                    work.begin(args.command)
                    raise
            work.begin(args.command)
            if args.command == 'init':
                command_init(settings, work, args)
            elif args.command == 'sessions':
                command_sessions(settings, work, args)
            else:
                work.check_identity()
                if args.command == 'audit':
                    exit_code = command_audit(settings, work, args)
                    work.finish('COMPLETE', exit_code=exit_code)
                    return exit_code
                elif args.command == 'plan':
                    command_plan(settings, work, args)
                elif args.command == 'inspect-items':
                    from cleanup_plans import inspect_items
                    inspect_items(settings, work)
                elif args.command == 'inspect-spell-history':
                    from cleanup_spell_history import inspect_history
                    inspect_history(settings, work, args)
                elif args.command == 'inspect-migration-blockers':
                    from cleanup_migration_evidence import inspect
                    inspect(settings, work, args)
                elif args.command == 'status':
                    command_status(settings, work, args)
                else:
                    command_action(settings, work, args)
            work.finish('COMPLETE', exit_code=0)
        return 0
    except (Exception, KeyboardInterrupt) as error:
        code = (error.code if isinstance(error, CleanupError) else(
            'INTERRUPTED' if isinstance(error, KeyboardInterrupt)
            else 'CLEANUP_FAILED'))
        message = (str(error)
            or 'Operation interrupted; inspect archive state before retrying')
        hint = error.hint if isinstance(error, CleanupError) else (
            'Inspect the private error report; existing evidence was '
            'retained.'
        )
        if settings:
            message, hint = settings.redact(message), settings.redact(hint)
        report = {'code': code, 'message': message, 'hint': hint,
            'time_utc': now()}
        if work and work.operation:
            trace = traceback.format_exc()
            try:
                write_json(work.operation / 'error.json', report)
                (work.operation / 'traceback.txt').write_text(settings.redact(
                    trace))
                work.finish('FAILED_OR_UNCERTAIN', error=report)
                report['report'] = str(work.operation / 'error.json')
            except (OSError, ValueError):
                report['report_error'] = (
                    'Cannot persist the error journal; check workspace '
                    'permissions and free disk space.'
                )
        print('ERROR ' + json.dumps(report, sort_keys=True), file=sys.stderr)
        return 130 if isinstance(error, KeyboardInterrupt) else 2
