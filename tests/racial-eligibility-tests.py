#!/usr/bin/env python3
"""Wrong-race retirement stays opt-in, fixed-catalog and spell-only."""
import copy,importlib.util,json,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'lib'))
from cleanup_console import CleanupError,parser
from cleanup_eligibility import select,RACIAL_CATALOG
from spells import Metadata,Unsupported,reconstruct

def module(name,file):
    spec=importlib.util.spec_from_file_location(name,ROOT/'tests'/file)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result
semantic=module('racial_semantic','spell-state-tests.py')
fixture=module('racial_assets','spell-fixtures.py')
racials=module('racial_catalog_assets','racial-eligibility-fixtures.py')

class RacialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.path=Path(cls.temp.name)
        cls.profile=json.loads((ROOT/'compatibility/tc335-acwotlk-v2/spell-metadata.json').read_text())
        original=fixture.stores
        fixture.stores=lambda p:racials.extend(original(p),p)
        fixture.write_assets(cls.path,cls.profile)
        cls.tc=Metadata('tc',cls.path/'tc-dbc','tc',cls.profile,semantic.World())
        cls.ac=Metadata('ac',cls.path/'ac-dbc','ac',cls.profile,semantic.World())
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()
    def setUp(self):
        self.tc,self.ac=copy.deepcopy(type(self).tc),copy.deepcopy(type(self).ac)
        self.state={'characters':[[1,10,6,80,0,2,0,32]],
          'character_spell':[[1,s,1,0]for s in (20597,28875,59224,59539)]+[[1,6603,1,0]],
          'character_talent':[], 'character_skills':[[1,755,375,450]]}
    def review(self):return select(self.state,self.tc,self.ac,preview=True,reviewed_racials=True)
    def test_explicit_retirement_preserves_unrelated_source_and_native_load(self):
        before=copy.deepcopy(self.state)
        with self.assertRaises(Unsupported)as error:
            reconstruct((10,6,0,2),{s:(a,d)for _,s,a,d in self.state['character_spell']},{},{755:(375,450)},self.tc,self.ac,'tc-to-ac')
        self.assertEqual(error.exception.reason,'AC_WOULD_DELETE_SPELL')
        self.assertFalse(select(self.state,self.tc,self.ac,preview=True)[0])
        self.assertFalse(select(self.state,self.tc,self.ac,preview=True,absent_teachers=True)[0])
        rows,excluded,_,summary,_=self.review()
        self.assertEqual({r[1]for r in rows},{20597,28875,59224,59539})
        self.assertFalse(excluded);self.assertEqual(summary['reviewed_racial_rows'],4)
        self.assertEqual(summary['skill_rows_changed'],0)
        self.assertEqual(set(reconstruct((10,6,0,2),{6603:(1,0)},{},{755:(375,450)},self.tc,self.ac,'tc-to-ac')),{6603})
        self.assertEqual(self.state,before)
        self.assertEqual(select(self.state,self.tc,self.ac,4,reviewed_racials=True)[0],rows)
        with self.assertRaises(CleanupError):select(self.state,self.tc,self.ac,3,reviewed_racials=True)
    def test_legitimate_races_remain_and_class_only_mismatch_is_not_removed(self):
        for spell,race in ((20597,1),(59224,3),(28875,11),(59539,11)):
            self.state['characters'][0][1]=race
            self.state['character_spell']=[[1,spell,1,0]]
            self.assertFalse(self.review()[0])
        self.state['characters'][0][2]=10 # Valid bit mask, invalid character class.
        self.assertFalse(self.review()[0])
    def test_all_guards_remain(self):
        for field,value in ((6,1),(7,4),(3,81),(5,0)):
            original=self.state['characters'][0][field];self.state['characters'][0][field]=value
            self.assertFalse(self.review()[0]);self.state['characters'][0][field]=original
        self.state['character_skills'] += [[1,k,1,1]for k in (101,754,760)]
        self.assertFalse(self.review()[0])
    def test_catalog_and_routes_are_frozen_in_both_worlds(self):
        for core in ('tc','ac'):
            for change in (lambda m:m.spells[59224].__setitem__(95,98),
                           lambda m:m.abilities[59224][0].__setitem__(1,760),
                           lambda m:m.stores['SkillLine'][101].__setitem__(1,7),
                           lambda m:m.stores['SkillRaceClassInfo'][68].__setitem__(2,0),
                           lambda m:m.learns[59224].append((6603,1,False)),
                           lambda m:m.scripts[59224].add('spell_unknown'),
                           lambda m:m.aura_owners[59224].add(12282),
                           lambda m:m.additional.add(59224)):
                tc,ac=copy.deepcopy(self.tc),copy.deepcopy(self.ac);change(tc if core=='tc'else ac)
                self.assertNotIn(59224,{r[1]for r in select(self.state,tc,ac,preview=True,reviewed_racials=True)[0]},(core,change))
    def test_no_category_wide_or_mode_bypass(self):
        for m in (self.tc,self.ac):
            m.spells[900099]=m.spells[59224].copy();m.spells[900099][0]=900099
            m.abilities[900099]=[m.abilities[59224][0].copy()];m.abilities[900099][0][2]=900099
        self.state['character_spell'] += [[1,900099,1,0]]
        self.assertNotIn(900099,{r[1]for r in self.review()[0]})
        with self.assertRaises(CleanupError):select(self.state,self.tc,self.ac,preview=True,reviewed_racials=True,absent_teachers=True)
        with self.assertRaises(SystemExit):parser().parse_args(['plan','spell-eligibility','--migration-inspection','latest','--reviewed-racials','--absent-teachers','--preview'])

if __name__=='__main__':unittest.main()
