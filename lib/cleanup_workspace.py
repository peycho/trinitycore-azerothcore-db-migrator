"""Locked cleanup sessions, operation journals and sealed batch lookup."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import fcntl
import json
from pathlib import Path
from typing import Any, TYPE_CHECKING

from cleanup_errors import fail
from cleanup_files import (
    local_id,
    now,
    private_dir,
    token,
    toolkit_hashes,
    verify,
    verify_implementation_hashes,
    write_json,
)
from cleanup_types import DatabaseState, Evidence

if TYPE_CHECKING:
    from cleanup_config import Settings


class Workspace:
    """Private session state and operation journals under an exclusive lock."""

    operation: Path | None
    root: Path
    session: Path | None
    settings: Settings

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.root = settings.workspace
        self.session = None
        self.operation = None

    @contextmanager
    def locked(self) -> Iterator[None]:
        """Hold the exclusive workspace lock for the duration of a command."""
        private_dir(self.root)
        lock = self.root / '.lock'
        if lock.is_symlink():
            fail('SYMLINK_REFUSED', 'Workspace lock cannot be a symlink')
        with lock.open('a') as stream:
            lock.chmod(0o600)
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                fail('WORKSPACE_BUSY',
                    'Another cleanup command holds this workspace lock')
            yield

    def current(self) -> Evidence:
        pointer = (json.loads((self.root / 'current.json').read_text()) if (
            self.root / 'current.json').exists() else None)
        if not pointer:
            fail('SESSION_REQUIRED', 'No cleanup session is selected',
                'Run console init after importing the stopped '
                'preparation databases.')
        self.session = self.root / 'sessions' / local_id(pointer['session'])
        if not self.session.is_dir():
            fail('SESSION_MISSING',
                'Selected session directory is missing; evidence was not '
                'recreated')
        private_dir(self.session)
        return json.loads((self.session / 'session.json').read_text())

    def begin(self, command: str) -> None:
        base = ((self.session / 'operations') if self.session
            else self.root / 'operations')
        private_dir(base)
        self.operation = base / token(command)
        private_dir(self.operation)
        # Persist the journal before checking toolkit completeness, so a
        # missing
        # runtime/template still produces a usable error report and final
        # state.
        entry: OperationReport = {'command': command, 'state': 'STARTED',
            'started_utc': now()}
        write_json(self.operation / 'operation.json', entry)
        entry['toolkit_sha256'] = toolkit_hashes()
        write_json(self.operation / 'operation.json', entry)

    def finish(self, state: DatabaseState, **details: Any) -> None:
        if self.operation:
            item = json.loads((self.operation / 'operation.json').read_text())
            item.update(state=state, finished_utc=now(), **details)
            write_json(self.operation / 'operation.json', item)

    def check_identity(self, role: str = 'audit') -> Evidence:
        session = self.current()
        actual = self.settings.identity(role)
        if actual != session['identity']:
            expected = session['identity']
            changed = ([key for key in ('uuid', 'version') if actual.get(key)
                != expected.get(key)])
            for group, keys in (('schemas', ('characters', 'auth', 'world')), (
                'connection', ('host', 'port', 'socket'))):
                changed.extend(group + '.' + key for key in keys
                    if actual.get(group, {}).get(key)
                    != expected.get(group, {}).get(key))
            fail('SESSION_ENDPOINT_CHANGED', 'Session identity changed: '
                + ', '.join(changed or ['identity fields']),
                'Restore the original settings, or run console init '
                'followed by a fresh audit and plan after an intentional '
                'connection change or database import. A connection-only '
                'change does not require a database reimport.')
        return session

    def batch(self, batch_id: str | None) -> tuple[Path, BatchManifest]:
        if not batch_id:
            pointer = self.session / 'active-batch.json'
            if not pointer.exists():
                fail('BATCH_REQUIRED', 'No batch is selected',
                    'Generate a plan or pass --batch ID.')
            batch_id = json.loads(pointer.read_text())['batch']
        path = self.session / 'batches' / local_id(batch_id)
        if not path.is_dir():
            fail('BATCH_MISSING', f'Batch is not in this session: {batch_id}')
        contents = verify(path)
        manifest: BatchManifest = json.loads(contents['manifest.json'])
        if manifest.get('cleanup_session') != self.session.name:
            fail('SESSION_BATCH_MISMATCH',
                'Batch belongs to another cleanup session')
        verify_implementation_hashes(manifest)
        return path, manifest
