"""Guarded metadata checks and the history-repair compatibility entry point."""

from __future__ import annotations

import argparse
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
import csv
import io
import json
from pathlib import Path
import re
from typing import Any, Literal, TYPE_CHECKING

from cleanup_active_reset import KEYS, TABLES, columns, row_hash
import cleanup_death_coil as death_coil
import cleanup_dual_spec_teacher as dual_teacher
import cleanup_eligibility as eligibility
from cleanup_files import (
    PROFILE,
    ROOT,
    fail,
    identifier,
    local_id,
    sha,
    verify,
)
import cleanup_foreign_skills as foreign_skills
import cleanup_inactive_legacy as inactive_legacy
import cleanup_obsolete_riding as riding
import cleanup_ordinary_history as ordinary_history
import cleanup_ownership as ownership
import cleanup_pet_teaching as pet_teaching
from cleanup_plans import ranks, sha_json, snapshot
import cleanup_professions as professions
import cleanup_selected_passive as direct_passive
import cleanup_selected_rank_history as selected_history
import cleanup_shaman_dual_wield as shaman
import cleanup_shaman_offhand as offhand_repair
import cleanup_skill_teaching as skill_teaching
import cleanup_specialization_parent as specialization_parent
import cleanup_specializations as specializations
from cleanup_spell_history import audit_inputs, classify
import cleanup_talent_relations as relations
import cleanup_trained_history as trained_history
from cleanup_types import (
    DatabaseRow,
    DatabaseState,
    DeferredRow,
    Evidence,
    SpellRow,
)
from spells import Metadata, Unsupported

if TYPE_CHECKING:
    from cleanup_config import Settings
    from cleanup_workspace import Workspace


POLICY = 'tc-disabled-unselected-direct-talent-history-v1'
SCRIPT_POLICY = 'tc-disabled-reviewed-script-talent-history-v2'
POLICIES = (POLICY, SCRIPT_POLICY, relations.POLICY, relations.ROUTE_POLICY,
    selected_history.POLICY, trained_history.POLICY,
    trained_history.CHILD_POLICY, trained_history.PENDING_POLICY,
    ordinary_history.POLICY, ordinary_history.INACTIVE_DEFAULT_POLICY,
    ordinary_history.PENDING_DEFAULT_POLICY, ordinary_history.TRAINING_POLICY,
    *death_coil.POLICIES, *ownership.POLICIES, *eligibility.POLICIES,
    *pet_teaching.POLICIES, *inactive_legacy.POLICIES,
    *direct_passive.POLICIES, *shaman.POLICIES, *offhand_repair.POLICIES,
    *dual_teacher.POLICIES, *foreign_skills.POLICIES, *riding.POLICIES,
    *skill_teaching.POLICIES, *professions.POLICIES, *specializations.POLICIES)
MAX_GUIDS, MAX_SELECTED, MAX_PER_GUID = 40000, 500000, 10000
WORLD = {'spell_ranks': ['first_spell_id', 'spell_id', 'rank'],
    'spell_required': ['spell_id', 'req_spell'],
    'spell_learn_spell': ['entry', 'SpellID', 'Active'],
    'spell_script_names': ['spell_id', 'ScriptName'],
    'spell_custom_attr': ['entry', 'attributes'],
    'playercreateinfo_spell_custom': ['racemask', 'classmask', 'Spell']}


def inspection(
    settings: Settings,
    work: Workspace,
    inspection_id: str,
) -> tuple[Path, Evidence, DatabaseState, list[DatabaseRow], Evidence]:
    path = work.session / 'inspections' / local_id(inspection_id)
    contents = verify(path)
    required = {'inspection.json', 'input-state.json', 'spell-history.tsv',
        'summary.tsv', 'README.md'}
    if set(contents) != required:
        fail('HISTORY_INSPECTION_INVALID',
            'Expected a complete direct spell-history inspection')
    report = json.loads(contents['inspection.json'])
    state = json.loads(contents['input-state.json'])
    if (report.get('status') != 'COMPLETE_REVIEW_ONLY' or report.get(
        'source_schema') != settings.schemas['characters']
        or report.get('source_uuid') != work.current()['identity']['uuid']
        or report.get('input_state_sha256') != sha_json(state)):
        fail('HISTORY_INSPECTION_INVALID',
            'Inspection status, source or snapshot differs')
    _, audit, fingerprints, expected = audit_inputs(settings, work, report[
        'audit'])
    if report.get('audit_files_sha256') != fingerprints:
        fail('HISTORY_INSPECTION_INVALID',
            'Inspection references a different sealed audit')
    stores, _, dbc = ranks(settings)
    if report.get('dbc_sha256') != dbc:
        fail('DBC_DRIFT', 'Inspection DBC files differ')
    rows = classify(state, stores, expected)
    saved = (list(csv.reader(io.StringIO(contents['spell-history.tsv'].decode(
    )), delimiter='\t'))[1:])
    if saved != [[str(value) for value in row] for row in rows]:
        fail('HISTORY_INSPECTION_INVALID',
            'Inspection dispositions differ from recomputed ownership')
    return path, report, state, rows, audit


