"""Captured inspection and metadata consistency checks."""
from __future__ import annotations

import argparse
from typing import TYPE_CHECKING

from cleanup_active_reset import TABLES
import cleanup_death_coil as death_coil
from cleanup_disabled_history import (
    POLICY,
    SCRIPT_POLICY,
    enabled_ids_query,
    inspection,
    read_world,
)
import cleanup_eligibility as eligibility
from cleanup_files import ROOT, fail, sha, verify
import cleanup_foreign_skills as foreign_skills
from cleanup_history_models import (
    HistoryEvidence,
    HistoryOptions,
    HistoryPolicy,
    HistorySelection,
    HistorySnapshot,
)
import cleanup_obsolete_riding as riding
import cleanup_ordinary_history as ordinary_history
import cleanup_ownership as ownership
import cleanup_pet_teaching as pet_teaching
from cleanup_plans import metadata, snapshot
import cleanup_professions as professions
import cleanup_selected_rank_history as selected_history
import cleanup_shaman_dual_wield as shaman
import cleanup_shaman_offhand as offhand_repair
import cleanup_skill_teaching as skill_teaching
import cleanup_specializations as specializations
import cleanup_talent_relations as relations
import cleanup_trained_history as trained_history

if TYPE_CHECKING:
    from cleanup_config import Settings
    from cleanup_workspace import Workspace


def capture_history_evidence(
    settings: Settings,
    work: Workspace,
    args: argparse.Namespace,
    options: HistoryOptions,
) -> HistoryEvidence:
    audit = None
    capture_report = None
    captured_layout = None
    context = None
    path = None
    report = None
    rows = None
    inspection_id = args.inspection
    if getattr(args, 'audit', None):
        from cleanup_spell_history import inspect_history
        inspection_id = inspect_history(settings, work, args).name
    if options.trained_mode:
        (path, report, state, context, audit, captured_world, captured_layout,
            capture_report) = trained_history.inspection(settings, work,
                args.migration_inspection)
        rows = []
    else:
        path, report, state, rows, audit = inspection(settings, work,
            inspection_id)
    if (options.parent_mode and {r[1] for r in captured_layout['columns'] if r[
        0] == 'character_spell'} != {'guid', 'spell', 'active', 'disabled'}):
        fail('UNSUPPORTED_PARENT_COLUMNS',
            'Parent-specialization repair requires stock character_spell '
            'columns; custom spell-specific fields need separate review')
    if (options.rekey_mode and {r[1] for r in captured_layout['columns'] if r[
        0] == 'character_spell'} != {'guid', 'spell', 'active', 'disabled'}):
        fail('UNSUPPORTED_REKEY_COLUMNS',
            'Passive rekey requires stock character_spell columns; '
            'custom spell-specific fields require separate review')
    inspection_sha = sha(path / 'SHA256SUMS')
    print('Reviewing effective TC world/DBC learning routes (read-only)',
        flush=True)
    effective, world = read_world(settings, exact_numeric=options.exact_mode)
    # Older sealed inspections retain their historical numeric digest. The
    # full typed rows/layout and asset hashes still have to match exactly;
    # new eligibility packets then use the stronger digest at every phase.
    same_world = (all(world[k] == captured_world[k] for k in ('layout',
        'rows')) if options.exact_mode
        else world
        == captured_world) if options.trained_mode else True
    if (options.trained_mode and (not same_world or effective.hashes
        != capture_report['dbc_sha256'])):
        fail('HISTORY_METADATA_DRIFT',
            'Effective TC metadata differs from the captured migration '
            'context')
    state['enabled_ids'] = (snapshot(settings, [('ids', enabled_ids_query(
        settings.schemas['characters']))])['ids'])
    return HistoryEvidence(
        audit=audit,
        capture_report=capture_report,
        captured_layout=captured_layout,
        context=context,
        effective=effective,
        inspection_sha=inspection_sha,
        path=path,
        report=report,
        rows=rows,
        state=state,
        world=world,
    )


