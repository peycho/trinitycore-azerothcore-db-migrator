#!/usr/bin/env python3
"""No database: evidence, metadata and generated SQL boundary regressions."""
import csv
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('talent_fixtures', ROOT/'tests/talent-cleanup-fixtures.py')
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)
planner = fixtures.planner


class TalentCleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        self.audit, self.dbc = fixtures.fixture(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def generate(self, **options):
        return planner.generate(self.audit, self.dbc, 3, self.path/'candidate', **options)

    def edit_json(self, name, change):
        path = self.audit/name
        data = json.loads(path.read_text())
        change(data)
        path.write_text(json.dumps(data))
        fixtures.seal(self.audit)

    def edit_findings(self, change):
        path = self.audit/'findings.tsv'
        with path.open(newline='') as stream:
            reader = csv.DictReader(stream, delimiter='\t')
            header = reader.fieldnames
            rows = list(reader)
        change(rows)
        fixtures.tsv(path, header, [[row[key] for key in header] for row in rows])
        fixtures.seal(self.audit)

    def test_exact_selection_deterministic_output_private_files_no_database(self):
        manifest = self.generate()
        self.assertEqual((manifest['selected_rows'], manifest['affected_characters']), (3,2))
        other = self.path/'second'
        planner.generate(self.audit, self.dbc, 3, other)
        target = self.path/'candidate'
        self.assertEqual({p.name:p.read_bytes() for p in target.iterdir()}, {p.name:p.read_bytes() for p in other.iterdir()})
        self.assertEqual(target.stat().st_mode & 0o777, 0o700)
        self.assertTrue(all(p.stat().st_mode & 0o077 == 0 for p in target.iterdir()))
        sql = (target/'00-setup.sql').read_text()
        self.assertIn('DELETE s FROM `tc_fixture_chars`.character_talent s JOIN expected', sql)
        self.assertNotIn('DELETE FROM `tc_fixture_chars`.character_spell', sql)
        self.assertNotIn('INSERT INTO `tc_fixture_chars`.character_spell', sql)
        self.assertIn('STOPPED_PREPARATION_COPY_ONLY', sql)
        self.assertNotIn('@CHAR_EQUAL@', sql)

    def test_output_reuse_never_overwrites(self):
        self.generate()
        original = (self.path/'candidate/manifest.json').read_bytes()
        with self.assertRaises(FileExistsError): self.generate()
        self.assertEqual((self.path/'candidate/manifest.json').read_bytes(), original)

    def test_complete_full_scope_audit_requires_its_skill_dbc_fingerprint(self):
        def change(data):
            data['scope'] = 'all'
            data['dbc_sha256']['SkillLine.dbc'] = planner.sha(self.dbc/'SkillLine.dbc')
        self.edit_json('audit.json', change)
        self.assertIn('SkillLine.dbc', self.generate()['dbc_sha256'])

    def test_unsealed_report_tampering_and_path_traversal_blocked(self):
        (self.audit/'findings.tsv').write_text('tampered')
        with self.assertRaisesRegex(ValueError, 'checksum mismatch'): self.generate()
        (self.audit/'SHA256SUMS').write_text('a'*64+'  ../escape\n')
        with self.assertRaisesRegex(ValueError, 'checksum entry'): self.generate()

    def test_incomplete_scope_and_producer_drift_blocked(self):
        self.edit_json('audit.json', lambda data: data.update(status='COMPLETE_WITH_LIMITATIONS'))
        with self.assertRaisesRegex(ValueError, 'COMPLETE audit'): self.generate()
        self.edit_json('audit.json', lambda data: data.update(status='COMPLETE', audit_tool_sha256='0'*64))
        with self.assertRaisesRegex(ValueError, 'producer/layout'): self.generate()

    def test_dbc_same_size_drift_blocked(self):
        path = self.dbc/'Talent.dbc'
        data = bytearray(path.read_bytes()); data[-1] ^= 1; path.write_bytes(data)
        with self.assertRaisesRegex(ValueError, 'DBC fingerprint'): self.generate()

    def test_valid_talent_rank_cannot_be_removed_even_with_resealed_audit(self):
        def change(rows):
            rows[0].update(source_key='1:12296:0', evidence=json.dumps({'spell':12296,'talentGroup':0,'matchesTalentEntryId':False}))
        self.edit_findings(change)
        with self.assertRaisesRegex(ValueError, 'selectable talent rank'): self.generate()

    def test_duplicate_keys_and_evidence_conflicts_blocked(self):
        self.edit_findings(lambda rows: rows.append(rows[0].copy()))
        with self.assertRaisesRegex(ValueError, 'Duplicate selected'): self.generate()
        def change(rows):
            rows.pop(); rows[0]['evidence'] = json.dumps({'spell': 442, 'talentGroup':0,'matchesTalentEntryId':False})
        self.edit_findings(change)
        with self.assertRaisesRegex(ValueError, 'evidence disagrees'): self.generate()

    def test_wrong_table_injection_and_native_key_bounds_blocked(self):
        self.edit_findings(lambda rows: rows[0].update(table='character_spell'))
        with self.assertRaisesRegex(ValueError, 'unexpected schema/table'): self.generate()
        self.edit_findings(lambda rows: rows[0].update(table='character_talent',source_key='1:130:256'))
        with self.assertRaisesRegex(ValueError, 'unsigned domains'): self.generate()

    def test_expected_count_schema_injection_and_archive_source_overlap_blocked(self):
        with self.assertRaisesRegex(ValueError, 'agree exactly'):
            planner.generate(self.audit,self.dbc,4,self.path/'candidate')
        with self.assertRaises(ValueError): self.generate(archive_schema='a`; DROP DATABASE b;')
        with self.assertRaisesRegex(ValueError, 'differ from every'): self.generate(archive_schema='tc_fixture_chars')

    def test_unsupported_talent_columns_blocked(self):
        with (self.audit/'schema-inventory.tsv').open('a') as stream:
            stream.write('C\ttc_fixture_chars\tcharacter_talent\tcustom_rank\tint unsigned\tNO\t\n')
        fixtures.seal(self.audit)
        with self.assertRaisesRegex(ValueError, 'three-column'): self.generate()


if __name__ == '__main__':
    unittest.main()
