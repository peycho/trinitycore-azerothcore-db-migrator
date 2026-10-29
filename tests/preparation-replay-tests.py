#!/usr/bin/env python3
"""Recipe replay must preserve guards, scope and failures across policy boundaries."""
import importlib.util, json, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'lib'))
spec = importlib.util.spec_from_file_location('replay',
    ROOT / 'tools/replay-source-preparation.py')
replay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(replay)
from cleanup_console import parser

class ReplayTests(unittest.TestCase):
    def test_recipe_refuses_arbitrary_commands_duplicates_and_resets(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'recipe.json'
            for data in ({'version': 1, 'policies': ['invalid-talents',
                'invalid-talents']}, {'version': True, 'policies': [
                    'invalid-talents']}, {'version': 1, 'policies': [
                        'reset-active-talents']}, {'version': 1, 'policies': [
                            'shell']}, {'version': 1, 'policies': []}, {
                                'version': 1,
                                'policies': ['invalid-talents'],
                                'command': 'rm'}):
                p.write_text(json.dumps(data))
                with self.assertRaises(ValueError):
                    replay.recipe(p)
            p.write_text(json.dumps({'version': 1, 'policies': [
                'invalid-talents', 'skill-caps']}))
            self.assertEqual(replay.recipe(p)['policies'], ['invalid-talents',
                'skill-caps'])
    def test_example_has_only_registered_unique_policies(self):
        d = replay.recipe(ROOT / 'config/preparation-recipe.example.json')
        self.assertEqual(set(d['policies']), set(replay.STEPS))
        for x in replay.STEPS.values():
            self.assertNotIn(x['command'][0], ('reset-talents',
                'reset-active-talents'))
    def test_scoped_audit_and_whole_source_capture_are_explicit(self):
        self.assertEqual(parser().parse_args(['audit', '--scope',
            'character-state']).scope, 'character-state')
        self.assertTrue(parser().parse_args(['inspect-migration-blockers',
            '--all-characters']).all_characters)
        with self.assertRaises(SystemExit):
            parser().parse_args(['inspect-migration-blockers',
                '--all-characters', '--report', 'saved.tsv'])
    def test_apply_error_stops_recipe_before_later_policies(self):
        obj = replay.Replay.__new__(replay.Replay)
        obj.policies = ['first', 'second']
        obj.report = {'steps': []}
        obj.session = Path('/tmp/synthetic-session')
        calls = []
        obj.save = lambda: None
        obj.plan = lambda name: ('fresh-batch', {'selected_rows': 2})
        def call(*args, **kw):
            calls.append(args)
            if args[0] == 'apply':
                raise RuntimeError('Apply failed')
        obj.call = call
        with self.assertRaisesRegex(RuntimeError, 'Apply failed'):
            obj.run(2)
        self.assertEqual([x[0] for x in calls], ['init', 'prepare', 'status',
            'apply'])
        self.assertEqual(len(obj.report['steps']), 1)
    def test_policy_mismatch_refuses_apply(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p / 'active-batch.json').write_text('{"batch":"new"}')
            (p / 'batches/new').mkdir(parents=True)
            (p / 'batches/new/manifest.json').write_text(
                '{"policy":"wrong-policy"}')
            (p / 'summary.tsv').write_text(
                'classification\treason_code\trows_found\nINVALID\tTALENT_VALUE_IS_NOT_RANK_SPELL\t2\n')
            obj = replay.Replay.__new__(replay.Replay)
            obj.session = p
            obj.fresh_audit = lambda: p
            calls = []
            obj.call = lambda * a, **k: calls.append(a)
            with self.assertRaisesRegex(RuntimeError, 'policy differs'):
                obj.plan('invalid-talents')
            self.assertFalse(any(x[0] == 'apply' for x in calls))
    def test_scoped_inspection_cannot_be_reused_from_old_blocker_report(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p / 'inspections/old-migration-blockers-x').mkdir(parents=True)
            (p / 'inspections/old-migration-blockers-x/inspection.json').write_text('{"scope":"SAVED_REPORT_CHARACTERS"}')
            obj = replay.Replay.__new__(replay.Replay)
            obj.session = p
            obj.context = None
            obj.call = lambda * a: None
            with self.assertRaisesRegex(RuntimeError, 'Whole-source evidence'):
                obj.fresh_context()


    def test_reviewed_reset_is_explicit_noop_when_history_absent_and_rejects_wrong_package(
        self,
    ):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'batches/bad').mkdir(parents=True)
            (root / 'active-batch.json').write_text('{"batch":"bad"}')
            (root / 'batches/bad/manifest.json').write_text(
                '{"policy":"unrelated"}')
            obj = replay.Replay.__new__(replay.Replay)
            obj.session = root
            obj.report = {'steps': []}
            obj.save = lambda: None
            obj.audit = obj.context = None
            calls = []
            obj.call = lambda * a: calls.append(a)
            obj.settings = SimpleNamespace(schemas={'characters': 'source'},
                sql=lambda * a: '0')
            obj.reset_unavailable_spec(42)
            self.assertFalse(calls)
            self.assertEqual(obj.report['steps'][-1]['state'], 'NO_SELECTION')
            obj.settings.sql = lambda * a: '31'
            with self.assertRaisesRegex(RuntimeError,
                'Unexpected reset exception policy'):
                obj.reset_unavailable_spec(42)
            self.assertEqual(calls, [('plan', 'reset-talents', '--guid',
                '42')])
            self.assertFalse(any(a[0] == 'apply' for a in calls))
            for invalid in (0, 2 ** 32, '42', True):
                with self.assertRaisesRegex(RuntimeError, 'GUID outside'):
                    obj.reset_unavailable_spec(invalid)

    def test_active_reset_exception_requires_explicit_reviewed_foreign_spell(
        self,
    ):
        from types import SimpleNamespace
        obj = replay.Replay.__new__(replay.Replay)
        obj.settings = SimpleNamespace(schemas={'characters': 'source'},
            sql=lambda q, r: '4' if 'at_login' in q else '0')
        obj.report = {'steps': []}
        obj.save = lambda: None
        obj.call = (lambda * args: (_ for _ in ()).throw(AssertionError(
            'Already pending reset must not be queued again')))
        obj.reset_active_exception('53899:12284')
        self.assertEqual(obj.report['steps'][0]['state'], 'NO_SELECTION')
        for text in ('53899', '0:12284', '53899:6603', '53899:12284:5'):
            with self.assertRaises(RuntimeError):
                obj.reset_active_exception(text)

    def test_reset_exceptions_follow_rank_cleanup_before_policy_replay(self):
        from types import SimpleNamespace
        obj = replay.Replay.__new__(replay.Replay)
        obj.policies = ['invalid-talents']
        obj.report = {'steps': []}
        obj.session = Path('/tmp/session')
        obj.save = lambda: None
        calls = []
        obj.call = lambda * a: calls.append(a)
        obj.apply_policy = (lambda name, number: calls.append(('policy', name,
            number)) or False)
        obj.reset_unavailable_spec = (lambda guid: calls.append(('unavailable',
            guid)))
        obj.reset_active_exception = (lambda value: calls.append(('active',
            value)))
        obj.review_spells = (lambda: (_ for _ in ()).throw(RuntimeError(
            'stop after ordering check')))
        with self.assertRaisesRegex(RuntimeError, 'ordering check'):
            obj.run(1, reviewed_unavailable_spec_resets= [99256],
                reviewed_active_resets= ['53899:12284'])
        self.assertEqual(calls[1:4], [('policy', 'invalid-talents', 0), (
            'unavailable', 99256), ('active', '53899:12284')])

    def test_handoff_requires_actual_spell_pass_and_complete_coverage(self):
        report = {'status': 'POLICY_FIXED_POINT', 'final_audit': {
            'status': 'COMPLETE', 'limitations': []}, 'spell_review': {
                'status': 'PASS'}}
        self.assertTrue(replay.handoff_ready(report))
        for status in ('BLOCKED', 'NOT_RUN_INPUTS_NOT_CONFIGURED', 'UNKNOWN',
            ''):
            report['spell_review']['status'] = status
            self.assertFalse(replay.handoff_ready(report))
        report['spell_review']['status'] = 'PASS'
        report['final_audit']['limitations'] = ['account parents unavailable']
        self.assertFalse(replay.handoff_ready(report))
        report['final_audit']['limitations'] = []
        report['status'] = 'PASS_LIMIT_REACHED'
        self.assertFalse(replay.handoff_ready(report))

    def migration_object(self, root):
        from types import SimpleNamespace
        obj = replay.Replay.__new__(replay.Replay)
        obj.output = root
        obj.report = {}
        obj.save = lambda: None
        def sql(query, role):
            return '0' if 'information_schema' in query else 'READY'
        obj.settings = SimpleNamespace(connection={'host': '127.0.0.1',
            'port': '33334', 'socket': ''}, schemas={'auth': 'auth',
                'characters': 'chars', 'world': 'tc_world'}, get=lambda a,
            b: 'ac_world', sql=sql)
        return obj
    def test_migration_uses_fresh_id_and_required_phase_order(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            config = root / 'trusted config.env'
            config.write_text('trusted config')
            obj = self.migration_object(root)
            calls = []
            values = ['127.0.0.1', '33334', '', 'tc-to-ac', 'auth', 'chars',
                'tc_world', 'ac_world', 'target_auth', 'target_chars',
                'control']
            def run(args, **kw):
                calls.append(args)
                return SimpleNamespace(returncode=0, stdout='\n'.join(values)
                    + '\n', stderr='')
            with patch.object(replay.subprocess, 'run', side_effect=run):
                self.assertEqual(obj.migrate(config), 0)
            self.assertEqual([x[-1] for x in calls[1:]], ['preflight',
                'archive-unsupported', 'assemble', 'load-auth',
                'load-characters', 'sanitize-target', 'validate', 'report'])
            wrapper =(root / 'migration.env').read_text()
            self.assertIn('MIGRATION_RUN_ID=', wrapper)
            self.assertIn("source '", wrapper)
            self.assertEqual(obj.report['status'], 'DATABASE_REHEARSAL_READY')
            self.assertEqual(obj.report['gameplay'], 'NOT_TESTED')
    def test_migration_stops_on_preflight_failure_and_input_mismatch(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            config = root / 'trusted.env'
            config.write_text('trusted config')
            obj = self.migration_object(root)
            calls = []
            values = ['127.0.0.1', '33334', '', 'tc-to-ac', 'auth', 'chars',
                'tc_world', 'ac_world', 'target_auth', 'target_chars',
                'control']
            def run(args, **kw):
                calls.append(args)
                return SimpleNamespace(returncode=0 if len(calls) == 1 else 1,
                    stdout='\n'.join(values) + '\n', stderr='')
            with patch.object(replay.subprocess, 'run',
                side_effect=run), self.assertRaisesRegex(RuntimeError,
                    'preflight failed'):
                obj.migrate(config)
            self.assertEqual(len(calls), 2)
            self.assertFalse(obj.report['migration_phases'])
            values[5] = 'different_source'
            calls.clear()
            with patch.object(replay.subprocess, 'run',
                side_effect=run), self.assertRaisesRegex(RuntimeError,
                    'differs'):
                obj.migrate(config)
            self.assertEqual(len(calls), 1)


    def test_cached_whole_source_rejects_same_count_roster_substitution(self):
        from types import SimpleNamespace
        from cleanup_plans import sha_json
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p / 'inspection.json').write_text(json.dumps({
                'scope': 'ALL_SOURCE_CHARACTERS',
                'scope_roster_sha256': sha_json([1, 2])}))
            obj = replay.Replay.__new__(replay.Replay)
            obj.context = p
            obj.settings = SimpleNamespace(schemas={'characters': 'source'},
                sql=lambda query: '1\n3\n')
            with self.assertRaisesRegex(RuntimeError, 'roster changed'):
                obj.fresh_context()

if __name__ == '__main__':
    unittest.main()
