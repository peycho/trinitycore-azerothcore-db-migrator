#!/usr/bin/env python3
"""Replay an explicit reviewed policy recipe; regenerate evidence and
archives.

This is preparation orchestration, not an approval bypass or native
reset runner. A guarded operation failure stops the run. Earlier APPLIED
archives are retained.
"""

from __future__ import annotations

import argparse
import collections
from collections.abc import Sequence
import csv
import itertools
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
from typing import TYPE_CHECKING
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'lib'))

from cleanup_console import Settings, Workspace, sha, write_json
from cleanup_recipe import STEPS
from cleanup_types import Evidence

if TYPE_CHECKING:
    from spell_metadata import Metadata


def recipe(path: Path) -> Evidence:
    data = json.loads(Path(path).read_text())
    if (set(data) != {'version', 'policies'} or type(data[
        'version']) is not int or data['version'] != 1
        or not isinstance(data['policies'], list) or not data['policies']
        or any(not isinstance(s, str) or s not in STEPS for s in data[
            'policies'])
        or len(set(data['policies'])) != len(data['policies'])):
        raise ValueError(
            'Expected version 1 and distinct registered policy IDs; '
            'arbitrary commands and resets are forbidden')
    return data


def handoff_ready(report: Evidence) -> bool:
    """Only complete audit and an actual successful spell review may hand
    off.
    """
    audit = report.get('final_audit', {})
    return (report.get('status') == 'POLICY_FIXED_POINT' and audit.get(
        'status') == 'COMPLETE'
        and audit.get('limitations') == [] and report.get('spell_review', {
        }).get('status') == 'PASS')