def read_world(
    settings: Settings,
    *,
    exact_numeric: bool = False,
) -> tuple[Metadata, Evidence]:
    """Capture effective TC input tables in one read-only consistent
    snapshot.
    """
    world = settings.schemas['world']
    names = ['spell_dbc', *WORLD]
    quoted = ','.join("'" + name + "'" for name in names)
    layout = snapshot(settings, [('columns',
        'SELECT '
        'JSON_ARRAY(TABLE_NAME,COLUMN_NAME,COLUMN_TYPE,IS_NULLABLE,ORDINAL_POSITION,EXTRA) '
        "row_value FROM information_schema.COLUMNS WHERE TABLE_SCHEMA='"
        f"{world}' AND TABLE_NAME IN ({quoted}) ORDER BY BINARY "
        'TABLE_NAME,ORDINAL_POSITION'), ('tables',
            'SELECT JSON_ARRAY(TABLE_NAME,ENGINE,TABLE_TYPE) row_value '
            f"FROM information_schema.TABLES WHERE TABLE_SCHEMA='{world}"
            f"' AND TABLE_NAME IN ({quoted}) ORDER BY BINARY TABLE_NAME")])
    if (sorted(layout['tables']) != sorted([[name, 'InnoDB', 'BASE TABLE']
        for name in names])):
        fail('HISTORY_WORLD_UNSUPPORTED',
            'Required native TC world metadata tables must exist and use '
            'InnoDB')
    queries = []
    for table in names:
        fields = ([identifier(row[1]) for row in layout['columns'] if row[0]
            == table])
        if not fields or len(fields) > 256:
            fail('HISTORY_WORLD_UNSUPPORTED',
                'Missing or oversized TC world layout: ' + table)
        expressions = ','.join('`' + name + '`' for name in fields)
        queries.append((table,
            f'SELECT JSON_ARRAY({expressions}) row_value FROM `{world}`.`'
            f'{table}` LIMIT 100001'))
        if exact_numeric:
            from cleanup_active_reset import exact_hex
            types = {r[1]: r[2] for r in layout['columns'] if r[0] == table}
            hashed = ("SHA2(CONCAT_WS('|'," + ','.join(
                f"IFNULL({exact_hex('`' + name + '`', types[name])},'N')"
                for name
                in fields) + '),256)')
        else:
            hashed = ("SHA2(CONCAT_WS('|'," + ','.join(
                f"IFNULL(HEX(`{name}`),'N')" for name in fields) + '),256)')
        queries.append(('digests', f"SELECT JSON_ARRAY('{table}"
            f"',COUNT(*),SHA2(COALESCE(GROUP_CONCAT({hashed} ORDER BY BINARY "
            f"{hashed} SEPARATOR ''),''),256)) row_value FROM `{world}`.`"
            f'{table}`'))
    state = snapshot(
        settings, queries,
        session_prefix="SET SESSION time_zone='+00:00';\nSET SESSION "
        'group_concat_max_len=6400001;\n',
    )
    if any(len(state[name]) > 100000 for name in names):
        fail('HISTORY_WORLD_UNSUPPORTED',
            'TC world metadata exceeds the 100000-row per-table bound')
    if snapshot(settings, [('columns',
        'SELECT '
        'JSON_ARRAY(TABLE_NAME,COLUMN_NAME,COLUMN_TYPE,IS_NULLABLE,ORDINAL_POSITION,EXTRA) '
        "row_value FROM information_schema.COLUMNS WHERE TABLE_SCHEMA='"
        f"{world}' AND TABLE_NAME IN ({quoted}) ORDER BY BINARY "
        'TABLE_NAME,ORDINAL_POSITION'), ('tables',
            'SELECT JSON_ARRAY(TABLE_NAME,ENGINE,TABLE_TYPE) row_value '
            f"FROM information_schema.TABLES WHERE TABLE_SCHEMA='{world}"
            f"' AND TABLE_NAME IN ({quoted}) ORDER BY BINARY TABLE_NAME")]) != layout:
        fail('SCHEMA_DRIFT', 'World metadata layout changed during planning')
    # Canonical multisets preserve duplicates and ignore physical row order.
    digests = sorted(state['digests'])
    if any(not isinstance(row[2], str) or not re.fullmatch('[a-f0-9]{64}', row[
        2]) for row in digests):
        fail('HISTORY_WORLD_UNSUPPORTED',
            'World content digest could not be computed')
    state = ({name: sorted(state[name], key=lambda row: json.dumps(row,
        separators= (',', ':'))) for name in names})
    class CapturedWorld:
        def rows(self, label: str, query: str) -> list[list[Any]]:
            if label == 'tc.spell_dbc.layout':
                return ([[r[1], r[2], r[3], r[4]] for r in layout['columns']
                    if r[0] == 'spell_dbc'])
            if label == 'tc.spell_dbc':
                return state['spell_dbc']
            fail('HISTORY_WORLD_UNSUPPORTED', 'Unexpected metadata query: '
                + label)

        def table(
            self,
            schema: str,
            table: str,
            fields: list[str],
            optional: bool = False,
        ) -> list[list[Any]]:
            actual = [r[1] for r in layout['columns'] if r[0] == table]
            positions = ({name.lower(): index for index, name in enumerate(
                actual)})
            if (schema != world or table not in WORLD or not {name.lower()
                for name in fields} <= set(positions)):
                fail('HISTORY_WORLD_UNSUPPORTED',
                    'Missing effective world fields: ' + table)
            return ([[row[positions[field.lower()]] for field in fields]
                for row in state[table]])
    profile = json.loads((PROFILE / 'spell-metadata.json').read_text())
    try:
        effective = Metadata('tc', settings.paths['tc_dbc'], world, profile,
            CapturedWorld())
    except Unsupported as error:
        fail(error.reason, 'TC history metadata: ' + str(error))
    effective.history_default_spells = ordinary_history.history_default_spells(
        layout, state)
    return effective, {'layout': dict(layout), 'rows': state,
        'digests': digests}


