#!/usr/bin/env python3
"""Selected ownership is authoritative; disabled and enabled conflicts differ."""
from collections import defaultdict
import copy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'lib'))
from cleanup_console import CleanupError
import cleanup_selected_rank_history as history


class SelectedRankHistoryTests(unittest.TestCase):
    def setUp(self):
        talents={s:(1,s-599) for s in range(600,605)}|{620:(2,1),621:(2,2)}
        tab=[0]*23;tab[20]=2
        talent_rows={s:[0,family]+[0]*21 for s,(family,_) in talents.items()}
        self.meta=SimpleNamespace(talents=talents,talent_rows=talent_rows,
            stores={'TalentTab':{1:tab,2:list(tab)},'SkillLine':{}},
            spells={s:[0]*234 for s in talents},invalid_talents=set(),
            learns=defaultdict(list),effect_learns=defaultdict(list),requires=defaultdict(set),
            abilities=defaultdict(list),scripts=defaultdict(set),script_policy={},history_default_spells=set(),
            chain=lambda s:tuple(range(600,605)) if s<610 else (620,621),check_spell=lambda s:None)
        self.rows=[[1,601,1,1,2,1,0,2,0,history.DISPOSITION,1,2,'[[600,0,1],[603,1,4]]'],
                   [1,602,0,1,2,1,0,2,0,history.DISPOSITION,1,3,'[[600,0,1],[603,1,4]]'],
                   [2,620,1,1,2,1,0,1,0,history.DISPOSITION,2,1,'[[621,0,2]]'],
                   [3,601,1,0,2,1,0,1,0,'REVIEW_ENABLED_OTHER_SELECTED_RANK',1,2,'[[600,0,1]]'],
                   [4,601,1,1,2,1,0,1,4,'DEFER_PENDING_NATIVE_RESET',1,2,'[[600,0,1]]']]
        self.state={'talents':[[1,600,0],[1,603,1],[2,621,0],[3,600,0],[4,600,0]],
                    'spells':[[r[0],r[1],r[2],r[3]] for r in self.rows]+[[1,600,1,0],[1,603,1,1],[2,621,1,0]]}

    def call(self):return history.select(self.rows,self.state,self.meta,3)

    def test_lower_and_higher_stale_ranks_both_specs_preserved(self):
        before=copy.deepcopy((self.rows,self.state))
        selected,excluded,proof=self.call()
        self.assertEqual(selected,[(1,601,1,1),(1,602,0,1),(2,620,1,1)])
        self.assertEqual(excluded,[])
        self.assertEqual(json.loads(proof[0][6]),[[600,0,1],[603,1,4]])
        self.assertEqual(json.loads(proof[0][7]),[[600,1,0],[603,1,1]])
        self.assertEqual((self.rows,self.state),before)
        self.assertEqual(self.call(),self.call())

    def test_selected_or_conflicting_group_ownership_never_removed(self):
        self.state['talents'].append([1,601,1])
        self.assertEqual([r[2] for r in self.call()[1]],['DEFER_SELECTED_RANK_OWNERSHIP']*2)
        self.state['talents']=[r for r in self.state['talents'] if r[0]!=1]
        self.assertEqual([r[2] for r in self.call()[1]],['DEFER_SELECTED_RANK_OWNERSHIP']*2)

    def test_enabled_unselected_sibling_defers_family(self):
        self.state['spells'].append([1,604,1,0])
        self.assertEqual([r[2] for r in self.call()[1]],['DEFER_ENABLED_UNSELECTED_FAMILY_RANK']*2)

    def test_missing_selected_spell_is_reported_without_grant_or_replacement(self):
        self.state['spells']=[r for r in self.state['spells'] if r[:2]!=[1,603]]
        proof=self.call()[2]
        self.assertEqual(json.loads(proof[0][7]),[[600,1,0],[603,None,None]])
        self.assertNotIn((1,603),{r[:2] for r in self.call()[0]})

    def test_independent_skill_default_and_dependency_routes_defer(self):
        for field in ('learns','effect_learns'):
            getattr(self.meta,field)[900]=[(601,1,True)]
            self.assertEqual(self.call()[1][0][2],'DEFER_INDEPENDENT_LEARN_ROUTE')
            getattr(self.meta,field).clear()
        self.meta.requires[900]={602}
        self.assertEqual(self.call()[1][0][2],'DEFER_SELECTED_FAMILY_DEPENDENCIES')
        self.meta.requires.clear();self.meta.learns[600]=[(900,1,True)]
        self.assertEqual(self.call()[1][0][2],'DEFER_SELECTED_FAMILY_DEPENDENCIES')
        self.meta.learns.clear();self.meta.history_default_spells={604}
        self.assertEqual(self.call()[1][0][2],'DEFER_SKILL_OR_DEFAULT_ROUTE')

    def test_professions_riding_unknown_skills_and_skill_effects_defer(self):
        ability=[0]*14;ability[1]=171
        self.meta.abilities[603]=[ability];self.meta.stores['SkillLine'][171]=[171,11]
        self.assertEqual(self.call()[1][0][2],'DEFER_SKILL_OR_DEFAULT_ROUTE')
        self.meta.abilities.clear();self.meta.spells[603][71]=40
        self.assertEqual(self.call()[1][0][2],'DEFER_TALENT_SKILL_EFFECT')

    def test_unknown_scripts_corrections_mixed_chains_and_class_defer(self):
        from spells import Unsupported
        self.meta.scripts[604]={'unknown'}
        self.assertEqual(self.call()[1][0][2],'DEFER_SCRIPTED_TALENT_FAMILY')
        self.meta.script_policy['unknown']='NO_SPELLBOOK_MUTATION'
        self.assertEqual(self.call()[1],[])
        def reject(s):
            if s==604:raise Unsupported('UNSUPPORTED_CORE_CORRECTION',str(s))
        self.meta.check_spell=reject
        self.assertEqual(self.call()[1][0][2],'DEFER_SELECTED_RANK_UNSUPPORTED_CORE_CORRECTION')
        self.meta.chain=lambda s:(600,900) if s<610 else (620,621)
        self.assertEqual(self.call()[1][0][2],'DEFER_MIXED_RANK_CHAIN')
        self.meta.stores['TalentTab'][1][20]=1
        self.assertEqual(self.call()[1][0][2],'DEFER_SELECTED_RANK_CLASS')

    def test_count_drift_invalid_flags_and_pending_resets(self):
        with self.assertRaises(CleanupError):history.select(self.rows,self.state,self.meta,2)
        self.state['spells'].append([1,604,2,1])
        self.assertEqual(self.call()[1][0][2],'DEFER_INVALID_FAMILY_SPELL_FLAGS')
        self.rows[0][8]=4
        self.assertEqual(self.call()[1][0][2],'DEFER_SELECTED_RANK_OWNERSHIP')


if __name__=='__main__':unittest.main()
