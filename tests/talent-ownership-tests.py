#!/usr/bin/env python3
"""Authoritative selected builds must never become guessed talent or skill grants."""
import copy
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'lib'))
from cleanup_console import CleanupError, parser
from cleanup_ownership import select, safe_script_classes, foreign_class_mask
from spells import Unsupported, reconstruct

spec = importlib.util.spec_from_file_location('semantic_fixture', ROOT/'tests/spell-state-tests.py')
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


class OwnershipTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.SpellTests.setUpClass()
        cls.base = fixture.SpellTests.tc

    @classmethod
    def tearDownClass(cls):
        fixture.SpellTests.tearDownClass()

    def setUp(self):
        self.meta = copy.deepcopy(self.base)
        self.meta.history_default_spells = set()
        self.state = {'characters': [[1,1,1,80,0,2,0,32]],
                      'character_talent': [[1,12282,0]],
                      'character_spell': [[1,12282,1,0], [1,12664,1,0], [1,6603,1,0]],
                      'character_skills': [[1,171,375,450]]}

    def review(self):
        return select(self.state, self.meta, preview=True)

    def test_old_conversion_fails_repaired_book_preserves_selected_and_unrelated(self):
        with self.assertRaises(Unsupported):
            reconstruct((1,1,0,2), {12282:(1,0),12664:(1,0),6603:(1,0)},
                        {12282:1}, {}, self.meta, fixture.SpellTests.ac, 'tc-to-ac')
        before = copy.deepcopy(self.state)
        rows, excluded, proof, summary, _ = self.review()
        self.assertEqual(rows, [(1,12664,1,0)])
        self.assertEqual(excluded, [])
        self.assertEqual(summary['enabled_rows_removed'], 1)
        self.assertEqual(summary['spell_rows_inserted'], 0)
        result = reconstruct((1,1,0,2), {12282:(1,0),6603:(1,0)},
                             {12282:1}, {}, self.meta, fixture.SpellTests.ac, 'tc-to-ac')
        self.assertEqual(set(result), {12282,6603})
        self.assertEqual(self.state, before)
        self.assertEqual(self.review(), (rows, excluded, proof, summary, self.review()[4]))

    def test_unowned_enabled_family_and_empty_book_are_allowed_only_by_new_policy(self):
        self.state['character_talent'] = []
        rows = self.review()[0]
        self.assertEqual(rows, [(1,12282,1,0),(1,12664,1,0)])
        self.assertNotIn(6603, [r[1] for r in rows])

    def test_foreign_opt_in_retires_only_exclusive_unselected_family_and_preserves_state(self):
        self.state['characters'][0][2]=5
        self.state['character_talent']=[]
        before=copy.deepcopy(self.state)
        self.assertEqual(self.review()[0],[])  # Default v1 stays unchanged.
        with self.assertRaises(Unsupported):
            reconstruct((1,5,0,2),{s:(a,d)for _,s,a,d in self.state['character_spell']},
                        {},{},self.meta,fixture.SpellTests.ac,'tc-to-ac')
        result=select(self.state,self.meta,preview=True,foreign_class_families=True)
        self.assertEqual(result[0],[(1,12282,1,0),(1,12664,1,0)])
        self.assertEqual(result[3]['foreign_family_rows'],2)
        self.assertTrue(all(p['foreign_class_mask']==1 and not p['selected_spell_groups']
                            for p in result[3]['native_owner_proofs']))
        self.assertEqual(self.state,before)
        retained={s:(a,d)for g,s,a,d in self.state['character_spell'] if (g,s)not in {(g,s)for g,s,_,_ in result[0]}}
        self.assertEqual(set(reconstruct((1,5,0,2),retained,{}, {},self.meta,fixture.SpellTests.ac,'tc-to-ac')),{6603})
        self.assertEqual(result,select(self.state,self.meta,preview=True,foreign_class_families=True))

    def test_unowned_shaman_dual_wield_keeps_its_native_skill_reward_blocker(self):
        self.state['characters'][0][1:3]=[11,7]
        self.state['character_talent']=[]
        self.state['character_spell']=[[1,674,1,0],[1,6603,1,0]]
        self.state['character_skills'].append([1,118,1,400])
        before=copy.deepcopy(self.state)
        self.assertEqual(self.meta.abilities[674][0][4],109)
        self.assertEqual(109 & (1 << (7-1)),64)
        rows,excluded,_,_,_=self.review()
        self.assertEqual(rows,[])
        self.assertIn((1,674,'DEFER_SKILL_REWARD_ROUTE'),excluded)
        self.assertEqual(self.state,before)

    def test_foreign_mode_preserves_same_class_owned_and_unowned_families_both_specs(self):
        for active in (0,1):
            self.state['characters'][0][4]=active
            self.state['character_talent']=[[1,12282,0],[1,12664,1]]
            self.assertEqual(select(self.state,self.meta,preview=True,foreign_class_families=True)[0],[])
        self.state['character_talent']=[]
        self.assertEqual(select(self.state,self.meta,preview=True,foreign_class_families=True)[0],[])

    def test_foreign_mode_never_removes_shared_dual_wield_or_skills(self):
        self.state['character_talent']=[]
        self.state['character_spell']=[[1,674,1,0],[1,6603,1,0]]
        self.state['character_skills'].append([1,118,1,1])
        before=copy.deepcopy(self.state)
        result=select(self.state,self.meta,preview=True,foreign_class_families=True)
        self.assertEqual(result[0],[])
        self.assertEqual(self.state,before)

    def test_foreign_mode_keeps_independent_skill_script_default_and_reset_guards(self):
        self.state['characters'][0][2]=5
        self.state['character_talent']=[]
        for kind in ('learn','skill','script','default','reset','online','foreign_selection'):
            with self.subTest(kind=kind):
                meta,state=copy.deepcopy(self.meta),copy.deepcopy(self.state)
                if kind=='learn':meta.learns[6603].append((12282,1,False))
                elif kind=='skill':meta.spells[12282][71]=44
                elif kind=='script':meta.scripts[12282].add('spell_unknown')
                elif kind=='default':meta.history_default_spells.add(12282)
                elif kind=='reset':state['characters'][0][7]=4
                elif kind=='online':state['characters'][0][6]=1
                else:state['character_talent']=[[1,12282,0]]
                self.assertEqual(select(state,meta,preview=True,foreign_class_families=True)[0],[])

    def test_foreign_class_contract_rejects_shared_invalid_and_truncated_tabs(self):
        root=12282;key=self.meta.talent_rows[root][1]
        self.assertEqual(foreign_class_mask(self.meta,{root},5),1)
        for mask in (0,3,1<<9,1<<4):
            self.meta.stores['TalentTab'][key][20]=mask
            self.assertEqual(foreign_class_mask(self.meta,{root},5),0)
        self.meta.stores['TalentTab'][key]=[]
        self.assertEqual(foreign_class_mask(self.meta,{root},5),0)

    def test_foreign_console_flag_is_explicit(self):
        args=parser().parse_args(['plan','talent-ownership','--migration-inspection','latest',
                                 '--foreign-class-families','--preview'])
        self.assertTrue(args.foreign_class_families)

    def test_both_specs_and_same_owner_union_preserve_authorized_rows(self):
        for active in (0,1):
            self.state['characters'][0][4] = active
            self.state['character_talent'] = [[1,12282,0],[1,12664,1]]
            self.state['character_spell'] = [[1,12282,1,int(active!=0)],
                                             [1,12664,1,int(active!=1)], [1,12663,0,1]]
            self.assertEqual(self.review()[0], [(1,12663,0,1)])
        self.state['character_talent'] = [[1,12282,0],[1,12282,1]]
        self.state['character_spell'] = [[1,12282,1,0],[1,12664,1,1]]
        self.assertEqual(self.review()[0], [(1,12664,1,1)])

    def test_native_child_higher_history_retired_without_higher_grant(self):
        self.state['characters'][0][2] = 11
        self.state['character_talent'] = [[1,37116,0]]
        self.state['character_spell'] = [[1,37116,1,0],[1,16952,1,0],[1,16958,1,0],
                                         [1,16954,1,0],[1,16961,1,1]]
        rows, _, proof, _, _ = self.review()
        self.assertEqual(rows, [(1,16954,1,0),(1,16961,1,1)])
        self.assertIn((1,801,16952,'SELECTED_TALENT_AUTHORITY','PRESERVED_AUTHORIZED',1,0), proof)
        result = reconstruct((1,11,0,2), {37116:(1,0),16952:(1,0),16958:(1,0)}, {37116:1},
                             {134:(400,400)}, self.meta, fixture.SpellTests.ac, 'tc-to-ac')
        self.assertIn(16952, result)
        self.assertNotIn(16954, result)
        self.assertEqual(result[16952]['disposition'], 'RUNTIME')
        native = self.review()[3]['native_owner_proofs'][0]
        self.assertIn([16952,1], native['native_authorization_masks'])
        self.assertIn([16952,[16952]], native['active_child_anchors'])

    def test_tc_legitimate_lower_native_child_prefix_is_never_retired(self):
        self.state['characters'][0][2] = 11
        self.state['character_talent'] = [[1,37117,0]]
        self.state['character_spell'] = [[1,37117,1,0],[1,16958,0,0],[1,16961,1,0]]
        self.assertEqual(self.review()[0], [])

    def test_active_missing_child_never_assumed_restored_by_tc_load(self):
        self.state['characters'][0][2] = 11
        self.state['character_talent'] = [[1,37116,0]]
        self.state['character_spell'] = [[1,37116,1,0],[1,16954,1,0]]
        self.assertEqual(self.review()[0], [])
        self.assertEqual(self.review()[1], [(1,16954,'DEFER_MISSING_NATIVE_CHILD_ANCHOR')])

    def prefix_review(self, **kwargs):
        return select(self.state, self.meta, preview=True, native_passive_prefixes=True, **kwargs)

    def native_prefix_book(self, active=0):
        self.state['characters'][0][2] = 11
        self.state['characters'][0][4] = active
        self.state['character_talent'] = [[1,37117,active]]
        self.state['character_spell'] = [[1,37117,1,0],[1,16952,1,1],[1,16958,0,1],
                                         [1,16954,1,0],[1,16961,1,0],[1,6603,1,0]]

    def test_prefix_opt_in_requires_existing_enabled_anchors_and_preserves_native_result(self):
        for active in (0,1):
            self.native_prefix_book(active)
            before = copy.deepcopy(self.state)
            self.assertEqual(self.review()[0], [])  # v1 has no prefix exception.
            rows, excluded, _, summary, _ = self.prefix_review()
            self.assertEqual(rows, [(1,16952,1,1),(1,16958,0,1)])
            self.assertEqual(excluded, [])
            self.assertEqual(summary['restorable_disabled_prefix_rows'], 2)
            self.assertEqual(summary['enabled_rows_removed'], 0)
            native = summary['native_owner_proofs'][0]
            self.assertEqual(native['prefix_restore_anchors'], [[16952,[16954]],[16958,[16961]]])
            self.assertEqual(self.state, before)
            retained = {s:(a,d) for g,s,a,d in self.state['character_spell'] if (g,s) not in {(g,s) for g,s,_,_ in rows}}
            result = reconstruct((1,11,active,2),retained,{37117:1<<active},{134:(400,400)},
                                 self.meta,fixture.SpellTests.ac,'tc-to-ac')
            self.assertEqual(result[16954]['mask'],1<<active)
            self.assertEqual(result[16961]['mask'],1<<active)
            self.assertEqual(self.prefix_review()[0], rows)

    def test_prefix_supports_four_native_families_and_same_or_different_both_spec_ranks(self):
        for family, cls, owners, children in fixture.fixtures.NATIVE_PASSIVE_TALENTS:
            for active in (0,1):
                for other in (owners[-1], owners[0]):
                    self.state['characters'][0][2:6] = [cls,80,active,2]
                    self.state['character_talent'] = [[1,owners[-1],active],[1,other,1-active]]
                    self.state['character_spell'] = [[1,owners[-1],1,0]]
                    if other != owners[-1]:
                        self.state['character_spell'].append([1,other,1,1])
                    prefixes = set()
                    for child in children[-1]:
                        prefixes.update(self.meta.predecessors(child))
                        self.state['character_spell'].append([1,child,1,0])
                    self.state['character_spell'].extend([1,s,1,1] for s in sorted(prefixes))
                    result = self.prefix_review()
                    self.assertEqual({r[1] for r in result[0]},prefixes,(family,active,other,result[1]))
                    self.assertTrue(all(r[3] for r in result[0]))

    def test_prefix_never_uses_missing_disabled_unowned_or_retiring_high_anchors(self):
        for mutation in ('missing','disabled','unowned','wrong_parent','no_owner','reset','online','requirement','script','skill','default'):
            self.native_prefix_book()
            meta = copy.deepcopy(self.meta)
            if mutation == 'missing': self.state['character_spell'] = [r for r in self.state['character_spell'] if r[1] not in (16954,16961)]
            elif mutation == 'disabled':
                for r in self.state['character_spell']:
                    if r[1] in (16954,16961): r[3] = 1
            elif mutation == 'unowned': self.state['character_talent'] = [[1,37116,0]]; self.state['character_spell'][0][1] = 37116
            elif mutation == 'wrong_parent': self.state['character_spell'][0][3] = 1
            elif mutation == 'no_owner': self.state['character_talent'] = []
            elif mutation == 'reset': self.state['characters'][0][7] = 4
            elif mutation == 'online': self.state['characters'][0][6] = 1
            elif mutation == 'requirement': meta.requires[16958].add(6603)
            elif mutation == 'script': meta.scripts[16958].add('unknown')
            elif mutation == 'skill': meta.spells[16958][71] = 44
            else: meta.history_default_spells.add(16958)
            self.assertEqual(select(self.state,meta,preview=True,native_passive_prefixes=True)[0],[],mutation)

    def test_prefix_is_separate_mode_and_does_not_expand_other_ownership_repairs(self):
        self.assertEqual(self.prefix_review()[0], [])
        self.native_prefix_book()
        for r in self.state['character_spell']:
            if r[1] in (16952,16958): r[3] = 0
        self.assertEqual(self.prefix_review()[0], [])
        with self.assertRaises(CleanupError):
            self.prefix_review(foreign_class_families=True)
        args=parser().parse_args(['plan','talent-ownership','--migration-inspection','latest','--native-passive-prefixes','--preview'])
        self.assertTrue(args.native_passive_prefixes)
        self.native_prefix_book()
        self.state['character_spell'].append([1,37116,1,0])
        self.assertEqual(self.prefix_review()[0], [])  # Direct rank conflicts need their own review.
        with mock.patch('sys.stderr'):
            with self.assertRaises(SystemExit):
                parser().parse_args(['plan','talent-ownership','--migration-inspection','latest',
                                     '--native-passive-prefixes','--foreign-class-families','--preview'])

    def test_pending_online_foreign_level_and_invalid_selections_defer(self):
        for field, value in ((7,4),(6,1),(3,200),(2,9),(1,32),(4,0xffffffff),(5,0xffffffff)):
            state = copy.deepcopy(self.state)
            self.state['characters'][0][field] = value
            self.assertEqual(self.review()[0], [], (field,value))
            self.state = state
        for talents in ([[1,12664,3]], [[1,12282,0],[1,12663,0]], [[1,130,0]], [[1,12282,0xffffffff]]):
            self.state['character_talent'] = talents
            self.assertEqual(self.review()[0], [])

    def test_missing_or_disabled_active_selected_parent_never_guessed(self):
        for rows in ([[1,12664,1,0]], [[1,12282,1,1],[1,12664,1,0]]):
            self.state['character_spell'] = rows
            self.assertEqual(self.review()[0], [])
            self.assertIn('DEFER_SELECTED_ACTIVE_ANCHOR', {r[2] for r in self.review()[1]})

    def test_inactive_owned_enabled_child_is_deferred_not_deleted(self):
        self.state['characters'][0][2] = 11
        self.state['character_talent'] = [[1,37116,1]]
        self.state['character_spell'] = [[1,37116,1,1],[1,16952,1,0]]
        self.assertEqual(self.review()[0], [])
        self.assertEqual(self.review()[1], [(1,16952,'DEFER_OWNED_CHILD_FLAGS')])

    def test_selected_prerequisite_ability_is_preserved_without_guessing(self):
        self.state['characters'][0][2] = 2
        self.state['character_talent'] = [[1,20911,0]]
        self.state['character_spell'] = [[1,20911,1,0],[1,25899,1,0]]
        self.assertEqual(self.review()[0], [])
        self.assertEqual(self.review()[1], [(1,25899,'DEFER_SELECTED_PREREQUISITE_CONTRACT')])

    def test_metadata_routes_skills_auras_scripts_cycles_and_changed_native_contracts(self):
        for mutation in ('default','skill_reward','skill_effect','skill_aura','script','incoming','cycle'):
            original = copy.deepcopy(self.meta)
            if mutation == 'default': self.meta.history_default_spells.add(12664)
            elif mutation == 'skill_reward':
                row=[0]*14;row[1]=183;row[9]=2;self.meta.abilities[12664]=[row]
            elif mutation == 'skill_effect': self.meta.spells[12664][71]=118
            elif mutation == 'skill_aura': self.meta.spells[12664][95]=30
            elif mutation == 'script': self.meta.scripts[12664].add('unreviewed')
            elif mutation == 'incoming': self.meta.learns[6603].append((12664,1,False))
            else: self.meta.requires[12664].add(12282)
            self.assertEqual(self.review()[0], [], mutation)
            self.meta=original

    def test_zero_results_wrong_counts_duplicate_keys_and_cli(self):
        with self.assertRaises(CleanupError): select(self.state,self.meta,2)
        self.assertEqual(select(self.state,self.meta,1)[0],[(1,12664,1,0)])
        self.state['character_spell'].append([1,12664,1,0])
        with self.assertRaises(CleanupError): self.review()
        args=parser().parse_args(['plan','talent-ownership','--migration-inspection','latest','--expect-rows','2'])
        self.assertEqual(args.expect_review_rows,2)
        self.assertTrue(args.talent_ownership)

    def test_prefix_retires_stale_enabled_higher_children_without_raising_selected_rank(self):
        self.state['characters'][0][2] = 6
        self.state['character_talent'] = [[1,61156,0]]
        disabled = (50096,50108,61274,61275)
        unauthorized = (50110,50111,61277,61278)
        self.state['character_spell'] = [[1,61156,1,0],[1,50109,1,0],[1,61276,1,0]]
        self.state['character_spell'] += [[1,s,1,1] for s in disabled]
        self.state['character_spell'] += [[1,s,1,0] for s in unauthorized]
        before = copy.deepcopy(self.state)
        rows, excluded, _, summary, _ = self.prefix_review()
        self.assertEqual({r[1] for r in rows},set(disabled+unauthorized))
        self.assertEqual(excluded,[])
        self.assertEqual(summary['enabled_rows_removed'],4)
        self.assertEqual(summary['restorable_disabled_prefix_rows'],4)
        self.assertEqual(self.state,before)
        result = reconstruct((1,6,0,2),{61156:(1,0),50109:(1,0),61276:(1,0)},
                             {61156:1},{770:(400,400)},self.meta,fixture.SpellTests.ac,'tc-to-ac')
        self.assertEqual(result[50109]['mask'],1)
        self.assertEqual(result[61276]['mask'],1)
        self.assertFalse(set(unauthorized) & set(result))

    def test_spellbook_safe_label_does_not_authorize_skill_or_ownership_writes(self):
        for call in ('SetSkill(1,0,1,1);','SetFreePrimaryProfessions(2);','ResetTalents(true);',
                     'SetFreeTalentPoints(71);','CharacterDatabase.Execute(stmt);'):
            text='class spell_unsafe : public AuraScript { void Apply(){'+call+'} };'
            self.assertEqual(safe_script_classes(text), set())
        self.assertEqual(safe_script_classes('class spell_safe : public SpellScript { void Hit(){ SetHitDamage(1); } };'), {'spell_safe'})
        self.meta.scripts[12664].add('spell_safe')
        self.meta.script_policy['spell_safe']='NO_SPELLBOOK_MUTATION'
        self.assertEqual(self.review()[0], [])

    def test_relationship_work_and_provenance_are_bounded(self):
        with mock.patch('cleanup_ownership.MAX_ROWS', 1):
            with self.assertRaises(CleanupError) as error:
                self.review()
        self.assertEqual(error.exception.code, 'OWNERSHIP_BOUND')


if __name__ == '__main__':
    unittest.main()
