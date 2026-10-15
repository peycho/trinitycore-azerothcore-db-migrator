#!/usr/bin/env python3
"""Semantic regressions using synthetic WDBC assets and explicit expectations."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'lib'))
from spells import Database, Metadata, Unsupported, read_dbc, reconstruct
spec = importlib.util.spec_from_file_location('fixtures',ROOT/'tests/spell-fixtures.py')
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)
spec = importlib.util.spec_from_file_location('spell_profile',ROOT/'bin/generate-spell-metadata-profile.py')
spell_profile = importlib.util.module_from_spec(spec)
spec.loader.exec_module(spell_profile)


class World:
    def __init__(self):
        self.tables = {
            'spell_ranks': [[str(chain[0]),str(spell),str(rank)] for chain in fixtures.CHAINS for rank,spell in enumerate(chain,1)],
            'spell_required': [['25899','20911'], ['5209','5487']],
            'spell_learn_spell': [['900011','900012','1']],
        }
    def table(self,world,table,columns):
        return sorted(self.tables.get(table,[]),key=lambda row:int(row[0]))
    def rows(self,*args):
        return []


class MetadataReaderTests(unittest.TestCase):
    def test_registered_aliases_inherit_mutation_policy(self):
        policies = spell_profile.script_policies('''
class spell_safe : public SpellScript { void Hit() { SetHitDamage(1); } };
class spell_mutating : public AuraScript { void Apply() { player->LearnSpell(123); } };
RegisterSpellScriptWithArgs(spell_safe, "spell_safe_alias", 1);
RegisterSpellScriptWithArgs(spell_mutating, "spell_unsafe_alias", 1);
RegisterSpellScriptWithArgs(spell_unknown, "spell_unknown_alias", 1);
RegisterSpellAndAuraScriptPairWithArgs(spell_safe, spell_mutating, "spell_unsafe_pair", 1);
''')
        self.assertEqual(policies['spell_safe_alias'], 'NO_SPELLBOOK_MUTATION')
        self.assertEqual(policies['spell_unsafe_alias'], 'UNSUPPORTED_SPELLBOOK_MUTATION')
        self.assertEqual(policies['spell_unsafe_pair'], 'UNSUPPORTED_SPELLBOOK_MUTATION')
        self.assertNotIn('spell_unknown_alias', policies)

    def test_blocker_summary_is_sorted_and_omits_character_identifiers(self):
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory)/'blockers.tsv'
            report.write_text('guid\tspell\treason_code\tdetail\n'
                '47\t*\tINVALID_TALENT_OWNERSHIP\t130\n'
                '229\t*\tUNAUTHORIZED_TALENT_SPELL\t5209\n'
                '57\t*\tINVALID_TALENT_OWNERSHIP\t442\n')
            result = subprocess.run(['bash', '-c', 'source "$1/lib/spells.sh"; summarize_spell_blockers "$2"',
                'fixture', str(ROOT), str(report)], text=True, capture_output=True, check=True)
            self.assertIn('INVALID_TALENT_OWNERSHIP\t2\nUNAUTHORIZED_TALENT_SPELL\t1\n', result.stderr)
            self.assertNotIn('130', result.stderr)
            self.assertNotIn('229', result.stderr)

    def test_canonical_world_rows_ignore_fetch_order_but_detect_full_content_drift(self):
        class Reader(Database):
            def __init__(self):
                super().__init__([])
                self.data = [['2', 'beta\u0431'], ['1', 'alpha'], ['1', 'alpha']]
            def rows(self, label, query):
                if label.endswith('.present'):
                    return iter([['1']])
                if label.endswith('.layout'):
                    return iter([['ID'], ['Description']])
                self.assert_query = query
                return iter(self.data)
        reader = Reader()
        expected = reader.table('world', 'spell_dbc', ['ID', 'Description'])
        original = reader.fingerprints['world.spell_dbc']
        self.assertNotIn('ORDER BY', reader.assert_query)
        reader.data.reverse()
        self.assertEqual(reader.table('world', 'spell_dbc', ['ID', 'Description']), expected)
        self.assertEqual(reader.fingerprints['world.spell_dbc'], original)
        reader.data[0][1] += 'changed'
        reader.table('world', 'spell_dbc', ['ID', 'Description'])
        self.assertNotEqual(reader.fingerprints['world.spell_dbc'], original)

    def test_query_failure_is_reported_as_read_error_without_character_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client = root / 'mysql'
            client.write_text("#!/bin/sh\nprintf '%s\\n' 'ERROR 1038 (HY001): Out of sort memory' >&2\nexit 1\n")
            client.chmod(0o755)
            env = os.environ | {'PATH': str(root) + ':' + os.environ['PATH']}
            profile = ROOT/'compatibility/tc335-acwotlk-v2/spell-metadata.json'
            result = subprocess.run([sys.executable, str(ROOT/'lib/spells.py'),
                '--profile', str(profile), '--output', str(root), '--source-characters', 'chars',
                '--control', 'control', '--run-id', 'fixture', '--direction', 'tc-to-ac', '--mysql'],
                env=env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn('Spell metadata read failed', result.stderr)
            self.assertIn('SPELL_METADATA_QUERY_FAILED', (root/'spell-metadata-errors.tsv').read_text())
            self.assertEqual(len((root/'spell-state-blockers.tsv').read_text().splitlines()), 1)
            self.assertEqual((root/'spell-expected.sql').read_text(), '')
            wrapper = subprocess.run(['bash', '-c', r'''
set -Eeuo pipefail
source "$1/lib/spells.sh"
MIGRATION_ROOT=$1
COMPATIBILITY_PROFILE_DIR=$1/compatibility/tc335-acwotlk-v2
REPORTS_DIR=$2/reports
RUN_ID=fixture
SOURCE_CHARACTERS_SCHEMA=chars
SOURCE_WORLD_SCHEMA=tc_world
TARGET_WORLD_SCHEMA=ac_world
TRINITYCORE_DBC_DIR=unused
AZEROTHCORE_DBC_DIR=unused
CONTROL_SCHEMA=control
MIGRATION_DIRECTION=tc-to-ac
MYSQL_ARGS=()
require_command() { :; }
sql_escape() { printf '%s' "$1"; }
mysql_query() { printf '%s\n' "$*" >> "$REPORTS_DIR/queries"; }
die() { printf '%s\n' "$*" >&2; exit 1; }
prepare_spell_snapshot capture
''', 'fixture', str(ROOT), str(root)], env=env, text=True, capture_output=True)
            self.assertNotEqual(wrapper.returncode, 0)
            self.assertIn('compatibility could not be established', wrapper.stderr)
            self.assertNotIn('Spell state is incompatible', wrapper.stderr)
            self.assertTrue((root/'reports/fixture/spell-metadata-errors.tsv').exists())
            queries = (root/'reports/queries').read_text()
            self.assertNotIn('migration_reject', queries)
            self.assertNotIn('spell_expected', queries)


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

    def test_ordinary_prerequisite_can_be_a_reconstructed_lower_rank(self):
        result = self.convert({5209:(1,0),9634:(1,0)}, cls=11)
        self.assertEqual(set(result), {5209,5487,9634})
        self.assertTrue(result[5487]['derived'])
        self.assertEqual(result[5487]['proofs'], [[9634,[9634,5487],'LOWER_RANK']])
        self.assertTrue(all(row['mask']==3 for row in result.values()))
        self.fails('UNAUTHORIZED_TALENT_SPELL',lambda:self.convert({5209:(1,0)},cls=11))
        self.fails('UNREPRESENTABLE_DISABLED_SPELL',lambda:self.convert({5209:(1,0),9634:(1,1)},cls=11))
        ac = copy.deepcopy(self.ac)
        ac.position[9634] = (9634,0)
        self.fails('INCOMPATIBLE_SPELL_CHAIN',lambda:self.convert({5209:(1,0),9634:(1,0)},cls=11,ac=ac))
        self.fails('UNAUTHORIZED_TALENT_SPELL',lambda:self.convert({12296:(1,0)},cls=1))
        self.fails('UNAUTHORIZED_TALENT_SPELL',lambda:reconstruct((1,1,0,1),{12296:(1,1)}, {}, {},
                   self.tc,self.ac,'tc-to-ac'))
        self.fails('INVALID_TALENT_OWNERSHIP',lambda:self.convert({12296:(1,0)},{130:1},cls=1))

    def test_reviewed_encounter_script_and_unknown_script_boundary(self):
        tc,ac = copy.deepcopy(self.tc),copy.deepcopy(self.ac)
        name = 'spell_murmur_sonic_boom_effect'
        path = 'src/server/scripts/Outland/Auchindoun/ShadowLabyrinth/boss_murmur.cpp'
        for metadata in (tc,ac):
            self.assertEqual(metadata.script_policy[name], 'NO_SPELLBOOK_MUTATION')
            self.assertIn(path, self.profile['inputs'][metadata.core])
            self.assertNotIn('spell_murmur_thundering_storm', metadata.script_policy)
            metadata.scripts[38795].add(name)
        self.assertEqual(set(self.convert({38795:(1,0)},tc=tc,ac=ac)), {38795})
        ac.scripts[38795].add('spell_unreviewed_encounter')
        self.fails('UNSUPPORTED_LEARNING_SCRIPT',lambda:self.convert({38795:(1,0)},tc=tc,ac=ac))

    def test_native_aliases_and_enum_field_copy_corrections(self):
        for metadata in [self.tc,self.ac]:
            self.assertEqual(metadata.script_policy['spell_pal_judgement_of_justice'], 'NO_SPELLBOOK_MUTATION')
        self.assertEqual(self.ac.spells[34074][71:74], [6,6,6])
        self.assertEqual(self.ac.spells[34074][97], 4)
        self.assertEqual(self.ac.spells[51470][72], 6)
        self.assertEqual(self.ac.spells[51470][96], 107)
        self.assertEqual(self.ac.spells[51470][111], 12)
        self.assertEqual(self.ac.spells[54349][72], self.ac.spells[54349][71])
        self.assertEqual(self.ac.spells[54349][96], self.ac.spells[54349][95])
        self.assertEqual(self.ac.spells[54349][87], self.ac.spells[54349][86])
        self.assertEqual(set(self.convert({34074:(1,0)},cls=3)), {34074})
        self.assertEqual(self.convert({}, {51470:1},cls=7)[51470]['disposition'], 'TALENT')
        self.assertEqual(self.convert({}, {54349:2},cls=9)[54349]['disposition'], 'TALENT')
        tc = copy.deepcopy(self.tc)
        tc.correction_guards[34074].append('visibility')
        self.fails('UNSUPPORTED_CORE_CORRECTION',lambda:self.convert({34074:(1,0)},cls=3,tc=tc))

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
