#!/usr/bin/env python3
"""Retire explicit unavailable history, never fabricate a missing legacy chain."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'lib'))
from cleanup_inactive_legacy import select,LEGACY
from cleanup_console import CleanupError,parser
from spells import Metadata,reconstruct,Unsupported
spec=importlib.util.spec_from_file_location('legacy_assets',ROOT/'tests/inactive-legacy-fixtures.py')
assets=importlib.util.module_from_spec(spec);spec.loader.exec_module(assets)
spec=importlib.util.spec_from_file_location('semantic_assets',ROOT/'tests/spell-state-tests.py')
semantic=importlib.util.module_from_spec(spec);spec.loader.exec_module(semantic)


class LegacyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.profile=json.loads((ROOT/'compatibility/tc335-acwotlk-v2/spell-metadata.json').read_text())
        root=Path(cls.temp.name);assets.base.write_assets(root,cls.profile)
        cls.tc=Metadata('tc',root/'tc-dbc','tc',cls.profile,semantic.World())
        cls.ac=Metadata('ac',root/'ac-dbc','ac',cls.profile,semantic.World())
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()
    def setUp(self):
        self.source=copy.deepcopy(self.tc);self.target=copy.deepcopy(self.ac)
        self.state={'characters':[[1,1,1,80,0,2,0,32]],'character_talent':[[1,23881,0],[1,12664,1]],
            'character_spell':[[1,s,0,0]for s in LEGACY[:-1]]+[[1,30335,1,0],[1,23881,1,0],[1,6603,1,0]],
            'character_skills':[[1,171,375,450]]}
    def review(self):return select(self.state,self.source,self.target,preview=True)

    def test_old_migration_fails_and_exact_retirement_preserves_active_spells_and_builds(self):
        book={s:(a,d)for _,s,a,d in self.state['character_spell']};talents={23881:1,12664:2}
        with self.assertRaises(Unsupported) as error:
            reconstruct((1,1,0,2),book,talents,{},self.source,self.target,'tc-to-ac')
        self.assertEqual(error.exception.reason,'UNREPRESENTABLE_INACTIVE_SPELL')
        before=copy.deepcopy(self.state)
        rows,excluded,_,summary,_=self.review()
        self.assertEqual(rows,[(1,s,0,0)for s in LEGACY[:-1]])
        self.assertEqual(excluded,[]);self.assertEqual(summary['active_rows_removed'],0)
        self.assertEqual(summary['spell_rows_inserted'],0)
        self.assertEqual(self.review(),(rows,excluded,self.review()[2],summary,[]))
        retired={s for _,s,_,_ in rows}
        after={s:flags for s,flags in book.items()if s not in retired}
        out=reconstruct((1,1,0,2),after,talents,{},self.source,self.target,'tc-to-ac')
        self.assertIn(30335,out);self.assertIn(23881,out)
        self.assertFalse(retired & out.keys());self.assertEqual(self.state,before)
        self.assertTrue(all(self.source.chain(s)==(s,)for s in LEGACY))
        self.assertFalse(summary['eligibility_proofs'][0]['rank_links_inferred'])

    def test_both_specs_same_ownership_and_nonhighest_active_anchor(self):
        self.state['characters'][0][4]=1
        self.state['character_talent']=[[1,23881,0],[1,23881,1]]
        self.state['character_spell']=[[1,23892,1,0],[1,23893,0,0],[1,23881,1,0]]
        self.assertEqual(self.review()[0],[(1,23893,0,0)])
        self.assertEqual(self.review()[3]['eligibility_proofs'][0]['retained_active_spells'],[[23892,1,0]])

    def test_missing_active_anchor_disabled_mix_reset_online_foreign_invalid_talents_defer(self):
        baseline=copy.deepcopy(self.state)
        mutations=[lambda s:s['character_spell'].pop(4),
            lambda s:s['character_spell'][0].__setitem__(3,1),
            lambda s:s['characters'][0].__setitem__(7,4),lambda s:s['characters'][0].__setitem__(6,1),
            lambda s:s['characters'][0].__setitem__(2,2),
            lambda s:s['character_talent'].append([1,23881,0])]
        for mutate in mutations:
            self.state=copy.deepcopy(baseline);mutate(self.state)
            self.assertEqual(self.review()[0],[])

    def test_no_default_trainer_script_skill_talent_learning_requirement_trigger_or_chain_routes(self):
        mutations=[lambda m:m.scripts[23892].add('new_script'),lambda m:m.abilities[23892].append([0]*14),
            lambda m:m.trainer_taught.add(23892),lambda m:m.requires[23892].add(6603),
            lambda m:m.learns[23892].append((6603,1,False)),lambda m:m.learn_parents[23892].add(6603),
            lambda m:m.spells[6603].__setitem__(116,23892),lambda m:m.additional.add(23892)]
        for mutate in mutations:
            self.source=copy.deepcopy(self.tc);self.target=copy.deepcopy(self.ac)
            mutate(self.target);self.assertEqual(self.review()[0],[])
        self.source=copy.deepcopy(self.tc);self.target=copy.deepcopy(self.ac)
        self.source.history_default_spells={23892};self.assertEqual(self.review()[0],[])

    def test_paired_changes_are_not_an_automatic_contract_exception(self):
        for field in (4,19,41,71,80,86,95,116,208):
            self.source=copy.deepcopy(self.tc);self.target=copy.deepcopy(self.ac)
            for meta in (self.source,self.target):meta.spells[23892][field]^=1
            self.assertEqual(self.review()[0],[],field)

    def test_other_inactive_or_active_spells_stay_untouched_and_counts_are_exact(self):
        self.state['character_spell'].append([1,48782,0,0])
        self.assertNotIn(48782,{r[1]for r in self.review()[0]})
        with self.assertRaises(CleanupError):select(self.state,self.source,self.target,3)
        self.state['character_spell'].append([1,23892,0,0])
        with self.assertRaises(CleanupError):self.review()
        args=parser().parse_args(['plan','inactive-legacy-spells','--migration-inspection','latest','--expect-rows','4'])
        self.assertTrue(args.inactive_legacy);self.assertEqual(args.expect_review_rows,4)


if __name__=='__main__':unittest.main()
