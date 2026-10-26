#!/usr/bin/env python3
"""Absent direct roots do not authorize removing selected or enabled abilities."""
from collections import Counter, defaultdict
import copy
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'lib'))
from cleanup_console import CleanupError
from spells import Unsupported
import cleanup_trained_history as history


class TrainedHistoryTests(unittest.TestCase):
    def setUp(self):
        tab=[0]*23;tab[20]=1
        self.meta=SimpleNamespace(spells={s:[0]*234 for s in (100,101,102,200,201,202,900)},
            talents={100:(1,1),200:(2,1)},talent_rows={100:[1,1],200:[2,1]},
            stores={'SkillLine':{},'TalentTab':{1:tab}},invalid_talents=set(),
            learns=defaultdict(list),effect_learns=defaultdict(list),requires=defaultdict(set),
            abilities=defaultdict(list),scripts=defaultdict(set),script_policy={},history_default_spells=set(),
            chain=lambda s:(100,101,102) if 100<=s<=102 else (200,201,202) if 200<=s<=202 else (s,),
            first=lambda s:100 if 100<=s<=102 else 200 if 200<=s<=202 else s,check_spell=lambda s:None)
        self.state={'characters':[[1,1,1,80,0,2,0,0],[2,1,1,80,1,2,0,0]],
            'character_spell':[[1,102,1,1],[1,101,0,1],[1,900,1,0],[2,202,1,1]],
            'character_talent':[],'character_skills':[[1,118,1,1]]}
    def call(self):return history.select(self.state,self.meta,3)

    def test_absent_direct_root_and_lower_rank_no_grant(self):
        before=copy.deepcopy(self.state);selected,excluded,proof,summary,_=self.call()
        self.assertEqual(selected,[(1,101,0,1),(1,102,1,1),(2,202,1,1)])
        self.assertEqual(excluded,[]);self.assertEqual(summary['selected_direct_rows'],0)
        self.assertIn((1,1,100,'DIRECT_TALENT','ABSENT_NO_GRANT','',''),proof)
        self.assertEqual(self.state,before);self.assertEqual(self.call(),self.call())

    def test_pending_family_history_is_wholly_disabled_and_never_completes_reset(self):
        self.state['characters'][0][7]=36
        self.state['character_spell'].append([1,100,1,1])
        original=copy.deepcopy(self.state)
        result=history.select(self.state,self.meta,None,orphan_children=True,preview=True,pending_history=True)
        self.assertEqual(result[0],[(1,100,1,1),(1,101,0,1),(1,102,1,1)])
        self.assertEqual(self.state,original);self.assertTrue(result[3]['pending_native_reset_preserved']);self.assertFalse(result[3]['reset_executed'])
        for group in (0,1):
            self.state=copy.deepcopy(original);self.state['character_talent']=[[1,100,group]]
            self.assertFalse(history.select(self.state,self.meta,None,orphan_children=True,preview=True,pending_history=True)[0])
        for spell in (100,101,102):
            self.state=copy.deepcopy(original);next(r for r in self.state['character_spell']if r[0]==1 and r[1]==spell)[3]=0
            self.assertFalse(history.select(self.state,self.meta,None,orphan_children=True,preview=True,pending_history=True)[0])
        self.state=copy.deepcopy(original);self.state['characters'][0][6]=1
        self.assertFalse(history.select(self.state,self.meta,None,orphan_children=True,preview=True,pending_history=True)[0])
        with self.assertRaises(CleanupError):history.select(original,self.meta,None,pending_history=True)

    def test_selected_owner_in_either_group_preserves_whole_chain(self):
        for group in (0,1):
            self.state['character_talent']=[[1,100,group]]
            self.assertEqual(Counter(r[2] for r in self.call()[1]),{'DEFER_SELECTED_RELATED_TALENT':2})

    def test_enabled_root_or_related_rank_defers_group(self):
        for spell in (100,101):
            state=copy.deepcopy(self.state)
            self.state['character_spell']=[r for r in self.state['character_spell'] if r[1]!=spell]+[[1,spell,0,0]]
            expected=sum(r[3]==1 and r[1] not in self.meta.talents for r in self.state['character_spell'])
            result=history.select(self.state,self.meta,expected)
            self.assertTrue(all(r[2]=='DEFER_ENABLED_RELATED_SPELL' for r in result[1]))
            self.state=state

    def test_online_pending_and_foreign_class_never_qualify(self):
        for field,value,reason in ((6,1,'DEFER_ONLINE_CHARACTER'),(7,4,'DEFER_PENDING_NATIVE_RESET'),(2,2,'DEFER_FOREIGN_CLASS_TALENT')):
            char=list(self.state['characters'][0]);self.state['characters'][0][field]=value
            self.assertEqual({r[2] for r in self.call()[1]},{reason});self.state['characters'][0]=char

    def test_invalid_or_conflicting_ownership_defers_even_another_family(self):
        for owners in ([[1,900,0]],[[1,200,2]],[[1,200,0],[1,200,0]]):
            self.state['character_talent']=owners
            self.assertEqual({r[2] for r in self.call()[1]},{'DEFER_INVALID_TALENT_SELECTION'})

    def test_independent_defaults_and_skill_routes_defer(self):
        self.meta.learns[900]=[(102,1,False)]
        self.assertEqual({r[2] for r in self.call()[1]},{'DEFER_INDEPENDENT_LEARN_ROUTE'})
        self.meta.learns.clear();self.meta.history_default_spells={101}
        self.assertEqual({r[2] for r in self.call()[1]},{'DEFER_CUSTOM_DEFAULT_ROUTE'})
        self.meta.history_default_spells.clear();ability=[0]*14;ability[9]=2;self.meta.abilities[102]=[ability]
        self.assertIn('DEFER_SKILL_REWARD_ROUTE',{r[2] for r in self.call()[1]})

    def test_skill_effects_unknown_scripts_and_corrections_defer(self):
        self.meta.spells[101][71]=118
        self.assertEqual({r[2] for r in self.call()[1]},{'DEFER_TALENT_SKILL_EFFECT'})
        self.meta.spells[101][71]=0;self.meta.scripts[101].add('unknown')
        self.assertEqual({r[2] for r in self.call()[1]},{'DEFER_SCRIPTED_TALENT_FAMILY'})
        self.meta.script_policy['unknown']='NO_SPELLBOOK_MUTATION'
        self.assertEqual(self.call()[1],[])
        def check(s):
            if s==101:raise Unsupported('UNSUPPORTED_CORE_CORRECTION',str(s))
        self.meta.check_spell=check
        self.assertEqual({r[2] for r in self.call()[1]},{'DEFER_RELATION_UNSUPPORTED_CORE_CORRECTION'})

    def test_reachable_children_cannot_escape_enabled_or_cycle_guards(self):
        self.meta.effect_learns[100]=[(900,1,True)]
        self.assertEqual({r[2] for r in self.call()[1]},{'DEFER_ENABLED_RELATED_SPELL'})
        self.meta.requires[100].add(900)
        self.assertEqual({r[2] for r in self.call()[1]},{'DEFER_RELATION_CYCLE'})

    def test_count_and_invalid_flags_are_guarded(self):
        with self.assertRaises(CleanupError):history.select(self.state,self.meta,2)
        self.state['character_spell'][0][2]=2
        self.assertEqual({r[2] for r in self.call()[1]},{'DEFER_INVALID_RELATED_FLAGS'})
        self.state['character_spell'].append([1,102,1,1])
        with self.assertRaises(CleanupError):history.select(self.state,self.meta,4)


