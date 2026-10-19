#!/usr/bin/env python3
"""Authorization and exact preservation boundaries for missing native skills."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'lib'))
from spells import Metadata
from cleanup_native_skills import select,skill_cells
from cleanup_console import parser
spec=importlib.util.spec_from_file_location('native_skill_fixtures',ROOT/'tests/native-skill-fixtures.py')
assets=importlib.util.module_from_spec(spec);spec.loader.exec_module(assets)
class World:
    def rows(self,*args):return []
    def table(self,*args,**kw):return []
class NativeSkillsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();p=Path(self.tmp.name)
        profile=json.loads((ROOT/'compatibility/tc335-acwotlk-v2/spell-metadata.json').read_text());assets.base.write_assets(p,profile)
        self.meta=Metadata('tc',p/'tc-dbc','world',profile,World())
        self.state={'characters':[[1,1,1,80,0,2,0,0],[2,1,6,70,1,2,0,0]],'character_spell':[[1,63644,1,0],[2,53428,1,0]],'character_talent':[], 'character_skills':[]}
    def tearDown(self):self.tmp.cleanup()
    def selected(self,names=('generic','runeforging')):return select(self.state,self.meta,names)
    def test_native_values_and_ownership_inputs_unchanged(self):
        before=copy.deepcopy(self.state);selected,excluded,proof=self.selected()
        self.assertEqual(selected,[(1,183,400,400),(2,776,1,1)]);self.assertFalse(excluded);self.assertEqual(self.state,before)
        self.assertEqual([p['original']for p in proof],['ABSENT','ABSENT'])
    def test_existing_rows_are_never_changed_even_if_malformed(self):
        self.state['character_skills']=[[1,183,0,400],[2,776,5,5]]
        self.assertEqual(self.selected()[0],[])
    def test_disabled_inactive_and_absent_anchor_do_not_authorize_skill(self):
        for flags in ((0,0),(1,1),(0,1)):
            self.state['character_spell'][0][2:]=flags
            self.assertNotIn(183,[r[1]for r in self.selected()[0]])
        self.state['character_spell']=[];self.assertEqual(self.selected()[0],[])
    def test_single_spec_switch_cannot_establish_second_spec(self):
        self.state['characters'][0][5]=1
        selected,excluded,_=self.selected();self.assertEqual(selected,[(2,776,1,1)])
        self.assertEqual(excluded,[(1,183,'DEFER_NO_ENABLED_NATIVE_SKILL_ANCHOR')])
        self.state['character_spell'][0][1]=2382
        self.assertIn((1,183,400,400),self.selected()[0])
    def test_pending_reset_online_and_foreign_runeforging_are_deferred(self):
        for index,value,reason in ((6,1,'DEFER_ONLINE_CHARACTER'),(7,4,'DEFER_PENDING_NATIVE_RESET'),(2,1,'DEFER_FOREIGN_CLASS_SKILL')):
            old=list(self.state['characters'][1]);self.state['characters'][1][index]=value
            self.assertIn((2,776,reason),self.selected()[1]);self.state['characters'][1]=old
    def test_levels_are_bounded_and_not_inferred_from_skills(self):
        for level in (1,80):
            self.state['characters'][0][3]=level;self.assertIn((1,183,level*5,level*5),self.selected()[0])
        for level in (0,81,255):
            self.state['characters'][0][3]=level;self.assertIn((1,183,'DEFER_NATIVE_SKILL_CHARACTER_STATE'),self.selected()[1])
    def test_changed_effects_or_requirements_cannot_authorize_skill(self):
        self.meta.spells[63644][71]=36;self.assertIn((1,183,'DEFER_NATIVE_SKILL_SPELL_CONTRACT'),self.selected()[1])
        self.meta.spells[63644][71]=162;self.meta.requires[63644].add(6603)
        self.assertIn((1,183,'DEFER_NATIVE_SKILL_SPELL_CONTRACT'),self.selected()[1])
    def test_generic_category_flags_tiers_and_native_acquisition_are_required(self):
        for change in ('category','flags','tier','acquire'):
            original=copy.deepcopy(self.meta)
            if change=='category':self.meta.stores['SkillLine'][183][1]=11
            if change=='flags':self.meta.stores['SkillRaceClassInfo'][5][4]=0
            if change=='tier':self.meta.stores['SkillRaceClassInfo'][5][6]=999
            if change=='acquire':self.meta.abilities[63644][0][9]=0
            self.assertIn((1,183,'DEFER_NATIVE_SKILL_METADATA'),self.selected()[1]);self.meta=original
    def test_arbitrary_recipe_alone_does_not_establish_runeforging(self):
        self.state['character_spell'][1][1]=53323
        self.assertEqual(self.selected(['runeforging'])[0],[])
    def test_explicit_skill_subset_and_deterministic_merging(self):
        self.state['character_spell'].append([1,63645,1,0])
        rows,_,proof=self.selected(['generic']);self.assertEqual(rows,[(1,183,400,400)])
        self.assertEqual([r['spell']for r in proof[0]['anchors']],[63644,63645])
    def test_numeric_skill_hash_matches_mysql_hex_convention(self):
        self.assertEqual(skill_cells([[1,183,400,400]])[0][:3],('character_skills',1,1))
        self.assertEqual(skill_cells([[2,776,1,1],[1,183,400,400]]),skill_cells([[1,183,400,400],[2,776,1,1]]))
    def test_command_is_separate_from_skill_clamp(self):
        args=parser().parse_args(['plan','native-skills','--migration-inspection','example','--expect-rows','2'])
        self.assertEqual(args.kind,'native-skills');self.assertEqual(args.skills,['generic','runeforging'])
        preview=parser().parse_args(['plan','native-skills','--preview'])
        self.assertTrue(preview.preview);self.assertIsNone(preview.migration_inspection)
    def test_v2_normalizes_only_nonzero_generic_and_records_originals(self):
        self.state['character_skills']=[[1,183,5,350],[2,776,5,5]]
        before=copy.deepcopy(self.state)
        rows,excluded,proof=select(self.state,self.meta,['generic'],True)
        self.assertEqual(rows,[(1,183,400,400)]);self.assertFalse(excluded)
        self.assertEqual(proof[0]['original'],[5,350]);self.assertEqual(proof[0]['action'],'NORMALIZE_GENERIC')
        self.assertEqual(self.state,before)
        self.state['character_skills'][0][2]=0
        self.assertEqual(select(self.state,self.meta,['generic'],True)[1],[(1,183,'DEFER_ZERO_VALUE_NATIVE_SKILL')])
    def teacher(self):
        self.state['character_spell'][0][1]=63680
        self.meta.learns[63680]=list(self.meta.effect_learns[63680])
    def test_v2_teacher_only_anchor_and_old_policy_regression(self):
        self.teacher()
        self.assertEqual(self.selected(['generic'])[0],[])
        rows,excluded,proof=select(self.state,self.meta,['generic'],True)
        self.assertEqual(rows,[(1,183,400,400)]);self.assertFalse(excluded)
        self.assertEqual(proof[0]['teacher_contract']['children'],[63645,63644])
        self.assertFalse(proof[0]['teacher_contract']['effects_executed'])
        self.assertNotIn(63624,[p['spell']for p in proof[0]['anchors']])
    def test_v2_teacher_does_not_authorize_single_spec_disabled_or_inactive(self):
        self.teacher();self.state['characters'][0][5]=1
        self.assertEqual(select(self.state,self.meta,['generic'],True)[0],[])
        self.state['characters'][0][5]=2
        for flags in ((0,0),(0,1),(1,1)):
            self.state['character_spell'][0][2:]=flags
            self.assertEqual(select(self.state,self.meta,['generic'],True)[0],[])
    def test_v2_teacher_mechanics_and_routes_fail_closed(self):
        self.teacher()
        for mutation in ('effect','child','route','flags','minimum','category','tier','ability'):
            original=copy.deepcopy(self.meta)
            if mutation=='effect':self.meta.spells[63680][71]=3
            elif mutation=='child':self.meta.spells[63645][80]=1
            elif mutation=='route':self.meta.learns[63680].append((6603,1,False))
            elif mutation=='flags':self.meta.stores['SkillRaceClassInfo'][5][4]=0
            elif mutation=='minimum':self.meta.stores['SkillRaceClassInfo'][5][5]=1
            elif mutation=='category':self.meta.stores['SkillLine'][183][1]=7
            elif mutation=='tier':self.meta.stores['SkillRaceClassInfo'][5][6]=1
            else:self.meta.abilities[63644][0][9]=0
            self.assertEqual(select(self.state,self.meta,['generic'],True)[1],[(1,183,'DEFER_NATIVE_SKILL_TEACHER_CONTRACT')])
            self.meta=original
    def test_v2_overlap_is_deterministic_and_already_native_is_noop(self):
        self.teacher();self.state['character_spell'] += [[1,63644,1,0],[1,63645,1,0]]
        rows,_,proof=select(self.state,self.meta,['generic'],True)
        self.assertEqual(rows,[(1,183,400,400)])
        self.assertEqual([p['spell']for p in proof[0]['anchors']],[63644,63645,63680])
        self.assertEqual(select({**self.state,'character_spell':list(reversed(self.state['character_spell']))},self.meta,['generic'],True)[2],proof)
        self.state['character_skills']=[[1,183,400,400]]
        self.assertEqual(select(self.state,self.meta,['generic'],True)[0],[])
    def test_v2_preserves_native_target_skill_slot_bound(self):
        self.state['character_skills']=[[1,1000+i,1,1] for i in range(127)]
        self.assertEqual(select(self.state,self.meta,['generic'],True)[1],[(1,183,'DEFER_NATIVE_SKILL_SLOT_LIMIT')])
        self.state['character_skills'].pop()
        self.assertEqual(select(self.state,self.meta,['generic'],True)[0],[(1,183,400,400)])
    def test_v2_parser_requires_explicit_opt_in(self):
        args=parser().parse_args(['plan','native-skills','--skills','generic','--normalize-generic','--preview'])
        self.assertTrue(args.normalize_generic)
        self.assertFalse(parser().parse_args(['plan','native-skills','--preview']).normalize_generic)
if __name__=='__main__':unittest.main()