def check_metadata(settings: Settings, manifest: Evidence) -> None:
    from cleanup_native_skills import (
        SWITCH_POLICY,
        SWITCH_ACK,
        PENDING_POLICY,
        pending_sources,
    )
    import cleanup_racial_skills as racial_skills
    if manifest.get('policy') == racial_skills.POLICY:
        target, target_world = eligibility.read_target(settings)
        if (manifest.get('native_racial_ack') != racial_skills.ACK or sha(
            ROOT / 'lib/cleanup_native_skills.py') != manifest.get(
                'native_skill_reader_sha256') or sha(
                    ROOT / 'lib/cleanup_racial_skills.py') != manifest.get(
                        'racial_reader_sha256') or sha(racial_skills.CATALOG)
            != manifest.get('racial_catalog_sha256')
            or racial_skills.native_sources(settings.paths) != manifest.get(
                'racial_native_sources') or sha_json(target_world)
            != manifest.get(
                'target_world_sha256') or target.hashes != manifest.get(
                    'target_dbc_sha256') or manifest.get(
                        'numeric_fingerprint')
            != 'EXACT_FRACTIONAL_V1' or sha(
                ROOT / 'lib/cleanup_active_reset.py') != manifest.get(
                    'numeric_reader_sha256') or sha(
                        ROOT / 'lib/cleanup_eligibility.py') != manifest.get(
                            'world_guard_reader_sha256')):
            fail('RACIAL_SKILL_POLICY_DRIFT',
                'Native racial skill/metadata/consumer contract changed')
    if (manifest.get('policy') in (trained_history.PENDING_POLICY,
        death_coil.PENDING_POLICY,
        ordinary_history.PENDING_DEFAULT_POLICY)):
        if (manifest.get('numeric_fingerprint') != 'EXACT_FRACTIONAL_V1'
            or sha(ROOT / 'lib/cleanup_active_reset.py') != manifest.get(
                'numeric_reader_sha256') or sha(
                    ROOT / 'lib/cleanup_eligibility.py') != manifest.get(
                        'world_guard_reader_sha256')):
            fail('PENDING_NUMERIC_POLICY_DRIFT',
                'Pending repair exact numeric/world guards differ')
    if manifest.get('policy') == trained_history.PENDING_POLICY:
        if (manifest.get('pending_history_ack') != trained_history.PENDING_ACK
            or pending_sources(settings.paths) != manifest.get(
                'pending_native_sources') or sha(
                    ROOT / 'lib/cleanup_trained_history.py') != manifest.get(
                        'pending_history_reader_sha256')):
            fail('PENDING_HISTORY_POLICY_DRIFT',
                'Pending-reset family policy or native consumers changed')
    if (manifest.get('policy') == PENDING_POLICY and pending_sources(
        settings.paths) != manifest.get('pending_native_sources')):
        fail('PENDING_GENERIC_NATIVE_DRIFT', 'Native reset consumers changed')
    if manifest.get('policy') in (SWITCH_POLICY, PENDING_POLICY):
        if (manifest.get('native_switch_ack') != SWITCH_ACK
            or manifest.get('numeric_fingerprint') != 'EXACT_FRACTIONAL_V1'
            or sha(ROOT / 'lib/cleanup_native_skills.py') != manifest.get(
                'native_skill_reader_sha256')
            or sha(ROOT / 'lib/cleanup_active_reset.py') != manifest.get(
                'numeric_reader_sha256')
            or sha(ROOT / 'lib/cleanup_eligibility.py') != manifest.get(
                'world_guard_reader_sha256')):
            fail('NATIVE_SWITCH_POLICY_DRIFT',
                'Known-switch skill policy or exact numeric/world guards '
                'differ; retain original toolkit')
    if manifest.get('policy') == ordinary_history.TRAINING_POLICY:
        if (manifest.get('training_prerequisite_ack')
            != ordinary_history.TRAINING_ACK
            or sha(ROOT / 'lib/cleanup_ordinary_history.py')
            != manifest.get('ordinary_reader_sha256')
            or sha(ROOT / 'lib/cleanup_eligibility.py') != manifest.get(
                'world_guard_reader_sha256')
            or manifest.get('numeric_fingerprint') != 'EXACT_FRACTIONAL_V1'
            or sha(ROOT / 'lib/cleanup_active_reset.py') != manifest.get(
                'numeric_reader_sha256')
            or ordinary_history.configuration_contract(settings,
                training_prerequisites=True) != manifest.get(
                    'configuration_contract')):
            fail('ORDINARY_TRAINING_POLICY_DRIFT',
                'Ordinary training policy, guards, metadata reader or '
                'configuration differs; retain original toolkit')
    if (manifest.get('policy') in (*eligibility.POLICIES,
        *pet_teaching.POLICIES, *inactive_legacy.POLICIES,
        *direct_passive.POLICIES, *shaman.POLICIES, *offhand_repair.POLICIES,
        *dual_teacher.POLICIES, *foreign_skills.POLICIES, *riding.POLICIES,
        *skill_teaching.POLICIES, *professions.POLICIES,
        *specializations.POLICIES)):
        if (manifest.get('numeric_fingerprint') != 'EXACT_FRACTIONAL_V1'
            or sha(ROOT / 'lib/cleanup_active_reset.py') != manifest.get(
                'numeric_reader_sha256')):
            fail('ELIGIBILITY_POLICY_DRIFT',
                'Exact numeric fingerprint contract differs from this '
                'candidate')
        if (sha(ROOT / 'lib/cleanup_eligibility.py') != manifest.get(
            'eligibility_reader_sha256')):
            fail('ELIGIBILITY_POLICY_DRIFT',
                'Eligibility selector differs; retain the original '
                'toolkit for restoration')
        if (eligibility.configuration_contract(settings) != manifest.get(
            'configuration_contract')):
            fail('ELIGIBILITY_CONFIG_DRIFT',
                'Eligibility configuration differs from the reviewed '
                'candidate')
    if manifest.get('policy') == eligibility.ACTION_POLICY:
        if (manifest.get('foreign_action_ack') != eligibility.ACTION_ACK
            or sha(eligibility.ACTION_CATALOG) != manifest.get(
                'foreign_action_catalog_sha256')):
            fail('FOREIGN_ACTION_POLICY_DRIFT',
                'Inactive foreign action contract changed; retain '
                'original toolkit')
    if manifest.get('policy') == eligibility.SWIPE_POLICY:
        if (manifest.get('swipe_ack') != eligibility.SWIPE_ACK
            or sha(eligibility.SWIPE_CATALOG) != manifest.get(
                'swipe_catalog_sha256')):
            fail('FOREIGN_SWIPE_POLICY_DRIFT',
                'Inactive foreign Swipe contract changed; retain '
                'original toolkit')
    if manifest.get('policy') == eligibility.RACIAL_POLICY:
        if (manifest.get('racial_ack') != eligibility.RACIAL_ACK
            or sha(eligibility.RACIAL_CATALOG) != manifest.get(
                'racial_catalog_sha256')):
            fail('RACIAL_POLICY_DRIFT',
                'Reviewed racial acknowledgement or catalog changed; '
                'retain original toolkit')
    if (manifest.get('policy') == eligibility.CAST_SCRIPT_POLICY
        and manifest.get('cast_script_ack')
        != eligibility.CAST_SCRIPT_ACK):
        fail('CAST_SCRIPT_ACK_INVALID',
            'Reviewed nonlearning cast callback acknowledgement differs')
    if (manifest.get('policy') == eligibility.ABSENT_TEACHER_POLICY
        and manifest.get('absent_teacher_ack')
        != eligibility.ABSENT_TEACHER_ACK):
        fail('ABSENT_TEACHER_ACK_INVALID',
            'Absent-teacher contract differs from the reviewed batch')
    if (manifest.get('policy') in pet_teaching.POLICIES and sha(
        ROOT / 'lib/cleanup_pet_teaching.py') != manifest.get(
            'pet_teaching_reader_sha256')):
        fail('PET_TEACHING_POLICY_DRIFT',
            'Pet-teaching selector differs; retain the original toolkit '
            'for restoration')
    if manifest.get('policy') in specializations.POLICIES:
        parent_policy = (manifest.get('policy')
            in specializations.PARENT_POLICIES)
        invalid_equipment = (manifest.get('policy') in (
            specializations.INVALID_ITEMS_POLICY,
            specializations.PARENT_INVALID_ITEMS_POLICY))
        if (invalid_equipment and sha(specializations.ITEM_CATALOG)
            != manifest.get('specialization_item_catalog_sha256')):
            fail('SPECIALIZATION_ITEM_POLICY_DRIFT',
                'Native invalid-item contract changed')
        if (manifest.get('specialization_ack') != (specialization_parent.ACK
            if parent_policy else specializations.ACK)
            or sha(ROOT / 'lib/cleanup_specializations.py')
            != manifest.get('specialization_reader_sha256')
            or sha(specializations.CATALOG) != manifest.get(
                'specialization_catalog_sha256')
            or sha(ROOT / 'lib/cleanup_professions.py') != manifest.get(
                'profession_reader_sha256')
            or sha(professions.CATALOG) != manifest.get(
                'profession_catalog_sha256')):
            fail('SPECIALIZATION_POLICY_DRIFT',
                'Specialization selector or fixed catalogs changed; '
                'retain original toolkit')
        if (specializations.native_sources(settings.paths,
            native_invalid_items=invalid_equipment) != manifest.get(
                'specialization_native_sources')):
            fail('SPECIALIZATION_NATIVE_SOURCE_DRIFT',
                'Native specialization/equipment consumers changed')
        if (parent_policy and sha(
            ROOT / 'lib/cleanup_specialization_parent.py') != manifest.get(
                'specialization_parent_reader_sha256')):
            fail('SPECIALIZATION_PARENT_POLICY_DRIFT',
                'Parent-specialization reader changed; retain original '
                'toolkit')
        if (specializations.read_equipment(settings, manifest[
            'character_guids'], native_invalid_items=invalid_equipment)
            != manifest.get('specialization_equipment')):
            fail('SPECIALIZATION_EQUIPMENT_DRIFT',
                'Equipment or item requirement evidence changed')
    if manifest.get('policy') == professions.PENDING_POLICY:
        if (manifest.get('pending_profession_ack') != professions.PENDING_ACK
            or pending_sources(settings.paths) != manifest.get(
                'pending_native_sources')):
            fail('PENDING_PROFESSION_POLICY_DRIFT',
                'Pending profession repair or native reset consumers '
                'changed')
    if manifest.get('policy') in professions.POLICIES:
        if (manifest.get('profession_activation_ack') != professions.ACK
            or sha(ROOT / 'lib/cleanup_professions.py') != manifest.get(
                'profession_reader_sha256')
            or sha(professions.CATALOG) != manifest.get(
                'profession_catalog_sha256')):
            fail('PROFESSION_POLICY_DRIFT',
                'Profession activation reader or fixed catalog differs; '
                'retain original toolkit')
    if manifest.get('policy') == skill_teaching.POLICY:
        if (manifest.get('skill_teaching_ack') != skill_teaching.ACK
            or sha(ROOT / 'lib/cleanup_skill_teaching.py') != manifest.get(
                'skill_teaching_reader_sha256')
            or sha(skill_teaching.CATALOG) != manifest.get(
                'skill_teaching_catalog_sha256')):
            fail('SKILL_TEACHER_POLICY_DRIFT',
                'Skill-teaching selector or fixed catalog differs; '
                'retain original toolkit')
    if manifest.get('policy') in riding.POLICIES:
        legacy_horse = manifest.get('policy') == riding.HORSE_POLICY
        invalid_items = (manifest.get('policy') in (
            riding.INVALID_ITEMS_POLICY, riding.HORSE_POLICY))
        catalog = riding.HORSE_CATALOG if legacy_horse else riding.CATALOG
        if (manifest.get('riding_ack') != (riding.HORSE_ACK if legacy_horse
            else riding.INVALID_ITEMS_ACK if invalid_items else riding.ACK)
            or sha(ROOT / 'lib/cleanup_obsolete_riding.py')
            != manifest.get('riding_reader_sha256')
            or sha(catalog) != manifest.get('riding_catalog_sha256')
            or sha(ROOT / 'lib/cleanup_shaman_dual_wield.py')
            != manifest.get('starting_skill_reader_sha256')
            or riding.native_sources(settings.paths,
                native_invalid_items=invalid_items, legacy_horse=legacy_horse)
            != manifest.get('riding_native_sources')
            or invalid_items and sha(riding.ITEM_CATALOG) != manifest.get(
                'riding_item_catalog_sha256')):
            fail('OBSOLETE_RIDING_POLICY_DRIFT',
                'Obsolete riding contract differs; retain the original '
                'toolkit')
        if riding.defaults(settings) != manifest.get('riding_default_skills'):
            fail('OBSOLETE_RIDING_DEFAULT_DRIFT',
                'Starting-skill inputs changed')
        guids = manifest['character_guids']
        if (riding.read_items(settings, guids,
            native_invalid_items=invalid_items) != manifest.get(
                'riding_items')):
            fail('OBSOLETE_RIDING_ITEM_DRIFT',
                'Owned/inventory/mail item requirements changed')
    if manifest.get('policy') in (*shaman.POLICIES, *offhand_repair.POLICIES):
        offhand_mode = manifest['policy'] == offhand_repair.POLICY
        if (offhand_mode and (sha(ROOT / 'lib/cleanup_shaman_offhand.py')
            != manifest.get('offhand_reader_sha256')
            or offhand_repair.native_sources(settings.paths) != manifest.get(
                'offhand_native_sources'))):
            fail('SHAMAN_OFFHAND_POLICY_DRIFT',
                'Off-hand reconciliation selector/consumers changed')
        if (manifest.get('shaman_ack') != (offhand_repair.ACK if offhand_mode
            else shaman.ACK)
            or sha(ROOT / 'lib/cleanup_shaman_dual_wield.py')
            != manifest.get('shaman_reader_sha256')):
            fail('SHAMAN_POLICY_DRIFT',
                'Shaman coupled repair contract differs; retain original '
                'toolkit')
        if shaman.defaults(settings) != manifest.get('shaman_default_skills'):
            fail('SHAMAN_DEFAULT_DRIFT',
                'Native starting-skill metadata changed')
    if manifest.get('policy') in foreign_skills.POLICIES:
        expected_ack = foreign_skills.policy_ack(manifest['policy'])
        if (manifest.get('foreign_skill_ack') != expected_ack
            or foreign_skills.reader_hashes() != manifest.get(
                'foreign_skill_readers') or foreign_skills.native_sources(
                    settings.paths) != manifest.get('foreign_skill_sources')):
            fail('FOREIGN_SKILL_POLICY_DRIFT',
                'Foreign skill selector, dependencies or native '
                'consumers changed')
        ids = manifest['character_guids']
        if (riding.read_items(settings, ids, native_invalid_items=True)
            != manifest.get('foreign_skill_items') or (manifest['policy']
                != foreign_skills.native_actions.POLICIES[
                    'forbidden-pairs-stowing'][0] and offhand_repair.read(
                        settings,
                        ids, equipment_slots=range(19)) != manifest.get(
                            'foreign_skill_equipment')) or shaman.defaults(
                                settings)
            != manifest.get('foreign_skill_defaults')):
            fail('FOREIGN_SKILL_ITEM_DRIFT',
                'Native defaults, inventory or owned item evidence '
                'changed')
    if manifest.get('policy') == dual_teacher.POLICY:
        if (manifest.get('dual_teacher_ack') != dual_teacher.ACK or sha(
            ROOT / 'lib/cleanup_dual_spec_teacher.py') != manifest.get(
                'dual_reader_sha256') or pending_sources(settings.paths)
            != manifest.get('dual_native_sources')):
            fail('DUAL_TEACHER_POLICY_DRIFT',
                'Unavailable dual-spec teacher policy or native consumer '
                'changed')
    if manifest.get('policy') == direct_passive.POLICY:
        if (manifest.get('direct_passive_ack') != direct_passive.ACK
            or sha(ROOT / 'lib/cleanup_selected_passive.py')
            != manifest.get('direct_passive_reader_sha256')
            or sha(ROOT / 'lib/cleanup_ownership.py') != manifest.get(
                'ownership_reader_sha256')):
            fail('DIRECT_PASSIVE_POLICY_DRIFT',
                'Direct passive authority contract differs; retain '
                'original toolkit')
    if manifest.get('policy') == inactive_legacy.POLICY:
        if (manifest.get('inactive_legacy_ack') != inactive_legacy.ACK
            or sha(ROOT / 'lib/cleanup_inactive_legacy.py')
            != manifest.get('inactive_legacy_reader_sha256')):
            fail('INACTIVE_LEGACY_POLICY_DRIFT',
                'Inactive legacy selector or acknowledgement differs; '
                'retain original toolkit')
    if manifest.get('policy') == pet_teaching.COWER_POLICY:
        if (manifest.get('cower_ack') != pet_teaching.COWER_ACK
            or pet_teaching.cower_sources(settings.paths) != manifest.get(
                'cower_native_contract')):
            fail('COWER_NATIVE_CONTRACT_DRIFT',
                'Native Cower contract differs from the reviewed batch')
    if (manifest.get('policy') in ownership.POLICIES and sha(
        ROOT / 'lib/cleanup_ownership.py') != manifest.get(
            'ownership_reader_sha256')):
        fail('OWNERSHIP_POLICY_DRIFT',
            'Ownership selection code differs from this reviewed batch; '
            'retain its original toolkit for restore')
    if manifest.get('policy') == ownership.OVERLEVEL_POLICY:
        if (manifest.get('overlevel_ownership_ack') != ownership.OVERLEVEL_ACK
            or sha(ROOT / 'lib/cleanup_ownership.py') != manifest.get(
                'ownership_reader_sha256') or manifest.get(
                    'numeric_fingerprint')
            != 'EXACT_FRACTIONAL_V1' or sha(
                ROOT / 'lib/cleanup_active_reset.py') != manifest.get(
                    'numeric_reader_sha256') or sha(
                        ROOT / 'lib/cleanup_eligibility.py') != manifest.get(
                            'world_guard_reader_sha256')):
            fail('OVERLEVEL_OWNERSHIP_POLICY_DRIFT',
                'Overlevel unselected-history repair or native numeric '
                'readers changed')
    if manifest.get('policy') == ownership.PENDING_POLICY:
        if (manifest.get('pending_ownership_ack') != ownership.PENDING_ACK
            or pending_sources(settings.paths) != manifest.get(
                'pending_native_sources') or sha(
                    ROOT / 'lib/cleanup_ownership.py') != manifest.get(
                        'ownership_reader_sha256') or manifest.get(
                            'numeric_fingerprint')
            != 'EXACT_FRACTIONAL_V1' or sha(
                ROOT / 'lib/cleanup_active_reset.py') != manifest.get(
                    'numeric_reader_sha256') or sha(
                        ROOT / 'lib/cleanup_eligibility.py') != manifest.get(
                            'world_guard_reader_sha256')):
            fail('PENDING_OWNERSHIP_POLICY_DRIFT',
                'Pending ownership repair or native/numeric consumers '
                'changed')
    if manifest.get('policy') == ownership.FOREIGN_POLICY:
        if (manifest.get('foreign_family_ack') != ownership.FOREIGN_ACK
            or manifest.get('numeric_fingerprint') != 'EXACT_FRACTIONAL_V1'
            or sha(ROOT / 'lib/cleanup_active_reset.py') != manifest.get(
                'numeric_reader_sha256')
            or sha(ROOT / 'lib/cleanup_eligibility.py') != manifest.get(
                'world_guard_reader_sha256')):
            fail('OWNERSHIP_FOREIGN_POLICY_DRIFT',
                'Foreign-family policy or exact numeric/world guards '
                'differ; retain original toolkit')
    if manifest.get('policy') == ownership.PREFIX_POLICY:
        if (manifest.get('native_prefix_ack') != ownership.PREFIX_ACK
            or manifest.get('numeric_fingerprint') != 'EXACT_FRACTIONAL_V1'
            or sha(ROOT / 'lib/cleanup_active_reset.py') != manifest.get(
                'numeric_reader_sha256')
            or sha(ROOT / 'lib/cleanup_eligibility.py') != manifest.get(
                'world_guard_reader_sha256')):
            fail('OWNERSHIP_PREFIX_POLICY_DRIFT',
                'Native-prefix policy or exact numeric/world guards '
                'differ; retain original toolkit')
    if manifest.get('policy') == ownership.REKEY_POLICY:
        if (manifest.get('native_rekey_ack') != ownership.REKEY_ACK
            or manifest.get('numeric_fingerprint') != 'EXACT_FRACTIONAL_V1'
            or sha(ROOT / 'lib/cleanup_active_reset.py') != manifest.get(
                'numeric_reader_sha256')
            or sha(ROOT / 'lib/cleanup_eligibility.py') != manifest.get(
                'world_guard_reader_sha256')):
            fail('OWNERSHIP_REKEY_POLICY_DRIFT',
                'Passive rekey policy or exact numeric/world guards '
                'differ; retain original toolkit')
    if manifest.get('policy') == ownership.AURA_ALIAS_POLICY:
        if (manifest.get('aura_alias_ack') != ownership.AURA_ALIAS_ACK
            or manifest.get('numeric_fingerprint') != 'EXACT_FRACTIONAL_V1'
            or sha(ROOT / 'lib/cleanup_active_reset.py') != manifest.get(
                'numeric_reader_sha256')
            or sha(ROOT / 'lib/cleanup_eligibility.py') != manifest.get(
                'world_guard_reader_sha256')):
            fail('OWNERSHIP_ALIAS_POLICY_DRIFT',
                'Aura-alias policy or exact numeric/world guards differ; '
                'retain original toolkit')
    if manifest.get('policy') == ordinary_history.PENDING_DEFAULT_POLICY:
        if (manifest.get('pending_default_ack')
            != ordinary_history.PENDING_DEFAULT_ACK or pending_sources(
                settings.paths) != manifest.get('pending_native_sources')
            or sha(
                ROOT / 'lib/cleanup_ordinary_history.py') != manifest.get(
                    'pending_ordinary_reader_sha256')):
            fail('PENDING_DEFAULT_POLICY_DRIFT',
                'Pending ordinary default policy or native consumers '
                'changed')
    if (manifest.get('policy') in (ordinary_history.INACTIVE_DEFAULT_POLICY,
        ordinary_history.PENDING_DEFAULT_POLICY)):
        if (ordinary_history.configuration_contract(settings) != manifest.get(
            'configuration_contract')):
            fail('ORDINARY_HISTORY_CONFIG_DRIFT',
                'Configuration contract differs from the reviewed '
                'ordinary-history batch')
    if manifest.get('policy') == death_coil.PENDING_POLICY:
        if (manifest.get('pending_death_coil_ack') != death_coil.PENDING_ACK
            or pending_sources(settings.paths) != manifest.get(
                'pending_native_sources') or sha(
                    ROOT / 'lib/cleanup_ordinary_history.py') != manifest.get(
                        'pending_ordinary_reader_sha256') or sha(
                            ROOT / 'lib/cleanup_death_coil.py')
            != manifest.get(
                'pending_death_coil_reader_sha256')):
            fail('PENDING_DEATH_COIL_POLICY_DRIFT',
                'Pending Death Coil policy or native consumers changed')
    if manifest.get('policy') in death_coil.POLICIES:
        if (death_coil.configuration_contract(settings) != manifest.get(
            'configuration_contract')):
            fail('DEATH_COIL_CONFIG_DRIFT',
                'Configuration contract differs from the reviewed Death '
                'Coil batch')
    settings.check_paths()
    if (sha(PROFILE / 'spell-metadata.json') != manifest.get(
        'metadata_profile_sha256')):
        fail('HISTORY_METADATA_DRIFT',
            'Spell metadata policy differs from the reviewed batch')
    for key, entry in manifest.get('core_compatibility', {}).items():
        if (settings.compatibility.get(key, {}).get('manifest_sha256')
            != entry.get('manifest_sha256')):
            fail('CORE_PROFILE_MISMATCH',
                'Core compatibility manifests differ from the reviewed '
                'history batch')
    effective, world = read_world(settings, exact_numeric=manifest.get(
        'policy') in (*eligibility.POLICIES, *pet_teaching.POLICIES,
            *inactive_legacy.POLICIES, *direct_passive.POLICIES,
            *shaman.POLICIES,
            *offhand_repair.POLICIES, *dual_teacher.POLICIES,
            *foreign_skills.POLICIES, *riding.POLICIES,
            *skill_teaching.POLICIES,
            *professions.POLICIES, *specializations.POLICIES,
            ordinary_history.TRAINING_POLICY,
            ordinary_history.PENDING_DEFAULT_POLICY,
            trained_history.PENDING_POLICY, death_coil.PENDING_POLICY,
            ownership.FOREIGN_POLICY, ownership.PREFIX_POLICY,
            ownership.AURA_ALIAS_POLICY, ownership.REKEY_POLICY,
            ownership.PENDING_POLICY, ownership.OVERLEVEL_POLICY,
            SWITCH_POLICY,
            PENDING_POLICY, racial_skills.POLICY))
    if (sha_json(world) != manifest.get('world_sha256') or effective.hashes
        != manifest.get('semantic_dbc_sha256')):
        fail('HISTORY_METADATA_DRIFT',
            'Effective TC world/DBC metadata differs from this reviewed '
            'history batch')
    if (manifest.get('policy') in (*eligibility.POLICIES,
        *pet_teaching.POLICIES, *inactive_legacy.POLICIES,
        *direct_passive.POLICIES, *shaman.POLICIES, *offhand_repair.POLICIES,
        *dual_teacher.POLICIES, *foreign_skills.POLICIES, *riding.POLICIES,
        *skill_teaching.POLICIES, *professions.POLICIES,
        *specializations.POLICIES)):
        target, captured = eligibility.read_target(settings)
        if (sha_json(captured) != manifest.get('target_world_sha256')
            or target.hashes != manifest.get('target_dbc_sha256')):
            fail('ELIGIBILITY_TARGET_DRIFT',
                'Effective AC world/DBC metadata differs from the '
                'reviewed candidate')


