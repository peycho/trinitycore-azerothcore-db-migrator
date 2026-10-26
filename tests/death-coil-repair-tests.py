#!/usr/bin/env python3
"""Only the explicit Death Coil policy may permit native base-rank availability."""
from collections import defaultdict
from contextlib import redirect_stderr
import copy
import io
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'lib'))
from cleanup_console import CleanupError, parser
import cleanup_death_coil as dc
import cleanup_ordinary_history as ordinary


class DeathCoilTests(unittest.TestCase):
    def setUp(self):
        spells={s:[0]*234 for s in (*dc.CHAIN,100,200,6603)}
        for s in dc.CHAIN:spells[s][71]=3
        tab=[0]*23;tab[20]=32
        self.meta=SimpleNamespace(spells=spells,talents={100:(1,1)},talent_rows={100:[1,1]},
            stores={'TalentTab':{1:tab},'SkillLine':{772:[772,7],171:[171,11]},
                    'SkillRaceClassInfo':{895:[895,772,0xffffffff,32,0x410,0,0,0]}},
            learns=defaultdict(list),effect_learns=defaultdict(list),requires=defaultdict(set),
            abilities=defaultdict(list),scripts=defaultdict(set),
            script_policy={'spell_dk_death_coil':'NO_SPELLBOOK_MUTATION'},
            history_default_spells={49895},
            chain=lambda s:dc.CHAIN if s in dc.CHAIN else (s,),check_spell=lambda s:None)
        for i,s in enumerate(dc.CHAIN):
            self.meta.abilities[s]=[[1000+i,772,s,0,32,0,0,1,dc.CHAIN[i+1] if i<4 else 0,2 if i==0 else 0,0,0,0,0]]
            self.meta.scripts[s]={'spell_dk_death_coil'}
        self.state={'characters':[[1,1,6,80,0,2,0,0],[2,2,6,62,1,2,0,0],
                                  [3,1,6,80,0,1,0,0],[4,1,6,80,0,1,0,4],[5,1,1,80,0,1,0,0]],
            'character_spell':[[1,49895,1,1],[1,6603,1,0],[2,49892,1,1],[2,49893,1,1],
                               [3,200,1,1],[4,49894,1,1],[5,49893,1,1]],
            'character_talent':[[1,100,0],[1,100,1]],
            'character_skills':[[1,772,1,1],[1,171,350,450],[2,772,310,310],[4,772,400,400],[5,772,400,400]]}

    def review(self):return ordinary.select(self.state,self.meta,None,preview=True,native_death_coil=True)

    def test_explicit_policy_no_insertion_no_higher_grant_and_old_controls(self):
        original=copy.deepcopy(self.state)
        selected,excluded,proof,summary,_=ordinary.select(self.state,self.meta,6,native_death_coil=True)
        self.assertEqual(selected,[(1,49895,1,1),(2,49892,1,1),(2,49893,1,1)])
        self.assertEqual({r[2] for r in excluded},{'DEFER_OUTSIDE_NATIVE_DEATH_COIL','DEFER_PENDING_NATIVE_RESET','DEFER_NATIVE_DEATH_COIL_CLASS'})
        self.assertEqual(summary['native_base_characters'],2)
        self.assertEqual(summary['existing_native_skill_normalizations'],1)
        self.assertEqual(summary['spell_rows_inserted'],0);self.assertEqual(summary['skill_rows_changed'],0)
        self.assertIn((1,47541,47541,dc.ROLE,'NATIVE_BASE_FROM_EXISTING_SKILL','',''),proof)
        self.assertIn((2,47541,49895,dc.ROLE,'ABSENT_NO_GRANT','',''),proof)
        self.assertEqual(self.state,original);self.assertEqual(self.review(),self.review())
        for flag in (False,True):
            old=ordinary.select(self.state,self.meta,6,inactive_custom_defaults=flag)
            self.assertFalse(any(r[1] in dc.CHAIN for r in old[0]))

    def test_pending_native_base_keeps_reset_and_all_selected_state(self):
        original=copy.deepcopy(self.state)
        rows,_,_,summary,_=ordinary.select(self.state,self.meta,None,preview=True,native_death_coil=True,pending_death_coil=True)
        self.assertEqual(rows,[(4,49894,1,1)]);self.assertEqual(self.state,original)
        self.assertTrue(summary['pending_native_reset_preserved']);self.assertFalse(summary['reset_executed'])
        self.assertEqual(summary['spell_rows_inserted'],0);self.assertEqual(summary['skill_rows_changed'],0)
        self.state['character_spell'].append([4,49895,1,0])
        self.assertFalse(ordinary.select(self.state,self.meta,None,preview=True,native_death_coil=True,pending_death_coil=True)[0])
        with self.assertRaises(CleanupError):ordinary.select(original,self.meta,None,preview=True,pending_death_coil=True)
        args=parser().parse_args(['plan','disabled-spell-history','--migration-inspection','latest','--pending-native-death-coil','--preview'])
        self.assertTrue(args.pending_native_death_coil)

    def test_cli_and_configuration_are_explicit_and_independent(self):
        args=parser().parse_args(['plan','disabled-spell-history','--migration-inspection','latest','--native-death-coil','--preview'])
        self.assertTrue(args.native_death_coil);self.assertFalse(args.inactive_custom_defaults)
        with redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):
            parser().parse_args(['plan','disabled-spell-history','--migration-inspection','latest','--native-death-coil','--inactive-custom-defaults','--preview'])
        for value in ('','1','unknown'):
            with self.assertRaises(CleanupError) as raised:dc.configuration_contract(SimpleNamespace(get=lambda *args:value))
            self.assertEqual(raised.exception.code,'DEATH_COIL_CONFIG_REQUIRED')
        self.assertEqual(dc.configuration_contract(SimpleNamespace(get=lambda *args:'0'))['value'],0)

    def test_metadata_exact_reward_route_and_no_skill_or_profession_exception(self):
        original=copy.deepcopy(self.meta.abilities)
        for index,value in ((1,171),(3,1),(4,0),(7,2),(8,0),(9,1),(10,2)):
            self.meta.abilities=copy.deepcopy(original);self.meta.abilities[47541][0][index]=value
            self.assertFalse(self.review()[0])
        self.meta.abilities=copy.deepcopy(original);self.meta.abilities[49893][0][9]=2
        self.assertFalse(self.review()[0])
        self.meta.abilities=copy.deepcopy(original);self.meta.abilities[47541]*=2
        self.assertFalse(self.review()[0])
        self.meta.abilities=original;self.meta.stores['SkillLine'][772][1]=11
        self.assertFalse(self.review()[0])

    def test_existing_skill_required_and_stored_values_are_preserved(self):
        old=copy.deepcopy(self.state['character_skills'])
        for value,cap in ((0,400),(401,400),(1,401)):
            self.state['character_skills'][0]=[1,772,value,cap]
            self.assertFalse(any(r[0]==1 for r in self.review()[0]))
        self.state['character_skills']=[r for r in old if r[:2]!=[1,772]]
        self.assertFalse(any(r[0]==1 for r in self.review()[0]))
        self.state['character_skills']=old+[[1,772,400,400]]
        self.assertFalse(any(r[0]==1 for r in self.review()[0]))
        self.state['character_skills']=old
        self.assertEqual(self.review()[3]['native_base_proofs'][0]['stored_skill_cap'],1)
        self.assertEqual(self.state['character_skills'],old)

    def test_skill_race_class_tier_and_flags_are_verified(self):
        row=self.meta.stores['SkillRaceClassInfo'][895]
        original=list(row)
        for index,value in ((2,0),(3,0),(4,16),(5,55),(6,1)):
            row[:]=original;row[index]=value
            self.assertFalse(self.review()[0])
        row[:]=original;self.meta.stores['SkillRaceClassInfo'][896]=list(row)
        self.assertFalse(self.review()[0])

    def test_native_base_absence_and_all_present_higher_ranks_disabled(self):
        self.state['character_spell'][0]=[1,49895,0,1]
        self.assertIn((1,49895,'DEFER_NATIVE_DEATH_COIL_FLAGS'),self.review()[1])
        self.state['character_spell'][0]=[1,49895,1,1]
        for flags,reason in (((1,0),'DEFER_ENABLED_RELATED_SPELL'),((0,0),'DEFER_ENABLED_RELATED_SPELL'),
                             ((1,1),'DEFER_STORED_NATIVE_BASE')):
            self.state['character_spell'].append([1,47541,*flags])
            selected,excluded,*_=self.review()
            self.assertFalse(any(r[0]==1 for r in selected));self.assertIn((1,49895,reason),excluded)
            self.state['character_spell'].pop()
        self.state['character_spell'].append([1,49892,0,0])
        self.assertFalse(any(r[0]==1 for r in self.review()[0]))

    def test_routes_scripts_visibility_and_talent_ancestry_still_block(self):
        for parent,child in ((200,47541),(47541,200),(49895,47541)):
            self.meta.learns[parent]=[(child,1,False)]
            self.assertFalse(self.review()[0]);self.meta.learns.clear()
        self.meta.requires[47541].add(200);self.assertFalse(self.review()[0]);self.meta.requires.clear()
        self.meta.scripts[49892]={'other'};self.assertFalse(self.review()[0]);self.meta.scripts[49892]={'spell_dk_death_coil'}
        self.meta.spells[47541][4]=64;self.assertFalse(self.review()[0]);self.meta.spells[47541][4]=0
        self.meta.spells[49892][71]=36;self.assertFalse(self.review()[0]);self.meta.spells[49892][71]=3
        self.meta.effect_learns[100]=[(47541,1,True)];self.meta.spells[100][71]=36;self.meta.spells[100][116]=47541
        self.assertFalse(any(r[1] in dc.CHAIN for r in self.review()[0]))

    def test_invalid_ownership_online_and_metadata_chain_changes(self):
        self.state['character_talent'].append([1,100,0])
        self.assertFalse(any(r[0]==1 for r in self.review()[0]));self.state['character_talent'].pop()
        self.state['characters'][0][6]=1
        self.assertFalse(any(r[0]==1 for r in self.review()[0]));self.state['characters'][0][6]=0
        self.meta.chain=lambda s:dc.CHAIN[:-1] if s in dc.CHAIN[:-1] else (s,)
        self.assertFalse(self.review()[0])

    def test_expected_count_and_completed_preview_do_not_create_grants(self):
        with self.assertRaises(CleanupError) as e:ordinary.select(self.state,self.meta,3,native_death_coil=True)
        self.assertEqual(e.exception.code,'ORDINARY_HISTORY_SELECTION_MISMATCH')
        self.state['character_spell']=[[1,6603,1,0]]
        selected,_,_,summary,_=self.review()
        self.assertFalse(selected);self.assertEqual(summary['reviewed_candidate_rows'],0)
        self.assertEqual(summary['native_base_characters'],0)


if __name__=='__main__':unittest.main()