class Replay:

    audit: Path | None
    config: Path
    context: Path | None
    last_operation: Path | None
    output: Path
    policies: list[str]
    report: Evidence
    sequence: int
    session: Path
    settings: Settings
    state: Evidence | None

    def __init__(
        self,
        config: str | Path,
        output: Path,
        policies: list[str],
    ) -> None:
        self.settings = Settings(config)
        self.settings.safety()
        self.output = Path(output)
        self.output.mkdir(mode=0o700, parents=True, exist_ok=False)
        self.policies = policies
        self.audit = None
        self.context = None
        self.state = None
        self.report = {'status': 'RUNNING', 'policies': policies, 'steps': [],
            'migration': 'NOT_RUN', 'gameplay': 'NOT_TESTED',
            'approval': 'UNREVIEWED',
            'config_sha256': sha(Path(config)),
            'registry_sha256': sha(ROOT / 'lib/cleanup_recipe.py')}
        self.config = Path(config).resolve()
        self.sequence = 0
        self.save()

    def save(self) -> None:
        write_json(self.output / 'replay.json', self.report)

    def call(self, *args: str | int, allow: tuple[int, ...] = (0,)) -> int:
        self.sequence += 1
        before = (set((self.session / 'operations').iterdir()) if hasattr(self,
            'session') else set())
        prefix = self.output / f'{self.sequence:04d}-{args[0]}'
        with prefix.with_suffix('.stdout').open(
            'w') as out, prefix.with_suffix('.stderr').open('w') as err:
            result = subprocess.run([sys.executable, str(ROOT / 'console'),
                '--config', str(self.config), *map(str, args)], stdout=out,
                stderr=err)
        if result.returncode not in allow:
            error = prefix.with_suffix('.stderr').read_text()
            if result.returncode == 2 and error.startswith('ERROR '):
                try:
                    code = json.loads(error.removeprefix('ERROR '))['code']
                except (ValueError, KeyError): code = 'CONSOLE_FAILED'
            else:
                code = 'CONSOLE_FAILED'
            raise RuntimeError(
                f'{code}: command {args[0]} failed; inspect {prefix}'
                '.stderr')
        work = Workspace(self.settings)
        work.current()
        self.session = work.session
        created = set((self.session / 'operations').iterdir()) - before
        if args[0] != 'init' and len(created) != 1:
            raise RuntimeError(
                'Cannot identify exactly one new console operation; '
                'concurrent/stale output refused')
        self.last_operation = created.pop() if created else None
        return result.returncode

    def fresh_audit(self) -> Path:
        if self.audit is None:
            self.call('audit', '--scope', 'character-state', allow= (0, 1))
            pointer = json.loads((
                self.session / 'latest-audit.json').read_text())
            self.audit = self.session / 'audits' / pointer['audit']
        return self.audit

    def fresh_context(self) -> Path:
        if self.context is None:
            self.call('inspect-migration-blockers', '--all-characters')
            self.context = (sorted((self.session / 'inspections').glob(
                '*-migration-blockers-*'))[-1])
        data = json.loads((self.context / 'inspection.json').read_text())
        if data.get('scope') != 'ALL_SOURCE_CHARACTERS':
            raise RuntimeError('Whole-source evidence required')
        from cleanup_plans import sha_json
        source = self.settings.schemas['characters']
        roster = [int(x) for x in self.settings.sql(
            f'SELECT guid FROM `{source}`.characters ORDER BY guid LIMIT '
            '40001;').splitlines()]
        if sha_json(roster) != data.get('scope_roster_sha256'):
            raise RuntimeError(
                'Whole-source character roster changed; fresh evidence '
                'required')
        return self.context

    def operation(self) -> Path:
        if self.last_operation is None:
            raise RuntimeError('No completed console operation')
        return self.last_operation

    def plan(self, name: str) -> tuple[Path | None, Evidence]:
        step = STEPS[name]
        mode = step['count']
        cmd = ['plan', *step['command']]
        if mode.startswith('audit-'):
            audit = self.fresh_audit()
            reason = ('TALENT_VALUE_IS_NOT_RANK_SPELL' if mode
                == 'audit-talents' else 'SKILL_VALUE_EXCEEDS_CAP')
            with (audit / 'summary.tsv').open() as f:
                count = sum(int(r['rows_found']) for r in csv.DictReader(f,
                    delimiter='\t') if r['reason_code'] == reason)
            if not count:
                return None, {'selected_rows': 0}
            cmd += ['--audit', audit.name, '--expect-rows', str(count)]
        elif mode in ('direct', 'selected'):
            audit = self.fresh_audit()
            self.call('inspect-spell-history', '--audit', audit.name)
            history = (sorted((self.session / 'inspections').glob(
                '*-spell-history-*'))[-1])
            disposition = ('REVIEW_DISABLED_NO_SELECTED_FAMILY' if mode
                == 'direct' else 'REVIEW_DISABLED_OTHER_SELECTED_RANK')
            count = json.loads((history / 'inspection.json').read_text())[
                'dispositions'].get(disposition, 0)
            if not count:
                return None, {'selected_rows': 0}
            cmd += ['--inspection', history.name, '--expect-review-rows', str(
                count)]
        else:
            context = self.fresh_context()
            cmd += ['--migration-inspection', context.name]
            if mode == 'trained':
                from cleanup_disabled_history import read_world
                meta, _ = read_world(self.settings)
                state = (json.loads((context / 'source-state.json').read_text(
                ))['rows'])
                count = sum(d == 1 and s not in meta.talents and meta.first(s)
                    in meta.talents for _, s, a, d in state['character_spell'])
                if not count:
                    return None, {'selected_rows': 0}
                cmd += ['--expect-review-rows', str(count)]
            else:
                self.call(*cmd, '--preview')
                reviews = list(self.operation().glob('*review.json'))
                if len(reviews) != 1:
                    raise RuntimeError(
                        'Expected exactly one policy preview report')
                review = json.loads(reviews[0].read_text())
                summary = review.get('summary', review)
                if review.get('policy', step['policy']) != step['policy']:
                    raise RuntimeError('Preview policy differs from recipe')
                if not summary['selected_rows']:
                    return None, summary
                count = (summary['reviewed_candidate_rows'] if mode
                    == 'preview-review' else summary['selected_rows'])
                cmd += ['--expect-review-rows' if mode == 'preview-review'
                    else '--expect-rows', str(count)]
        try:
            self.call(*cmd)
        except RuntimeError as error:
            if str(error).startswith('HISTORY_NO_ELIGIBLE_ROWS:'):
                return None, {'selected_rows': 0,
                    'deferred': 'See retained policy selection error report'}
            raise
        batch = (json.loads((self.session / 'active-batch.json').read_text())[
            'batch'])
        manifest = json.loads((
            self.session / 'batches' / batch / 'manifest.json').read_text())
        if manifest['policy'] != step['policy']:
            raise RuntimeError(
                'Generated policy differs from recipe; no apply attempted')
        return batch, {'selected_rows': manifest.get('selected_rows',
            manifest.get('expected_rows')), 'policy': manifest['policy']}

    def review_spells(self) -> None:
        """Same reconstruction function as preflight, without expectation
        SQL.
        """
        if not self.settings.get('target', 'world'):
            self.report['spell_review'] = {
                'status': 'NOT_RUN_INPUTS_NOT_CONFIGURED'}
            return
        from cleanup_console import PROFILE
        from spells import (
            Database,
            Metadata,
            reconstruct,
            Unsupported,
            character_rows,
            POLICY,
        )
        output = self.output / 'spell-reconstruction'
        output.mkdir(mode=0o700)
        counts = collections.Counter()
        reviewed = 0
        profile = json.loads((PROFILE / 'spell-metadata.json').read_text())
        with self.settings.client('audit') as args:
            db = Database([*args,
                '--init-command=SET SESSION transaction_read_only=ON'])
            tc = Metadata('tc', self.settings.paths['tc_dbc'],
                self.settings.schemas['world'], profile, db)
            ac = Metadata('ac', self.settings.paths['ac_dbc'],
                self.settings.get('target', 'world'), profile, db)
            with (output / 'spell-state-blockers.tsv').open('w') as f:
                writer = csv.writer(f, delimiter='\t', lineterminator='\n')
                writer.writerow(['guid', 'spell', 'reason_code', 'detail'])
                for guid, group in itertools.groupby(character_rows(db,
                    self.settings.schemas['characters'], 'tc-to-ac'),
                    lambda r: int(r[0])):
                    character = level = None
                    stored = {}
                    talents = collections.defaultdict(int)
                    skills = {}
                    for _, kind, a, b, c, d in group:
                        a, b, c, d = map(int, (a, b, c, d))
                        if kind == '0':
                            character = (a, b, c, d)
                        elif kind == '1':
                            talents[a] |= b
                        elif kind == '2':
                            skills[a] = (b, c)
                        elif kind == '4':
                            level = a
                        else:
                            stored[a] = (b, c)
                    if character is None or not (stored or talents):
                        continue
                    reviewed += 1
                    try:
                        reconstruct(character, stored, talents, skills, tc, ac,
                            'tc-to-ac', level=level)
                    except Unsupported as error:
                        counts[error.reason] += 1; writer.writerow([guid, '*',
                            error.reason, str(error).replace('\t',
                                ' ').replace('\n', ' ')])
                    if reviewed % 5000 == 0:
                        print('Reviewed spell state for ' + str(reviewed)
                            + ' characters', flush=True)
        result = {'status': 'BLOCKED' if counts else 'PASS',
            'reviewed_characters': reviewed,
            'blocked_characters': sum(counts.values()),
            'reasons': dict(sorted(counts.items())), 'policy': POLICY,
            'fingerprints': db.fingerprints,
            'limitations': [
                'First reconstruction failure per character; no expectation '
                'SQL or gameplay proof',
                'No auth/account validation; full audit and migration '
                'phases remain required']}
        write_json(output / 'review.json', result)
        self.report['spell_review'] = result
        self.save()

    def migrate(self, config: str | Path) -> int:
        """Run the existing phases only after complete preparation evidence."""
        original = Path(config).resolve()
        fingerprint = sha(original)
        run_id = str(uuid.uuid4())
        wrapper = self.output / 'migration.env'
        wrapper.write_text('source ' + shlex.quote(str(original))
            + '\nMIGRATION_RUN_ID=' + shlex.quote(run_id) + '\n')
        keys = ('MYSQL_HOST', 'MYSQL_PORT', 'MYSQL_SOCKET',
            'MIGRATION_DIRECTION',
            'SOURCE_AUTH_SCHEMA', 'SOURCE_CHARACTERS_SCHEMA',
            'SOURCE_WORLD_SCHEMA', 'TARGET_WORLD_SCHEMA',
            'TARGET_AUTH_SCHEMA', 'TARGET_CHARACTERS_SCHEMA',
            'CONTROL_SCHEMA')
        script = (
            'set -Eeuo pipefail; MIGRATION_ROOT=$1; source '
            '"$1/lib/common.sh"; source "$1/lib/compatibility.sh"; '
            'load_configuration "$2"; '
        )
        script += ('for key in ' + ' '.join(keys)
            + '; do printf \'%s\\n\' "${!key}"; done')
        result = subprocess.run(['bash', '-c', script, 'bash', str(ROOT), str(
            wrapper)], capture_output=True, text=True)
        (self.output / 'migration-config.stderr').write_text(result.stderr)
        lines = result.stdout.splitlines()
        if result.returncode or len(lines) != len(keys):
            raise RuntimeError(
                'Migration configuration validation failed; no phase '
                'started')
        values = dict(zip(keys, lines))
        connection = self.settings.connection
        expected = {'MYSQL_HOST': connection['host'], 'MYSQL_PORT': connection[
            'port'], 'MYSQL_SOCKET': connection['socket'],
            'MIGRATION_DIRECTION': 'tc-to-ac',
            'SOURCE_AUTH_SCHEMA': self.settings.schemas['auth'],
            'SOURCE_CHARACTERS_SCHEMA': self.settings.schemas[
                'characters'], 'SOURCE_WORLD_SCHEMA': self.settings.schemas[
                    'world'],
            'TARGET_WORLD_SCHEMA': self.settings.get('target', 'world')}
        if any(values[k] != v for k, v in expected.items()):
            raise RuntimeError(
                'Migration endpoint/source/world differs from the prepared '
                'source')
        from cleanup_console import identifier
        targets = ([identifier(values[k]) for k in ('TARGET_AUTH_SCHEMA',
            'TARGET_CHARACTERS_SCHEMA', 'CONTROL_SCHEMA')])
        if (len(set(targets)) != 3 or set(targets) & set(
            self.settings.schemas.values()) or values['TARGET_WORLD_SCHEMA']
            in targets):
            raise RuntimeError('Migration targets overlap preparation inputs')
        names = ','.join("'" + n + "'" for n in targets)
        count = self.settings.sql(
            'SELECT COUNT(*) FROM information_schema.TABLES WHERE '
            'TABLE_SCHEMA IN (' + names
            + ") AND TABLE_TYPE='BASE TABLE';", 'admin').strip()
        if count != '0':
            raise RuntimeError(
                'Fresh empty migration targets and control schema required; '
                'nothing was dropped')
        self.report.update(migration='RUNNING', migration_run_id=run_id,
            migration_config_sha256=fingerprint, migration_phases= [])
        self.save()
        for phase in ('preflight', 'archive-unsupported', 'assemble',
            'load-auth', 'load-characters', 'sanitize-target', 'validate',
            'report'):
            if sha(original) != fingerprint:
                raise RuntimeError(
                    'Migration configuration changed during replay')
            print('Migration: ' + phase, flush=True)
            with (self.output / (phase + '.stdout')).open('w') as out, (
                self.output / (phase + '.stderr')).open('w') as err:
                result = subprocess.run([str(ROOT / 'bin/migrate.sh'),
                    '--config', str(wrapper), phase], stdout=out, stderr=err)
            if result.returncode:
                raise RuntimeError('Migration ' + phase
                    + ' failed; see retained phase reports')
            self.report['migration_phases'].append(phase)
            self.save()
        status = self.settings.sql('SELECT status FROM `' + targets[2]
            + "`.migration_run WHERE run_id='" + run_id + "';", 'admin').strip(
            )
        if status != 'READY':
            raise RuntimeError('Migration did not reach database READY')
        self.report.update(status='DATABASE_REHEARSAL_READY',
            migration='READY', gameplay='NOT_TESTED')
        self.save()
        return 0

    def reset_active_exception(self, value: str) -> None:
        """An explicit GUID:foreign-spell exception, never a staff
        heuristic.
        """
        try:
            guid, spell = map(int, value.split(':'))
        except (ValueError, AttributeError): raise RuntimeError(
            'Active reset requires reviewed GUID:SPELL')
        if not 1 <= guid <= 0xffffffff or spell != 12284:
            raise RuntimeError(
                'Active reset requires the reviewed foreign-spell '
                'contract 12284')
        source = self.settings.schemas['characters']
        flags = self.settings.sql(
            f'SELECT at_login FROM `{source}`.characters WHERE guid='
            f'{guid};',
            'audit').strip()
        if not flags:
            raise RuntimeError('Reviewed active-reset character is absent')
        present = int(self.settings.sql(
            f'SELECT COUNT(*) FROM `{source}`.character_spell WHERE guid='
            f'{guid} AND spell={spell};', 'audit').strip())
        entry = {'id': 'reviewed-active-reset', 'guid': guid,
            'foreign_spell': spell, 'state': 'NO_SELECTION'}
        self.report['steps'].append(entry)
        self.save()
        if int(flags) & 4 and not present:
            entry['native_reset'] = 'ALREADY PENDING NEXT LOGIN'
            self.save()
            return
        count = int(self.settings.sql(
            f'SELECT COUNT(*) FROM `{source}`.character_talent WHERE guid='
            f'{guid};', 'audit').strip())
        self.call('plan', 'reset-active-talents', '--guid', str(guid),
            '--remove-spells', str(spell), '--expect-talent-rows', str(count))
        self.apply_reset_exception(entry, 'tc-active-build-native-reset-v1')

    def apply_reset_exception(
        self,
        entry: Evidence,
        expected_policy: str,
    ) -> None:
        batch = (json.loads((self.session / 'active-batch.json').read_text())[
            'batch'])
        manifest = json.loads((
            self.session / 'batches' / batch / 'manifest.json').read_text())
        if manifest['policy'] != expected_policy:
            raise RuntimeError('Unexpected reset exception policy')
        entry.update(state='CANDIDATE', batch=batch,
            native_reset='PENDING NEXT LOGIN after apply')
        self.save()
        self.call('prepare', '--batch', batch)
        self.call('apply', '--batch', batch)
        self.call('status', '--batch', batch)
        row = next(csv.DictReader((self.operation() / 'status.tsv').read_text(
        ).splitlines(), delimiter='\t'))
        if row.get('state') != 'APPLIED':
            raise RuntimeError('Reset exception checkpoint is not APPLIED')
        entry['state'] = 'APPLIED'
        self.audit = None
        self.context = None
        self.save()

    def reset_unavailable_spec(self, guid: int) -> None:
        """Explicit single-character exception; never inferred from GM
        status.
        """
        if type(guid) != int or not 1 <= guid <= 0xffffffff:
            raise RuntimeError('Reset GUID outside native domain')
        source = self.settings.schemas['characters']
        count = int(self.settings.sql(
            f'SELECT COUNT(*) FROM `{source}`.character_talent WHERE guid='
            f'{guid} AND talentGroup=1;', 'audit').strip())
        entry = {'id': 'reviewed-unavailable-spec-reset', 'guid': guid,
            'state': 'NO_SELECTION', 'summary': {
                'unavailable_group_rows': count}}
        self.report['steps'].append(entry)
        self.save()
        if not count:
            return
        # The existing planner rechecks offline state, ONE configured spec,
        # active group zero, nonempty retained group zero, exact class ranks,
        # complete source originals and every existing SQL guard. A changed
        # character stops here; never reinterpret a new valid second spec.
        self.call('plan', 'reset-talents', '--guid', str(guid))
        self.apply_reset_exception(entry,
            'tc-single-character-native-talent-reset-v1')

    def apply_policy(self, name: str, number: int) -> bool:
        print(f'Pass {number}: {name}', flush=True)
        batch, summary = self.plan(name)
        entry = {'pass': number, 'id': name, 'summary': summary,
            'batch': batch, 'state': 'NO_SELECTION'}
        if not batch:
            self.report['steps'].append(entry)
            self.save()
            return False
        entry['state'] = 'CANDIDATE'
        self.report['steps'].append(entry)
        self.save()
        self.call('prepare', '--batch', batch)
        self.call('status', '--batch', batch)
        self.call('apply', '--batch', batch)
        self.call('status', '--batch', batch)
        row = next(csv.DictReader((self.operation() / 'status.tsv').read_text(
        ).splitlines(), delimiter='\t'))
        if row.get('state') != 'APPLIED':
            raise RuntimeError(
                'Batch state is not APPLIED; reconcile before continuing')
        entry['state'] = 'APPLIED'
        self.audit = None
        self.context = None
        self.save()
        print('Applied ' + batch, flush=True)
        return True

    def run(
        self,
        max_passes: int,
        migration_config: Path | None = None,
        reviewed_unavailable_spec_resets: Sequence[int] = (),
        reviewed_active_resets: Sequence[str] = (),
    ) -> int:
        self.call('init', '--label', 'fresh-snapshot-policy-replay')
        self.report['session'] = self.session.name
        self.report['explicit_unavailable_spec_reset_guids'] = list(
            reviewed_unavailable_spec_resets)
        self.save()
        if reviewed_unavailable_spec_resets or reviewed_active_resets:
            if 'invalid-talents' not in self.policies:
                raise RuntimeError(
                    'Reviewed reset replay requires the reviewed '
                    'invalid-talents policy first')
            self.apply_policy('invalid-talents', 0)
        for guid in reviewed_unavailable_spec_resets:
            self.reset_unavailable_spec(guid)
        self.report['explicit_active_reset_exceptions'] = list(
            reviewed_active_resets)
        self.save()
        for value in reviewed_active_resets:
            self.reset_active_exception(value)
        for number in range(1, max_passes + 1):
            applied = 0
            for name in self.policies:
                applied += int(self.apply_policy(name, number))
            if not applied:
                self.report['status'] = 'POLICY_FIXED_POINT'
                break
        else:
            self.report['status'] = 'PASS_LIMIT_REACHED'
        self.review_spells()
        # A scoped preparation audit never substitutes for the complete
        # migration gate.
        before = set((self.session / 'audits').iterdir())
        self.call('audit', '--scope', 'all', allow= (0, 1, 2))
        created = set((self.session / 'audits').iterdir()) - before
        if len(created) != 1:
            raise RuntimeError(
                'Expected a new final full audit; stale audits are '
                'refused')
        final_audit = json.loads((created.pop() / 'audit.json').read_text())
        self.report['final_audit'] = final_audit
        self.report['migration'] = 'BLOCKED_PENDING_FULL_REHEARSAL'
        self.save()
        print(self.report['status'] + '; final audit ' + final_audit['status'],
            flush=True)
        if handoff_ready(self.report) and migration_config:
            return self.migrate(migration_config)
        return 2


