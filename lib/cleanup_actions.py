"""Execute reviewed packages with archive and acknowledgement guards."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
from typing import TYPE_CHECKING

from cleanup_errors import CleanupError, fail
from cleanup_files import identifier, sha, verify
from cleanup_types import Evidence

if TYPE_CHECKING:
    from cleanup_config import Settings
    from cleanup_workspace import Workspace


def command_action(
    settings: Settings,
    work: Workspace,
    args: argparse.Namespace,
) -> None:
    path, manifest = work.batch(args.batch)
    settings.safety()
    _validate_action_metadata(settings, manifest)
    work.check_identity('admin' if args.command == 'prepare' else 'write')
    contents, scripts, principal = _prepare_archive(settings, manifest, path,
        args.command)
    action = {'prepare': '01-prepare.sql', 'apply': '02-apply.sql',
        'restore': '03-restore.sql'} [args.command]
    ack = manifest.get('ack_variable', 'talent_cleanup_ack')
    if ack not in ('talent_cleanup_ack', 'recovery_ack', 'skill_cleanup_ack'):
        fail('INVALID_POLICY', 'Unknown cleanup acknowledgement variable')
    configuration_ack = _configuration_acknowledgements(manifest)
    query = f"SET @{ack}='STOPPED_PREPARATION_COPY_ONLY';\n"
    result = _execute_action_sql(settings, manifest, query + configuration_ack
        + scripts[action], principal)
    _record_action_result(settings, work, manifest, contents, result)


def _validate_action_metadata(settings: Settings, manifest: Evidence) -> None:
    from cleanup_disabled_history import POLICIES, check_metadata
    from cleanup_native_skills import POLICIES as NATIVE_SKILL_POLICIES
    if manifest.get('policy') in (*POLICIES, *NATIVE_SKILL_POLICIES):
        check_metadata(settings, manifest)
    for name, expected_hash in manifest.get('dbc_sha256', {}).items():
        if (not re.fullmatch('[A-Za-z0-9]+\\.dbc', name) or sha(settings.paths[
            'tc_dbc'] / name) != expected_hash):
            fail('DBC_DRIFT', 'DBC assets differ from the reviewed batch',
                'Keep the original metadata or generate a new audit and '
                'batch.')


def _prepare_archive(
    settings: Settings,
    manifest: Evidence,
    path: Path,
    command: str,
) -> tuple[dict[str, bytes], dict[str, str], list[str]]:
    archive = identifier(manifest['archive_schema'])
    # Snapshot the verified SQL before invoking mysql, so replacing a file
    # after
    # checksum verification cannot change the statement executed by this call.
    contents = verify(path)
    scripts = ({name: contents[name].decode() for name in ('00-setup.sql',
        '01-prepare.sql', '02-apply.sql', '03-restore.sql')})
    exists = (settings.sql(
        "SELECT COUNT(*) FROM information_schema.SCHEMATA WHERE SCHEMA_NAME='"
        + archive + "';", 'admin').strip() == '1')
    if command == 'prepare' and not exists:
        settings.sql(scripts['00-setup.sql'], 'admin')
        exists = True
    if not exists:
        fail('BATCH_NOT_PREPARED', 'Archive does not exist yet',
            'Run prepare first; it creates only the new archive and '
            'captures originals.')
    # Reject partial DDL, a foreign schema, or a mismatched control record.
    procedures = set(settings.sql(
        'SELECT ROUTINE_NAME FROM information_schema.ROUTINES WHERE '
        "ROUTINE_SCHEMA='" + archive + "';", 'admin').splitlines())
    expected = set(re.findall('CREATE PROCEDURE ([A-Za-z0-9_]+)\\(', scripts[
        '00-setup.sql']))
    if procedures != expected:
        fail('PARTIAL_ARCHIVE', 'Archive procedures are incomplete or changed',
            'Retain and inspect the partial archive; never drop/reuse it '
            'automatically. Generate a new batch if needed.')
    header = settings.sql(
        f'SELECT batch_key,source_schema,source_uuid FROM `{archive}`.batch '
        'WHERE id=1;', 'admin').strip().split('\t')
    if (header != [manifest['batch_key'], settings.schemas['characters'],
        manifest['source_uuid']]):
        fail('ARCHIVE_OWNERSHIP',
            'Archive provenance differs from the selected batch')
    # Archive permissions are limited to the newly owned schema. Source table
    # write privileges stay an operator decision and are never granted here.
    principal = settings.sql('SELECT '
        "QUOTE(SUBSTRING_INDEX(CURRENT_USER(),'@',1)),QUOTE(SUBSTRING_INDEX(CURRENT_USER(),'@',-1));", 'write').strip().split('\t')
    if len(principal) != 2:
        fail('WRITER_IDENTITY',
            'Cannot establish the authenticated writer account')
    settings.sql(
        f'GRANT SELECT,INSERT,UPDATE,DELETE,EXECUTE ON `{archive}`.* TO '
        f'{principal[0]}@{principal[1]};', 'admin')
    return contents, scripts, principal


def _history_acknowledgements(manifest: Evidence) -> str:
    configuration_ack = ''
    from cleanup_native_skills import SWITCH_POLICY, SWITCH_ACK, PENDING_POLICY
    from cleanup_trained_history import (
        PENDING_POLICY as PENDING_HISTORY_POLICY,
        PENDING_ACK,
    )
    if manifest.get('policy') == PENDING_HISTORY_POLICY:
        if manifest.get('pending_history_ack') != PENDING_ACK:
            fail('PENDING_HISTORY_ACK_INVALID',
                'Pending history acknowledgement differs')
        configuration_ack += f"SET @pending_history_ack='{PENDING_ACK}';\n"
    from cleanup_racial_skills import (
        POLICY as RACIAL_SKILL_POLICY,
        ACK as RACIAL_SKILL_ACK,
    )
    if manifest.get('policy') == RACIAL_SKILL_POLICY:
        if manifest.get('native_racial_ack') != RACIAL_SKILL_ACK:
            fail('RACIAL_SKILL_ACK_INVALID',
                'Racial-skill acknowledgement differs')
        configuration_ack += (
            f"SET @native_racial_skills_ack='{RACIAL_SKILL_ACK}'; SET "
            '@eligibility_tc_all_spells=0; SET '
            '@eligibility_ac_custom_spells=0;\n'
        )
    if manifest.get('policy') in (SWITCH_POLICY, PENDING_POLICY):
        if manifest.get('native_switch_ack') != SWITCH_ACK:
            fail('NATIVE_SWITCH_ACK_INVALID',
                'Known-switch skill acknowledgement differs from the '
                'reviewed candidate')
        configuration_ack += "SET @native_generic_switch_ack='KNOWN_SWITCH_SKILL_ONLY';\n"
    from cleanup_ordinary_history import (
        INACTIVE_DEFAULT_POLICY,
        TRAINING_POLICY,
        TRAINING_ACK,
        PENDING_DEFAULT_POLICY,
        PENDING_DEFAULT_ACK,
    )
    from cleanup_death_coil import (
        POLICY as DEATH_COIL_POLICY,
        PENDING_POLICY as PENDING_DEATH_COIL_POLICY,
        PENDING_ACK as PENDING_DEATH_COIL_ACK,
    )
    if manifest.get('policy') == PENDING_DEFAULT_POLICY:
        if manifest.get('pending_default_ack') != PENDING_DEFAULT_ACK:
            fail('PENDING_DEFAULT_ACK_INVALID',
                'Pending default acknowledgement differs')
        configuration_ack += f"SET @pending_default_ack='{PENDING_DEFAULT_ACK}';\n"
    if manifest.get('policy') == PENDING_DEATH_COIL_POLICY:
        if manifest.get('pending_death_coil_ack') != PENDING_DEATH_COIL_ACK:
            fail('PENDING_DEATH_COIL_ACK_INVALID',
                'Pending Death Coil acknowledgement differs')
        configuration_ack += f"SET @pending_death_coil_ack='{PENDING_DEATH_COIL_ACK}';\n"
    if (manifest.get('policy') in (INACTIVE_DEFAULT_POLICY,
        PENDING_DEFAULT_POLICY, DEATH_COIL_POLICY, PENDING_DEATH_COIL_POLICY,
        TRAINING_POLICY)):
        configuration_ack += 'SET @ordinary_history_all_spells=0;\n'
    if manifest.get('policy') == TRAINING_POLICY:
        if manifest.get('training_prerequisite_ack') != TRAINING_ACK:
            fail('ORDINARY_TRAINING_ACK_INVALID',
                'Training-prerequisite acknowledgement differs from '
                'reviewed policy')
        configuration_ack += (
            'SET '
            "@ordinary_training_ack='REVIEWED_TRAINING_PREREQUISITES_ONLY';\n"
        )
    if (manifest.get('policy') in (DEATH_COIL_POLICY,
        PENDING_DEATH_COIL_POLICY)):
        configuration_ack += 'SET @ordinary_history_native_base=47541;\n'
    return configuration_ack


def _ownership_acknowledgements(manifest: Evidence) -> str:
    configuration_ack = ''
    from cleanup_ownership import(POLICIES as OWNERSHIP_POLICIES,
        ACK as OWNERSHIP_ACK,
        FOREIGN_POLICY, FOREIGN_ACK, PREFIX_POLICY,
        PREFIX_ACK,
        AURA_ALIAS_POLICY, AURA_ALIAS_ACK,
        REKEY_POLICY, REKEY_ACK)
    if manifest.get('policy') in OWNERSHIP_POLICIES:
        if manifest.get('ownership_ack') != OWNERSHIP_ACK:
            fail('OWNERSHIP_ACK_INVALID',
                'Ownership policy acknowledgement differs from the '
                'reviewed candidate')
        configuration_ack += (
            "SET @talent_ownership_ack='SELECTED_TALENTS_AUTHORITATIVE';\n")
    from cleanup_ownership import (
        PENDING_POLICY as PENDING_OWNER_POLICY,
        PENDING_ACK as PENDING_OWNER_ACK,
        OVERLEVEL_POLICY,
        OVERLEVEL_ACK,
    )
    if manifest.get('policy') == OVERLEVEL_POLICY:
        if manifest.get('overlevel_ownership_ack') != OVERLEVEL_ACK:
            fail('OVERLEVEL_ACK_INVALID',
                'Overlevel ownership acknowledgement differs')
        configuration_ack += f"SET @overlevel_ownership_ack='{OVERLEVEL_ACK}';\n"
    if manifest.get('policy') == PENDING_OWNER_POLICY:
        if manifest.get('pending_ownership_ack') != PENDING_OWNER_ACK:
            fail('PENDING_OWNERSHIP_ACK_INVALID',
                'Pending ownership acknowledgement differs')
        configuration_ack += f"SET @pending_ownership_ack='{PENDING_OWNER_ACK}';\n"
    if manifest.get('policy') == FOREIGN_POLICY:
        if manifest.get('foreign_family_ack') != FOREIGN_ACK:
            fail('OWNERSHIP_FOREIGN_ACK_INVALID',
                'Foreign-family acknowledgement differs from the '
                'reviewed candidate')
        configuration_ack += (
            'SET '
            "@talent_foreign_family_ack='UNSELECTED_FOREIGN_FAMILIES_ONLY';\n"
        )
    if manifest.get('policy') == PREFIX_POLICY:
        if manifest.get('native_prefix_ack') != PREFIX_ACK:
            fail('OWNERSHIP_PREFIX_ACK_INVALID',
                'Native-prefix acknowledgement differs from the reviewed '
                'candidate')
        configuration_ack += (
            'SET '
            "@talent_native_prefix_ack='RETAIN_AUTHORIZED_HIGHER_ANCHORS';\n"
        )
    if manifest.get('policy') == REKEY_POLICY:
        if manifest.get('native_rekey_ack') != REKEY_ACK:
            fail('OWNERSHIP_REKEY_ACK_INVALID',
                'Already-known lower passive acknowledgement differs')
        configuration_ack += (
            'SET '
            "@talent_native_rekey_ack='ONLY_ALREADY_KNOWN_SELECTED_LOWER_PASSIVES';\n"
        )
    if manifest.get('policy') == AURA_ALIAS_POLICY:
        if manifest.get('aura_alias_ack') != AURA_ALIAS_ACK:
            fail('OWNERSHIP_ALIAS_ACK_INVALID',
                'Aura-alias acknowledgement differs from the reviewed '
                'candidate')
        configuration_ack += (
            'SET '
            "@talent_aura_alias_ack='UNSELECTED_REVIEWED_AURA_ALIASES_ONLY';\n"
        )
    return configuration_ack


def _eligibility_acknowledgements(manifest: Evidence) -> str:
    configuration_ack = ''
    from cleanup_eligibility import (
        POLICIES as ELIGIBILITY_POLICIES,
        ACK as ELIGIBILITY_ACK,
        ABSENT_TEACHER_POLICY,
        ABSENT_TEACHER_ACK,
        RACIAL_POLICY,
        RACIAL_ACK,
        SWIPE_POLICY,
        SWIPE_ACK,
        ACTION_POLICY,
        ACTION_ACK,
        CAST_SCRIPT_POLICY,
        CAST_SCRIPT_ACK,
    )
    if manifest.get('policy') in ELIGIBILITY_POLICIES:
        if manifest.get('eligibility_ack') != ELIGIBILITY_ACK:
            fail('ELIGIBILITY_ACK_INVALID',
                'Eligibility acknowledgement differs from the reviewed '
                'candidate')
        configuration_ack += (
            'SET '
            "@spell_eligibility_ack='RETIRE_VERIFIED_INELIGIBLE_SPELLS';\n"
        )
        configuration_ack += (
            'SET @eligibility_tc_all_spells=0; SET '
            '@eligibility_ac_custom_spells=0;\n'
        )
    if manifest.get('policy') == CAST_SCRIPT_POLICY:
        if manifest.get('cast_script_ack') != CAST_SCRIPT_ACK:
            fail('CAST_SCRIPT_ACK_INVALID',
                'Reviewed nonlearning callback acknowledgement differs')
        configuration_ack += f"SET @eligibility_cast_scripts_ack='{CAST_SCRIPT_ACK}';\n"
    if manifest.get('policy') == ACTION_POLICY:
        if manifest.get('foreign_action_ack') != ACTION_ACK:
            fail('FOREIGN_ACTION_ACK_INVALID',
                'Inactive foreign action acknowledgement differs')
        configuration_ack += f"SET @eligibility_foreign_action_ack='{ACTION_ACK}';\n"
    if manifest.get('policy') == SWIPE_POLICY:
        if manifest.get('swipe_ack') != SWIPE_ACK:
            fail('FOREIGN_SWIPE_ACK_INVALID',
                'Inactive foreign Swipe acknowledgement differs')
        configuration_ack += f"SET @eligibility_swipe_ack='{SWIPE_ACK}';\n"
    if manifest.get('policy') == RACIAL_POLICY:
        if manifest.get('racial_ack') != RACIAL_ACK:
            fail('RACIAL_ACK_INVALID',
                'Reviewed racial acknowledgement differs from the '
                'candidate')
        configuration_ack += f"SET @eligibility_racials_ack='{RACIAL_ACK}';\n"
    if manifest.get('policy') == ABSENT_TEACHER_POLICY:
        if manifest.get('absent_teacher_ack') != ABSENT_TEACHER_ACK:
            fail('ABSENT_TEACHER_ACK_INVALID',
                'Absent-teacher acknowledgement differs from the '
                'reviewed candidate')
        configuration_ack += (
            'SET '
            "@eligibility_absent_teachers_ack='VERIFIED_TEACHERS_ABSENT';\n"
        )
    return configuration_ack


def _specialization_acknowledgements(manifest: Evidence) -> str:
    configuration_ack = ''
    from cleanup_specializations import (
        POLICY as SPECIALIZATION_POLICY,
        ACK as SPECIALIZATION_ACK,
    )
    from cleanup_specializations import (
        INVALID_ITEMS_POLICY,
        PARENT_INVALID_ITEMS_POLICY,
    )
    if manifest.get('policy') in (SPECIALIZATION_POLICY, INVALID_ITEMS_POLICY):
        if manifest.get('specialization_ack') != SPECIALIZATION_ACK:
            fail('SPECIALIZATION_ACK_INVALID',
                'Specialization retirement acknowledgement differs')
        configuration_ack += (
            f"SET @specialization_retirement_ack='{SPECIALIZATION_ACK}';\n")
        configuration_ack += (
            'SET @eligibility_tc_all_spells=0; SET '
            '@eligibility_ac_custom_spells=0;\n'
        )
    from cleanup_specialization_parent import (
        POLICY as PARENT_POLICY,
        ACK as PARENT_ACK,
    )
    if manifest.get('policy') in (PARENT_POLICY, PARENT_INVALID_ITEMS_POLICY):
        if manifest.get('specialization_ack') != PARENT_ACK:
            fail('SPECIALIZATION_PARENT_ACK_INVALID',
                'Parent-specialization acknowledgement differs')
        configuration_ack += f"SET @specialization_retirement_ack='{PARENT_ACK}';\n"
        configuration_ack += (
            'SET @eligibility_tc_all_spells=0; SET '
            '@eligibility_ac_custom_spells=0;\n'
        )
    return configuration_ack


def _profession_acknowledgements(manifest: Evidence) -> str:
    configuration_ack = ''
    from cleanup_professions import (
        POLICY as PROFESSION_POLICY,
        ACK as PROFESSION_ACK,
        PENDING_POLICY as PENDING_PROFESSION_POLICY,
        PENDING_ACK as PENDING_PROFESSION_ACK,
    )
    if manifest.get('policy') == PENDING_PROFESSION_POLICY:
        if manifest.get('pending_profession_ack') != PENDING_PROFESSION_ACK:
            fail('PENDING_PROFESSION_ACK_INVALID',
                'Pending profession acknowledgement differs')
        configuration_ack += f"SET @pending_profession_ack='{PENDING_PROFESSION_ACK}';\n"
    if (manifest.get('policy') in (PROFESSION_POLICY,
        PENDING_PROFESSION_POLICY)):
        if manifest.get('profession_activation_ack') != PROFESSION_ACK:
            fail('PROFESSION_ACK_INVALID',
                'Profession activation acknowledgement differs')
        configuration_ack += f"SET @profession_activation_ack='{PROFESSION_ACK}';\n"
        configuration_ack += (
            'SET @eligibility_tc_all_spells=0; SET '
            '@eligibility_ac_custom_spells=0;\n'
        )
    from cleanup_skill_teaching import (
        POLICY as SKILL_TEACHING_POLICY,
        ACK as SKILL_TEACHING_ACK,
    )
    if manifest.get('policy') == SKILL_TEACHING_POLICY:
        if manifest.get('skill_teaching_ack') != SKILL_TEACHING_ACK:
            fail('SKILL_TEACHER_ACK_INVALID',
                'Skill-teaching acknowledgement differs')
        configuration_ack += f"SET @skill_teaching_ack='{SKILL_TEACHING_ACK}';\n"
        configuration_ack += (
            'SET @eligibility_tc_all_spells=0; SET '
            '@eligibility_ac_custom_spells=0;\n'
        )
    return configuration_ack


def _foreign_skill_acknowledgements(manifest: Evidence) -> str:
    configuration_ack = ''
    from cleanup_foreign_skills import (
        POLICIES as FOREIGN_SKILL_POLICIES,
        policy_ack as foreign_policy_ack,
    )
    if manifest.get('policy') in FOREIGN_SKILL_POLICIES:
        foreign_ack = foreign_policy_ack(manifest['policy'])
        if manifest.get('foreign_skill_ack') != foreign_ack:
            fail('FOREIGN_SKILL_ACK_INVALID',
                'Foreign skill-family acknowledgement differs')
        configuration_ack += (
            f"SET @foreign_skill_family_ack='{foreign_ack}'; SET "
            '@eligibility_tc_all_spells=0; SET '
            '@eligibility_ac_custom_spells=0;\n'
        )
    from cleanup_dual_spec_teacher import (
        POLICY as DUAL_TEACHER_POLICY,
        ACK as DUAL_TEACHER_ACK,
    )
    if manifest.get('policy') == DUAL_TEACHER_POLICY:
        if manifest.get('dual_teacher_ack') != DUAL_TEACHER_ACK:
            fail('DUAL_TEACHER_ACK_INVALID',
                'Dual-spec teacher acknowledgement differs')
        configuration_ack += (
            f"SET @spell_eligibility_ack='{DUAL_TEACHER_ACK}'; SET "
            '@eligibility_tc_all_spells=0; SET '
            '@eligibility_ac_custom_spells=0;\n'
        )
    return configuration_ack


def _coupled_repair_acknowledgements(manifest: Evidence) -> str:
    configuration_ack = ''
    from cleanup_shaman_dual_wield import (
        POLICY as SHAMAN_POLICY,
        ACK as SHAMAN_ACK,
    )
    from cleanup_shaman_offhand import (
        POLICY as OFFHAND_POLICY,
        ACK as OFFHAND_ACK,
    )
    from cleanup_obsolete_riding import (
        POLICY as RIDING_POLICY,
        POLICIES as RIDING_POLICIES,
        ACK as RIDING_ACK,
        INVALID_ITEMS_POLICY,
        INVALID_ITEMS_ACK,
        HORSE_POLICY,
        HORSE_ACK,
    )
    if manifest.get('policy') in RIDING_POLICIES:
        riding_ack = (HORSE_ACK if manifest['policy'] == HORSE_POLICY
            else INVALID_ITEMS_ACK if manifest.get('policy')
            == INVALID_ITEMS_POLICY else RIDING_ACK)
        if manifest.get('riding_ack') != riding_ack:
            fail('OBSOLETE_RIDING_ACK_INVALID',
                'Obsolete riding spell/skill acknowledgement differs')
        configuration_ack += f"SET @obsolete_riding_ack='{riding_ack}';\n"
        configuration_ack += (
            'SET @eligibility_tc_all_spells=0; SET '
            '@eligibility_ac_custom_spells=0;\n'
        )
    if manifest.get('policy') in (SHAMAN_POLICY, OFFHAND_POLICY):
        shaman_ack = (OFFHAND_ACK if manifest['policy'] == OFFHAND_POLICY
            else SHAMAN_ACK)
        if manifest.get('shaman_ack') != shaman_ack:
            fail('SHAMAN_ACK_INVALID',
                'Coupled Shaman acknowledgement differs')
        configuration_ack += f"SET @shaman_dual_wield_ack='{shaman_ack}';\n"
        configuration_ack += (
            'SET @eligibility_tc_all_spells=0; SET '
            '@eligibility_ac_custom_spells=0;\n'
        )
    return configuration_ack


def _direct_passive_acknowledgements(manifest: Evidence) -> str:
    configuration_ack = ''
    from cleanup_ownership import ACK as OWNERSHIP_ACK
    from cleanup_selected_passive import (
        POLICY as DIRECT_PASSIVE_POLICY,
        ACK as DIRECT_PASSIVE_ACK,
    )
    if manifest.get('policy') == DIRECT_PASSIVE_POLICY:
        if (manifest.get('direct_passive_ack') != DIRECT_PASSIVE_ACK
            or manifest.get('ownership_ack') != OWNERSHIP_ACK):
            fail('DIRECT_PASSIVE_ACK_INVALID',
                'Direct passive authority acknowledgement differs')
        configuration_ack += (
            'SET '
            "@direct_passive_ack='SELECTED_LOWER_DIRECT_PASSIVES_AUTHORITATIVE';\n"
        )
        configuration_ack += (
            "SET @talent_ownership_ack='SELECTED_TALENTS_AUTHORITATIVE';\n")
        configuration_ack += (
            'SET @eligibility_tc_all_spells=0; SET '
            '@eligibility_ac_custom_spells=0;\n'
        )
    return configuration_ack


def _legacy_acknowledgements(manifest: Evidence) -> str:
    configuration_ack = ''
    from cleanup_inactive_legacy import (
        POLICY as INACTIVE_LEGACY_POLICY,
        ACK as INACTIVE_LEGACY_ACK,
    )
    if manifest.get('policy') == INACTIVE_LEGACY_POLICY:
        if manifest.get('inactive_legacy_ack') != INACTIVE_LEGACY_ACK:
            fail('INACTIVE_LEGACY_ACK_INVALID',
                'Inactive legacy acknowledgement differs')
        configuration_ack += (
            'SET '
            "@inactive_legacy_ack='RETIRE_ONLY_INACTIVE_LEGACY_BLOODTHIRST';\n"
        )
        configuration_ack += (
            'SET @eligibility_tc_all_spells=0; SET '
            '@eligibility_ac_custom_spells=0;\n'
        )
    return configuration_ack


def _pet_acknowledgements(manifest: Evidence) -> str:
    configuration_ack = ''
    from cleanup_pet_teaching import (
        POLICIES as PET_TEACHING_POLICIES,
        ACK as PET_TEACHING_ACK,
        COWER_POLICY,
        COWER_ACK,
    )
    if manifest.get('policy') in PET_TEACHING_POLICIES:
        if manifest.get('pet_teaching_ack') != PET_TEACHING_ACK:
            fail('PET_TEACHING_ACK_INVALID',
                'Pet-teaching acknowledgement differs from the reviewed '
                'candidate')
        configuration_ack += "SET @pet_teaching_ack='RETIRE_VERIFIED_PET_TEACHERS';\n"
        configuration_ack += (
            'SET @pet_teaching_tc_all_spells=0; SET '
            '@pet_teaching_ac_custom_spells=0;\n'
        )
    if manifest.get('policy') == COWER_POLICY:
        if manifest.get('cower_ack') != COWER_ACK:
            fail('COWER_ACK_INVALID',
                'Cower acknowledgement differs from the reviewed '
                'candidate')
        configuration_ack += "SET @pet_teaching_cower_ack='REVIEWED_COWER_CHILD_ONLY';\n"
    return configuration_ack


def _configuration_acknowledgements(manifest: Evidence) -> str:
    return (
        _history_acknowledgements(manifest) +
        _ownership_acknowledgements(manifest) +
        _eligibility_acknowledgements(manifest) +
        _specialization_acknowledgements(manifest) +
        _profession_acknowledgements(manifest) +
        _foreign_skill_acknowledgements(manifest) +
        _coupled_repair_acknowledgements(manifest) +
        _direct_passive_acknowledgements(manifest) +
        _legacy_acknowledgements(manifest) +
        _pet_acknowledgements(manifest)
    )


def _execute_action_sql(
    settings: Settings,
    manifest: Evidence,
    query: str,
    principal: list[str],
) -> str:
    from cleanup_disabled_history import POLICIES
    from cleanup_native_skills import (
        POLICY as NATIVE_SKILLS_POLICY,
        GENERIC_POLICY,
    )
    from cleanup_ownership import REKEY_POLICY
    from cleanup_shaman_dual_wield import POLICY as SHAMAN_POLICY
    from cleanup_shaman_offhand import POLICY as OFFHAND_POLICY
    from cleanup_foreign_skills import POLICIES as FOREIGN_SKILL_POLICIES
    from cleanup_obsolete_riding import POLICIES as RIDING_POLICIES
    try:
        result = settings.sql(query, 'write', headers=True)
    except CleanupError as error:
        if (manifest.get('policy') == REKEY_POLICY and 'UPDATE command denied'
            in str(error)):
            error.hint = (
                'Passive rekey needs UPDATE(spell) on character_spell for '
                'apply and exact inverse restore. Source grants were not '
                'added automatically; see '
                'runbooks/talent-ownership-repair.md.')
        if manifest.get('policy') in POLICIES and manifest.get(
            'policy') != REKEY_POLICY and any(
                text in str(error) for text in ('DELETE command denied',
                    'INSERT command denied')):
            error.hint = (
                'This history policy needs DELETE on character_spell for '
                'apply and INSERT for exact restore. Have the preparation '
                'administrator grant only those source privileges to the '
                'configured writer, then retry; no source grants were added '
                'automatically.')
        if (manifest.get('policy') in (SHAMAN_POLICY, OFFHAND_POLICY,
            *FOREIGN_SKILL_POLICIES, *RIDING_POLICIES) and any(text in str(
                error) for text in ('DELETE command denied',
                    'INSERT command denied'))):
            error.hint = (
                'Coupled repair requires DELETE/INSERT on character_spell '
                'AND character_skills for apply/exact restore. No source '
                'grants were added automatically.')
        if manifest.get('policy') == 'tc-active-build-native-reset-v1' and any(
            text in str(error) for text in ('DELETE command denied',
                'INSERT command denied', 'UPDATE command denied')):
            error.hint = (
                'This reviewed reset needs DELETE/INSERT on character_spell '
                'and UPDATE(at_login) on characters. Have the preparation '
                'administrator grant only those source privileges to the '
                'configured writer, then retry; no source grants were added '
                'automatically.')
        if (manifest.get('policy') == 'tc-skill-clamp-stored-cap-v1'
            and 'UPDATE command denied' in str(error)):
            error.hint = (
                'The skill policy needs the writer column privilege. An '
                'administrator can run: GRANT UPDATE (`value`) ON `'
                f"{settings.schemas['characters']}`.`character_skills` TO "
                f'{principal[0]}@{principal[1]}; Then retry this batch. '
                'Source privileges were not added automatically.')
        if (manifest.get('policy') == NATIVE_SKILLS_POLICY and any(text in str(
            error) for text in ('INSERT command denied',
                'DELETE command denied'))):
            error.hint = (
                'Native skill repair needs INSERT on character_skills for '
                'apply and DELETE for exact restore. Have the preparation '
                'administrator grant only those privileges to the configured '
                'writer; no source grants were added automatically.')
        if (manifest.get('policy') == GENERIC_POLICY and any(text in str(
            error) for text in ('INSERT command denied',
                'DELETE command denied', 'UPDATE command denied'))):
            error.hint = (
                'Generic v2 needs UPDATE(value,max) for normalization, plus '
                'INSERT/DELETE if the package includes absent rows. Source '
                'grants were not added automatically; see '
                'runbooks/native-skill-repair.md.')
        raise
    return result


def _record_action_result(
    settings: Settings,
    work: Workspace,
    manifest: Evidence,
    contents: dict[str, bytes],
    result: str,
) -> None:
    from cleanup_death_coil import (
        POLICY as DEATH_COIL_POLICY,
        PENDING_POLICY as PENDING_DEATH_COIL_POLICY,
    )
    (work.operation / 'result.tsv').write_text(result)
    status = settings.sql(contents['04-status.sql'].decode(), 'write',
        headers=True)
    (work.operation / 'status.tsv').write_text(status)
    print(result.strip() + '\nStatus: ' + str(work.operation / 'status.tsv'))
    if (manifest.get('policy') in (DEATH_COIL_POLICY,
        PENDING_DEATH_COIL_POLICY)):
        print('Death Coil rank 1 is native skill-derived state on load; no '
            'spell row was inserted. Native gameplay and existing skill '
            'normalization still require acceptance.')
