#!/usr/bin/env python3
"""Ordinary cleanup never widens availability or borrows talent cleanup rules."""
from collections import defaultdict
import copy
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'lib'))
from cleanup_console import CleanupError, parser
from spells import Unsupported
import cleanup_ordinary_history as ordinary
import cleanup_trained_history as trained


class OrdinaryHistoryTests(unittest.TestCase):
    def setUp(self):
        tab=[0]*23;tab[20]=1
        self.meta=SimpleNamespace(spells={s:[0]*234 for s in (100,200,201,300,400,500)},
            talents={100:(1,1)},talent_rows={100:[1,1]},invalid_talents=set(),
            stores={'TalentTab':{1:tab},'SkillLine':{1:[1,7],171:[171,11]},
                    'SkillRaceClassInfo':{1:[1,1,0,1,0,0,0]}},
            learns=defaultdict(list),effect_learns=defaultdict(list),requires=defaultdict(set),
            abilities=defaultdict(list),scripts=defaultdict(set),script_policy={},history_default_spells=set(),
            chain=lambda s:(200,201) if s in (200,201) else (s,),
            check_spell=lambda s:None)
        self.meta.effect_learns[100]=[(300,1,True)]
        self.meta.spells[100][71]=36;self.meta.spells[100][116]=300
        self.state={'characters':[[1,1,1,80,0,2,0,0],[2,1,1,80,1,2,0,0]],
            'character_spell':[[1,200,0,1],[1,201,1,1],[1,400,1,0],[2,201,1,1],[1,300,1,1]],
            'character_talent':[[1,100,0],[2,100,1]],'character_skills':[[1,171,320,450]]}

    def review(self):return ordinary.select(self.state,self.meta,None,preview=True)

    def test_exact_isolated_family_absent_rank_no_grant_and_old_failing_control(self):
        before=copy.deepcopy(self.state)
        selected,excluded,proof,summary,_=ordinary.select(self.state,self.meta,3)
        self.assertEqual(selected,[(1,200,0,1),(1,201,1,1),(2,201,1,1)])
        self.assertFalse(excluded);self.assertEqual(summary['selected_characters'],2)
        self.assertIn((2,200,200,'ORDINARY_RANK','ABSENT_NO_GRANT','',''),proof)
        self.assertEqual(self.state,before);self.assertEqual(self.review(),self.review())
        self.meta.first=lambda s:200 if s in (200,201) else s
        with self.assertRaises(CleanupError) as e:trained.select(self.state,self.meta,3)
        self.assertEqual(e.exception.code,'TRAINED_HISTORY_SELECTION_MISMATCH')

    def test_enabled_and_invalid_siblings_defer_whole_family(self):
        for flags,reason in (((1,0),'DEFER_ENABLED_RELATED_SPELL'),((0,0),'DEFER_ENABLED_RELATED_SPELL'),
                             ((2,1),'DEFER_INVALID_RELATED_FLAGS'),((1,2),'DEFER_INVALID_RELATED_FLAGS')):
            self.state['character_spell'][0]=[1,200,*flags]
            selected,excluded,*_=self.review()
            self.assertEqual(selected,[(2,201,1,1)])
            self.assertEqual({r[2] for r in excluded},{reason})

    def test_all_talent_ancestry_and_aura_routes_remain_protected(self):
        self.meta.effect_learns[300]=[(200,1,True)]
        self.meta.spells[300][71]=36;self.meta.spells[300][116]=200
        self.assertEqual(self.review()[3]['reviewed_candidate_rows'],0)
        self.meta.effect_learns[300]=[]
        for name in ('aura_owners','world_aura_owners','additional'):
            setattr(self.meta,name,{200})
            self.assertEqual({r[2] for r in self.review()[1]},{'DEFER_TALENT_OR_AURA_ROUTE'})
            delattr(self.meta,name)

    def test_every_dependency_direction_and_internal_cycle_defers(self):
        for kind in ('incoming','outgoing','effect','requirement','cycle'):
            self.meta.learns.clear();self.meta.requires.clear()
            if kind=='incoming':self.meta.learns[400]=[(200,1,False)]
            elif kind=='outgoing':self.meta.learns[201]=[(400,1,False)]
            elif kind=='requirement':self.meta.requires[200].add(400)
            elif kind=='cycle':self.meta.learns[201]=[(200,1,False)]
            else:self.meta.effect_learns[201]=[(400,1,True)]
            self.assertEqual({r[2] for r in self.review()[1]},{'DEFER_LEARNING_OR_REQUIREMENT_ROUTE'})
            self.meta.effect_learns.pop(201,None)

    def test_whole_chain_skill_profession_reward_and_default_guards(self):
        for effect in (36,40,44,47,118):
            self.meta.spells[200][71]=effect
            self.assertFalse(self.review()[0])
        self.meta.spells[200][71]=0
        for skill,acquire,reason in ((1,2,'DEFER_SKILL_REWARD_ROUTE'),(171,0,'DEFER_PROFESSION_OR_RIDING_RELATION'),
                                   (776,0,'DEFER_PROFESSION_OR_RIDING_RELATION'),(999,0,'DEFER_UNSUPPORTED_RELATION_METADATA')):
            row=[0]*14;row[1]=skill;row[9]=acquire;self.meta.abilities[200]=[row]
            self.assertEqual({r[2] for r in self.review()[1]},{reason})
        self.meta.abilities.clear();self.meta.history_default_spells={200}
        self.assertEqual({r[2] for r in self.review()[1]},{'DEFER_CUSTOM_DEFAULT_ROUTE'})

    def test_unknown_scripts_and_core_corrections_never_bypass_metadata(self):
        self.meta.scripts[200].add('test_script')
        self.assertEqual({r[2] for r in self.review()[1]},{'DEFER_SCRIPTED_SPELL_FAMILY'})
        self.meta.script_policy['test_script']='NO_SPELLBOOK_MUTATION'
        self.assertEqual(len(self.review()[0]),3)
        def fail(spell):raise Unsupported('UNSUPPORTED_CORE_CORRECTION',str(spell))
        self.meta.check_spell=fail
        self.assertEqual({r[2] for r in self.review()[1]},{'DEFER_RELATION_UNSUPPORTED_CORE_CORRECTION'})

    def test_character_and_both_spec_ownership_validation(self):
        for field,value,reason in ((6,1,'DEFER_ONLINE_CHARACTER'),(7,4,'DEFER_PENDING_NATIVE_RESET'),
            (1,0,'DEFER_INVALID_CHARACTER_STATE'),(2,0,'DEFER_INVALID_CHARACTER_STATE'),
            (3,81,'DEFER_INVALID_CHARACTER_STATE'),(4,2,'DEFER_INVALID_CHARACTER_STATE')):
            old=self.state['characters'][0][field];self.state['characters'][0][field]=value
            self.assertEqual({r[2] for r in self.review()[1]},{reason})
            self.state['characters'][0][field]=old
        for talents in ([[1,500,0]],[[1,100,2]],[[1,100,0],[1,100,0]]):
            self.state['character_talent']=talents
            self.assertEqual({r[2] for r in self.review()[1]},{'DEFER_INVALID_TALENT_SELECTION'})

    def test_native_race_class_eligibility_is_required_for_ability_associations(self):
        row=[0]*14;row[1]=1;row[4]=2;self.meta.abilities[200]=[row]
        self.assertEqual({r[2] for r in self.review()[1]},{'DEFER_SPELL_RACE_CLASS'})
        row[4]=1
        self.assertEqual(len(self.review()[0]),3)

    def test_unknown_duplicate_and_malformed_ranks_never_get_removed(self):
        self.state['character_spell'].append([1,9999,1,1])
        self.assertIn((1,9999,'DEFER_UNKNOWN_SPELL'),self.review()[1])
        self.state['character_spell'].append([1,201,1,1])
        with self.assertRaises(CleanupError):self.review()
        self.state['character_spell'].pop();self.meta.chain=lambda s:(200,201,200) if s==200 else (s,)
        with self.assertRaises(CleanupError):self.review()

    def test_count_preview_zero_no_eligible_and_cli_are_explicit(self):
        for expected in (None,0,1,4,500001):
            with self.assertRaises(CleanupError) as e:ordinary.select(self.state,self.meta,expected)
            self.assertEqual(e.exception.code,'ORDINARY_HISTORY_SELECTION_MISMATCH')
        args=parser().parse_args(['plan','disabled-spell-history','--migration-inspection','latest','--preview'])
        self.assertTrue(args.ordinary_spell_history and args.preview);self.assertIsNone(args.inspection)
        self.state['character_spell']=[[1,400,1,0]]
        self.assertEqual(self.review()[3]['reviewed_candidate_rows'],0)
        self.state['character_spell']=[[1,200,1,1],[1,201,1,0]]
        with self.assertRaises(CleanupError) as e:ordinary.select(self.state,self.meta,1)
        self.assertEqual(e.exception.code,'HISTORY_NO_ELIGIBLE_ROWS')


if __name__=='__main__':unittest.main()
