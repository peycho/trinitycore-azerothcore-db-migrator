#!/usr/bin/env python3
"""Semantic regressions using synthetic WDBC assets and explicit expectations."""
import copy
import importlib.util
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'lib'))
from spells import Metadata, Unsupported, read_dbc, reconstruct
spec = importlib.util.spec_from_file_location('fixtures',ROOT/'tests/spell-fixtures.py')
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)


class World:
    def __init__(self):
        self.tables = {
            'spell_ranks': [[str(chain[0]),str(spell),str(rank)] for chain in fixtures.CHAINS for rank,spell in enumerate(chain,1)],
            'spell_required': [['25899','20911']],
            'spell_learn_spell': [['900011','900012','1']],
        }
    def table(self,world,table,columns):
        return sorted(self.tables.get(table,[]),key=lambda row:int(row[0]))
    def rows(self,*args):
        return []


class SpellTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.path = Path(cls.temporary.name)
        cls.profile = json.loads((ROOT/'compatibility/tc335-acwotlk-v2/spell-metadata.json').read_text())
        fixtures.write_assets(cls.path,cls.profile)
        cls.tc = Metadata('tc',cls.path/'tc-dbc','tc',cls.profile,World())
        cls.ac = Metadata('ac',cls.path/'ac-dbc','ac',cls.profile,World())
    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()
    def convert(self,stored,talents=None,skills=None,cls=2,active=0,reverse=False,tc=None,ac=None):
        tc,ac = tc or self.tc,ac or self.ac
        return reconstruct((1,cls,active,2),stored,talents or {},fixtures.CLASS_SKILLS if skills is None else skills,
                           ac if reverse else tc,tc if reverse else ac,
                           'ac-to-tc' if reverse else 'tc-to-ac')
    def fails(self,reason,call):
        with self.assertRaises(Unsupported) as error:
            call()
        self.assertEqual(error.exception.reason,reason)

    def test_highest_only_regression_and_no_higher_grant(self):
        for index,chain in enumerate(fixtures.CHAINS[:7]):
            # The old mapping has one stored row; the correct known set is the
            # chain prefix, which deliberately excludes the final unlearned rank.
            stored = {chain[-2]:(1,0)}
            result = self.convert(stored,cls=2 if index<3 else 5 if index<5 else 9)
            self.assertEqual(set(result),set(chain[:-1]))
            self.assertLess(len(stored),len(result))
            self.assertTrue(all(row['mask']==3 for row in result.values()))

    def test_complete_chain_and_overlapping_derivations(self):
        chain = fixtures.CHAINS[1]
        result = self.convert({spell:(1,0) for spell in reversed(chain)})
        self.assertEqual(set(result),set(chain))
        self.assertFalse(any(row['derived'] for row in result.values()))
        self.assertEqual(result,self.convert({spell:(1,0) for spell in chain}))
        self.assertGreater(len(result[chain[0]]['proofs']),1)

    def test_talent_masks_both_groups_and_disabled_inactive_owner(self):
        for active in [0,1]:
            for mask in [1,2,3]:
                disabled = int(not mask & (1<<active))
                result = self.convert({48825:(1,disabled)}, {20473:mask},active=active)
                self.assertEqual(set(result),set(fixtures.CHAINS[7]))
                self.assertTrue(all(row['mask']==mask for row in result.values()))
                self.assertEqual(result[48825]['authorization']['owner_masks'],[(20473,mask)])
        self.fails('UNREPRESENTABLE_DISABLED_SPELL',lambda:self.convert({48782:(1,1)}))
        self.fails('UNREPRESENTABLE_INACTIVE_SPELL',lambda:self.convert({48825:(0,1)},{20473:2}))
        self.fails('TC_SPELL_OWNERSHIP_CONFLICT',lambda:self.convert({48825:(1,0)},{20473:2}))
        self.fails('UNAUTHORIZED_TALENT_SPELL',lambda:self.convert({48825:(1,0)}))

    def test_inactive_superseded_rank_is_known(self):
        result = self.convert({48942:(1,0),643:(0,0)})
        self.assertEqual(set(result),set(fixtures.CHAINS[0]))
        self.fails('UNREPRESENTABLE_INACTIVE_SPELL',lambda:self.convert({48782:(0,0)}))
        self.fails('UNREPRESENTABLE_INACTIVE_SPELL',lambda:self.convert({643:(0,0)}))

    def test_direct_talent_ranks_never_expand_or_change_ownership(self):
        ownership = {12664:1,12282:2}
        result = self.convert({},ownership,cls=1)
        self.assertEqual(set(result),set(ownership))
        self.assertEqual(result[12664]['disposition'],'TALENT')
        self.assertNotIn(12663,result)
        self.fails('CONFLICTING_TALENT_RANKS',lambda:self.convert({}, {12664:1,12282:1},cls=1))

    def test_temporary_dependency_and_persistent_additional_ranks(self):
        result = self.convert({900003:(1,0)},{900000:1},cls=5)
        self.assertEqual(result[900010]['disposition'],'RUNTIME')
        self.assertEqual(result[900001]['mask'],1)
        self.assertEqual(result[900000]['disposition'],'TALENT')
        self.assertTrue(all(result[x]['mask']==1 for x in [900001,900002,900003,900010]))
        self.assertNotIn(900012,result)
        self.fails('UNSUPPORTED_DEPENDENT_LEARN',lambda:self.convert({900011:(1,0)}))

    def test_prerequisite_authorization(self):
        result = self.convert({25899:(1,1)},{20911:2})
        self.assertEqual(result[25899]['mask'],2)
        self.fails('UNAUTHORIZED_TALENT_SPELL',lambda:self.convert({25899:(1,0)}))

    def test_profession_riding_preserve_existing_caps(self):
        skills = {171:(320,450),762:(300,300)}
        original = copy.deepcopy(skills)
        result = self.convert({51304:(1,0),34091:(1,0)},skills=skills,cls=1)
        self.assertEqual(set(result),set(fixtures.CHAINS[10]+fixtures.CHAINS[11]))
        self.assertEqual(skills,original)
        self.fails('SPELL_WOULD_CHANGE_SKILL',lambda:self.convert({51304:(1,0)},skills={171:(320,375)},cls=1))
        self.fails('SPELL_WOULD_CHANGE_SKILL',lambda:self.convert({34091:(1,0)},skills={762:(225,300)},cls=1))
        self.fails('SPELL_WOULD_CHANGE_SKILL',lambda:self.convert({51304:(1,0)},cls=1))
        ac = copy.deepcopy(self.ac)
        ac.stores['SkillTiers'][171][22] = 525
        self.fails('INCOMPATIBLE_SKILL_METADATA',lambda:self.convert({51304:(1,0)},skills=skills,cls=1,ac=ac))
        ac = copy.deepcopy(self.ac)
        ac.stores['SkillRaceClassInfo'][171][3] = 1 << 8
        self.fails('AC_WOULD_DELETE_SPELL',lambda:self.convert({51304:(1,0)},skills=skills,cls=1,ac=ac))

    def test_malformed_cycle_and_source_target_disagreement(self):
        world = World()
        world.tables['spell_ranks'][1][2] = '3'
        self.fails('MALFORMED_SPELL_CHAIN',lambda:Metadata('tc',self.path/'tc-dbc','tc',self.profile,world))
        tc = copy.deepcopy(self.tc)
        tc.learns[900012].append((900011,1,False))
        self.fails('CYCLIC_SPELL_RELATIONSHIP',lambda:self.convert({900011:(1,0)},tc=tc))
        ac = copy.deepcopy(self.ac)
        ac.position[48942] = (48942,0)
        self.fails('INCOMPATIBLE_SPELL_CHAIN',lambda:self.convert({48942:(1,0)},ac=ac))
        self.fails('UNKNOWN_SPELL_ID',lambda:self.convert({999999:(1,0)}))

    def test_reverse_preserves_authorized_specializations(self):
        result = self.convert({48825:(2,0)},{20473:2},active=0,reverse=True)
        self.assertEqual(result[48825]['disabled'],1)
        self.assertEqual(result[20473]['disposition'],'TALENT')
        self.assertNotIn(48782,result)
        active = self.convert({48825:(2,0)},{20473:2},active=1,reverse=True)
        self.assertEqual(active[48825]['disabled'],0)
        self.assertEqual(active[20473]['disposition'],'PERSISTENT')
        self.fails('UNREPRESENTABLE_AC_SPELL_MASK',lambda:self.convert({48782:(1,0)},reverse=True))
        stored_tc = {spell:(row['active'],row['disabled']) for spell,row in result.items()
                     if row['disposition']=='PERSISTENT'}
        roundtrip = self.convert(stored_tc,{20473:2},active=0)
        self.assertEqual(set(roundtrip),set(fixtures.CHAINS[7]))
        self.assertTrue(all(row['mask']==2 for row in roundtrip.values()))

    def test_dbc_header_and_overlay_rules(self):
        path = self.path/'broken.dbc'
        path.write_bytes(struct.pack('<4s4I',b'WDBC',1,1,4,1)+struct.pack('<I',1))
        self.fails('INVALID_DBC',lambda:read_dbc(path,'n'))
        self.fails('MISSING_DBC',lambda:Metadata('tc',self.path/'missing','tc',self.profile,World()))
        class Collision(World):
            def rows(self,*args):
                fmt = self_profile['tc_spell_sql_format']
                row = ['0'] * fmt.count('p')
                row[0] = '6603'
                return [row]
        self_profile = self.profile
        self.fails('TC_DBC_OVERLAY_COLLISION',lambda:Metadata('tc',self.path/'tc-dbc','tc',self.profile,Collision()))


if __name__ == '__main__':
    unittest.main()
