#!/usr/bin/env python3
"""Closed disabled group selection must preserve every live learning route."""
from collections import defaultdict
import copy
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'lib'))
from cleanup_console import CleanupError
import cleanup_talent_relations as relations


class TalentRelationsTests(unittest.TestCase):
    def setUp(self):
        spells={s:[0]*234 for s in (100,101,200,201,600,601,900)}
        chains={100:(100,101),101:(100,101),200:(200,201),201:(200,201)}
        self.meta=SimpleNamespace(spells=spells,talents={100:(1,1),101:(1,2),600:(2,1)},
            invalid_talents=set(),requires=defaultdict(set),learns=defaultdict(list),effect_learns=defaultdict(list),
            abilities=defaultdict(list),scripts=defaultdict(set),script_policy={},history_default_spells=set(),
            stores={'SkillLine':{}},
            chain=lambda s:chains.get(s,(s,)),check_spell=lambda s:None)
        self.meta.learns[100]=[(200,1,False)]
        self.meta.effect_learns[101]=[(201,1,True)]
        self.rows=[[1,100,1,1,1,1,0,2,0,'REVIEW_DISABLED_NO_SELECTED_FAMILY',1,1,'[]'],
                   [1,101,0,1,1,1,0,2,0,'REVIEW_DISABLED_NO_SELECTED_FAMILY',1,2,'[]'],
                   [2,600,1,1,1,1,0,1,0,'REVIEW_DISABLED_NO_SELECTED_FAMILY',2,1,'[]']]
        self.state={'spells':[[r[0],r[1],r[2],r[3]] for r in self.rows],'talents':[]}
        self.stored=self.state['spells']+[[1,200,0,1],[1,900,1,0]]

    def call(self):
        return relations.select(self.rows,self.state,self.meta,self.stored,3)

    def test_exact_disabled_roots_children_and_absent_rank_no_grant(self):
        before=copy.deepcopy((self.rows,self.state,self.stored))
        selected,excluded,proof,summary,edges=self.call()
        self.assertEqual(selected,[(1,100,1,1),(1,101,0,1),(1,200,0,1),(2,600,1,1)])
        self.assertEqual(excluded,[])
        self.assertIn((1,1,201,'RANK_OR_DEPENDENT','ABSENT_NO_GRANT','',''),proof)
        self.assertEqual(summary['selected_root_rows'],3)
        self.assertEqual(summary['selected_related_rows'],1)
        self.assertEqual(edges,[(100,200,'WORLD_LEARN'),(101,201,'EFFECT_LEARN')])
        self.assertEqual((self.rows,self.state,self.stored),before)
        self.assertEqual(self.call(),self.call())

    def test_enabled_child_or_any_rank_defers_entire_group(self):
        self.stored[-2]=[1,200,1,0]
        self.assertEqual(self.call()[1],[(1,100,'DEFER_ENABLED_RELATED_SPELL'),(1,101,'DEFER_ENABLED_RELATED_SPELL')])
        self.stored[-2]=[1,201,0,0]
        self.assertEqual(self.call()[1][0][2],'DEFER_ENABLED_RELATED_SPELL')

    def test_selected_inactive_spec_is_not_removed(self):
        self.state['talents']=[[1,100,1]]
        self.assertEqual(self.call()[1][0][2],'DEFER_SELECTED_RELATED_TALENT')

    def test_mixed_chain_disabled_higher_rank_supported_enabled_rank_preserved(self):
        original=self.meta.chain
        self.meta.chain=lambda s:(600,601) if s in (600,601) else original(s)
        self.stored.append([2,601,0,1])
        self.assertIn((2,601,0,1),self.call()[0])
        self.stored[-1]=[2,601,0,0]
        self.assertEqual(self.call()[1],[(2,600,'DEFER_ENABLED_RELATED_SPELL')])

    def test_independent_incoming_route_defers_even_if_teacher_not_stored(self):
        self.meta.learns[900]=[(201,1,False)]
        self.assertEqual(self.call()[1][0][2],'DEFER_INDEPENDENT_LEARN_ROUTE')

    def test_shared_talent_owner_is_ambiguous(self):
        self.meta.talents[200]=(3,1)
        self.state['spells'].append([1,200,0,1])
        self.assertEqual(self.call()[1][0][2],'DEFER_SHARED_TALENT_RELATION')

    def test_cycle_and_internal_rank_dependency_are_rejected(self):
        self.meta.learns[200]=[(100,1,False)]
        self.assertEqual(self.call()[1][0][2],'DEFER_RELATION_CYCLE')
        self.meta.learns.pop(200)
        self.meta.requires[101]={100}
        self.assertEqual(self.call()[1][0][2],'DEFER_RELATION_CYCLE')

    def test_skill_default_and_script_guards_apply_to_absent_children(self):
        self.meta.history_default_spells={201}
        self.assertEqual(self.call()[1][0][2],'DEFER_CUSTOM_DEFAULT_ROUTE')
        self.meta.history_default_spells.clear()
        ability=[0]*14;ability[9]=2;self.meta.abilities[201]=[ability]
        self.assertEqual(self.call()[1][0][2],'DEFER_SKILL_REWARD_ROUTE')
        self.meta.abilities.clear()
        for effect in (40,44,47,118):
            self.meta.spells[201][71]=effect
            self.assertEqual(self.call()[1][0][2],'DEFER_TALENT_SKILL_EFFECT')
        self.meta.spells[201][71]=0
        self.meta.scripts[201]={'unknown_script'}
        self.assertEqual(self.call()[1][0][2],'DEFER_SCRIPTED_TALENT_FAMILY')
        self.meta.script_policy['unknown_script']='NO_SPELLBOOK_MUTATION'
        self.assertEqual(self.call()[1],[])

    def test_invalid_pet_learn_and_core_correction_are_not_guessed(self):
        from spells import Unsupported
        self.meta.spells[101][71]=36;self.meta.spells[101][116]=99999
        self.assertEqual(self.call()[1][0][2],'DEFER_UNSUPPORTED_RELATION_METADATA')
        self.meta.spells[101][116]=201;self.meta.spells[101][86]=5
        self.assertEqual(self.call()[1][0][2],'DEFER_UNSUPPORTED_RELATION_METADATA')
        self.meta.spells[101][86]=0
        def reject(s):
            if s==201:raise Unsupported('UNSUPPORTED_CORE_CORRECTION',str(s))
        self.meta.check_spell=reject
        self.assertEqual(self.call()[1][0][2],'DEFER_RELATION_UNSUPPORTED_CORE_CORRECTION')

    def test_recipes_secondary_professions_and_riding_remain_separate(self):
        ability=[0]*14;ability[1]=171
        self.meta.abilities[201]=[ability]
        for category in (9,11):
            self.meta.stores['SkillLine'][171]=[171,category]
            self.assertEqual(self.call()[1][0][2],'DEFER_PROFESSION_OR_RIDING_RELATION')
        self.meta.stores['SkillLine'].clear();ability[1]=762
        self.assertEqual(self.call()[1][0][2],'DEFER_PROFESSION_OR_RIDING_RELATION')
        ability[1]=99999
        self.assertEqual(self.call()[1][0][2],'DEFER_UNSUPPORTED_RELATION_METADATA')

    def test_direct_input_drift_invalid_flags_and_duplicate_keys_rejected(self):
        self.stored[0]=[1,100,1,0]
        with self.assertRaises(CleanupError) as caught:self.call()
        self.assertEqual(caught.exception.code,'HISTORY_INPUT_DRIFT')
        self.stored[0]=[1,100,1,1]
        self.stored[-2]=[1,200,2,1]
        self.assertEqual(self.call()[1][0][2],'DEFER_INVALID_RELATED_FLAGS')
        self.stored.append(self.stored[0])
        with self.assertRaises(CleanupError) as caught:self.call()
        self.assertEqual(caught.exception.code,'HISTORY_RELATION_BOUND')

    def test_bounded_traversal_and_malformed_membership(self):
        old=relations.MAX_CLOSURE
        try:
            relations.MAX_CLOSURE=3
            self.assertEqual(self.call()[1][0][2],'DEFER_RELATION_BOUND')
        finally:relations.MAX_CLOSURE=old
        self.meta.chain=lambda s:(s,s)
        with self.assertRaises(CleanupError) as caught:self.call()
        self.assertEqual(caught.exception.code,'HISTORY_RELATION_METADATA')


