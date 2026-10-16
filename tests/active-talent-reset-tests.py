#!/usr/bin/env python3
"""Offline boundaries for the explicitly selected native-reset preparation batch."""
import copy
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'lib'))
import cleanup_active_reset as reset
from cleanup_console import CleanupError
spec=importlib.util.spec_from_file_location('fixtures',ROOT/'tests/spell-fixtures.py')
fixtures=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixtures)
import json

class ActiveResetTests(unittest.TestCase):
    def setUp(self):
        self.stores=fixtures.stores(json.loads((ROOT/'compatibility/tc335-acwotlk-v2/spell-metadata.json').read_text()))
        tab=[0]*24;tab[0]=125;tab[20]=1;self.stores['TalentTab'][125]=tab
        talent=[0]*23;talent[0:2]=[125,125];talent[4]=12284;self.stores['Talent'][125]=talent
        spell=[0]*234;spell[0]=12284;spell[4]=464;spell[71]=6;spell[95]=280;self.stores['Spell'][12284]=spell
        self.character=[[1,1,'Warlock',80,9,0,2,0]]
        self.talents=[[1,17877,0]]
        self.spells=[[1,12284,1,0],[1,17877,1,0],[1,6603,1,0]]
    def call(self,requested='12284',expected=1):
        return reset.selection(self.character,self.talents,self.spells,self.stores,requested,expected)
    def fails(self,code,callback):
        with self.assertRaises(CleanupError) as caught:callback()
        self.assertEqual(caught.exception.code,code)
    def test_foreign_key_selected_active_ownership_and_unrelated_rows_retained(self):
        before=copy.deepcopy((self.character,self.talents,self.spells,self.stores))
        self.assertEqual(self.call(),([(1,12284,1,0)],1))
        self.assertEqual((self.character,self.talents,self.spells,self.stores),before)
        self.character[0][5]=1;self.talents[0][2]=1
        self.assertEqual(self.call()[0],[(1,12284,1,0)])
    def test_populated_inactive_builds_are_blocked(self):
        self.talents.append([1,17877,1])
        self.fails('INACTIVE_BUILD_NOT_EMPTY',lambda:self.call(expected=2))
    def test_online_invalid_specs_and_expected_count_are_blocked(self):
        for index,value in [(7,1),(6,0),(5,2),(4,10)]:
            before=self.character[0][index];self.character[0][index]=value
            self.fails('ACTIVE_RESET_STATE_UNSUPPORTED',self.call)
            self.character[0][index]=before
        self.fails('RESET_TALENT_COUNT_CHANGED',lambda:self.call(expected=81))
    def test_own_talent_arbitrary_spell_and_unreviewed_foreign_rank_blocked(self):
        for spell in ('17877','6603'):
            self.fails('FOREIGN_TALENT_REQUIRED',lambda:self.call(spell))
        self.fails('FOREIGN_TALENT_UNREVIEWED',lambda:self.call('12296'))
        self.stores['Spell'][12284][72]=36
        self.fails('FOREIGN_TALENT_UNREVIEWED',self.call)
    def test_changed_warrior_catalog_or_effect_shape_is_blocked(self):
        self.stores['TalentTab'][125][20]=0
        self.fails('FOREIGN_TALENT_UNREVIEWED',self.call)
        self.stores['TalentTab'][125][20]=1
        self.stores['Spell'][12284][95]=108
        self.fails('FOREIGN_TALENT_UNREVIEWED',self.call)

    def test_flags_duplicate_selection_and_missing_row_blocked(self):
        self.fails('INVALID_SPELL_SELECTION',lambda:self.call('12284,12284'))
        self.fails('INVALID_SPELL_SELECTION',lambda:self.call('12284;DELETE'))
        for flags in ((0,0),(1,1),(0,1)):
            self.spells[0][2:]=flags
            self.fails('FOREIGN_TALENT_STATE_CHANGED',self.call)
        self.spells.pop(0)
        self.fails('FOREIGN_TALENT_STATE_CHANGED',self.call)
    def test_no_enabled_selected_talent_and_other_foreign_talents_are_blocked(self):
        self.spells[1][3]=1
        self.fails('RESET_ENABLED_TALENT_REQUIRED',self.call)
        self.spells[1][3]=0
        self.spells.append([1,12296,1,0])
        self.fails('OTHER_FOREIGN_TALENTS_ENABLED',self.call)

    def test_unknown_wrong_class_and_conflicting_talent_ownership_blocked(self):
        self.talents[0][1]=130
        self.fails('RESET_RANK_UNSUPPORTED',self.call)
        self.talents[0][1]=12284
        self.fails('RESET_RANK_UNSUPPORTED',self.call)

if __name__=='__main__':unittest.main()
