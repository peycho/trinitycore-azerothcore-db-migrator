#!/usr/bin/env python3
"""Selected direct ranks are native ownership, never recursively inferred ranks."""
import copy,importlib.util,json,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'lib'))
from cleanup_selected_passive import select
from cleanup_console import CleanupError,parser
from spells import Metadata,reconstruct,Unsupported
spec=importlib.util.spec_from_file_location('direct_assets',ROOT/'tests/selected-passive-fixtures.py')
assets=importlib.util.module_from_spec(spec);spec.loader.exec_module(assets)
spec=importlib.util.spec_from_file_location('direct_semantic',ROOT/'tests/spell-state-tests.py')
semantic=importlib.util.module_from_spec(spec);spec.loader.exec_module(semantic)


class DirectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();profile=json.loads((ROOT/'compatibility/tc335-acwotlk-v2/spell-metadata.json').read_text())
        path=Path(cls.temp.name);assets.base.write_assets(path,profile)
        cls.tc=Metadata('tc',path/'tc-dbc','tc',profile,semantic.World())
        cls.ac=Metadata('ac',path/'ac-dbc','ac',profile,semantic.World())
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()
    def setUp(self):
        self.source=copy.deepcopy(self.tc);self.target=copy.deepcopy(self.ac);self.build(assets.FAMILIES[0])
    def build(self,family,active=0):
        _,cls,_,skill,ranks,*_=family
        self.state={'characters':[[1,1,cls,80,active,2,0,32]],
            'character_talent':[[1,ranks[0],active]],'character_spell':[[1,ranks[-1],1,0],[1,6603,1,0]],
            'character_skills':[[1,skill,400,400],[1,171,375,450]]}
        if family[0]==1638:self.state['character_talent'].append([1,17323,active])
    def review(self):return select(self.state,self.source,self.target,preview=True)
    def test_old_blocker_corrected_by_exact_ownership_both_specs_all_families_and_reverse(self):
        for family in assets.FAMILIES:
            for active in (0,1):
                with self.subTest(family=family[0],active=active):
                    self.build(family,active);original=copy.deepcopy(self.state)
                    selected,excluded,_,summary,_=self.review();self.assertEqual(selected,[(1,family[4][-1],1,0)])
                    self.assertEqual(excluded,[]);self.assertEqual(self.review()[0],selected)
                    book={s:(a,d)for _,s,a,d in self.state['character_spell']};talents={s:1<<k for _,s,k in self.state['character_talent']}
                    skills={s:(v,c)for _,s,v,c in self.state['character_skills']}
                    with self.assertRaises(Unsupported)as error:reconstruct((1,family[1],active,2),book,talents,skills,self.source,self.target,'tc-to-ac')
                    self.assertEqual(error.exception.reason,'UNAUTHORIZED_TALENT_SPELL')
                    del book[family[4][-1]]
                    result=reconstruct((1,family[1],active,2),book,talents,skills,self.source,self.target,'tc-to-ac')
                    chosen=result[family[4][0]];self.assertEqual(chosen['mask'],1<<active);self.assertEqual(chosen['disposition'],'TALENT')
                    self.assertFalse(set(family[4][1:])&result.keys());self.assertEqual(self.state,original)
                    self.assertFalse(summary['eligibility_proofs'][0]['source_lower_rank_reconstructed'])
                    reverse=reconstruct((1,family[1],active,2),{6603:(3,)},talents,skills,self.target,self.source,'ac-to-tc')
                    self.assertEqual(reverse[family[4][0]]['disposition'],'PERSISTENT')
                    self.assertNotIn(family[4][-1],reverse)
    def test_inactive_selection_is_preserved_and_cannot_supply_retiring_rank(self):
        self.state['character_talent'].append([1,12677,1]);self.assertEqual(self.review()[0],[])
        self.state['character_talent'][-1][1]=12676
        result=self.review();self.assertEqual(result[0],[(1,12677,1,0)])
        self.assertEqual(result[3]['eligibility_proofs'][0]['selected_spell_groups'],[[12295,0],[12676,1]])
        self.state['character_talent'][-1][1]=12295
        masks=dict(self.review()[3]['eligibility_proofs'][0]['native_authorization_masks']);self.assertEqual(masks[12295],3)
    def test_retained_selected_rows_multiple_conflicts_and_no_flag_repairs(self):
        self.state['character_spell'] += [[1,12295,1,0],[1,12676,1,0]]
        result=self.review();self.assertEqual(result[0],[(1,12676,1,0),(1,12677,1,0)])
        self.assertIn([12295,1,0],result[3]['eligibility_proofs'][0]['retained_source_flags'])
        self.state['character_spell'][-2][3]=1
        self.assertEqual(self.review()[0],[]) # never rewrite a selected owner's flags

    def test_numeric_id_order_does_not_order_divine_intellect(self):
        self.build(assets.FAMILIES[2]);self.state['character_talent']=[[1,20209,0]]
        self.assertEqual(self.review()[0],[(1,20208,1,0)])
        self.state['character_talent']=[[1,20208,0]];self.state['character_spell'][0][1]=20209
        self.assertEqual(self.review()[0],[]) # no higher selected promotion under this policy
    def test_unsafe_flags_ownership_pending_online_level_and_missing_prerequisite_defer(self):
        baseline=copy.deepcopy(self.state)
        mutations=[lambda s:s['characters'][0].__setitem__(7,4),lambda s:s['characters'][0].__setitem__(6,1),
          lambda s:s['characters'][0].__setitem__(3,200),lambda s:s['characters'][0].__setitem__(2,2),
          lambda s:s['character_talent'].append([1,12676,0]),lambda s:s['character_talent'].clear()]
        for a,d in ((0,0),(1,1),(0,1),(2,0)):
            mutations.append(lambda s,a=a,d=d:s['character_spell'][0].__setitem__(slice(2,None),[a,d]))
        for mutation in mutations:
            self.state=copy.deepcopy(baseline);mutation(self.state);self.assertEqual(self.review()[0],[])
        self.build(assets.FAMILIES[3]);self.state['character_talent'].pop();self.assertEqual(self.review()[0],[])
    def test_actual_pair_and_even_matching_mutated_contracts_are_rejected(self):
        for both in (False,True):
            for index,value in ((4,400),(71,36),(95,30),(116,6603),(12,0)):
                self.source=copy.deepcopy(self.tc);self.target=copy.deepcopy(self.ac)
                for meta in ([self.source,self.target]if both else [self.target]):meta.spells[12677][index]=value
                self.assertEqual(self.review()[0],[])
        self.source=copy.deepcopy(self.tc);self.target=copy.deepcopy(self.ac)
        self.target.abilities[12677][0][9]=2;self.assertEqual(self.review()[0],[])
        self.target=copy.deepcopy(self.ac);self.target.scripts[12677].add('unreviewed');self.assertEqual(self.review()[0],[])
        self.target=copy.deepcopy(self.ac);self.target.talents[12676]=(999,2);self.assertEqual(self.review()[0],[])
    def test_preview_counts_parser_and_prior_default_policy_retains_guards(self):
        from cleanup_ownership import select as prior
        self.assertEqual(prior(self.state,self.source,preview=True)[0],[])
        with self.assertRaises(CleanupError):select(self.state,self.source,self.target,2)
        self.assertEqual(select(self.state,self.source,self.target,1)[0],[(1,12677,1,0)])
        args=parser().parse_args(['plan','talent-ownership','--selected-direct-passives','--migration-inspection','latest','--preview'])
        self.assertTrue(args.selected_direct_passives)
        with self.assertRaises(SystemExit):parser().parse_args(['plan','talent-ownership','--selected-direct-passives','--native-passive-rekey','--migration-inspection','latest','--preview'])

if __name__=='__main__':unittest.main()
