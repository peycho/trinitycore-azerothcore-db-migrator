#!/usr/bin/env python3
"""Profession availability corrections require known ranks and preserved skills."""
import copy,importlib.util,json,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'lib'))
from cleanup_professions import select,contract,RULES
from cleanup_console import CleanupError,parser
from spells import Metadata,reconstruct,Unsupported
spec=importlib.util.spec_from_file_location('profession_assets',ROOT/'tests/profession-activation-fixtures.py');assets=importlib.util.module_from_spec(spec);spec.loader.exec_module(assets)
spec=importlib.util.spec_from_file_location('profession_world',ROOT/'tests/spell-state-tests.py');semantic=importlib.util.module_from_spec(spec);spec.loader.exec_module(semantic)


class ProfessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();p=Path(cls.temp.name);profile=json.loads((ROOT/'compatibility/tc335-acwotlk-v2/spell-metadata.json').read_text())
        assets.base.write_assets(p,profile)
        cls.tc=Metadata('tc',p/'tc-dbc','tc',profile,assets.world(semantic.World));cls.ac=Metadata('ac',p/'ac-dbc','ac',profile,assets.world(semantic.World))
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()
    def setUp(self):
        self.tc=copy.deepcopy(type(self).tc);self.ac=copy.deepcopy(type(self).ac)
        self.state={'characters':[[1,4,4,32,0,2,0,32]],'character_talent':[],
            'character_spell':[[1,2108,0,0],[1,6603,1,0],[1,3275,1,0]],'character_skills':[[1,165,78,150]]}
    def review(self):return select(self.state,self.tc,self.ac,preview=True)
    def test_pending_profession_changes_only_activation_and_retains_reset(self):
        self.state['characters'][0][7]=36
        before=copy.deepcopy(self.state);self.assertFalse(self.review()[0])
        rows,excluded,_,summary,_=select(self.state,self.tc,self.ac,preview=True,pending_reset=True)
        self.assertEqual(rows,[(1,2108,0,0)]);self.assertFalse(excluded);self.assertEqual(self.state,before)
        self.assertTrue(summary['pending_native_reset_preserved']);self.assertFalse(summary['reset_executed'])
        self.state['characters'][0][7]=32;self.assertFalse(select(self.state,self.tc,self.ac,preview=True,pending_reset=True)[0])

    def test_fixed_catalog_and_explicit_activation_native_round_trip(self):
        for m in (self.tc,self.ac):
            for root in map(int,RULES['roots']):self.assertTrue(contract(m,root),(m.core,root))
        original=copy.deepcopy(self.state);rows,excluded,_,summary,_=self.review()
        self.assertEqual(rows,[(1,2108,0,0)]);self.assertFalse(excluded);self.assertEqual(self.state,original)
        self.assertEqual(summary['spell_rows_activated'],1);self.assertEqual(summary['spell_rows_inserted'],0)
        book={s:(a,d)for _,s,a,d in self.state['character_spell']};skills={165:(78,150)}
        with self.assertRaises(Unsupported)as e:reconstruct((4,4,0,2),book,{},skills,self.tc,self.ac,'tc-to-ac',level=32)
        self.assertEqual(e.exception.reason,'UNREPRESENTABLE_INACTIVE_SPELL')
        book[2108]=(1,0);out=reconstruct((4,4,0,2),book,{},skills,self.tc,self.ac,'tc-to-ac',level=32)
        self.assertIn(2108,out);self.assertNotIn(3104,out)
        reverse=reconstruct((4,4,0,2),{s:(r['mask'],)for s,r in out.items()if r['disposition']=='PERSISTENT'}, {},skills,self.ac,self.tc,'ac-to-tc',level=32)
        self.assertIn(2108,reverse);self.assertNotIn(3104,reverse)
    def test_all_four_existing_crafting_anchors_no_two_profession_assumption(self):
        self.state['characters'][0][2]=1
        self.state['character_spell']=[[1,s,0,0]for s in (26790,29844,30350,32549)]
        self.state['character_skills']=[[1,s,1,375]for s in (197,164,202,165)]
        before=copy.deepcopy(self.state);self.assertEqual(len(self.review()[0]),4);self.assertEqual(self.state,before)
    def test_never_activate_specializations_or_invent_missing_ranks(self):
        self.state['character_spell'].append([1,9788,0,0]);r=self.review()
        self.assertEqual(r[0],[(1,2108,0,0)]);self.assertEqual(r[1],[(1,9788,'DEFER_SPECIALIZATION_OR_UNREVIEWED_PROFESSION')])
        self.state['character_spell']=[[1,3275,0,0]];self.assertFalse(self.review()[0])
    def test_pending_reset_online_invalid_ownership_and_character_guards(self):
        original=copy.deepcopy(self.state)
        for field,v in ((1,9),(2,10),(3,81),(4,2),(5,3),(6,1),(7,4)):
            self.state=copy.deepcopy(original);self.state['characters'][0][field]=v;self.assertFalse(self.review()[0])
        self.state=copy.deepcopy(original);self.state['character_talent']=[[1,987654,0]];self.assertFalse(self.review()[0])
    def test_skill_and_stored_family_guards(self):
        original=copy.deepcopy(self.state)
        for skills in ([],[[1,165,0,150]],[[1,165,151,150]],[[1,165,78,149]]):
            self.state=copy.deepcopy(original);self.state['character_skills']=skills;self.assertFalse(self.review()[0])
        self.state=copy.deepcopy(original);self.state['character_spell'].append([1,3104,1,0]);self.assertFalse(self.review()[0])
        for flags in ((1,0),(0,1),(1,1)):
            self.state=copy.deepcopy(original);self.state['character_spell'][0][2:]=flags;self.assertFalse(self.review()[0])
    def test_identical_custom_metadata_in_both_worlds_is_not_stock_authorization(self):
        for field in (4,71,72,76,111,116):
            self.tc=copy.deepcopy(type(self).tc);self.ac=copy.deepcopy(type(self).ac)
            for m in (self.tc,self.ac):m.spells[2108][field]^=1
            self.assertFalse(self.review()[0])
        for attr in ('requires','learn_parents','prerequisite_users','scripts'):
            self.tc=copy.deepcopy(type(self).tc);self.ac=copy.deepcopy(type(self).ac)
            for m in (self.tc,self.ac):getattr(m,attr)[2108].add(6603 if attr!='scripts' else 'custom')
            self.assertFalse(self.review()[0])
    def test_skill_catalog_and_native_route_mutations_defer(self):
        for core in ('tc','ac'):
            self.tc=copy.deepcopy(type(self).tc);self.ac=copy.deepcopy(type(self).ac)
            m=getattr(self,core);m.stores['SkillLine'][165][1]=0
            self.assertFalse(self.review()[0])
        self.tc=copy.deepcopy(type(self).tc);self.ac=copy.deepcopy(type(self).ac)
        self.ac.abilities[2108]=[];self.assertFalse(self.review()[0])
        self.tc=copy.deepcopy(type(self).tc);self.ac=copy.deepcopy(type(self).ac)
        self.ac.aura_owners[2108].add(6603);self.assertFalse(self.review()[0])
    def test_higher_known_anchor_requires_its_native_cap(self):
        self.state['character_spell']=[[1,32549,0,0]]
        self.state['character_skills']=[[1,165,1,300]];self.assertFalse(self.review()[0])
        self.state['character_skills']=[[1,165,1,375]];self.assertEqual(self.review()[0],[(1,32549,0,0)])
    def test_count_duplicate_and_cli_guards(self):
        with self.assertRaises(CleanupError):select(self.state,self.tc,self.ac,2)
        self.state['character_spell'].append([1,2108,0,0])
        with self.assertRaises(CleanupError):self.review()
        args=parser().parse_args(['plan','profession-activation','--migration-inspection','latest','--preview']);self.assertTrue(args.profession_activation)


if __name__=='__main__':unittest.main()
