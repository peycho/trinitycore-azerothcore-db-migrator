#!/usr/bin/env python3
"""Semantic regressions using synthetic WDBC assets and explicit expectations."""
import copy
from collections import Counter
from types import SimpleNamespace
from unittest import mock
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
from spells import Database, Metadata, Unsupported, read_dbc, reconstruct, script_review, main
spec = importlib.util.spec_from_file_location('fixtures',ROOT/'tests/spell-fixtures.py')
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)
spec = importlib.util.spec_from_file_location('spell_profile',ROOT/'bin/generate-spell-metadata-profile.py')
spell_profile = importlib.util.module_from_spec(spec)
spec.loader.exec_module(spell_profile)


class World:
    def __init__(self):
        self.tables = {
            'spell_ranks': [[str(chain[0]),str(spell),str(rank)] for chain in fixtures.CHAINS+fixtures.NATIVE_PASSIVE_CHAINS for rank,spell in enumerate(chain,1)]
                           + [['47179','47179','1'],['47179','47180','2']],
            'spell_required': [['25899','20911'], ['5209','5487']],
            'spell_learn_spell': [['900011','900012','1'],['53428','53341','1'],['53428','53343','1'],['33943','34090','1']],
            'spell_script_names': [['-33872','spell_dru_nurturing_instinct']],
        }
    def table(self,world,table,columns):
        rows=list(self.tables.get(table,[]))
        if table=='spell_script_names':
            rows += ([['7744','spell_wotf_shared_cd'],['37377','spell_warl_t4_2p_bonus_shadow']]
                     if world=='tc' else [['40081','spell_black_template_free_friend'],
                                      ['40326','spell_teron_gorefiend_shadowy_construct']])
        if world=='ac' and table=='spell_ranks':
            rows += [['44440','44440','1'],['44440','44441','2']]
        if table=='trainer_spell':
            return rows
        return sorted(rows,key=lambda row:int(row[0]))
    def rows(self,*args):
        return []


