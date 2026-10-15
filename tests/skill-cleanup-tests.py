#!/usr/bin/env python3
"""Offline selection and sealed-evidence boundaries for the skill clamp policy."""
import csv
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'lib'))
import cleanup_console as console
import cleanup_skills as skills

spec=importlib.util.spec_from_file_location('skill_fixtures',ROOT/'tests/talent-cleanup-fixtures.py')
fixtures=importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)


class SkillTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        audit,dbc=fixtures.fixture(self.root)
        session=self.root/'session'
        (session/'audits').mkdir(parents=True)
        self.audit=session/'audits/full-audit'
        audit.rename(self.audit)
        self.status=json.loads((self.audit/'audit.json').read_text())
        self.status.update(scope='all',audited_input_rows={'character_skills':3})
        self.status['dbc_sha256']['SkillLine.dbc']=console.sha(dbc/'SkillLine.dbc')
        self.settings=SimpleNamespace(paths={'tc_dbc':dbc},schemas=self.status['schemas'],compatibility={})
        self.work=SimpleNamespace(session=session,operation=self.root/'operation',
            current=lambda:{'identity':{'uuid':self.status['server']['uuid']}})
        self.work.operation.mkdir()
        self.args=SimpleNamespace(audit='full-audit',expect_rows=2)
        self.selected=[(1,171,450,300),(2,762,150,75)]
        self.save()

    def tearDown(self):
        self.temp.cleanup()

    def save(self,rows=None):
        if rows is None:
            rows=self.selected
        (self.audit/'audit.json').write_text(json.dumps(self.status))
        fixtures.tsv(self.audit/'findings.tsv',
            ['classification','schema','table','source_key','reason_code','evidence'],
            [('INVALID',self.settings.schemas['characters'],'character_skills',f'{g}:{s}',
              'SKILL_VALUE_EXCEEDS_CAP',json.dumps({'skill':s,'value':v,'max':m})) for g,s,v,m in rows])
        fixtures.tsv(self.audit/'summary.tsv',['classification','reason_code','rows_found'],
            [('INVALID','SKILL_VALUE_EXCEEDS_CAP',len(rows))])
        fixtures.seal(self.audit)

    def read(self):
        return skills.audit_inputs(self.settings,self.work,self.args)

    def assert_code(self,code):
        with self.assertRaises(console.CleanupError) as raised:
            self.read()
        self.assertEqual(raised.exception.code,code)

    def test_exact_audited_values_are_selected(self):
        self.assertEqual(self.read()[3],self.selected)

    def test_expected_count_and_duplicate_keys_are_rejected(self):
        self.args.expect_rows=1
        self.assert_code('SKILL_SELECTION_MISMATCH')
        self.args.expect_rows=2
        self.save([self.selected[0],self.selected[0]])
        self.assert_code('SKILL_SELECTION_MISMATCH')

    def test_zero_caps_unknown_skills_equal_values_and_boolean_evidence_are_rejected(self):
        for row in ((1,171,450,0),(1,65535,450,300),(1,171,300,300),(1,171,True,1)):
            with self.subTest(row=row):
                self.save([row,self.selected[1]])
                self.assert_code('SKILL_CLAMP_UNSUPPORTED')

    def test_incomplete_or_talent_only_audits_are_rejected(self):
        for update in ({'status':'INCOMPLETE'},{'scope':'talents'},{'limitations':['missing-world']}):
            with self.subTest(update=update):
                old=dict(self.status)
                self.status.update(update)
                self.save()
                self.assert_code('FULL_AUDIT_REQUIRED')
                self.status=old

    def test_wrong_source_identity_and_producer_are_rejected(self):
        self.status['schemas']={**self.settings.schemas,'characters':'other_chars'}
        self.save()
        self.assert_code('AUDIT_SESSION_MISMATCH')
        self.status['schemas']=self.settings.schemas
        self.status['audit_tool_sha256']='0'*64
        self.save()
        self.assert_code('AUDIT_PRODUCER_CHANGED')

    def test_report_tampering_and_symlinks_are_rejected(self):
        target=self.audit/'findings.tsv'
        original=target.read_text()
        target.write_text(original+'changed')
        self.assert_code('AUDIT_CHANGED')
        target.unlink()
        other=self.root/'copy.tsv'
        other.write_text(original)
        target.symlink_to(other)
        self.assert_code('AUDIT_CHANGED')

    def test_dbc_drift_and_summary_mismatch_are_rejected(self):
        dbc=self.settings.paths['tc_dbc']/'SkillLine.dbc'
        original=dbc.read_bytes()
        dbc.write_bytes(original+b'changed')
        self.assert_code('DBC_DRIFT')
        dbc.write_bytes(original)
        fixtures.tsv(self.audit/'summary.tsv',['classification','reason_code','rows_found'],
            [('INVALID','SKILL_VALUE_EXCEEDS_CAP',99)])
        fixtures.seal(self.audit)
        self.assert_code('SKILL_SELECTION_MISMATCH')

    def test_new_policy_is_available_in_parser(self):
        args=console.parser().parse_args(['plan','skills','--expect-rows','63'])
        self.assertEqual((args.kind,args.expect_rows),('skills',63))

    def test_untrusted_audit_digest_cannot_become_sql(self):
        self.status['audited_results_sha256']="'; DROP DATABASE ignored; --"
        self.save()
        self.assert_code('SKILL_EVIDENCE_INVALID')

    def test_live_skill_drift_and_online_characters_block_planning(self):
        columns=[]
        for table,fields in [('characters',[('guid','int unsigned','PRI'),('online','tinyint unsigned','')]),
                             ('character_skills',[('guid','int unsigned','PRI'),('skill','smallint unsigned','PRI'),
                                                  ('value','smallint unsigned',''),('max','smallint unsigned','')])]:
            columns.extend([table,name,typ,'NO',key,'','',i] for i,(name,typ,key) in enumerate(fields,1))
        meta={'columns':columns}
        state={'invalid':[list(r) for r in self.selected],
               'characters':[[1,0],[2,1]],'counts':[[3,3]]}
        for drift in ('online','value'):
            with self.subTest(drift=drift):
                if drift=='value':
                    state['characters'][1][1]=0
                    state['invalid'][0][2]+=1
                with patch.object(skills,'metadata',return_value=meta),patch.object(skills,'snapshot',return_value=state):
                    with self.assertRaises(console.CleanupError) as raised:
                        skills.plan_skills(self.settings,self.work,self.args,self.work.session/'new-batch')
                self.assertEqual(raised.exception.code,'SKILL_CHARACTER_UNAVAILABLE' if drift=='online' else 'SKILL_INPUT_DRIFT')
                self.assertFalse((self.work.session/'new-batch').exists())


if __name__=='__main__':
    unittest.main()