def script_bindings(effective: Metadata) -> list[tuple[int, int, str, str]]:
    """Review every direct-family binding against the protected TC
    contract.

    The broader reconstruction checker also supports runtime aura
    helpers and cast-only research spells. Neither contract authorizes
    history cleanup. Only the existing NO_SPELLBOOK_MUTATION contract is
    eligible here.
    """
    bindings = []
    for spell, (family, _) in sorted(effective.talents.items()):
        for name in sorted(effective.scripts[spell]):
            reason = ''
            if effective.script_policy.get(name) != 'NO_SPELLBOOK_MUTATION':
                reason = 'UNREVIEWED_HISTORY_SCRIPT'
            else:
                try:
                    effective.check_script(spell, name)
                except Unsupported as error:
                    reason = error.reason
            bindings.append((family, spell, name, reason))
    return bindings


def check_retained_scripts(state: DatabaseState, effective: Metadata) -> None:
    parents = {spell for _, spell, _ in state['talents']}
    parents.update(row[0] for row in state.get('enabled_ids', []))
    for spell in sorted(parents):
        try:
            for name in sorted(effective.scripts[spell]):
                effective.check_script(spell, name)
        except Unsupported as error:
            fail(error.reason,
                'Selected talent script needs review before history '
                'cleanup: '
                + str(error))


