#!/usr/bin/env python3
"""Bounded registered aliases must never authorize arbitrary scripts or skills."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'lib'))
from cleanup_console import CleanupError,parser
from cleanup_ownership import select,registered_aura_aliases,script_contracts,AURA_ALIASES
from spells import Metadata
spec = importlib.util.spec_from_file_location('aura_alias_fixture',ROOT/'tests/aura-alias-fixtures.py')
assets = importlib.util.module_from_spec(spec)
spec.loader.exec_module(assets)
TC = Path(os.environ.get('TRINITYCORE_DIR',ROOT.parent/'TrinityCore'))


class World:
    def rows(self,*args): return []
    def table(self,world,table,columns):
        if table == 'spell_script_names':
            return [[-ranks[0],name] for _,ranks,name in assets.FAMILIES]
        return []


class AuraAliasTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        profile = json.loads((ROOT/'compatibility/tc335-acwotlk-v2/spell-metadata.json').read_text())
        assets.base.write_assets(Path(cls.temp.name),profile)
        cls.base = Metadata('tc',Path(cls.temp.name)/'tc-dbc','tc',profile,World())

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def setUp(self):
        self.meta = copy.deepcopy(self.base)
        self.meta.history_default_spells = set()
        self.state = {'characters':[[1,1,2,80,0,2,0,32]],'character_talent':[],
                      'character_spell':[[1,ranks[-1],1,0] for _,ranks,_ in assets.FAMILIES]+[[1,6603,1,0]],
                      'character_skills':[[1,171,375,450]]}

    def review(self,**kwargs):
        return select(self.state,self.meta,preview=True,source_dir=TC,reviewed_aura_aliases=True,**kwargs)

    def test_old_policy_blocks_named_aliases_new_mode_retires_only_unselected_families(self):
        self.assertEqual(select(self.state,self.meta,preview=True,source_dir=TC)[0],[])
        before = copy.deepcopy(self.state)
        result = self.review()
        self.assertEqual(result[0],sorted(tuple(r) for r in before['character_spell'] if r[1]!=6603))
        self.assertEqual(result[3]['enabled_rows_removed'],4)
        self.assertEqual(result[3]['spell_rows_inserted'],0)
        self.assertEqual(self.state,before)
        self.assertEqual(self.review(),result)
        self.assertEqual({p['script_alias'] for p in result[3]['native_owner_proofs']},set(AURA_ALIASES))

    def test_both_specs_ownership_any_rank_and_pending_reset_preserved(self):
        for active in (0,1):
            for group in (0,1):
                self.state['characters'][0][4] = active
                self.state['character_talent'] = [[1,ranks[0],group] for _,ranks,_ in assets.FAMILIES]
                self.assertEqual(self.review()[0],[])
        self.state['character_talent'] = []
        self.state['characters'][0][7] = 4
        self.assertEqual(self.review()[0],[])
        self.state['characters'][0][7] = 0
        self.state['characters'][0][6] = 1
        self.assertEqual(self.review()[0],[])

    def test_stored_helpers_changed_aura_mechanics_and_skill_routes_defer_family(self):
        for helper in (63510,63514,63531):
            original = copy.deepcopy(self.meta)
            self.meta.spells[helper][71] = 36
            denied = self.review()[0]
            self.assertLess(len(denied),4)
            self.meta = original
            self.state['character_spell'].append([1,helper,1,0])
            self.assertLess(len(self.review()[0]),4)
            self.state['character_spell'].pop()
        for change in ('requirement','learn','script','skill','target','trigger'):
            original = copy.deepcopy(self.meta)
            if change=='requirement': self.meta.requires[63514].add(6603)
            elif change=='learn': self.meta.learns[63514].append((6603,1,False))
            elif change=='script': self.meta.scripts[63514].add('unknown')
            elif change=='skill': self.meta.spells[63514][95] = 30
            elif change=='target': self.meta.spells[63514][86] = 5
            else: self.meta.spells[63514][116] = 123
            self.assertNotIn(20140,[r[1] for r in self.review()[0]],change)
            self.meta = original

    def test_independent_defaults_foreign_shared_and_skill_guards_remain(self):
        self.state['characters'][0][2] = 1
        self.assertEqual(self.review()[0],[])
        self.state['characters'][0][2] = 2
        self.meta.history_default_spells.update(ranks[0] for _,ranks,_ in assets.FAMILIES)
        self.assertEqual(self.review()[0],[])
        self.meta.history_default_spells.clear()
        self.meta.learns[6603].append((20138,1,False))
        self.assertNotIn(20140,[r[1] for r in self.review()[0]])

    def test_registration_is_literal_unique_bounded_and_not_arbitrary_alias_discovery(self):
        source = (TC/'src/server/scripts/Spells/spell_paladin.cpp').read_text()
        self.assertEqual(registered_aura_aliases(source),set(AURA_ALIASES))
        original = 'RegisterSpellScriptWithArgs(spell_pal_improved_aura, "spell_pal_improved_devotion_aura", SPELL_PALADIN_IMPROVED_DEVOTION_AURA);'
        for replacement in (original+original,original.replace('spell_pal_improved_aura,','spell_unknown,'),
                            original.replace('SPELL_PALADIN_IMPROVED_DEVOTION_AURA);','63514);')):
            self.assertNotIn('spell_pal_improved_devotion_aura',registered_aura_aliases(source.replace(original,replacement)))
        unsafe = source.replace('Unit* target = GetTarget();','SetSkill(1,0,1,1); Unit* target = GetTarget();')
        self.assertEqual(registered_aura_aliases(unsafe),set())
        self.assertFalse(set(AURA_ALIASES) & script_contracts(TC))
        self.assertTrue(set(AURA_ALIASES) <= script_contracts(TC,reviewed_aura_aliases=True))

    def test_counts_and_policy_cli_are_explicit(self):
        with self.assertRaises(CleanupError):
            select(self.state,self.meta,3,source_dir=TC,reviewed_aura_aliases=True)
        with self.assertRaises(CleanupError): self.review(native_passive_prefixes=True)
        args = parser().parse_args(['plan','talent-ownership','--migration-inspection','latest',
                                   '--reviewed-aura-aliases','--preview'])
        self.assertTrue(args.reviewed_aura_aliases)


if __name__ == '__main__': unittest.main()