class MetadataReaderTests(unittest.TestCase):
    def test_indexed_family_writes_are_bounded_and_conditional_access_stays_blocked(self):
        changes,guarded=spell_profile.indexed_family_corrections(
            'spellInfo->SpellFamilyFlags[2] = 0x10; spellInfo->SpellFamilyFlags[0] |= FLAG;',{'FLAG':4})
        self.assertEqual(changes,[[211,'=',16],[209,'|=',4]])
        self.assertFalse(guarded)
        for body in ('if (condition) { spellInfo->SpellFamilyFlags[0] |= 0x40; }',
                     'while (condition) { spellInfo->SpellFamilyFlags[0] |= 0x40; }',
                     'do { spellInfo->SpellFamilyFlags[0] |= 0x40; } while (condition);',
                     'spellInfo->SpellFamilyFlags[index] = 16;',
                     'spellInfo->SpellFamilyFlags[3] = 16;',
                     'spellInfo->SpellFamilyFlags[1] = spellInfo->SpellFamilyFlags[2];'):
            self.assertTrue(spell_profile.indexed_family_corrections(body,{})[1],body)

    def test_registered_aliases_inherit_mutation_policy(self):
        policies = spell_profile.script_policies('''
class spell_safe : public SpellScript { void Hit() { SetHitDamage(1); } };
class spell_mutating : public AuraScript { void Apply() { player->LearnSpell(123); } };
RegisterSpellScriptWithArgs(spell_safe, "spell_safe_alias", 1);
RegisterSpellScriptWithArgs(spell_mutating, "spell_unsafe_alias", 1);
RegisterSpellScriptWithArgs(spell_unknown, "spell_unknown_alias", 1);
RegisterSpellAndAuraScriptPairWithArgs(spell_safe, spell_mutating, "spell_unsafe_pair", 1);
new spell_safe<123, 456>("spell_legacy_safe");
new spell_mutating<123, 456>("spell_legacy_unsafe");
new spell_unknown("spell_legacy_unknown");
new spell_safe<123>("spell_unreviewed_legacy");
''',legacy_aliases={'spell_legacy_safe':'spell_safe','spell_legacy_unsafe':'spell_mutating',
                    'spell_legacy_unknown':'spell_unknown'})
        self.assertEqual(policies['spell_safe_alias'], 'NO_SPELLBOOK_MUTATION')
        self.assertEqual(policies['spell_unsafe_alias'], 'UNSUPPORTED_SPELLBOOK_MUTATION')
        self.assertEqual(policies['spell_unsafe_pair'], 'UNSUPPORTED_SPELLBOOK_MUTATION')
        self.assertNotIn('spell_unknown_alias', policies)
        self.assertEqual(policies['spell_legacy_safe'], 'NO_SPELLBOOK_MUTATION')
        self.assertEqual(policies['spell_legacy_unsafe'], 'UNSUPPORTED_SPELLBOOK_MUTATION')
        self.assertNotIn('spell_legacy_unknown', policies)
        self.assertNotIn('spell_unreviewed_legacy', policies)

    def test_reviewed_template_aliases_require_exact_implementation_and_arguments(self):
        content = """
template <uint32 Id> class spell_safe : public SpellScript { void Hit() { CastSpell(Id); } };
template <uint32 Id> class spell_bad : public SpellScript { void Hit() { LearnSpell(Id); } };
RegisterSpellScriptWithArgs(spell_safe<CONST>, "spell_safe_alias");
RegisterAuraScriptWithArgs(spell_bad<CONST>, "spell_bad_alias");
RegisterSpellScriptWithArgs(spell_safe<OTHER>, "spell_wrong_argument");
RegisterSpellScriptWithArgs(spell_bad<CONST>, "spell_wrong_implementation");
RegisterSpellScriptWithArgs(spell_unknown<CONST>, "spell_unknown_impl");
RegisterSpellScriptWithArgs(spell_safe<CONST>, "spell_unreviewed_template");
"""
        aliases={name:('spell_safe',('CONST',)) for name in
                 ('spell_safe_alias','spell_wrong_argument','spell_wrong_implementation','spell_unknown_impl')}
        aliases['spell_bad_alias']=('spell_bad',('CONST',))
        policies=spell_profile.script_policies(content,template_aliases=aliases)
        self.assertEqual(policies['spell_safe_alias'],'NO_SPELLBOOK_MUTATION')
        for name in aliases.keys()-{'spell_safe_alias'}:
            self.assertEqual(policies[name],'UNSUPPORTED_SPELLBOOK_MUTATION')
        self.assertNotIn('spell_unreviewed_template',policies)
        duplicate=content+'RegisterSpellScriptWithArgs(spell_safe<OTHER>, "spell_safe_alias");'
        self.assertEqual(spell_profile.script_policies(duplicate,template_aliases=aliases)['spell_safe_alias'],
                         'UNSUPPORTED_SPELLBOOK_MUTATION')

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
            self.assertEqual(json.loads((root/'reports/fixture/spell-script-review.json').read_text())['status'],
                             'INCOMPLETE')
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
    def convert(self,stored,talents=None,skills=None,cls=2,active=0,reverse=False,tc=None,ac=None,race=1):
        tc,ac = tc or self.tc,ac or self.ac
        return reconstruct((race,cls,active,2),stored,talents or {},fixtures.CLASS_SKILLS if skills is None else skills,
                           ac if reverse else tc,tc if reverse else ac,
                           'ac-to-tc' if reverse else 'tc-to-ac')
    def fails(self,reason,call):
        with self.assertRaises(Unsupported) as error:
            call()
        self.assertEqual(error.exception.reason,reason)

    def test_remaining_nonlearning_script_bindings_preserve_only_known_spells(self):
        for spell in (7744,37377,40081,40326):
            skills={220:(1,1)} if spell==7744 else {}
            for reverse in (False,True):
                result=self.convert({spell:(3,) if reverse else (1,0)},skills=skills,cls=1,race=5,reverse=reverse)
                self.assertEqual(set(result),{spell})
                self.assertEqual(result[spell]['disposition'],'PERSISTENT')
                self.assertEqual(result[spell]['mask'],3)
        self.fails('SPELL_WOULD_ADD_SKILL',lambda:self.convert({7744:(1,0)},skills={},cls=1,race=5))
        self.fails('AC_WOULD_DELETE_SPELL',lambda:self.convert({7744:(1,0)},skills={220:(1,1)},cls=1,race=1))
        for metadata,spell,name in [(self.tc,7744,'spell_wotf_shared_cd'),
                                    (self.tc,37377,'spell_warl_t4_2p_bonus_shadow'),
                                    (self.ac,40081,'spell_black_template_free_friend'),
                                    (self.ac,40326,'spell_teron_gorefiend_shadowy_construct')]:
            self.assertEqual(metadata.script_policy[name],'NO_SPELLBOOK_MUTATION')
            altered=copy.deepcopy(metadata)
            altered.scripts[spell].add('spell_unreviewed_template')
            self.fails('UNSUPPORTED_LEARNING_SCRIPT',lambda:altered.check_spell(spell))
        self.assertNotIn('spell_black_template_harpooners_mark_aura',self.ac.script_policy)

    def test_script_inventory_covers_each_binding_despite_earlier_ownership_failure(self):
        tc,ac=copy.deepcopy(self.tc),copy.deepcopy(self.ac)
        ac.scripts[40081].update({'unreviewed_one','unreviewed_two'})
        tc.scripts[40081].add('unreviewed_three')
        ac.correction_guards[40081].append('visibility')
        stored=Counter({40326:2,40081:1})
        talents=Counter({33873:1})
        rows=script_review((tc,ac),stored,talents)
        guards=[row for row in rows if row['status']=='REVIEW_REQUIRED']
        self.assertEqual({row['script'] for row in guards},
                         {'unreviewed_one','unreviewed_two','unreviewed_three'})
        self.assertTrue(all(row['reason_code']=='UNSUPPORTED_LEARNING_SCRIPT' for row in guards))
        self.assertEqual(rows,script_review((ac,tc),stored,talents))
        self.assertFalse(any(row['spell']==7744 for row in rows))
        with tempfile.TemporaryDirectory() as directory:
            args=SimpleNamespace(mysql=[], profile=str(ROOT/'compatibility/tc335-acwotlk-v2/spell-metadata.json'),
                output=directory,source_characters='chars',source_world='tc',target_world='ac',
                tc_dbc='unused',ac_dbc='unused',direction='tc-to-ac',control='control',run_id='fixture')
            records=[['1','0','1','1','0','2'],['1','1','130','1','0','0'],
                     ['1','3','40081','1','0','0'],['1','3','40326','1','0','0'],
                     ['2','0','1','1','0','2'],['2','1','33873','1','0','0'],
                     ['2','1','33873','2','0','0'],['2','3','40326','1','0','0'],
                     ['3','3','7744','1','0','0']]
            with mock.patch('spells.Database',return_value=SimpleNamespace(fingerprints={})), \
                 mock.patch('spells.Metadata',side_effect=lambda core,*unused:tc if core=='tc' else ac), \
                 mock.patch('spells.character_rows',return_value=iter(records)):
                self.assertEqual(main(args),1)
            report=json.loads((Path(directory)/'spell-script-review.json').read_text())
            self.assertEqual(report['status'],'COMPLETE')
            self.assertEqual(report['bindings'],rows)
            self.assertEqual(len(report['input_sha256']),64)
            self.assertIn('INVALID_TALENT_OWNERSHIP',(Path(directory)/'spell-state-blockers.tsv').read_text())
            self.assertEqual((Path(directory)/'spell-expected.sql').read_text(),'')

    def test_shadowy_construct_regression_and_unsafe_encounter_boundary(self):
        ac=copy.deepcopy(self.ac)
        del ac.script_policy['spell_teron_gorefiend_shadowy_construct']
        self.fails('UNSUPPORTED_LEARNING_SCRIPT',lambda:self.convert({40326:(1,0)},ac=ac,skills={}))
        self.assertNotIn('spell_teron_gorefiend_shadowy_construct',self.tc.script_policy)
        self.assertNotIn('spell_teron_gorefiend_shadow_of_death_remove',self.ac.script_policy)
        self.fails('UNREPRESENTABLE_DISABLED_SPELL',lambda:self.convert({40326:(1,1)},skills={}))
        ac=copy.deepcopy(self.ac)
        ac.scripts[40326].add('spell_teron_gorefiend_shadow_of_death_remove')
        self.fails('UNSUPPORTED_LEARNING_SCRIPT',lambda:self.convert({40326:(1,0)},ac=ac,skills={}))

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

    def test_dual_wield_has_independent_class_skill_ownership(self):
        for cls in (1,3,4,6):
            skills={118:(1,1)}
            for active in (0,1):
                result=self.convert({674:(1,0)},skills=skills,cls=cls,active=active)
                self.assertEqual(set(result),{674})
                self.assertEqual(result[674]['mask'],3)
                self.assertEqual(result[674]['disposition'],'PERSISTENT')
                self.assertEqual(result[674]['authorization']['policy'],'ORDINARY_SKILL_AUTHORIZATION')
                self.assertEqual(len(result[674]['authorization']['independent_skill_routes']),2)
                reverse=self.convert({674:(3,)},skills=skills,cls=cls,active=active,reverse=True)
                self.assertEqual((reverse[674]['active'],reverse[674]['disabled']),(1,0))
            self.assertEqual(skills,{118:(1,1)})
            self.assertEqual(self.convert({},skills=skills,cls=cls),{})
            self.fails('SPELL_WOULD_CHANGE_SKILL',lambda:self.convert({674:(1,0)},skills={},cls=cls))
            self.fails('UNREPRESENTABLE_DISABLED_SPELL',lambda:self.convert({674:(1,1)},skills=skills,cls=cls))
        self.fails('UNAUTHORIZED_TALENT_SPELL',lambda:self.convert({674:(1,0)},skills={118:(1,1)},cls=7))
        self.fails('UNAUTHORIZED_TALENT_SPELL',lambda:self.convert({674:(1,0)},skills={118:(1,1)},cls=2))
        for active in (0,1):
            for mask in (1,2,3):
                result=self.convert({674:(1,int(not mask & (1<<active)))},{30798:mask},
                                    skills={118:(1,1)},cls=7,active=active)
                self.assertEqual(result[674]['mask'],mask)
                self.assertEqual(result[674]['disposition'],'RUNTIME')
                self.assertNotIn('independent_skill_routes',result[674]['authorization'])

    def test_independent_skill_routes_require_paired_native_evidence(self):
        for mutation in ('ability_class','ability_race','acquire','skill_class','skill_race',
                         'not_trainable','mismatch','talent_class','unknown_talent_class','generic_class'):
            tc,ac=copy.deepcopy(self.tc),copy.deepcopy(self.ac)
            if mutation=='ability_class':ac.abilities[674][0][4]=64
            elif mutation=='ability_race':ac.abilities[674][0][3]=2
            elif mutation=='acquire':ac.abilities[674][0][9]=0
            elif mutation=='skill_class':ac.stores['SkillRaceClassInfo'][132][3]=64
            elif mutation=='skill_race':ac.stores['SkillRaceClassInfo'][132][2]=2
            elif mutation=='not_trainable':ac.stores['SkillRaceClassInfo'][132][4]|=0x100
            elif mutation=='mismatch':ac.abilities[674][0][7]=2
            elif mutation=='unknown_talent_class':ac.stores['TalentTab'][1690][20]=0
            elif mutation=='generic_class':ac.abilities[674][0][4]=0
            else:ac.stores['TalentTab'][1690][20]|=1
            self.fails('UNAUTHORIZED_TALENT_SPELL',lambda:self.convert({674:(1,0)},skills={118:(1,1)},cls=1,tc=tc,ac=ac))
        # A generic class-skill association is not a skill-reward route.
        tc,ac=copy.deepcopy(self.tc),copy.deepcopy(self.ac)
        for metadata in (tc,ac):
            metadata.abilities[900010].append([999,118,900010,0,16,0,0,1,0,0,0,0,0,0])
        self.fails('UNAUTHORIZED_TALENT_SPELL',lambda:self.convert({900010:(1,0)},cls=5,tc=tc,ac=ac))

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

    def test_disabled_unowned_history_stays_blocked_with_ownership_evidence(self):
        stored,ownership={12282:(1,1)},{12664:1}
        with self.assertRaises(Unsupported) as error:
            self.convert(stored,ownership,cls=1)
        self.assertEqual(error.exception.reason,'UNAUTHORIZED_TALENT_SPELL')
        self.assertIn('stored_flags=(1, 1)',str(error.exception))
        self.assertIn('selected_same_talent=[(12664, 1)]',str(error.exception))
        self.assertIn('eligible_mask=0',str(error.exception))
        self.assertEqual(stored,{12282:(1,1)})
        self.assertEqual(ownership,{12664:1})
        self.fails('UNREPRESENTABLE_AC_SPELL_MASK',
                   lambda:self.convert({6603:(0,)},reverse=True))

    def test_temporary_dependency_and_persistent_additional_ranks(self):
        result = self.convert({900003:(1,0)},{900000:1},cls=5)
        self.assertEqual(result[900010]['disposition'],'RUNTIME')
        tc,ac=copy.deepcopy(self.tc),copy.deepcopy(self.ac)
        for metadata in (tc,ac):
            metadata.requires[900010].add(6603)
            metadata.requires[48825].add(6603)
        self.fails('UNAUTHORIZED_TALENT_SPELL',lambda:self.convert({900010:(1,0),6603:(1,0)},cls=5,tc=tc,ac=ac))
        self.fails('UNAUTHORIZED_TALENT_SPELL',lambda:self.convert({48825:(1,0),6603:(1,0)},tc=tc,ac=ac))
        authorized=self.convert({900010:(1,1),6603:(1,0)},{900000:2},cls=5,tc=tc,ac=ac)
        self.assertEqual(authorized[900010]['mask'],2)
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
        self.fails('MISSING_SPELL_PREREQUISITE',lambda:self.convert({5209:(1,0)},cls=11))
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
            self.assertNotIn('spell_teron_gorefiend_shadow_of_death_remove',metadata.script_policy)
            metadata.scripts[38795].add(name)
        self.assertEqual(set(self.convert({38795:(1,0)},tc=tc,ac=ac)), {38795})
        ac.scripts[38795].add('spell_unreviewed_encounter')
        self.fails('UNSUPPORTED_LEARNING_SCRIPT',lambda:self.convert({38795:(1,0)},tc=tc,ac=ac))

    def test_runeforging_quest_credit_handler_preserves_only_known_enchantments(self):
        tc=copy.deepcopy(self.tc)
        name='spell_chapter1_runeforging_credit'
        self.assertEqual(tc.script_policy[name],'NO_SPELLBOOK_MUTATION')
        self.assertNotIn(name,self.ac.script_policy)
        self.assertNotIn('spell_chapter1_emblazon_runeblade',tc.script_policy)
        for spell in fixtures.RUNEFORGING:
            tc.scripts[spell].add(name)
            result=self.convert({spell:(1,0)},skills={776:(1,1)},cls=6,tc=tc)
            self.assertEqual(set(result),{spell})
            self.assertEqual(result[spell]['mask'],3)
            reverse=self.convert({spell:(3,)},skills={776:(1,1)},cls=6,tc=tc,reverse=True)
            self.assertEqual((reverse[spell]['active'],reverse[spell]['disabled']),(1,0))
        self.fails('SPELL_WOULD_ADD_SKILL',lambda:self.convert({53341:(1,0)},skills={},cls=6,tc=tc))
        for value,cap in ((0,1),(1,450),(2,2)):
            self.fails('SPELL_WOULD_CHANGE_SKILL',lambda:self.convert({53341:(1,0)},skills={776:(value,cap)},cls=6,tc=tc))
        ac=copy.deepcopy(self.ac)
        ac.stores['SkillRaceClassInfo'][776][6]=171
        self.fails('INCOMPATIBLE_SKILL_METADATA',lambda:self.convert({53341:(1,0)},skills={776:(1,1)},cls=6,tc=tc,ac=ac))
        tc.scripts[53341].add('spell_chapter1_emblazon_runeblade')
        self.fails('UNSUPPORTED_LEARNING_SCRIPT',lambda:self.convert({53341:(1,0)},skills={776:(1,1)},cls=6,tc=tc))

    def test_runeforging_dependencies_delegate_to_verified_native_skill_rewards(self):
        for reverse in (False,True):
            result=self.convert({53428:(3,) if reverse else (1,0)},skills={776:(1,1)},cls=6,reverse=reverse)
            self.assertEqual(set(result),{53428,53341,53343})
            for spell in (53341,53343):
                self.assertEqual(result[spell]['disposition'],'SKILL')
                self.assertEqual(result[spell]['mask'],3)
                self.assertTrue(result[spell]['derived'])
                proof=result[spell]['authorization']['native_skill_rewards'][0]
                self.assertEqual((proof['parent'],proof['skill'],proof['value'],proof['max']),(53428,776,1,1))
            self.assertEqual(result[53428]['disposition'],'PERSISTENT')
        merged=self.convert({53428:(1,0),53341:(1,0)},skills={776:(1,1)},cls=6)
        self.assertFalse(merged[53341]['derived'])
        self.assertEqual(len(merged[53341]['proofs']),2)
        self.fails('SPELL_WOULD_ADD_SKILL',lambda:self.convert({53428:(1,0)},skills={},cls=6))
        self.fails('SPELL_WOULD_CHANGE_SKILL',lambda:self.convert({53428:(1,0)},skills={776:(1,450)},cls=6))
        for mutation in ('method','class','threshold','superseded','effects','inactive'):
            tc,ac=copy.deepcopy(self.tc),copy.deepcopy(self.ac)
            if mutation=='method':ac.abilities[53341][0][9]=0
            elif mutation=='class':ac.abilities[53341][0][4]=64
            elif mutation=='threshold':ac.abilities[53341][0][7]=2
            elif mutation=='superseded':ac.abilities[53341][0][8]=53343
            elif mutation=='effects':ac.spells[53341][71]=3
            else:tc.learns[53428][0]=(53341,0,False)
            self.fails('UNSUPPORTED_DEPENDENT_LEARN',lambda:self.convert({53428:(1,0)},skills={776:(1,1)},cls=6,tc=tc,ac=ac))

    def test_nurturing_instinct_uses_native_transient_helpers_without_spell_rows(self):
        for active in (0,1):
            for reverse in (False,True):
                result=self.convert({}, {33872:1,33873:2},cls=11,active=active,reverse=reverse)
                self.assertEqual(set(result),{33872,33873,47179,47180})
                for parent,child,mask in ((33872,47179,1),(33873,47180,2)):
                    self.assertEqual(result[parent]['disposition'],
                                     'PERSISTENT' if reverse and mask & (1<<active) else 'TALENT')
                    self.assertEqual(result[child]['disposition'],'AURA')
                    self.assertEqual(result[child]['mask'],mask)
                    self.assertEqual(result[child]['authorization']['owner_masks'],[(parent,mask)])
                    self.assertEqual(result[child]['proofs'],[[parent,[parent,child],'NATIVE_TALENT_AURA']])
        both=self.convert({}, {33873:3},cls=11)
        self.assertEqual(set(both),{33873,47180})
        self.assertEqual(both[47180]['mask'],3)
        tc=copy.deepcopy(self.tc)
        tc.learns[47180].append((6603,1,False))
        self.assertEqual(set(self.convert({}, {33873:3},cls=11,tc=tc)),{33873,47180})
        self.fails('UNSUPPORTED_AURA_HELPER_SPELL_ROW',lambda:self.convert({47180:(1,0)}, {33873:1},cls=11))
        self.fails('UNSUPPORTED_AURA_HELPER_SPELL_ROW',lambda:self.convert({47180:(1,1)},cls=11))
        self.fails('UNAUTHORIZED_TALENT_SPELL',lambda:self.convert({33873:(1,1)},cls=11))
        tc,ac=copy.deepcopy(self.tc),copy.deepcopy(self.ac)
        tc.scripts[33873].clear()
        self.fails('INCOMPATIBLE_TALENT_AURA_SCRIPT',lambda:self.convert({}, {33873:1},cls=11,tc=tc,ac=ac))
        ac=copy.deepcopy(self.ac)
        ac.scripts[34914].add('spell_dru_nurturing_instinct')
        self.fails('UNSUPPORTED_TALENT_AURA_SCRIPT',lambda:self.convert({}, {34914:1},cls=5,ac=ac))
        for mutation in ('aura','helper','stance','rank','unknown'):
            ac=copy.deepcopy(self.ac)
            if mutation=='aura':ac.spells[33873][95]=4
            elif mutation=='helper':ac.spells[47180][71]=36
            elif mutation=='stance':ac.spells[47180][12]=0
            elif mutation=='rank':ac.talents[33873]=(1792,1)
            else:ac.scripts[6603].add('spell_dru_nurturing_instinct')
            reason='INVALID_TALENT_OWNERSHIP' if mutation=='rank' else 'UNSUPPORTED_TALENT_AURA_SCRIPT'
            self.fails(reason,lambda:self.convert({6603:(1,0)}, {33873:1},cls=11,ac=ac))

    def test_native_aliases_and_enum_field_copy_corrections(self):
        for metadata in [self.tc,self.ac]:
            self.assertEqual(metadata.script_policy['spell_pal_judgement_of_justice'], 'NO_SPELLBOOK_MUTATION')
            self.assertEqual(metadata.script_policy['spell_pal_seal_of_corruption'], 'NO_SPELLBOOK_MUTATION')
            self.assertEqual(metadata.script_policy['spell_teron_gorefiend_shadow_of_death'], 'NO_SPELLBOOK_MUTATION')
            self.assertEqual(metadata.spells[51726][211],0x10)
            metadata.check_spell(51726)
        self.assertEqual(self.tc.script_policy['spell_murmur_sonic_boom'],'NO_SPELLBOOK_MUTATION')
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

    def test_native_runtime_child_does_not_grant_ac_only_predecessor(self):
        for active in (0,1):
            lower=self.convert({}, {64353:1<<active},cls=8,active=active)
            self.assertIn(64350,lower)
            self.assertNotIn(44441,lower)
            result=self.convert({}, {64357:3},cls=8,active=active)
            self.assertEqual(result[44441]['disposition'],'RUNTIME')
            self.assertEqual(result[44441]['mask'],3)
            self.assertNotIn(44440,result)
            stored=self.convert({44441:(1,0)},{64357:1<<active},cls=8,active=active)
            self.assertEqual(stored[44441]['disposition'],'RUNTIME')
            self.assertEqual(stored[44441]['mask'],1<<active)
            self.assertNotIn(44440,stored)
            reverse=self.convert({}, {64357:1<<active},cls=8,active=active,reverse=True)
            self.assertEqual(reverse[44441]['disposition'],'PERSISTENT')
            self.assertNotIn(44440,reverse)
            disabled=self.convert({44441:(1,1)},{64357:1<<(1-active)},cls=8,active=active)
            self.assertEqual(disabled[44441]['mask'],1<<(1-active))
            with self.assertRaises(Unsupported) as error:
                self.convert({44441:(1,1),64357:(1,1)},cls=8,active=active)
            self.assertIn('stored_flags=(1, 1); selected_learn_owners=[]',str(error.exception))
        self.fails('INCOMPATIBLE_SPELL_CHAIN',lambda:self.convert({44441:(1,0)},cls=8))

    def test_unselected_hidden_talent_child_is_not_an_ordinary_grant(self):
        for flags in ((1,0),(1,1),(0,0)):
            self.fails('UNAUTHORIZED_TALENT_SPELL',lambda:self.convert({900010:flags},cls=5))
        result=self.convert({900010:(1,1)},{900000:2},cls=5)
        self.assertEqual(result[900010]['mask'],2)
        self.assertEqual(result[900010]['disposition'],'RUNTIME')
        # 12308 is not a rank of talent 12296 (different Talent.dbc entries).
        with self.assertRaises(Unsupported) as error:
            self.convert({12296:(1,1)},{12308:1},cls=1)
        self.assertIn('selected_same_talent=[]',str(error.exception))

    def test_research_is_preserved_without_discovering_or_changing_skills(self):
        name='spell_gen_profession_research'
        for spell,skill in ((60893,171),(61177,773),(61288,773)):
            tc,ac=copy.deepcopy(self.tc),copy.deepcopy(self.ac)
            for metadata in (tc,ac):
                self.assertEqual(metadata.script_policy[name],'UNSUPPORTED_SPELLBOOK_MUTATION')
                metadata.scripts[spell].add(name)
            skills={skill:(320,450)}
            result=self.convert({spell:(1,0)},skills=skills,tc=tc,ac=ac)
            self.assertEqual(set(result),{spell})
            self.assertEqual(result[spell]['mask'],3)
            self.assertEqual(len(result[spell]['authorization']['load_script_contracts']),2)
            self.assertEqual(skills,{skill:(320,450)})
            reverse=self.convert({spell:(3,)},skills=skills,tc=tc,ac=ac,reverse=True)
            self.assertEqual(set(reverse),{spell})
            self.fails('RESEARCH_SKILL_MISSING',lambda:self.convert({spell:(1,0)},skills={},tc=tc,ac=ac))
            self.fails('RESEARCH_SKILL_MISSING',lambda:self.convert({spell:(1,0)},skills={skill:(0,450)},tc=tc,ac=ac))
            altered=copy.deepcopy(ac)
            altered.stores['SkillLine'][skill][1]=7
            self.fails('UNSUPPORTED_LEARNING_SCRIPT',lambda:self.convert({spell:(1,0)},skills=skills,tc=tc,ac=altered))
            for index in (0,1,2):
                altered=copy.deepcopy(ac)
                altered.spells[spell][71+index]=36
                self.fails('UNSUPPORTED_LEARNING_SCRIPT',lambda:self.convert({spell:(1,0)},skills=skills,tc=tc,ac=altered))
            for flags,stances in ((0x40,0),(0x80,1)):
                altered=copy.deepcopy(tc)
                altered.spells[spell][4]|=flags
                altered.spells[spell][12]=stances
                self.fails('UNSUPPORTED_LEARNING_SCRIPT',lambda:self.convert({spell:(1,0)},skills=skills,tc=altered,ac=ac))
        tc=copy.deepcopy(self.tc)
        tc.scripts[6603].add(name)
        self.fails('UNSUPPORTED_LEARNING_SCRIPT',lambda:self.convert({6603:(1,0)},tc=tc))

    def test_unreviewed_source_runtime_predecessor_obligation_stays_blocked(self):
        tc,ac=copy.deepcopy(self.tc),copy.deepcopy(self.ac)
        tc.native_passive_ranks={}
        ac.native_passive_ranks={}
        self.fails('UNSUPPORTED_TEMPORARY_RANK_CHAIN',lambda:self.convert({}, {37117:1},cls=11,tc=tc,ac=ac))

    def test_reviewed_native_passive_ranks_preserve_exact_selected_children(self):
        for family,cls,owners,children in fixtures.NATIVE_PASSIVE_TALENTS:
            for owner,learned in zip(owners,children):
                result=self.convert({}, {owner:1},cls=cls,skills={})
                self.assertEqual(set(result),{owner,*learned})
                self.assertEqual(result[owner]['disposition'],'TALENT')
                for child in learned:
                    self.assertEqual(result[child]['disposition'],'RUNTIME')
                    self.assertEqual(result[child]['mask'],1)
                    self.assertEqual(result[child]['authorization']['native_passive_rank']['tc_predecessors'],list(self.tc.predecessors(child)))
                    self.assertFalse(result[child]['authorization']['native_passive_rank']['target_predecessors_persisted'])
                reverse=self.convert({}, {owner:1},cls=cls,skills={},reverse=True)
                expected={owner,*learned}
                for child in learned:expected.update(self.tc.predecessors(child))
                self.assertEqual(set(reverse),expected)
                self.assertEqual({s for s,r in reverse.items() if r['disposition']=='PERSISTENT'}, {owner,*learned})
                again=self.convert({s:(r['active'],r['disabled']) for s,r in reverse.items() if r['disposition']=='PERSISTENT'},
                                   {owner:1},cls=cls,skills={})
                self.assertEqual({s:r['mask'] for s,r in result.items()},{s:r['mask'] for s,r in again.items()})

    def test_native_passive_cross_spec_ranks_and_stored_predecessor_provenance(self):
        talents={37117:1,37116:2}
        for active in (0,1):
            result=self.convert({},talents,cls=11,active=active,skills={})
            self.assertEqual({s:result[s]['mask'] for s in (16958,16952,16961,16954)},
                             {16958:2,16952:2,16961:1,16954:1})
            reverse=self.convert({},talents,cls=11,active=active,skills={},reverse=True)
            self.assertEqual(reverse[16958]['mask'],3)
            self.assertEqual(reverse[16952]['mask'],3)
            stored={s:(r['active'],r['disabled']) for s,r in reverse.items() if r['disposition']=='PERSISTENT'}
            again=self.convert(stored,talents,cls=11,active=active,skills={})
            self.assertEqual({s:r['mask'] for s,r in result.items()},{s:r['mask'] for s,r in again.items()})
            self.assertEqual(again[16961]['authorization']['native_passive_rank']['stored_predecessors'],
                             [[16958,*stored[16958]]] if 16958 in stored else [])
            inactive=16961 if active==1 else 16958
            self.assertNotEqual(reverse[inactive]['disposition'],'PERSISTENT')
        normalized=self.convert({16958:(0,0)}, {37117:1},cls=11,skills={})
        self.assertNotIn(16958,normalized)
        self.assertEqual(normalized[16961]['authorization']['native_passive_rank']['stored_predecessors'],[[16958,0,0]])
        self.fails('UNREPRESENTABLE_DISABLED_SPELL',lambda:self.convert({16958:(1,1)},{37117:1},cls=11,skills={}))
        self.fails('UNAUTHORIZED_TALENT_SPELL',lambda:self.convert({16961:(1,0)},cls=11,skills={}))
        self.fails('UNAUTHORIZED_TALENT_SPELL',lambda:self.convert({16961:(1,0)},{37116:1},cls=11,skills={}))
        self.fails('UNAUTHORIZED_TALENT_SPELL',lambda:self.convert({51986:(1,1)},{49146:2},cls=6,skills={}))

    def test_native_passive_contract_rejects_mutating_shared_or_changed_metadata(self):
        for mutation in ('visible','skill','learn','stance','effect_value','required','route','class_skill','parent','trainer'):
            tc,ac=copy.deepcopy(self.tc),copy.deepcopy(self.ac)
            if mutation=='visible':ac.spells[16961][4]&=~64
            elif mutation=='skill':ac.spells[16958][71]=118
            elif mutation=='learn':tc.learns[16958].append((6603,1,False))
            elif mutation=='stance':ac.spells[16961][12]=0
            elif mutation=='effect_value':ac.spells[16961][80]+=1
            elif mutation=='required':tc.prerequisite_users[16958].add(6603)
            elif mutation=='route':tc.learn_parents[16958].add(6603)
            elif mutation=='class_skill':ac.abilities[16958][0][9]=2
            elif mutation=='parent':ac.spells[37117][86]=5
            elif mutation=='trainer':ac.trainer_taught.add(16958)
            self.fails('UNSUPPORTED_NATIVE_PASSIVE_RANK',lambda:self.convert({}, {37117:1},cls=11,skills={},tc=tc,ac=ac))

    def test_native_passive_trainer_catalog_is_exclusion_evidence_and_validated(self):
        world=World()
        world.tables['trainer_spell']=[['16958']]
        ac=Metadata('ac',self.path/'ac-dbc','ac',self.profile,world)
        self.fails('UNSUPPORTED_NATIVE_PASSIVE_RANK',lambda:self.convert({}, {37117:1},cls=11,skills={},ac=ac))
        world.tables['trainer_spell']=[['900000']]
        ac=Metadata('ac',self.path/'ac-dbc','ac',self.profile,world)
        self.assertIn(900010,ac.trainer_taught)
        for value in ('NULL','text','-1','4294967296'):
            world.tables['trainer_spell']=[[value]]
            self.fails('INVALID_TRAINER_SPELL_METADATA',lambda:Metadata('ac',self.path/'ac-dbc','ac',self.profile,world))

    def test_flight_form_restores_verified_riding_without_changing_skills(self):
        for active in (0,1):
            for anchor in (33943,40120):
                skills={762:(225,225)}
                result=self.convert({anchor:(1,0)},skills=skills,cls=11,active=active)
                self.assertEqual(set(result),set(fixtures.CHAINS[14][:1 if anchor==33943 else 2]+fixtures.CHAINS[11][:3]))
                self.assertTrue(all(row['mask']==3 and row['disposition']=='PERSISTENT' for row in result.values()))
                self.assertNotIn(34091,result)
                self.assertEqual(skills,{762:(225,225)})
                proof=result[34090]['authorization']['persistent_world_dependencies'][0]
                self.assertEqual(proof['policy'],'TC_WORLD_LOAD_PERSISTENT_RIDING')
                self.assertEqual(proof['stored_skill'],[225,225])
                self.assertEqual(proof['skill_category'],9)
                self.assertIn([anchor,[anchor]+([] if anchor==33943 else [33943])+[34090],
                               'TC_WORLD_PERSISTENT_DEPENDENCY'],result[34090]['proofs'])
                reverse=self.convert({s:(r['mask'],0) for s,r in result.items()},skills=skills,cls=11,reverse=True)
                self.assertEqual(set(reverse),set(result))
        complete=self.convert({33943:(1,0),34091:(1,0)},skills={762:(300,300)},cls=11)
        self.assertEqual(set(complete),{33943,*fixtures.CHAINS[11]})
        repeated=self.convert({34090:(1,0),33943:(1,0)},skills={762:(225,225)},cls=11)
        self.assertFalse(repeated[34090]['derived'])
        self.assertEqual(repeated,self.convert({33943:(1,0),34090:(1,0)},skills={762:(225,225)},cls=11))

    def test_flight_form_dependency_requires_existing_compatible_riding_and_ordinary_ownership(self):
        self.fails('SPELL_WOULD_ADD_SKILL',lambda:self.convert({33943:(1,0)},skills={},cls=11))
        for skills in ({762:(150,150)},{762:(225,300)},{762:(300,300)}):
            self.fails('SPELL_WOULD_CHANGE_SKILL',lambda:self.convert({33943:(1,0)},skills=skills,cls=11))
        self.fails('AC_WOULD_DELETE_SPELL',lambda:self.convert({33943:(1,0)},skills={762:(225,225)},cls=1))
        self.fails('UNREPRESENTABLE_DISABLED_SPELL',lambda:self.convert({33943:(1,1)},skills={762:(225,225)},cls=11))
        tc=copy.deepcopy(self.tc)
        tc.learns[33943]=[(34090,0,False)]
        self.fails('UNSUPPORTED_DEPENDENT_LEARN',lambda:self.convert({33943:(1,0)},skills={762:(225,225)},cls=11,tc=tc))
        tc=copy.deepcopy(self.tc)
        tc.learns[33943]=[]
        self.assertEqual(set(self.convert({33943:(1,0)},skills={762:(225,225)},cls=11,tc=tc)),{33943})
        for core in ('tc','ac'):
            tc,ac=copy.deepcopy(self.tc),copy.deepcopy(self.ac)
            metadata=tc if core=='tc' else ac
            metadata.spells[33943][95]=4
            self.fails('UNSUPPORTED_DEPENDENT_LEARN',lambda:self.convert({33943:(1,0)},skills={762:(225,225)},cls=11,tc=tc,ac=ac))
        tc,ac=copy.deepcopy(self.tc),copy.deepcopy(self.ac)
        for metadata in (tc,ac):
            metadata.spells[34090][71]=36
        self.fails('UNSUPPORTED_DEPENDENT_LEARN',lambda:self.convert({33943:(1,0)},skills={762:(225,225)},cls=11,tc=tc,ac=ac))

    def test_flight_form_requires_native_secondary_riding_category(self):
        self.assertEqual(self.tc.stores['SkillLine'][762][1],9)
        self.assertEqual(self.ac.stores['SkillLine'][762][1],9)
        for core in ('tc','ac','both'):
            for category in (7,11):
                tc,ac=copy.deepcopy(self.tc),copy.deepcopy(self.ac)
                for name,metadata in (('tc',tc),('ac',ac)):
                    if core in (name,'both'):
                        metadata.stores['SkillLine'][762][1]=category
                self.fails('UNSUPPORTED_DEPENDENT_LEARN',lambda:self.convert(
                    {33943:(1,0)},skills={762:(225,225)},cls=11,tc=tc,ac=ac))

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