def select(
    rows: Iterable[Sequence[Any]],
    state: DatabaseState,
    effective: Metadata,
    expected_review_rows: int,
    include_reviewed_scripts: bool = False,
) -> tuple[list[SpellRow], list[DeferredRow]]:
    candidates = ([row for row in rows if row[9]
        == 'REVIEW_DISABLED_NO_SELECTED_FAMILY'])
    if (not 1 <= expected_review_rows <= MAX_SELECTED or len(candidates)
        != expected_review_rows):
        fail('HISTORY_SELECTION_MISMATCH',
            '--expect-review-rows must equal the inspection '
            'disabled/no-selected-family total')
    enabled_families = set()
    for guid, spell, _, disabled in state['spells']:
        if not disabled and spell in effective.talents:
            enabled_families.add((guid, effective.talents[spell][0]))
    check_retained_scripts(state, effective)
    incoming = {child for links in (effective.learns, effective.effect_learns)
        for values in links.values()
        for child, _, _ in values}
    # An alternate skill/default learning route needs a separate representation
    # decision, even though disabled AddSpell itself returns before effects.
    skill_rewards = {spell for spell, abilities in effective.abilities.items()
        if any(row[9] in (1, 2) for row in abilities)}
    families = defaultdict(set)
    for spell, (family, _) in effective.talents.items():
        families[family].add(spell)
    bindings = script_bindings(effective) if include_reviewed_scripts else[]
    rejected_scripts = {family for family, _, _, reason in bindings if reason}
    required_parents = ({parent for parents in getattr(effective, 'requires', {
    }).values() for parent in parents})
    family_exclusions = {}
    for family, members in families.items():
        if members & incoming:
            family_exclusions[family] = 'DEFER_INDEPENDENT_LEARN_ROUTE'
        elif members & skill_rewards:
            family_exclusions[family] = 'DEFER_SKILL_REWARD_ROUTE'
        elif members & getattr(effective, 'history_default_spells', set()):
            family_exclusions[family] = 'DEFER_CUSTOM_DEFAULT_ROUTE'
        elif ((members & required_parents or any(effective.learns[spell]
            or effective.effect_learns[spell] for spell in members))):
            family_exclusions[family] = 'DEFER_TALENT_DEPENDENCIES'
        elif (any(effective.scripts[spell] for spell in members) and (
            not include_reviewed_scripts or family in rejected_scripts)):
            family_exclusions[family] = 'DEFER_SCRIPTED_TALENT_FAMILY'
        elif (hasattr(effective, 'spells') and any(set(effective.spells[spell][
            71:74]) & {44, 47, 118} for spell in members)):
            family_exclusions[family] = 'DEFER_TALENT_SKILL_EFFECT'
    selected, excluded = [], []
    for row in candidates:
        guid, spell, active, disabled = row[:4]
        family = effective.talents.get(spell, (None, None))[0]
        chain = effective.chain(spell)
        reason = None
        if (disabled != 1 or active not in (0, 1) or spell
            in effective.invalid_talents
            or family != row[10] or effective.talents.get(spell) != (row[
                10], row[11])):
            reason = 'DEFER_EFFECTIVE_TALENT_IDENTITY'
        elif any(member not in effective.talents or effective.talents[member][
            0] != family for member in chain):
            reason = 'DEFER_MIXED_RANK_CHAIN'
        elif (guid, family) in enabled_families:
            reason = 'DEFER_ENABLED_FAMILY_SPELL'
        elif family in family_exclusions:
            reason = family_exclusions[family]
        if reason:
            excluded.append((guid, spell, reason))
        else:
            selected.append((guid, spell, active, disabled))
    if not selected:
        fail('HISTORY_NO_ELIGIBLE_ROWS',
            'No disabled direct talent history rows satisfy this policy')
    if len({row[0] for row in selected}) > MAX_GUIDS:
        fail('HISTORY_SNAPSHOT_BOUND',
            'Affected character count exceeds 40000; use a separately '
            'scoped policy')
    return selected, excluded