class ReviewedRouteTests(unittest.TestCase):
    def build(self,root,family,cls):
        spells={s:[0]*234 for s in (root,600,51266,50334,50321,1831,11113,30798,674,900)}
        talents={root:(family,1),600:(99,1)}
        for spell,row in spells.items():row[0]=spell
        spells[51266][71:74]=[36,36,0];spells[51266][116:119]=[50321,50334,0]
        spells[1831][71]=36;spells[1831][116]=11113
        spells[30798][71]=36;spells[30798][116]=674;spells[674][71]=40
        tab=[0]*23;tab[20]=1<<(cls-1)
        talent=[0]*23;talent[1]=family
        meta=SimpleNamespace(spells=spells,talents=talents,talent_rows={root:talent},
            stores={'SkillLine':{118:[118,7]},'TalentTab':{family:tab}},
            invalid_talents=set(),requires=defaultdict(set),learns=defaultdict(list),effect_learns=defaultdict(list),
            abilities=defaultdict(list),scripts=defaultdict(set),script_policy={},history_default_spells=set(),
            chain=lambda s:(s,),check_spell=lambda s:None)
        for parent,child in ((51266,50334),(51266,50321),(1831,11113),(30798,674)):
            meta.effect_learns[parent].append((child,1,False))
        ability=[0]*14;ability[1:3]=[118,674];ability[4]=109;ability[9]=2
        meta.abilities[674]=[ability]
        rows=[[1,root,1,1,cls,1,0,2,0,'REVIEW_DISABLED_NO_SELECTED_FAMILY',family,1,'[]'],
              [2,600,1,1,1,1,0,1,0,'REVIEW_DISABLED_NO_SELECTED_FAMILY',99,1,'[]']]
        state={'spells':[[r[0],r[1],r[2],r[3]] for r in rows],'talents':[]}
        return meta,rows,state,list(state['spells'])

    def test_reviewed_teachers_are_explicit_and_all_related_rows_disabled(self):
        for root,family,cls,teacher in ((50334,1927,11,51266),(11113,32,8,1831)):
            with self.subTest(root=root):
                meta,rows,state,stored=self.build(root,family,cls)
                self.assertEqual(relations.select(rows,state,meta,stored,2)[1][0][2],'DEFER_INDEPENDENT_LEARN_ROUTE')
                stored.append([1,teacher,0,1])
                result=relations.select(rows,state,meta,stored,2,True)
                self.assertIn((1,teacher,0,1),result[0])
                self.assertIn((root,teacher),result[3]['reviewed_teacher_pairs'])
                stored[-1]=[1,teacher,1,0]
                self.assertEqual(relations.select(rows,state,meta,stored,2,True)[1][0][2],'DEFER_ENABLED_RELATED_SPELL')

    def test_unknown_teacher_route_and_altered_contract_do_not_qualify(self):
        meta,rows,state,stored=self.build(50334,1927,11)
        meta.effect_learns[900]=[(51266,1,False)]
        self.assertEqual(relations.select(rows,state,meta,stored,2,True)[1][0][2],'DEFER_INDEPENDENT_LEARN_ROUTE')
        meta.effect_learns.pop(900);meta.spells[51266][71]=6
        self.assertEqual(relations.select(rows,state,meta,stored,2,True)[1][0][2],'DEFER_REVIEWED_TEACHER_CONTRACT')
        meta.spells[51266][71]=36;meta.stores['TalentTab'][1927][20]=128
        self.assertEqual(relations.select(rows,state,meta,stored,2,True)[1][0][2],'DEFER_REVIEWED_TEACHER_CONTRACT')

    def test_missing_berserk_target_is_native_rejection_only_for_absent_teacher(self):
        meta,rows,state,stored=self.build(50334,1927,11)
        del meta.spells[50321]
        # Metadata's LEARN edge reader excludes the missing child, exactly as
        # pinned SpellMgr does. The raw target still makes the teacher invalid.
        meta.effect_learns[51266]=[(50334,1,False)]
        result=relations.select(rows,state,meta,stored,2,True)
        self.assertIn((1,50334,1,1),result[0])
        self.assertEqual(result[3]['rejected_missing_target_teachers'],[(50334,51266,50321)])
        self.assertIn((1,1927,51266,'REJECTED_NATIVE_TEACHER','ABSENT_INVALID_TEACHER','',''),result[2])
        for flags in ((1,1),(1,0)):
            stored.append([1,51266,*flags])
            self.assertEqual(relations.select(rows,state,meta,stored,2,True)[1][0][2],'DEFER_INVALID_TEACHER_STORED')
            stored.pop()
        stored.append([1,50321,1,1])
        self.assertEqual(relations.select(rows,state,meta,stored,2,True)[1][0][2],'DEFER_INVALID_TEACHER_STORED')

    def test_shaman_root_only_preserves_every_shared_spell_state(self):
        for flags in ((1,0),(0,0),(1,1),(0,1)):
            with self.subTest(flags=flags):
                meta,rows,state,stored=self.build(30798,1690,7)
                stored.append([1,674,*flags])
                self.assertEqual(relations.select(rows,state,meta,stored,2)[1][0][2],'DEFER_SKILL_REWARD_ROUTE')
                result=relations.select(rows,state,meta,stored,2,True)
                self.assertEqual(result[0],[(1,30798,1,1),(2,600,1,1)])
                self.assertEqual(result[3]['selected_related_rows'],0)
                self.assertEqual(result[3]['preserved_shared_route_rows'],1)
                self.assertIn((1,1690,674,'RANK_OR_DEPENDENT','PRESERVED_SHARED_SKILL_ROUTE',*flags),result[2])

    def test_shaman_missing_child_is_not_granted_and_selected_root_deferred(self):
        meta,rows,state,stored=self.build(30798,1690,7)
        result=relations.select(rows,state,meta,stored,2,True)
        self.assertIn((1,1690,674,'RANK_OR_DEPENDENT','ABSENT_NO_GRANT','',''),result[2])
        state['talents']=[[1,30798,1]]
        self.assertEqual(relations.select(rows,state,meta,stored,2,True)[1][0][2],'DEFER_SELECTED_RELATED_TALENT')

    def test_shaman_exception_rejects_other_classes_ranks_or_new_routes(self):
        meta,rows,state,stored=self.build(30798,1690,7)
        rows[0][4]=1
        self.assertEqual(relations.select(rows,state,meta,stored,2,True)[1][0][2],'DEFER_REVIEWED_DUAL_WIELD_CONTRACT')
        rows[0][4]=7;meta.effect_learns[900]=[(30798,1,False)]
        self.assertEqual(relations.select(rows,state,meta,stored,2,True)[1][0][2],'DEFER_REVIEWED_DUAL_WIELD_CONTRACT')
        meta.effect_learns.pop(900);meta.chain=lambda s:(30798,900) if s in (30798,900) else (s,)
        self.assertEqual(relations.select(rows,state,meta,stored,2,True)[1][0][2],'DEFER_REVIEWED_DUAL_WIELD_CONTRACT')

    def test_cli_accepts_explicit_inspection_or_audit(self):
        from cleanup_console import parser
        for option in ('--inspection','--audit'):
            args=parser().parse_args(['plan','disabled-talent-history',option,'evidence-id',
                                     '--expect-review-rows','438','--include-reviewed-routes'])
            self.assertTrue(args.include_reviewed_routes)
            self.assertEqual(getattr(args,option[2:]),'evidence-id')


if __name__=='__main__':unittest.main()
