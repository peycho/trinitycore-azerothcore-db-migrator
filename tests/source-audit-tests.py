#!/usr/bin/env python3
"""Source-health audit regressions; no database required."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('source_audit', ROOT/'tools/audit-tc-source.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)
spec = importlib.util.spec_from_file_location('source_fixtures', ROOT/'tests/spell-fixtures.py')
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)


class SourceAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.path = Path(cls.temporary.name)
        cls.profile = json.loads((ROOT/'compatibility/tc335-acwotlk-v2/spell-metadata.json').read_text())
        fixtures.write_assets(cls.path, cls.profile)
        cls.stores,cls.ranks,_ = audit.catalog(cls.path/'tc-dbc',cls.profile,'all')

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def findings(self, rows, custom=(), complete=True):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            findings = audit.Findings(output)
            audit.audit_character(1,rows,self.stores,self.ranks,set(custom),complete,'chars',findings)
            findings.file.close()
            return findings.counts, (output/'findings.tsv').read_text()

    def test_all_invalid_talent_rows_are_reported_without_rank_guessing(self):
        counts,text = self.findings([['1','0','1','1','0','1'],
                                    ['1','1','130','0','0','0'], ['1','1','442','0','0','0']])
        self.assertEqual(counts[('INVALID','TALENT_VALUE_IS_NOT_RANK_SPELL')],2)
        self.assertIn('never infer a replacement rank',text)

    def test_valid_highest_only_and_inactive_ordinary_spells_are_not_bad_data(self):
        counts,_ = self.findings([['1','0','1','2','0','1'],
            ['1','3','48942','1','0','0'],['1','3','643','0','0','0']])
        self.assertFalse(counts)

    def test_disabled_unowned_talent_is_review_history_not_delete_permission(self):
        counts,text = self.findings([['1','0','1','1','0','1'],['1','3','12296','1','1','0']])
        self.assertEqual(counts[('REVIEW','DISABLED_UNOWNED_TALENT_HISTORY')],1)
        self.assertFalse(any(kind=='INVALID' for kind,_ in counts))
        self.assertIn('No activation, deletion or guessed ownership',text)

    def test_custom_spells_and_incomplete_catalog_do_not_become_false_invalids(self):
        rows = [['1','0','1','1','0','1'],['1','3','999999','1','0','0']]
        self.assertFalse(self.findings(rows,custom=[999999])[0])
        self.assertFalse(self.findings(rows,complete=False)[0])
        self.assertEqual(self.findings(rows)[0][('INVALID','UNKNOWN_SPELL_ID')],1)

    def test_talent_conflicts_specs_skills_and_orphans_are_independent_findings(self):
        counts,_ = self.findings([['1','0','1','1','0','1'],
            ['1','1','12282','0','0','0'],['1','1','12664','0','0','0'],
            ['1','1','12296','1','0','0'],['1','2','183','500','400','0'],
            ['1','3','12664','1','1','0']])
        for key in [('REVIEW','MULTIPLE_TALENT_RANKS_IN_GROUP'),('INVALID','TALENT_GROUP_OUT_OF_RANGE'),
                    ('INVALID','SKILL_VALUE_EXCEEDS_CAP'),('REVIEW','TALENT_SPELL_SPEC_STATE_CONFLICT')]:
            self.assertEqual(counts[key],1,key)
        counts,_=self.findings([['1','1','12664','0','0','0'],['1','3','6603','1','0','0']])
        self.assertEqual(counts[('ORPHAN','CHILD_WITHOUT_CHARACTER')],2)

    def test_connection_and_identifier_guards(self):
        for name in ['chars`; DELETE FROM x','a-b','å','a.b']:
            with self.assertRaises(ValueError): audit.ident(name)
        for flag in ['--execute=DELETE FROM x','-e','--force','--init-command=DELETE FROM x','--password=secret']:
            with self.assertRaises(ValueError): audit.mysql_arguments([flag])
        args=audit.mysql_arguments(['--no-defaults','--host=127.0.0.1','--user=reader'])
        self.assertEqual(args[-2:],['--skip-force','--init-command=SET SESSION transaction_read_only=ON'])

    def test_missing_native_schema_is_incomplete_and_never_generates_updates(self):
        coverage=[]
        with self.assertRaises(ValueError):
            audit.build_queries(SimpleNamespace(characters_schema='chars',auth_schema='auth',world_schema='world',scope='all'),{},None,coverage)
        self.assertEqual(coverage[0][1],'SKIPPED')

    def test_query_failure_seals_an_incomplete_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            client=root/'mysql'
            client.write_text("#!/bin/sh\nprintf '%s\\n' 'ERROR 1045: Access denied for audit fixture' >&2\nexit 1\n")
            client.chmod(0o755)
            result=subprocess.run([sys.executable,str(ROOT/'tools/audit-tc-source.py'),
                '--characters-schema','chars','--auth-schema','auth','--world-schema','world',
                '--tc-dbc',str(self.path/'tc-dbc'),'--output',str(root/'out'),'--mysql','--no-defaults'],
                env=os.environ|{'PATH':str(root)+':'+os.environ['PATH']},text=True,capture_output=True)
            self.assertEqual(result.returncode,2,result.stderr)
            status=json.loads((root/'out/audit.json').read_text())
            self.assertEqual(status['status'],'INCOMPLETE')
            self.assertEqual(status['cleanup_approval'],'NOT_GRANTED')
            self.assertTrue((root/'out/SHA256SUMS').exists())


if __name__=='__main__':
    unittest.main()