def aggregate(
    meta: DatabaseState,
    table: str,
    database: str,
    scope: str,
    alias: str = 's',
    *,
    exact_numeric: bool = False,
    join: str = '',
) -> str:
    keys = ','.join(f'{alias}.`{name}`' for name in KEYS[table])
    size = '+'.join(f'COALESCE(OCTET_LENGTH({alias}.`{name}`),0)' for name
        in columns(meta, table))
    hashed = (
        f'IF(({size})<=1048576,'
        f'{row_hash(meta, table, alias, exact_numeric=exact_numeric)}'
        ',NULL)'
    )
    return (f'SELECT {alias}.guid,COUNT(*) n,IF(COUNT({hashed}'
        f')=COUNT(*),SHA2(GROUP_CONCAT({hashed} ORDER BY {keys} SEPARATOR '
        f"''),256),NULL) h FROM `{database}`.`{table}` {alias} {join} WHERE "
        f'{scope} GROUP BY {alias}.guid')


def retirement_join(selected: Sequence[Sequence[Any]]) -> str:
    """Bound exact keys as a relation, avoiding thousands of per-row OR
    tests.
    """
    pairs = [list(row[:2]) for row in selected]
    if (not 1 <= len(pairs) <= MAX_SELECTED or len({tuple(p) for p in pairs})
        != len(pairs)
        or any(len(p) != 2 or any(type(v) is not int or not 1 <= v
            <= 0xffffffff for v in p) for p in pairs)):
        fail('HISTORY_SELECTION_INVALID',
            'Retirement projection needs distinct native character/spell '
            'keys')
    keys = json.dumps(pairs, separators= (',', ':'))
    # DISTINCT prevents derived-table merging. Without materialization MySQL
    # estimates JSON_TABLE at two rows and scans every key for every source
    # row.
    return (
        f"LEFT JOIN (SELECT DISTINCT k.guid,k.spell FROM JSON_TABLE('{keys}"
        "','$[*]' COLUMNS(guid INT UNSIGNED PATH '$[0]',spell INT UNSIGNED "
        "PATH '$[1]')) k) retired ON retired.guid=s.guid AND "
        'retired.spell=s.spell')