def main() -> int:
    os.umask(0o077)
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config', required=True)
    p.add_argument('--recipe', required=True)
    p.add_argument('--output', required=True)
    p.add_argument('--max-passes', type=int, default=4)
    p.add_argument('--reviewed-active-reset', action='append', default= [],
        metavar='GUID:SPELL',
        help='Individually reviewed active reset exception with foreign spell '
        '12284; retain active ownership until free native reset at '
        'login; never inferred')
    p.add_argument('--reviewed-unavailable-spec-reset', type=int,
        action='append', default= [], metavar='GUID',
        help='Explicit one-character exception: archive unavailable group 1 '
        'and queue a free native active reset, retaining active '
        'ownership until login; repeat only for individually reviewed '
        'GUIDs')
    p.add_argument('--migration-config',
        help='Optional trusted migration.env; fresh target/control schemas '
        'required; failures stop phase progression')
    p.add_argument('--apply-reviewed-recipe', action='store_true',
        help='Explicitly execute these already reviewed policies on the '
        'stopped preparation copy')
    args = p.parse_args()
    data = recipe(args.recipe)
    try:
        active_pairs = ([tuple(map(int, value.split(':'))) for value
            in args.reviewed_active_reset])
        if any(len(pair) != 2 or not 1 <= pair[0] <= 0xffffffff or pair[1]
            != 12284 for pair in active_pairs):
            raise ValueError()
    except ValueError: p.error(
        'Active reset exceptions require reviewed GUID:12284')
    reset_guids = (args.reviewed_unavailable_spec_reset + [pair[0] for pair
        in active_pairs])
    if (len(set(reset_guids)) != len(reset_guids) or any(not 1 <= g
        <= 0xffffffff for g in reset_guids)):
        p.error('Reviewed reset GUIDs must be distinct native unsigned '
            'identifiers')
    if not 1 <= args.max_passes <= 10:
        p.error('--max-passes must be 1-10')
    if not args.apply_reviewed_recipe:
        print(json.dumps({name: STEPS[name] for name in data['policies']},
            indent=2))
        return 0
    replay = Replay(args.config, args.output, data['policies'])
    try:
        return replay.run(args.max_passes, args.migration_config,
            args.reviewed_unavailable_spec_reset, args.reviewed_active_reset)
    except (Exception, KeyboardInterrupt) as error:
        replay.report['status'] = 'STOPPED'; replay.report[
            'error'] = replay.settings.redact(str(error)); replay.save()
        print(replay.report['error'], file=sys.stderr); return 2

if __name__ == '__main__':
    raise SystemExit(main())
