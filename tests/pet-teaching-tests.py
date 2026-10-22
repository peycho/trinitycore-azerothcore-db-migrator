#!/usr/bin/env python3
"""Explicit pet-teacher retirement must never become a player/pet grant policy."""
import copy
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'lib'))
from cleanup_console import CleanupError,parser
from cleanup_pet_teaching import select,CONTRACTS
from cleanup_eligibility import select as old_select
from spells import Metadata,reconstruct,Unsupported

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module

semantic=load('semantic',ROOT/'tests/spell-state-tests.py')
pet=load('pet_assets',ROOT/'tests/pet-teaching-fixtures.py')


class PetTeachingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import tempfile
        cls.tmp=tempfile.TemporaryDirectory();cls.path=Path(cls.tmp.name)
        cls.profile=__import__('json').loads((ROOT/'compatibility/tc335-acwotlk-v2/spell-metadata.json').read_text())
        original=semantic.fixtures.stores
        semantic.fixtures.stores=lambda p:pet.extend(original(p),p)
        try:semantic.fixtures.write_assets(cls.path,cls.profile)
        finally:semantic.fixtures.stores=original
        world=semantic.World()
        world.tables['spell_ranks'] += [[str(root),str(s),str(i)] for root,pairs in CONTRACTS.items() for i,(s,_) in enumerate(pairs,1)]
        cls.tc=Metadata('tc',cls.path/'tc-dbc','tc',cls.profile,world)
        cls.ac=Metadata('ac',cls.path/'ac-dbc','ac',cls.profile,world)

    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    def setUp(self):
        self.tc,self.ac=copy.deepcopy(type(self).tc),copy.deepcopy(type(self).ac)
        self.state={'characters':[[1,1,3,80,0,2,0,32]],
                    'character_spell':[[1,1747,0,0],[1,1749,1,0],[1,27351,1,0],[1,6603,1,0]],
                    'character_talent':[[1,900050,0],[1,900051,1]],
                    'character_skills':[[1,171,375,450],[1,762,300,300]]}

    def review(self):return select(self.state,self.tc,self.ac,preview=True)

    def test_old_conversion_fails_and_explicit_repair_removes_only_teachers(self):
        baseline=copy.deepcopy(self.state)
        with self.assertRaises(Unsupported) as e:
            reconstruct((1,3,0,2),{1749:(1,0),6603:(1,0)}, {}, {},self.tc,self.ac,'tc-to-ac')
        self.assertEqual(e.exception.reason,'UNSUPPORTED_PERSISTENT_LEARN_EFFECT')
        self.assertFalse(old_select(self.state,self.tc,self.ac,preview=True)[0])
        rows,excluded,proof,summary,edges=self.review()
        self.assertEqual(rows,[(1,1747,0,0),(1,1749,1,0),(1,27351,1,0)])
        self.assertFalse(excluded)
        self.assertIn((1,1747,1748,'PET_TEACHING_WRAPPER','ABSENT_NO_GRANT','',''),proof)
        self.assertEqual(summary['pet_rows_changed'],0)
        self.assertEqual(summary['spell_rows_inserted'],0)
        self.assertEqual(self.state,baseline)
        self.assertEqual(self.review(),(rows,excluded,proof,summary,edges))
        self.assertEqual(set(reconstruct((1,3,0,2),{6603:(1,0)},{},{},self.tc,self.ac,'tc-to-ac')),{6603})
        self.assertEqual(select(self.state,self.tc,self.ac,3)[0],rows)
        with self.assertRaises(CleanupError) as e:select(self.state,self.tc,self.ac,2)
        self.assertEqual(e.exception.code,'PET_TEACHING_SELECTION_MISMATCH')

    def test_both_specs_and_disabled_history_never_rewrite_flags_or_ownership(self):
        for active in (0,1):
            self.state['characters'][0][4]=active
            self.state['character_spell'][1][3]=active
            before=copy.deepcopy(self.state)
            self.assertEqual(len(self.review()[0]),3)
            self.assertEqual(self.state,before)

    def test_pending_online_foreign_invalid_characters_and_talents_defer(self):
        for index,value in ((7,4),(6,1),(2,1),(3,81),(5,0),(4,2),(1,32)):
            state=copy.deepcopy(self.state);self.state['characters'][0][index]=value
            self.assertFalse(self.review()[0],(index,value));self.state=state
        self.state['character_talent'].append([1,900050,0])
        self.assertFalse(self.review()[0])

    def test_nonpet_and_profession_teachers_are_never_selected(self):
        for m in (self.tc,self.ac):
            m.spells[27351][86]=1
        rows,excluded,*_=self.review()
        self.assertEqual({r[1] for r in rows},{1747,1749})
        self.assertEqual(excluded,[(1,27351,'DEFER_PET_TEACHER_EFFECT_CONTRACT')])
        self.state['character_spell'].append([1,10321,1,0])
        self.assertNotIn(10321,{r[1] for r in self.review()[0]})

    def test_whole_stored_family_deferred_for_unsafe_lower_prefix(self):
        self.tc.scripts[1748].add('spell_unknown')
        rows,excluded,*_=self.review()
        self.assertEqual(rows,[(1,27351,1,0)])
        self.assertEqual({r[1]for r in excluded},{1747,1749})

    def test_scripts_skills_talents_routes_and_effect_changes_defer(self):
        mutations=(lambda m:m.scripts[27351].add('spell_known'),
                   lambda m:m.scripts[27053].add('spell_known'),
                   lambda m:m.requires[27351].add(6603),
                   lambda m:m.prerequisite_users[27351].add(6603),
                   lambda m:m.learn_parents[27351].add(6603),
                   lambda m:m.learns[27351].append((6603,1,False)),
                   lambda m:m.talent_learn_owners[27351].add(900050),
                   lambda m:m.abilities[27351].append(m.abilities[465][0]),
                   lambda m:m.spells[27351].__setitem__(72,44),
                   lambda m:m.spells[27351].__setitem__(116,6603),
                   lambda m:m.spells[27351].__setitem__(4,64),
                   lambda m:m.spells[27351].__setitem__(12,1))
        for mutation in mutations:
            for core in ('tc','ac'):
                tc,ac=copy.deepcopy(self.tc),copy.deepcopy(self.ac)
                mutation(tc if core=='tc'else ac)
                rows,excluded,*_=select(self.state,tc,ac,preview=True)
                self.assertNotIn(27351,{r[1]for r in rows})
                self.assertIn(27351,{r[1]for r in excluded})

    def test_changed_known_child_and_malformed_ranks_are_rejected(self):
        self.ac.spells[27053][71]=44
        self.assertNotIn(27351,{r[1]for r in self.review()[0]})
        self.tc.chains[1747]=(1747,1749)
        with self.assertRaises(CleanupError):self.review()

    def test_missing_known_child_blocks_but_absent_untrained_higher_child_is_not_granted(self):
        self.state['character_spell']=[[1,35299,1,0]]
        for m in (self.tc,self.ac):
            for parent,child in ((35306,35296),(35307,35297),(35308,35298)):
                m.spells.pop(child);m.learns[parent]=[];m.effect_learns[parent]=[]
        rows,excluded,*_=self.review()
        self.assertEqual(rows,[(1,35299,1,0)]);self.assertFalse(excluded)
        self.tc.spells.pop(35290);self.tc.learns[35299]=[];self.tc.effect_learns[35299]=[]
        self.assertFalse(self.review()[0])

    def test_pet_ability_in_player_book_is_preserved_and_defers_teacher(self):
        self.state['character_spell'].append([1,27053,1,0])
        rows,excluded,*_=self.review()
        self.assertNotIn(27053,{r[1]for r in rows})
        self.assertIn((1,27351,'DEFER_PET_ABILITY_IN_PLAYER_BOOK'),excluded)

    def test_unknown_pet_teachers_and_conflicting_target_chains_defer(self):
        for m in (self.tc,self.ac):
            m.spells[6603][71],m.spells[6603][86],m.spells[6603][116]=36,5,27053
        self.assertIn((1,6603,'DEFER_UNREVIEWED_PET_TEACHER'),self.review()[1])
        self.ac.chains[1747]=(1747,1748)
        with self.assertRaises(CleanupError):self.review()

    def test_cli_requires_preview_or_exact_count(self):
        for options in (['--preview'],['--expect-rows','3']):
            args=parser().parse_args(['plan','pet-teaching','--migration-inspection','latest',*options])
            self.assertTrue(args.pet_teaching)


if __name__=='__main__':unittest.main()
