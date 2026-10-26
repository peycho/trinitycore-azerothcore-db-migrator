#!/usr/bin/env python3
"""Saved blocker reports are data; context capture grants no cleanup approval."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
import tarfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'lib'))
from cleanup_console import CleanupError, parser, verify
import cleanup_migration_evidence as evidence


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.root=Path(self.temporary.name)
        self.path=self.root/'saved.tsv'
        self.data='guid\tspell\treason_code\tdetail\n1\t*\tUNAUTHORIZED_TALENT_SPELL\t12282: stored_flags=(1, 1)\n2\t*\tUNSUPPORTED_DEPENDENT_LEARN\t33943:34090: no verified native AC dependency\n'
        self.path.write_text(self.data)
    def tearDown(self):self.temporary.cleanup()

    def test_complete_input_and_deterministic_grouping(self):
        data,rows=evidence.read_report(self.path)
        self.assertEqual(data,self.data.encode());self.assertEqual(len(rows),2)
        self.assertEqual(evidence.groups(rows),evidence.groups(list(reversed(rows))))
        self.assertIn(('UNAUTHORIZED_TALENT_SPELL','12282','1','1','12282: stored_flags=(1, 1)',1),evidence.groups(rows))

    def test_headers_duplicates_numeric_bounds_and_controls_rejected(self):
        cases=['bad\n',self.data+self.data.splitlines()[1]+'\n',
               self.data.replace('1\t*','0\t*'),self.data.replace('1\t*','4294967296\t*'),
               self.data.replace('1\t*','1\t4294967296'),self.data.replace('1\t*','01\t*'),
               self.data.replace('UNAUTHORIZED_TALENT_SPELL','invalid'),self.data.replace('stored_flags','\x00stored_flags')]
        for data in cases:
            with self.subTest(data=data[:40]):
                self.path.write_text(data)
                with self.assertRaises(CleanupError):evidence.read_report(self.path)

    def test_empty_invalid_utf8_missing_and_oversize_reports(self):
        self.path.write_text(self.data.splitlines()[0]+'\n')
        with self.assertRaisesRegex(CleanupError,'no blocker'):evidence.read_report(self.path)
        self.path.write_bytes(b'\xff')
        with self.assertRaises(CleanupError):evidence.read_report(self.path)
        self.path.write_text(self.data)
        with patch.object(evidence,'MAX_BYTES',4),self.assertRaises(CleanupError):evidence.read_report(self.path)
        self.path.unlink()
        with self.assertRaises(CleanupError):evidence.read_report(self.path)

    def test_character_and_detail_bounds(self):
        with patch.object(evidence,'MAX_CHARACTERS',1),self.assertRaises(CleanupError):evidence.read_report(self.path)
        self.path.write_text(self.data.replace('12282: stored_flags=(1, 1)','x'*16385))
        with self.assertRaises(CleanupError):evidence.read_report(self.path)

    def test_literal_detail_is_never_sql_and_core_prefixes_group(self):
        self.path.write_text(self.data.replace('12282: stored_flags=(1, 1)',"tc: 12282: $(false); DELETE FROM characters;"))
        _,rows=evidence.read_report(self.path)
        self.assertEqual(evidence.groups(rows)[0][1],'12282')
        self.assertIn('DELETE',rows[0][3])

    def test_capture_seals_context_and_preserves_active_batch(self):
        settings=SimpleNamespace(check_paths=lambda:None,schemas={'characters':'tc_chars'},compatibility={})
        work=SimpleNamespace(session=self.root,operation=self.root,current=lambda:{'identity':{'uuid':'source-uuid'}})
        (self.root/'active-batch.json').write_text('{"batch":"unchanged"}')
        state={'characters':[[1,1,1,80,0,2,0,4]],'character_spell':[[1,12282,1,1],[1,6603,1,0]],
               'character_talent':[[1,12664,1]],'character_skills':[[1,118,1,1]]}
        shape={'columns':[], 'tables':[]};queries=[]
        def snapshot(settings,items):queries.extend(items);return state
        with patch.object(evidence,'metadata',return_value=shape),patch.object(evidence,'require_shape'),\
             patch.object(evidence,'snapshot',side_effect=snapshot),\
             patch.object(evidence,'read_world',return_value=(SimpleNamespace(hashes={'Spell.dbc':'hash'}),{'rows':{}})),redirect_stdout(io.StringIO()):
            output=evidence.inspect(settings,work,SimpleNamespace(report=self.path,bundle=True))
        contents=verify(output);manifest=json.loads(contents['inspection.json'])
        self.assertEqual(manifest['cleanup_approval'],'NOT_GRANTED')
        self.assertEqual(manifest['migration_approval'],'UNREVIEWED')
        self.assertIn('target world overlays',str(manifest['limitations']))
        contexts=[json.loads(line) for line in contents['character-context.jsonl'].decode().splitlines()]
        self.assertEqual(contexts[0]['reported_flags_comparison'],'MATCH')
        self.assertFalse(contexts[1]['source_character_present'])
        self.assertEqual(contexts[0]['character_talent'],[[1,12664,1]])
        self.assertEqual(contexts[0]['character_skills'],[[1,118,1,1]])
        self.assertEqual((self.root/'active-batch.json').read_text(),'{"batch":"unchanged"}')
        self.assertTrue(all(query.startswith('SELECT ') and 'WHERE guid IN (1,2)' in query for _,query in queries))
        self.assertEqual({name for name,_ in queries},set(evidence.FIELDS))
        self.assertEqual((output.stat().st_mode&0o777),0o700)
        self.assertTrue(all(path.stat().st_mode&0o777==0o600 for path in output.iterdir()))
        with tarfile.open(self.root/'migration-blocker-context.tar.gz') as archive:
            self.assertEqual(set(archive.getnames()),{p.name for p in output.iterdir()})
            self.assertEqual(archive.extractfile('source-state.json').read(),contents['source-state.json'])

    def test_late_failure_retains_incomplete_input_without_executable_batch(self):
        settings=SimpleNamespace(check_paths=lambda:None,schemas={'characters':'tc_chars'})
        work=SimpleNamespace(session=self.root)
        with patch.object(evidence,'metadata',side_effect=CleanupError('UNSUPPORTED_SCHEMA','fixture')),redirect_stdout(io.StringIO()):
            with self.assertRaises(CleanupError):evidence.inspect(settings,work,SimpleNamespace(report=self.path))
        output=next((self.root/'inspections').iterdir())
        self.assertTrue((output/'INCOMPLETE').exists());self.assertTrue((output/'spell-state-blockers.tsv').exists())
        self.assertFalse(list(output.glob('*.sql')))

    def test_cli_requires_saved_report(self):
        args=parser().parse_args(['inspect-migration-blockers','--report','saved.tsv','--bundle'])
        self.assertEqual(args.report,'saved.tsv')
        self.assertTrue(args.bundle)

    def test_context_bound_and_schema_drift_never_seal_partial_evidence(self):
        settings=SimpleNamespace(check_paths=lambda:None,schemas={'characters':'tc_chars'})
        work=SimpleNamespace(session=self.root)
        for bound,shapes in ((1,[{},{}]),(5000000,[{}, {'changed':True}])):
            with self.subTest(bound=bound),patch.object(evidence,'metadata',side_effect=shapes),\
                 patch.object(evidence,'require_shape'),patch.object(evidence,'MAX_ROWS',bound),\
                 patch.object(evidence,'snapshot',return_value={'characters':[[1],[2]]}),redirect_stdout(io.StringIO()):
                with self.assertRaises(CleanupError):evidence.inspect(settings,work,SimpleNamespace(report=self.path))
        for output in (self.root/'inspections').iterdir():
            self.assertTrue((output/'INCOMPLETE').exists())
            self.assertFalse((output/'SHA256SUMS').exists())


    def test_whole_source_scope_has_no_saved_guid_filter_or_failure_claim(self):
        settings=SimpleNamespace(check_paths=lambda:None,schemas={'characters':'tc_chars'},compatibility={},sql=lambda q:'1\n2\n')
        work=SimpleNamespace(session=self.root,operation=self.root,current=lambda:{'identity':{'uuid':'source-uuid'}})
        state={'characters':[[1,1,1,80,0,1,0,0],[2,1,1,80,0,1,0,0]],'character_spell':[], 'character_talent':[],'character_skills':[]}
        with patch.object(evidence,'metadata',return_value={'columns':[],'tables':[]}),patch.object(evidence,'require_shape'),\
             patch.object(evidence,'snapshot',return_value=state),\
             patch.object(evidence,'read_world',return_value=(SimpleNamespace(hashes={}),{'rows':{}})),redirect_stdout(io.StringIO()):
            out=evidence.inspect(settings,work,SimpleNamespace(all_characters=True,report=None))
        packet=verify(out);report=json.loads(packet['inspection.json'])
        self.assertEqual(report['scope'],'ALL_SOURCE_CHARACTERS')
        self.assertEqual(report['reported_characters'],2)
        self.assertEqual(report['reason_counts'],{'PREPARATION_SCOPE':2})
        self.assertIn(b'not migration failures',packet['README.md'])
        self.assertEqual(report['cleanup_approval'],'NOT_GRANTED')

    def test_whole_source_bound_and_population_drift_fail_closed(self):
        settings=SimpleNamespace(check_paths=lambda:None,schemas={'characters':'tc_chars'},compatibility={},sql=lambda q:'1\n2\n')
        work=SimpleNamespace(session=self.root,operation=self.root,current=lambda:{'identity':{'uuid':'source-uuid'}})
        with patch.object(evidence,'MAX_CHARACTERS',1),self.assertRaises(CleanupError):
            evidence.inspect(settings,work,SimpleNamespace(all_characters=True,report=None))
        with patch.object(evidence,'metadata',return_value={'columns':[],'tables':[]}),patch.object(evidence,'require_shape'),\
             patch.object(evidence,'snapshot',return_value={'characters':[[1,1,1,80,0,1,0,0]]}),redirect_stdout(io.StringIO()):
            with self.assertRaises(CleanupError)as raised:evidence.inspect(settings,work,SimpleNamespace(all_characters=True,report=None))
        self.assertEqual(raised.exception.code,'SOURCE_SCOPE_DRIFT')


    def test_new_character_outside_initial_roster_rejects_capture(self):
        settings=SimpleNamespace(check_paths=lambda:None,schemas={'characters':'tc_chars'},compatibility={},sql=unittest.mock.Mock(side_effect=['1\n','1\n2\n']))
        work=SimpleNamespace(session=self.root,operation=self.root,current=lambda:{'identity':{'uuid':'source-uuid'}})
        state={'characters':[[1,1,1,80,0,1,0,0]],'character_spell':[],'character_talent':[],'character_skills':[]}
        with patch.object(evidence,'metadata',return_value={'columns':[],'tables':[]}),patch.object(evidence,'require_shape'),\
             patch.object(evidence,'snapshot',return_value=state),redirect_stdout(io.StringIO()):
            with self.assertRaises(CleanupError)as raised:evidence.inspect(settings,work,SimpleNamespace(all_characters=True,report=None))
        self.assertEqual(raised.exception.code,'SOURCE_SCOPE_DRIFT')


if __name__=='__main__':unittest.main()
