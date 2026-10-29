"""Explicit capture, selection, fingerprint and publication stages for
history repair.
"""
from __future__ import annotations

import argparse
from typing import TYPE_CHECKING

import cleanup_death_coil as death_coil
import cleanup_dual_spec_teacher as dual_teacher
import cleanup_eligibility as eligibility
from cleanup_files import ROOT, fail, sha
import cleanup_foreign_skills as foreign_skills
from cleanup_history_models import HistoryOptions
import cleanup_inactive_legacy as inactive_legacy
import cleanup_obsolete_riding as riding
import cleanup_ordinary_history as ordinary_history
import cleanup_pet_teaching as pet_teaching
import cleanup_professions as professions
import cleanup_selected_passive as direct_passive
import cleanup_shaman_dual_wield as shaman
import cleanup_shaman_offhand as offhand_repair
import cleanup_skill_teaching as skill_teaching
import cleanup_specialization_parent as specialization_parent
import cleanup_specializations as specializations

if TYPE_CHECKING:
    from cleanup_config import Settings


def resolve_history_options(
    settings: Settings,
    args: argparse.Namespace,
) -> HistoryOptions:
    dual_sources = None
    pending_native_sources = None
    foreign_skill_mode = getattr(args, 'foreign_skill_families', False)
    foreign_training = (foreign_skill_mode and getattr(args,
        'absent_training_actions', False))
    native_action = getattr(args, 'native_action', None)
    foreign_inventory_mode = native_action == 'forbidden-pairs-stowing'
    riding_mode = getattr(args, 'obsolete_riding', False)
    riding_horse = riding_mode and getattr(args, 'horse', False)
    riding_invalid_items = (riding_mode and (getattr(args,
        'native_invalid_items', False) or riding_horse))
    riding_catalog_file = (riding.HORSE_CATALOG if riding_horse
        else riding.CATALOG)
    riding_reader = (sha(ROOT / 'lib/cleanup_obsolete_riding.py')
        if riding_mode else None)
    riding_catalog = sha(riding_catalog_file) if riding_mode else None
    riding_item_catalog = (sha(riding.ITEM_CATALOG) if riding_invalid_items
        else None)
    specialization_mode = getattr(args, 'specialization_retirement', False)
    parent_mode = (specialization_mode and getattr(args,
        'parent_specialization', False))
    invalid_equipment = (specialization_mode and getattr(args,
        'native_invalid_items', False))
    parent_reader = (sha(ROOT / 'lib/cleanup_specialization_parent.py')
        if parent_mode else None)
    specialization_reader = (sha(ROOT / 'lib/cleanup_specializations.py')
        if specialization_mode else None)
    specialization_catalog = (sha(specializations.CATALOG)
        if specialization_mode else None)
    profession_mode = getattr(args, 'profession_activation', False)
    pending_professions = (profession_mode and getattr(args, 'pending_reset',
        False))
    if pending_professions:
        from cleanup_native_skills import pending_sources
        pending_native_sources = pending_sources(settings.paths)
    profession_reader = (sha(ROOT / 'lib/cleanup_professions.py')
        if profession_mode or specialization_mode else None)
    profession_catalog = (sha(professions.CATALOG) if profession_mode
        or specialization_mode else None)
    skill_teaching_mode = getattr(args, 'skill_teaching', False)
    teaching_reader = (sha(ROOT / 'lib/cleanup_skill_teaching.py')
        if skill_teaching_mode else None)
    teaching_catalog = (sha(skill_teaching.CATALOG) if skill_teaching_mode
        else None)
    dual_mode = getattr(args, 'dual_spec_teacher', False)
    if dual_mode:
        from cleanup_native_skills import pending_sources
        dual_sources = pending_sources(settings.paths)
    offhand_mode = getattr(args, 'reconcile_shaman_offhand', False)
    shaman_mode = (getattr(args, 'unselected_shaman_dual_wield', False)
        or offhand_mode)
    shaman_reader = (sha(ROOT / 'lib/cleanup_shaman_dual_wield.py')
        if shaman_mode else None)
    direct_mode = getattr(args, 'selected_direct_passives', False)
    direct_reader = (sha(ROOT / 'lib/cleanup_selected_passive.py')
        if direct_mode else None)
    direct_ownership_reader = (sha(ROOT / 'lib/cleanup_ownership.py')
        if direct_mode else None)
    pet_mode = getattr(args, 'pet_teaching', False)
    legacy_mode = getattr(args, 'inactive_legacy', False)
    two_world_mode = (getattr(args, 'spell_eligibility', False) or pet_mode
        or legacy_mode or direct_mode or shaman_mode or dual_mode
        or foreign_skill_mode or skill_teaching_mode or profession_mode
        or specialization_mode or riding_mode)
    legacy_reader = (sha(ROOT / 'lib/cleanup_inactive_legacy.py')
        if legacy_mode else None)
    pet_reader = (sha(ROOT / 'lib/cleanup_pet_teaching.py') if pet_mode
        else None)
    reviewed_cower = pet_mode and getattr(args, 'reviewed_cower', False)
    cast_script_mode = (getattr(args, 'spell_eligibility', False) and getattr(
        args, 'reviewed_cast_scripts', False))
    absent_teachers = (getattr(args, 'spell_eligibility', False) and getattr(
        args, 'absent_teachers', False))
    action_mode = (getattr(args, 'spell_eligibility', False) and getattr(args,
        'inactive_foreign_actions', False))
    action_catalog = sha(eligibility.ACTION_CATALOG) if action_mode else None
    swipe_mode = (getattr(args, 'spell_eligibility', False) and getattr(args,
        'inactive_foreign_swipes', False))
    swipe_catalog = sha(eligibility.SWIPE_CATALOG) if swipe_mode else None
    racial_mode = (getattr(args, 'spell_eligibility', False) and getattr(args,
        'reviewed_racials', False))
    racial_catalog = sha(eligibility.RACIAL_CATALOG) if racial_mode else None
    cower_proof = (pet_teaching.cower_sources(settings.paths)
        if reviewed_cower else None)
    native_selector = (foreign_skills if foreign_skill_mode else dual_teacher
        if dual_mode else riding if riding_mode else specialization_parent
        if parent_mode else specializations if specialization_mode
        else professions if profession_mode else skill_teaching
        if skill_teaching_mode else offhand_repair if offhand_mode else shaman
        if shaman_mode else direct_passive if direct_mode else inactive_legacy
        if legacy_mode else pet_teaching if pet_mode else eligibility)
    eligibility_reader = (sha(ROOT / 'lib/cleanup_eligibility.py')
        if two_world_mode else None)
    ownership_mode = (getattr(args, 'talent_ownership', False) and not (
        direct_mode or shaman_mode))
    ownership_reader = (sha(ROOT / 'lib/cleanup_ownership.py')
        if ownership_mode else None)
    overlevel_unselected = (ownership_mode and getattr(args,
        'unselected_overlevel_talents', False))
    pending_ownership = (ownership_mode and getattr(args,
        'pending_reset_ownership', False))
    if pending_ownership:
        from cleanup_native_skills import pending_sources
        pending_native_sources = pending_sources(settings.paths)
    foreign_mode = (ownership_mode and getattr(args, 'foreign_class_families',
        False))
    prefix_mode = (ownership_mode and getattr(args, 'native_passive_prefixes',
        False))
    alias_mode = (ownership_mode and getattr(args, 'reviewed_aura_aliases',
        False))
    rekey_mode = (ownership_mode and getattr(args, 'native_passive_rekey',
        False))
    if shaman_mode and not getattr(args, 'migration_inspection', None):
        fail('SHAMAN_INSPECTION_REQUIRED',
            'Coupled Shaman repair requires --migration-inspection')
    if (direct_mode and any(getattr(args, key, False) for key in (
        'foreign_class_families', 'native_passive_prefixes',
        'reviewed_aura_aliases', 'native_passive_rekey'))):
        fail('HISTORY_POLICY_CONFLICT',
            'Direct passive authority is a separate ownership policy')
    if sum((prefix_mode, foreign_mode, alias_mode, rekey_mode)) > 1:
        fail('HISTORY_POLICY_CONFLICT',
            'Ownership extensions are separate policies')
    trained_mode = bool(getattr(args, 'migration_inspection', None))
    pending_history = getattr(args, 'pending_reset_history', False)
    child_mode = (getattr(args, 'orphaned_talent_children', False)
        or pending_history)
    if pending_history and getattr(args, 'orphaned_talent_children', False):
        fail('HISTORY_POLICY_CONFLICT',
            'Choose one whole-family history policy')
    if pending_history:
        from cleanup_native_skills import pending_sources
        pending_native_sources = pending_sources(settings.paths)
    ordinary_mode = getattr(args, 'ordinary_spell_history', False)
    pending_defaults = getattr(args, 'pending_inactive_defaults', False)
    if pending_defaults:
        from cleanup_native_skills import pending_sources
        pending_native_sources = pending_sources(settings.paths)
    inactive_defaults = (getattr(args, 'inactive_custom_defaults', False)
        or pending_defaults)
    pending_death_coil = getattr(args, 'pending_native_death_coil', False)
    native_death_coil = (getattr(args, 'native_death_coil', False)
        or pending_death_coil)
    if pending_death_coil:
        from cleanup_native_skills import pending_sources
        pending_native_sources = pending_sources(settings.paths)
    training_prerequisites = getattr(args, 'training_prerequisites', False)
    strong_history_mode = (training_prerequisites or foreign_mode
        or prefix_mode or alias_mode or rekey_mode or pending_ownership
        or overlevel_unselected or pending_history or pending_death_coil
        or pending_defaults)
    exact_mode = two_world_mode or strong_history_mode
    ordinary_reader = (sha(ROOT / 'lib/cleanup_ordinary_history.py')
        if training_prerequisites else None)
    world_guard_reader = (sha(ROOT / 'lib/cleanup_eligibility.py')
        if strong_history_mode else None)
    numeric_reader = (sha(ROOT / 'lib/cleanup_active_reset.py')
        if strong_history_mode else None)
    if (training_prerequisites and (inactive_defaults or native_death_coil
        or not ordinary_mode)):
        fail('HISTORY_POLICY_CONFLICT',
            '--training-prerequisites is a separate ordinary-history '
            'policy')
    if native_death_coil and (inactive_defaults or not ordinary_mode):
        fail('HISTORY_POLICY_CONFLICT',
            '--native-death-coil is a separate ordinary-history policy')
    config_contract = (ordinary_history.configuration_contract(settings,
        training_prerequisites=True) if training_prerequisites else
        eligibility.configuration_contract(settings)
        if two_world_mode else
        death_coil.configuration_contract(settings)
        if native_death_coil else
        ordinary_history.configuration_contract(settings)
        if inactive_defaults else None)
    preview = getattr(args, 'preview', False)
    if child_mode and not trained_mode:
        fail('HISTORY_POLICY_CONFLICT',
            '--orphaned-talent-children requires --migration-inspection')
    if ordinary_mode and not trained_mode:
        fail('HISTORY_POLICY_CONFLICT',
            'Ordinary spell history requires --migration-inspection')
    if (preview and not (child_mode or ordinary_mode or ownership_mode
        or two_world_mode)):
        fail('HISTORY_POLICY_CONFLICT',
            '--preview requires the explicit talent-child or '
            'ordinary-history policy')
    selected_mode = getattr(args, 'selected_rank_history', False)
    if (trained_mode and any(getattr(args, field, False) for field in (
        'include_reviewed_scripts', 'include_inert_relations',
        'include_reviewed_routes', 'selected_rank_history'))):
        fail('HISTORY_POLICY_CONFLICT',
            '--migration-inspection cannot be combined with other '
            'direct-history modes')
    if (selected_mode and any(getattr(args, field, False) for field in (
        'include_reviewed_scripts', 'include_inert_relations',
        'include_reviewed_routes'))):
        fail('HISTORY_POLICY_CONFLICT',
            '--selected-rank-history cannot be combined with another '
            'history mode')
    return HistoryOptions(
        absent_teachers=absent_teachers,
        action_catalog=action_catalog,
        action_mode=action_mode,
        alias_mode=alias_mode,
        cast_script_mode=cast_script_mode,
        child_mode=child_mode,
        config_contract=config_contract,
        cower_proof=cower_proof,
        direct_mode=direct_mode,
        direct_ownership_reader=direct_ownership_reader,
        direct_reader=direct_reader,
        dual_mode=dual_mode,
        dual_sources=dual_sources,
        eligibility_reader=eligibility_reader,
        exact_mode=exact_mode,
        foreign_inventory_mode=foreign_inventory_mode,
        foreign_mode=foreign_mode,
        foreign_skill_mode=foreign_skill_mode,
        foreign_training=foreign_training,
        inactive_defaults=inactive_defaults,
        invalid_equipment=invalid_equipment,
        legacy_mode=legacy_mode,
        legacy_reader=legacy_reader,
        native_action=native_action,
        native_death_coil=native_death_coil,
        native_selector=native_selector,
        numeric_reader=numeric_reader,
        offhand_mode=offhand_mode,
        ordinary_mode=ordinary_mode,
        ordinary_reader=ordinary_reader,
        overlevel_unselected=overlevel_unselected,
        ownership_mode=ownership_mode,
        ownership_reader=ownership_reader,
        parent_mode=parent_mode,
        parent_reader=parent_reader,
        pending_death_coil=pending_death_coil,
        pending_defaults=pending_defaults,
        pending_history=pending_history,
        pending_native_sources=pending_native_sources,
        pending_ownership=pending_ownership,
        pending_professions=pending_professions,
        pet_mode=pet_mode,
        pet_reader=pet_reader,
        prefix_mode=prefix_mode,
        preview=preview,
        profession_catalog=profession_catalog,
        profession_mode=profession_mode,
        profession_reader=profession_reader,
        racial_catalog=racial_catalog,
        racial_mode=racial_mode,
        rekey_mode=rekey_mode,
        reviewed_cower=reviewed_cower,
        riding_catalog=riding_catalog,
        riding_catalog_file=riding_catalog_file,
        riding_horse=riding_horse,
        riding_invalid_items=riding_invalid_items,
        riding_item_catalog=riding_item_catalog,
        riding_mode=riding_mode,
        riding_reader=riding_reader,
        selected_mode=selected_mode,
        shaman_mode=shaman_mode,
        shaman_reader=shaman_reader,
        skill_teaching_mode=skill_teaching_mode,
        specialization_catalog=specialization_catalog,
        specialization_mode=specialization_mode,
        specialization_reader=specialization_reader,
        strong_history_mode=strong_history_mode,
        swipe_catalog=swipe_catalog,
        swipe_mode=swipe_mode,
        teaching_catalog=teaching_catalog,
        teaching_reader=teaching_reader,
        trained_mode=trained_mode,
        training_prerequisites=training_prerequisites,
        two_world_mode=two_world_mode,
        world_guard_reader=world_guard_reader,
    )