def resolve_history_policy(
    settings: Settings,
    args: argparse.Namespace,
    options: HistoryOptions,
) -> HistoryPolicy:
    target_effective = None
    target_world = None
    include_routes = getattr(args, 'include_reviewed_routes', False)
    include_relations = (getattr(args, 'include_inert_relations', False)
        or include_routes or options.trained_mode)
    include_scripts = (getattr(args, 'include_reviewed_scripts', False)
        or include_relations or options.selected_mode)
    policy = (trained_history.POLICY if options.trained_mode
        else selected_history.POLICY if options.selected_mode
        else relations.ROUTE_POLICY if include_routes else relations.POLICY
        if include_relations else SCRIPT_POLICY if include_scripts else POLICY)
    if options.child_mode:
        policy = (trained_history.PENDING_POLICY if options.pending_history
            else trained_history.CHILD_POLICY)
    if options.ordinary_mode:
        policy = (ordinary_history.PENDING_DEFAULT_POLICY
            if options.pending_defaults else ordinary_history.TRAINING_POLICY
            if options.training_prerequisites else death_coil.PENDING_POLICY
            if options.pending_death_coil else death_coil.POLICY
            if options.native_death_coil else
            ordinary_history.INACTIVE_DEFAULT_POLICY
            if options.inactive_defaults else ordinary_history.POLICY)
    if options.ownership_mode:
        policy = (ownership.OVERLEVEL_POLICY if options.overlevel_unselected
            else ownership.PENDING_POLICY if options.pending_ownership
            else ownership.REKEY_POLICY if options.rekey_mode
            else ownership.AURA_ALIAS_POLICY if options.alias_mode
            else ownership.PREFIX_POLICY if options.prefix_mode
            else ownership.FOREIGN_POLICY if options.foreign_mode
            else ownership.POLICY)
    if options.two_world_mode:
        policy = (foreign_skills.native_actions.POLICIES[
            options.native_action][0] if options.native_action
            else foreign_skills.TRAINING_POLICY if options.foreign_training
            else professions.PENDING_POLICY if options.pending_professions
            else specializations.PARENT_INVALID_ITEMS_POLICY
            if options.parent_mode and options.invalid_equipment
            else specializations.INVALID_ITEMS_POLICY
            if options.invalid_equipment else riding.HORSE_POLICY
            if options.riding_horse else riding.INVALID_ITEMS_POLICY
            if options.riding_invalid_items else pet_teaching.COWER_POLICY
            if options.reviewed_cower else
            eligibility.ABSENT_TEACHER_POLICY if options.absent_teachers
            else
            eligibility.CAST_SCRIPT_POLICY if options.cast_script_mode
            else eligibility.RACIAL_POLICY if options.racial_mode
            else eligibility.SWIPE_POLICY if options.swipe_mode
            else eligibility.ACTION_POLICY if options.action_mode
            else options.native_selector.POLICY)
        print(
            'Capturing effective AC world/DBC eligibility inputs '
            '(read-only)',
            flush=True)
        target_effective, target_world = eligibility.read_target(settings)
    return HistoryPolicy(
        include_relations=include_relations,
        include_routes=include_routes,
        include_scripts=include_scripts,
        policy=policy,
        target_effective=target_effective,
        target_world=target_world,
    )