class TalentChildHistoryTests(unittest.TestCase):
    def setUp(self):
        TrainedHistoryTests.setUp(self)
        for spell in (300,301,400):self.meta.spells[spell]=[0]*234
        previous_chain,previous_first=self.meta.chain,self.meta.first
        self.meta.chain=lambda s:(300,301) if s in (300,301) else previous_chain(s)
        self.meta.first=lambda s:300 if s in (300,301) else previous_first(s)
        self.meta.effect_learns[100]=[(300,1,True)]
        self.meta.effect_learns[200]=[(400,1,True)]
        self.meta.spells[100][71]=36;self.meta.spells[100][116]=300
        self.meta.spells[200][71]=36;self.meta.spells[200][116]=400
        self.state['character_spell']=[[1,301,1,1],[1,300,0,1],[1,900,1,0],[2,400,1,1]]

    def review(self):return history.select(self.state,self.meta,None,orphan_children=True,preview=True)

    def test_v6_failing_control_and_v7_absent_root_prefix_closure(self):
        with self.assertRaises(CleanupError) as error:
            history.select(self.state,self.meta,3)
        self.assertEqual(error.exception.code,'TRAINED_HISTORY_SELECTION_MISMATCH')
        before=copy.deepcopy(self.state)
        selected,excluded,proof,summary,_=history.select(self.state,self.meta,3,orphan_children=True)
        self.assertEqual(selected,[(1,300,0,1),(1,301,1,1),(2,400,1,1)])
        self.assertEqual(excluded,[])
        self.assertEqual(summary['reviewed_candidate_rows'],3)
        self.assertEqual(summary['selected_characters'],2)
        self.assertIn((1,1,100,'DIRECT_TALENT','ABSENT_NO_GRANT','',''),proof)
        self.assertNotIn(900,{r[1] for r in selected})
        self.assertEqual(self.state,before)
        self.assertEqual(self.review(),self.review())

    def test_selected_owner_in_either_spec_and_enabled_siblings_are_retained(self):
        for group in (0,1):
            self.state['character_talent']=[[1,100,group]]
            selected,excluded,*_=self.review()
            self.assertEqual(selected,[(2,400,1,1)])
            self.assertEqual(Counter(r[2] for r in excluded),{'DEFER_SELECTED_RELATED_TALENT':2})
        self.state['character_talent']=[]
        for spell in (100,101,301):
            before=copy.deepcopy(self.state)
            self.state['character_spell']=[r for r in self.state['character_spell'] if r[1]!=spell]+[[1,spell,1,0]]
            selected,excluded,*_=self.review()
            self.assertEqual(selected,[(2,400,1,1)])
            self.assertEqual({r[2] for r in excluded},{'DEFER_ENABLED_RELATED_SPELL'})
            self.state=before

    def test_whole_family_removes_only_present_disabled_rows(self):
        self.state['character_spell'] += [[1,100,1,1],[1,101,0,1]]
        selected,_,_,summary,_=history.select(self.state,self.meta,3,orphan_children=True)
        self.assertEqual(len(selected),5)
        self.assertEqual(summary['selected_direct_rows'],1)
        self.assertEqual(summary['selected_related_rows'],4)
        self.assertNotIn(102,{s for _,s,_,_ in selected})

    def test_character_pending_online_foreign_and_invalid_ownership_defer(self):
        for field,value,reason in ((6,1,'DEFER_ONLINE_CHARACTER'),(7,4,'DEFER_PENDING_NATIVE_RESET'),
                                   (2,2,'DEFER_FOREIGN_CLASS_TALENT'),(5,0,'DEFER_INVALID_CHARACTER_STATE')):
            char=self.state['characters'][0][:];self.state['characters'][0][field]=value
            selected,excluded,*_=self.review()
            self.assertEqual(selected,[(2,400,1,1)])
            self.assertEqual({r[2] for r in excluded},{reason})
            self.state['characters'][0]=char
        self.state['character_talent']=[[1,900,0]]
        self.assertEqual({r[2] for r in self.review()[1]},{'DEFER_INVALID_TALENT_SELECTION'})

    def test_independent_routes_skills_scripts_and_cycles_remain_deferred(self):
        for mutation,reason in (('incoming','DEFER_INDEPENDENT_LEARN_ROUTE'),
                                ('default','DEFER_CUSTOM_DEFAULT_ROUTE'),('skill','DEFER_TALENT_SKILL_EFFECT'),
                                ('script','DEFER_SCRIPTED_TALENT_FAMILY'),('cycle','DEFER_RELATION_CYCLE')):
            meta=copy.deepcopy(self.meta)
            if mutation=='incoming':self.meta.learns[900]=[(300,1,False)]
            elif mutation=='default':self.meta.history_default_spells={301}
            elif mutation=='skill':self.meta.spells[300][71]=118
            elif mutation=='script':self.meta.scripts[301].add('unreviewed')
            elif mutation=='cycle':self.meta.learns[301]=[(100,1,False)]
            self.assertEqual({r[2] for r in self.review()[1]},{reason})
            self.meta=meta

    def test_ambiguous_shared_child_is_not_assigned_a_guessed_owner(self):
        self.meta.effect_learns[200].append((300,1,True))
        selected,excluded,*_=self.review()
        self.assertFalse(any(s in (300,301) for _,s,_,_ in selected))
        self.assertEqual(Counter(r[2] for r in excluded)['DEFER_AMBIGUOUS_TALENT_DERIVATION'],2)

    def test_preview_zero_and_wrong_counts_never_select_a_package(self):
        for expected in (0,1,4,None):
            with self.assertRaises(CleanupError) as error:
                history.select(self.state,self.meta,expected,orphan_children=True)
            self.assertEqual(error.exception.code,'HISTORY_CHILD_SELECTION_MISMATCH')
        self.state['character_spell']=[[1,900,1,0]]
        self.assertEqual(self.review()[3]['reviewed_candidate_rows'],0)
        self.assertEqual(self.review()[0],[])


if __name__=='__main__':unittest.main()
