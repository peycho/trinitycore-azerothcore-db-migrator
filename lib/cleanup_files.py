"""Private files, sealed packages and toolkit implementation provenance."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
from types import ModuleType
import uuid

from cleanup_errors import fail
from cleanup_types import Evidence


ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / 'compatibility/tc335-acwotlk-v2'


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def token(prefix: str) -> str:
    return (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + prefix
        + '-' + uuid.uuid4().hex[:10])


def sha(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


IMPLEMENTATION_FILES = (
    'bin/generate-spell-metadata-profile.py',
    'lib/cleanup_actions.py',
    'lib/cleanup_active_reset.py',
    'lib/cleanup_arguments.py',
    'lib/cleanup_commands.py',
    'lib/cleanup_config.py',
    'lib/cleanup_console.py',
    'lib/cleanup_death_coil.py',
    'lib/cleanup_disabled_history.py',
    'lib/cleanup_dual_spec_teacher.py',
    'lib/cleanup_eligibility.py',
    'lib/cleanup_errors.py',
    'lib/cleanup_files.py',
    'lib/cleanup_foreign_skills.py',
    'lib/cleanup_history_evidence.py',
    'lib/cleanup_history_models.py',
    'lib/cleanup_history_options.py',
    'lib/cleanup_history_package.py',
    'lib/cleanup_history_publication.py',
    'lib/cleanup_history_selection.py',
    'lib/cleanup_history_snapshot.py',
    'lib/cleanup_history_sql.py',
    'lib/cleanup_history_workflow.py',
    'lib/cleanup_inactive_legacy.py',
    'lib/cleanup_migration_evidence.py',
    'lib/cleanup_native_actions.py',
    'lib/cleanup_native_skills.py',
    'lib/cleanup_obsolete_riding.py',
    'lib/cleanup_ordinary_history.py',
    'lib/cleanup_ownership.py',
    'lib/cleanup_pet_teaching.py',
    'lib/cleanup_plans.py',
    'lib/cleanup_policy_descriptions.json',
    'lib/cleanup_professions.py',
    'lib/cleanup_racial_skills.py',
    'lib/cleanup_recipe.py',
    'lib/cleanup_selected_passive.py',
    'lib/cleanup_selected_rank_history.py',
    'lib/cleanup_shaman_dual_wield.py',
    'lib/cleanup_shaman_offhand.py',
    'lib/cleanup_skill_teaching.py',
    'lib/cleanup_skills.py',
    'lib/cleanup_specialization_parent.py',
    'lib/cleanup_specializations.py',
    'lib/cleanup_spell_history.py',
    'lib/cleanup_talent_relations.py',
    'lib/cleanup_trained_history.py',
    'lib/cleanup_types.py',
    'lib/cleanup_workspace.py',
    'lib/spell_common.py',
    'lib/spell_metadata.py',
    'lib/spell_reconstruction.py',
    'lib/spell_rules.py',
    'lib/spells.py',
    'tools/audit-tc-source.py',
    'tools/plan-talent-cleanup.py',
    'tools/replay-source-preparation.py',
)


def toolkit_hashes() -> dict[str, str]:
    names = ('lib/cleanup_racial_skills.py',
        'lib/cleanup_racial_skill_catalog.json',
        'lib/cleanup_foreign_action_catalog.json',
        'lib/cleanup_specialization_parent.py',
        'tools/specialization-parent-repair.sql.in',
        'lib/cleanup_foreign_swipe_catalog.json',
        'lib/cleanup_racial_catalog.json', 'lib/cleanup_specializations.py',
        'lib/cleanup_specialization_catalog.json',
        'lib/cleanup_professions.py', 'lib/cleanup_profession_catalog.json',
        'tools/profession-activation-repair.sql.in',
        'lib/cleanup_skill_teaching.py',
        'lib/cleanup_skill_teaching_catalog.json',
        'lib/cleanup_shaman_dual_wield.py',
        'tools/shaman-dual-wield-repair.sql.in', 'console',
        'lib/cleanup_console.py', 'lib/cleanup_plans.py', 'lib/spells.py',
        'tools/audit-tc-source.py', 'tools/plan-talent-cleanup.py',
        'tools/talent-cleanup.sql.in',
        'tools/single-character-talent-reset.sql.in',
        'tools/container-recovery.sql.in', 'lib/cleanup_active_reset.py',
        'tools/active-talent-reset.sql.in', 'lib/cleanup_skills.py',
        'tools/skill-cleanup.sql.in',
        'lib/cleanup_spell_history.py', 'lib/cleanup_disabled_history.py',
        'lib/cleanup_talent_relations.py',
        'lib/cleanup_selected_rank_history.py',
        'lib/cleanup_migration_evidence.py', 'lib/cleanup_trained_history.py',
        'tools/disabled-talent-history.sql.in',
        'lib/cleanup_native_skills.py', 'lib/cleanup_ordinary_history.py',
        'lib/cleanup_death_coil.py', 'lib/cleanup_ownership.py',
        'lib/cleanup_eligibility.py', 'lib/cleanup_pet_teaching.py',
        'tools/pet-teaching-repair.sql.in',
        'tools/spell-eligibility-repair.sql.in',
        'tools/talent-ownership-repair.sql.in',
        'tools/passive-rekey-repair.sql.in', 'lib/cleanup_selected_passive.py',
        'lib/cleanup_inactive_legacy.py',
        'tools/inactive-legacy-repair.sql.in',
        'tools/native-skill-repair.sql.in',
        'tools/native-generic-repair.sql.in')
    names += ('lib/cleanup_native_actions.py',
        'lib/cleanup_native_action_catalog.json',
        'lib/cleanup_foreign_skills.py', 'tools/foreign-skill-repair.sql.in',
        'tools/foreign-skill-stowing.sql.in')
    names += ('lib/cleanup_dual_spec_teacher.py',
        'tools/dual-spec-teacher-repair.sql.in')
    names += ('lib/cleanup_shaman_offhand.py',
        'tools/shaman-offhand-repair.sql.in')
    names += ('lib/cleanup_obsolete_horse_catalog.json',
        'tools/obsolete-horse-repair.sql.in')
    names += ('lib/cleanup_obsolete_riding.py',
        'lib/cleanup_obsolete_riding_catalog.json',
        'lib/cleanup_obsolete_riding_item_catalog.json',
        'tools/obsolete-riding-repair.sql.in')
    names += IMPLEMENTATION_FILES
    hashes = {}
    for name in names:
        path = ROOT / name
        hint = (
            'Install all files from the same cleanup toolkit release '
            f'into {ROOT}; keep cleanup.ini and the existing workspace. '
            'No database reimport or new session is needed for this file '
            'repair.'
        )
        if not path.is_file():
            fail('TOOLKIT_INCOMPLETE', 'Required toolkit file is missing: '
                + name, hint)
        try:
            hashes[name] = sha(path)
        except OSError:
            fail('TOOLKIT_FILE_UNREADABLE',
                'Cannot read required toolkit file: ' + name,
                'Check this file owner and read permissions. ' + hint)
    return hashes


def identifier(value: object) -> str:
    if not re.fullmatch('[A-Za-z0-9_]{1,64}', str(value)):
        fail('INVALID_IDENTIFIER',
            'Expected a 1-64 character ASCII SQL identifier')
    return str(value)


def local_id(value: str) -> str:
    if not re.fullmatch('[A-Za-z0-9_-]{1,100}', value):
        fail('INVALID_ID', 'Invalid session, audit or batch ID')
    return value


def private_file(path: Path) -> None:
    if (path.is_symlink() or not path.is_file() or path.stat().st_uid
        != os.getuid() or stat.S_IMODE(path.stat().st_mode) & 0o077):
        fail('PRIVATE_FILE_REQUIRED',
            f'Expected an operator-owned private file: {path}',
            'Use chmod 600; do not put credentials in command arguments.')


def private_dir(path: Path) -> None:
    if path.is_symlink():
        fail('SYMLINK_REFUSED',
            f'Workspace directory cannot be a symlink: {path}')
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if (path.stat().st_uid != os.getuid() or stat.S_IMODE(path.stat().st_mode)
        & 0o077):
        fail('PRIVATE_DIRECTORY_REQUIRED',
            'Workspace directory must be operator-owned and private: '
            f'{path}',
            'Use chmod 700.')


def write_json(path: Path, value: object) -> None:
    temporary = path.with_name(path.name + '.tmp-' + uuid.uuid4().hex)
    with temporary.open('x') as stream:
        temporary.chmod(0o600)
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def seal(directory: Path) -> None:
    """Seal every package member except the manifest and incomplete marker."""
    paths = sorted(p for p in directory.iterdir() if p.is_file()
        and p.name not in ('SHA256SUMS', 'INCOMPLETE'))
    (directory / 'SHA256SUMS').write_text(''.join(sha(p) + '  ' + p.name
        + '\n' for p in paths))
    for path in paths + [directory / 'SHA256SUMS']:
        path.chmod(0o600)


def verify(directory: Path) -> dict[str, bytes]:
    """Validate the sealed package and retain its verified bytes for
    execution.
    """
    if directory.is_symlink() or (directory / 'INCOMPLETE').exists():
        fail('INCOMPLETE_PACKAGE',
            'Incomplete or symlinked package cannot be executed')
    manifest = directory / 'SHA256SUMS'
    if manifest.is_symlink():
        fail('PACKAGE_CHANGED', 'Symlinked checksum manifest refused')
    names = set()
    contents = {}
    for line in manifest.read_text().splitlines():
        match = re.fullmatch('([0-9a-f]{64})  ([A-Za-z0-9_.-]+)', line)
        if (not match or match[2] in names or match[2] in ('SHA256SUMS',
            'INCOMPLETE')):
            fail('PACKAGE_CHANGED',
                'Invalid or duplicate package checksum entry')
        name = match[2]
        path = directory / name
        if path.is_symlink() or not path.is_file():
            fail('PACKAGE_CHANGED',
                f'Package member is missing or symlinked: {name}')
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != match[1]:
            fail('PACKAGE_CHANGED', f'Package checksum differs: {name}',
                'Keep the evidence; generate a new batch rather than '
                'editing SQL.')
        names.add(name)
        contents[name] = data
    if (names != {p.name for p in directory.iterdir() if p.name
        != 'SHA256SUMS'}):
        fail('PACKAGE_CHANGED', 'Unsealed or missing files in package')
    return contents


def implementation_hashes(operation: Path | None = None) -> dict[str, str]:
    """Fingerprint every Python dependency of newly generated cleanup
    batches.
    """
    hashes = {name: sha(ROOT / name) for name in IMPLEMENTATION_FILES}
    if operation is not None:
        journal = json.loads((operation / 'operation.json').read_text())
        started = journal['toolkit_sha256']
        if any(started.get(name) != digest for name, digest in hashes.items()):
            fail('TOOLKIT_IMPLEMENTATION_DRIFT',
                'Toolkit implementation changed during package generation',
                'Retain the operation evidence and retry with one '
                'complete toolkit release.')
    return hashes


def verify_implementation_hashes(manifest: Evidence) -> None:
    """Keep new batches bound to their implementation without resealing old
    ones.
    """
    expected = manifest.get('implementation_sha256')
    if expected is not None and expected != implementation_hashes():
        fail('TOOLKIT_IMPLEMENTATION_DRIFT',
            'Toolkit implementation differs from the reviewed batch',
            'Use the matching frozen toolkit, or generate fresh evidence '
            'and a new batch.')