def verify_history_evidence(
    settings: Settings,
    options: HistoryOptions,
    evidence: HistoryEvidence,
    selection: HistorySelection,
    snapshot: HistorySnapshot,
    policy: HistoryPolicy,
) -> None:
    if options.training_prerequisites and (sha(
        ROOT / 'lib/cleanup_ordinary_history.py') != options.ordinary_reader
        or sha(ROOT / 'lib/cleanup_eligibility.py')
        != options.world_guard_reader
        or sha(ROOT / 'lib/cleanup_active_reset.py')
        != options.numeric_reader):
        fail('ORDINARY_TRAINING_POLICY_DRIFT',
            'Training policy or numeric/world guards changed during '
            'planning')
    if (options.foreign_mode or options.prefix_mode or options.alias_mode
        or options.rekey_mode) and (sha(ROOT / 'lib/cleanup_eligibility.py')
            != options.world_guard_reader
            or sha(ROOT / 'lib/cleanup_active_reset.py')
            != options.numeric_reader):
        fail('OWNERSHIP_REKEY_POLICY_DRIFT' if options.rekey_mode
            else 'OWNERSHIP_ALIAS_POLICY_DRIFT' if options.alias_mode
            else 'OWNERSHIP_PREFIX_POLICY_DRIFT' if options.prefix_mode
            else 'OWNERSHIP_FOREIGN_POLICY_DRIFT',
            'Exact numeric/world guards changed during planning')
    final_effective, final_world = read_world(settings,
        exact_numeric=options.exact_mode)
    if (metadata(settings, TABLES) != snapshot.meta or final_world
        != evidence.world or final_effective.hashes
        != evidence.effective.hashes):
        fail('HISTORY_METADATA_DRIFT',
            'Source schema/world metadata changed while planning')
    if (options.ownership_mode and sha(ROOT / 'lib/cleanup_ownership.py')
        != options.ownership_reader):
        fail('OWNERSHIP_POLICY_DRIFT',
            'Ownership selector changed while planning')
    if options.two_world_mode:
        final_target, final_target_world = eligibility.read_target(settings)
        if (final_target_world != policy.target_world or final_target.hashes
            != policy.target_effective.hashes
            or sha(ROOT / 'lib/cleanup_eligibility.py')
            != options.eligibility_reader
            or options.action_mode and sha(eligibility.ACTION_CATALOG)
            != options.action_catalog
            or options.swipe_mode and sha(eligibility.SWIPE_CATALOG)
            != options.swipe_catalog
            or options.racial_mode and sha(eligibility.RACIAL_CATALOG)
            != options.racial_catalog
            or options.pet_mode and sha(
                ROOT / 'lib/cleanup_pet_teaching.py') != options.pet_reader
            or options.legacy_mode and sha(
                ROOT / 'lib/cleanup_inactive_legacy.py')
            != options.legacy_reader
            or options.parent_mode and sha(
                ROOT / 'lib/cleanup_specialization_parent.py')
            != options.parent_reader
            or options.specialization_mode and (sha(
                ROOT / 'lib/cleanup_specializations.py')
                != options.specialization_reader
                or sha(specializations.CATALOG)
                != options.specialization_catalog
                or sha(
                    ROOT / 'lib/cleanup_professions.py')
                != options.profession_reader
                or sha(professions.CATALOG)
                != options.profession_catalog
                or specializations.native_sources(
                    settings.paths,
                    native_invalid_items=options.invalid_equipment)
                != selection.specialization_native_sources
                or specializations.read_equipment(
                    settings, [r[0] for r in evidence.context['characters']],
                    native_invalid_items=options.invalid_equipment)
                != selection.equipment)
            or options.profession_mode and (sha(
                ROOT / 'lib/cleanup_professions.py')
                != options.profession_reader
                or sha(professions.CATALOG)
                != options.profession_catalog)
            or options.skill_teaching_mode and (sha(
                ROOT / 'lib/cleanup_skill_teaching.py')
                != options.teaching_reader
                or sha(skill_teaching.CATALOG)
                != options.teaching_catalog)
            or options.shaman_mode and (sha(
                ROOT / 'lib/cleanup_shaman_dual_wield.py')
                != options.shaman_reader
                or shaman.inventory(settings,
                    evidence.context) != (selection.inventory_meta,
                        selection.offhand_rows)
                or options.offhand_mode and (
                    offhand_repair.read(settings,
                        offhand_repair.candidate_guids(
                            evidence.context)) != selection.offhand_capture
                    or offhand_repair.native_sources(settings.paths)
                    != selection.offhand_sources)
                or shaman.defaults(settings)
                != selection.default_skills)
            or options.foreign_skill_mode and (
                foreign_skills.reader_hashes() != selection.foreign_readers
                or foreign_skills.native_sources(settings.paths)
                != selection.foreign_sources or riding.read_items(settings,
                    selection.foreign_scope, native_invalid_items=True)
                != selection.foreign_items or offhand_repair.read(settings,
                    selection.foreign_scope, equipment_slots=range(19))
                != selection.foreign_equipment or shaman.defaults(settings)
                != selection.foreign_defaults)
            or options.riding_mode and (sha(
                ROOT / 'lib/cleanup_obsolete_riding.py')
                != options.riding_reader
                or sha(options.riding_catalog_file)
                != options.riding_catalog
                or options.riding_invalid_items and sha(
                    riding.ITEM_CATALOG) != options.riding_item_catalog
                or riding.native_sources(settings.paths,
                    native_invalid_items=options.riding_invalid_items,
                    legacy_horse=options.riding_horse)
                != selection.riding_sources
                or riding.read_items(settings,
                    selection.riding_scope,
                    native_invalid_items=options.riding_invalid_items)
                != selection.riding_items
                or riding.defaults(settings)
                != selection.riding_defaults)
            or options.direct_mode and (sha(
                ROOT / 'lib/cleanup_selected_passive.py')
                != options.direct_reader
                or sha(ROOT / 'lib/cleanup_ownership.py')
                != options.direct_ownership_reader)):
            fail('ELIGIBILITY_TARGET_DRIFT',
                'Eligibility reader or AC inputs changed during planning')
    verify(evidence.path)
    if sha(evidence.path / 'SHA256SUMS') != evidence.inspection_sha:
        fail('HISTORY_INSPECTION_INVALID',
            'Retained inspection changed during planning')
    if any(sha(settings.paths['tc_dbc'] / name) != checksum for name, checksum
        in evidence.audit['dbc_sha256'].items()):
        fail('DBC_DRIFT', 'DBC files changed while planning')
