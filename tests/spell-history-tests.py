#!/usr/bin/env python3
"""Read-only direct talent history review boundaries and sealed input tests."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'lib'))
import cleanup_console as console
import cleanup_spell_history as history

spec = importlib.util.spec_from_file_location('history_fixtures', ROOT/'tests/talent-cleanup-fixtures.py')
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        audit, dbc = fixtures.fixture(self.root)
        self.session = self.root/'session'
        (self.session/'audits').mkdir(parents=True)
        self.audit = self.session/'audits/full-audit'
        audit.rename(self.audit)
        self.status = json.loads((self.audit/'audit.json').read_text())
        self.status.update(scope='all', audited_input_rows={
            'characters':2, 'character_talent':1, 'character_spell':3})
        self.status['dbc_sha256']['SkillLine.dbc'] = console.sha(dbc/'SkillLine.dbc')
        self.settings = SimpleNamespace(paths={'tc_dbc':dbc}, schemas=self.status['schemas'])
        self.work = SimpleNamespace(session=self.session,
            current=lambda:{'identity':{'uuid':self.status['server']['uuid']}})
        self.stores = fixtures.assets.stores(json.loads((console.PROFILE/'spell-metadata.json').read_text()))
        self.state = {'characters':[[1,1,1,0,2,0,0], [2,1,1,0,1,0,0]],
                      'talents':[[1,12664,1]],
                      'spells':[[1,12282,1,1], [2,12296,1,1], [2,6603,1,0]]}
        self.expected = {(1,12282):(1,1), (2,12296):(1,1)}
        self.save()

    def tearDown(self):
        self.temp.cleanup()

    def save(self):
        (self.audit/'audit.json').write_text(json.dumps(self.status))
        fixtures.tsv(self.audit/'findings.tsv',
            ['classification','schema','table','source_key','reason_code','evidence'],
            [('REVIEW',self.settings.schemas['characters'],'character_spell',f'{guid}:{spell}',
              'DISABLED_UNOWNED_TALENT_HISTORY', json.dumps({'spell':spell,'active':a,'disabled':d}))
             for (guid,spell),(a,d) in self.expected.items()])
        fixtures.tsv(self.audit/'summary.tsv', ['classification','reason_code','rows_found'],
                     [('REVIEW','DISABLED_UNOWNED_TALENT_HISTORY',len(self.expected))])
        fixtures.seal(self.audit)

    def read(self):
        return history.audit_inputs(self.settings, self.work, 'full-audit')

    def code(self, expected, callback):
        with self.assertRaises(console.CleanupError) as raised:
            callback()
        self.assertEqual(raised.exception.code, expected)

    def test_disabled_other_selected_rank_is_separate_in_either_spec(self):
        original = copy.deepcopy((self.state,self.stores,self.expected))
        rows = history.classify(self.state,self.stores,self.expected)
        self.assertEqual(rows[0][9], 'REVIEW_DISABLED_OTHER_SELECTED_RANK')
        self.assertEqual(json.loads(rows[0][-1]), [[12664,1,3]])
        self.assertEqual(rows[1][9], 'REVIEW_DISABLED_NO_SELECTED_FAMILY')
        self.assertEqual((self.state,self.stores,self.expected), original)
        self.state['talents'][0][2] = 0
        self.assertEqual(history.classify(self.state,self.stores,self.expected)[0][9], rows[0][9])

    def test_enabled_foreign_online_and_pending_states_are_distinct(self):
        for field, value, disposition in (
                (2,9,'REVIEW_FOREIGN_CLASS_TALENT'),
                (5,1,'DEFER_ONLINE_CHARACTER'),
                (6,36,'DEFER_PENDING_NATIVE_RESET'),
                (4,0,'DEFER_INVALID_CHARACTER_STATE')):
            with self.subTest(disposition=disposition):
                state = copy.deepcopy(self.state)
                state['characters'][1][field] = value
                self.assertEqual(history.classify(state,self.stores,self.expected)[1][9], disposition)
        self.state['spells'][0][3] = 0
        self.expected[1,12282] = (1,0)
        self.state['spells'][1][3] = 0
        self.expected[2,12296] = (1,0)
        rows = history.classify(self.state,self.stores,self.expected)
        self.assertEqual(rows[0][9], 'REVIEW_ENABLED_OTHER_SELECTED_RANK')
        self.assertEqual(rows[1][9], 'REVIEW_ENABLED_NO_SELECTED_FAMILY')

    def test_invalid_conflicting_and_out_of_range_ownership_deferred(self):
        for selected in ([[1,130,0]], [[1,12664,2]], [[1,12664,1],[1,12663,1]], [[1,17877,0]]):
            with self.subTest(selected=selected):
                self.state['talents'] = selected
                self.assertEqual(history.classify(self.state,self.stores,self.expected)[0][9],
                                 'DEFER_INVALID_TALENT_SELECTION')

    def test_audit_key_flag_and_same_count_replacement_drift_rejected(self):
        for spell, active, disabled in ((12296,0,1), (12296,1,0), (12300,1,1)):
            with self.subTest(spell=spell,active=active,disabled=disabled):
                self.state['spells'][1] = [2,spell,active,disabled]
                self.code('HISTORY_INPUT_DRIFT',lambda:history.classify(self.state,self.stores,self.expected))

    def test_ordinary_and_indirect_spells_not_selected_for_history_review(self):
        self.state['spells'] += [[2,6603,1,0], [2,47827,1,0]]
        self.assertEqual(len(history.classify(self.state,self.stores,self.expected)), 2)
        self.state['talents'].append([2,12296,0])
        self.code('HISTORY_INPUT_DRIFT',lambda:history.classify(self.state,self.stores,self.expected))

    def test_ambiguous_metadata_and_missing_spell_are_deferred(self):
        talent = list(self.stores['Talent'][137])
        talent[0] = 9999
        self.stores['Talent'][9999] = talent
        self.assertEqual(history.classify(self.state,self.stores,self.expected)[1][9],
                         'DEFER_AMBIGUOUS_TALENT_METADATA')
        del self.stores['Talent'][9999]
        del self.stores['Spell'][12296]
        self.assertEqual(history.classify(self.state,self.stores,self.expected)[1][9],
                         'DEFER_MISSING_SPELL_METADATA')

    def test_exact_sealed_findings_and_latest_pointer(self):
        self.assertEqual(self.read()[3], self.expected)
        (self.session/'latest-audit.json').write_text(json.dumps({'audit':'full-audit'}))
        self.assertEqual(history.audit_inputs(self.settings,self.work,None)[3], self.expected)
        self.assertEqual(console.parser().parse_args(['inspect-spell-history']).command,'inspect-spell-history')

    def test_tampering_and_symlinks_refused(self):
        path = self.audit/'findings.tsv'
        original = path.read_text()
        path.write_text(original+'changed')
        self.code('AUDIT_CHANGED', self.read)
        path.unlink()
        copy_path = self.root/'copy.tsv'
        copy_path.write_text(original)
        path.symlink_to(copy_path)
        self.code('AUDIT_CHANGED', self.read)

    def test_missing_summary_duplicate_keys_and_invalid_flag_evidence_refused(self):
        fixtures.tsv(self.audit/'summary.tsv',['classification','reason_code','rows_found'],[])
        fixtures.seal(self.audit)
        self.code('HISTORY_EVIDENCE_INVALID', self.read)
        self.save()
        path = self.audit/'findings.tsv'
        text = path.read_text()
        path.write_text(text+text.splitlines()[1]+'\n')
        fixtures.seal(self.audit)
        self.code('HISTORY_EVIDENCE_INVALID', self.read)
        self.expected[2,12296] = (True,1)
        self.save()
        self.code('HISTORY_EVIDENCE_INVALID', self.read)

    def test_incomplete_wrong_identity_changed_producer_and_bounded_counts_refused(self):
        original = copy.deepcopy(self.status)
        for key,value,code in (
                ('status','INCOMPLETE','FULL_AUDIT_REQUIRED'),
                ('scope','talents','FULL_AUDIT_REQUIRED'),
                ('limitations',['missing-world'],'FULL_AUDIT_REQUIRED'),
                ('server',{'uuid':'different'},'AUDIT_SESSION_MISMATCH'),
                ('metadata_reader_sha256','0'*64,'AUDIT_PRODUCER_CHANGED'),
                ('audited_input_rows',{'characters':True},'HISTORY_INPUT_UNSUPPORTED')):
            self.status = {**original,key:value}
            if key == 'server':
                self.work.current = lambda:{'identity':{'uuid':original['server']['uuid']}}
            self.save()
            self.code(code,self.read)

    def test_dbc_drift_refused(self):
        dbc = self.settings.paths['tc_dbc']/'Talent.dbc'
        dbc.write_bytes(dbc.read_bytes()+b'drift')
        self.code('DBC_DRIFT',self.read)


if __name__ == '__main__':
    unittest.main()