def enabled_ids_query(source: str) -> str:
    return (
        'SELECT JSON_ARRAY(spell) row_value FROM (SELECT DISTINCT spell FROM '
        f'`{source}`.character_spell WHERE disabled=0) enabled_spells ORDER '
        'BY spell')


def check_sets(
    meta: DatabaseState,
    source: str,
    archive: str,
    counts: Mapping[str, int],
    changed_table: str | tuple[str, ...] = 'character_spell',
    *,
    exact_numeric: bool = False,
) -> dict[str, str]:
    blocks = {}
    for phase in ('original', 'archive', 'applied'):
        lines = []
        for table in TABLES:
            db = archive if phase == 'archive' else source
            actual_table = table + '_before' if phase == 'archive' else table
            query = aggregate(meta, table, db,
                's.guid IN (SELECT guid FROM affected)',
                exact_numeric=exact_numeric)
            if phase == 'archive':
                query = query.replace(f'`{db}`.`{table}`',
                    f'`{db}`.`{actual_table}`')
            expected = 'expected_snapshot'
            if (phase == 'applied' and table in ((changed_table,)
                if isinstance(changed_table, str) else changed_table)):
                expected = 'expected_after'
            lines.append(
                f''' IF (SELECT COUNT(*) FROM `{db}`.`{actual_table}` s WHERE s.guid IN (SELECT guid FROM affected))<>
     (SELECT COALESCE(SUM(row_count),0) FROM {expected} WHERE table_name='{table}')
 OR EXISTS(SELECT 1 FROM {expected} e LEFT JOIN ({query}) a ON a.guid=e.guid
     WHERE e.table_name='{table}' AND (a.guid IS NULL OR a.n<>e.row_count OR NOT (BINARY a.h<=>BINARY e.row_hash))) THEN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='{phase} {table} full-row fingerprint differs';
 END IF;''')
            if phase == 'archive':
                lines.append(
                    f''' IF (SELECT COUNT(*) FROM `{db}`.`{actual_table}`)<> {counts[table]} THEN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Unexpected rows in {table} archive'; END IF;''')
        blocks[phase] = '\n'.join(lines)
    return blocks


def plan_history(
    settings: Settings,
    work: Workspace,
    args: argparse.Namespace,
    output: Path,
) -> Literal[False] | None:
    """Generate a reviewed package through explicit, independently testable
    stages.
    """
    from cleanup_history_workflow import plan_history as build_history_plan

    return build_history_plan(settings, work, args, output)


def render_text(template: Path, values: Mapping[str, Any]) -> str:
    text = template.read_text()
    for name in ('CHECK_ORIGINAL', 'CHECK_ARCHIVE', 'CHECK_APPLIED',
        'ARCHIVE_INSERT'):
        text = text.replace('@' + name + '@', values[name])
    for name, value in values.items():
        text = text.replace('@' + name + '@', str(value))
    if re.search('@[A-Z_]+@', text):
        fail('UNEXPANDED_TEMPLATE',
            'Disabled history SQL has unresolved tokens')
    return text
