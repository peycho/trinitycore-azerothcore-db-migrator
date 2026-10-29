"""Reviewed batch identity and policy-specific manifest evidence."""
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any
import uuid

import cleanup_dual_spec_teacher as dual_teacher
import cleanup_eligibility as eligibility
from cleanup_files import PROFILE, ROOT, sha
import cleanup_foreign_skills as foreign_skills
from cleanup_history_models import (
    HistoryBatch,
    HistoryEvidence,
    HistoryOptions,
    HistoryPolicy,
    HistorySelection,
    HistorySnapshot,
)
import cleanup_inactive_legacy as inactive_legacy
import cleanup_obsolete_riding as riding
import cleanup_ordinary_history as ordinary_history
import cleanup_ownership as ownership
import cleanup_pet_teaching as pet_teaching
from cleanup_plans import sha_json
import cleanup_professions as professions
import cleanup_selected_passive as direct_passive
import cleanup_selected_rank_history as selected_history
import cleanup_skill_teaching as skill_teaching
import cleanup_specialization_parent as specialization_parent
import cleanup_specializations as specializations


def build_history_batch(
    output: Path,
    options: HistoryOptions,
    snapshot: HistorySnapshot,
    selection: HistorySelection,
    evidence: HistoryEvidence,
    policy: HistoryPolicy,
) -> HistoryBatch:
    template = ROOT / ('tools/foreign-skill-stowing.sql.in'
        if options.foreign_inventory_mode
        else 'tools/foreign-skill-repair.sql.in' if options.foreign_skill_mode
        else 'tools/dual-spec-teacher-repair.sql.in' if options.dual_mode
        else 'tools/specialization-parent-repair.sql.in'
        if options.parent_mode else 'tools/obsolete-horse-repair.sql.in'
        if options.riding_horse else 'tools/obsolete-riding-repair.sql.in'
        if options.riding_mode
        else 'tools/profession-activation-repair.sql.in'
        if options.profession_mode else 'tools/shaman-offhand-repair.sql.in'
        if options.offhand_mode else 'tools/shaman-dual-wield-repair.sql.in'
        if options.shaman_mode else 'tools/inactive-legacy-repair.sql.in'
        if options.legacy_mode else 'tools/pet-teaching-repair.sql.in'
        if options.pet_mode else 'tools/spell-eligibility-repair.sql.in'
        if options.two_world_mode else
        'tools/passive-rekey-repair.sql.in' if options.rekey_mode
        else 'tools/talent-ownership-repair.sql.in' if options.ownership_mode
        else 'tools/disabled-talent-history.sql.in')
    batch_inputs = {'policy': policy.policy, 'inspection': sha(
        evidence.path / 'SHA256SUMS'), 'snapshot': snapshot.cells,
        'after': snapshot.after,
        'selection': selection.selected, 'world': evidence.world,
        'meta': snapshot.meta, 'template': sha(template), 'id': output.name}
    if options.training_prerequisites:
        batch_inputs.update(
            training_prerequisite_proofs=selection.training_proofs,
            ordinary_reader_sha256=options.ordinary_reader,
            numeric_reader_sha256=options.numeric_reader,
            world_guard_reader_sha256=options.world_guard_reader)
    if options.strong_history_mode:
        batch_inputs.update(numeric_reader_sha256=options.numeric_reader,
            world_guard_reader_sha256=options.world_guard_reader)
    if options.ownership_mode:
        batch_inputs.update(ownership_reader_sha256=options.ownership_reader,
            ownership_proofs=selection.relation_proof,
            native_owner_proofs=selection.ownership_native_proofs)
    if options.two_world_mode:
        batch_inputs.update(
            eligibility_reader_sha256=options.eligibility_reader,
            eligibility_proofs=selection.eligibility_proofs,
            target_world=policy.target_world,
            target_dbc_sha256=policy.target_effective.hashes,
            numeric_reader_sha256=sha(
                ROOT / 'lib/cleanup_active_reset.py'))
    if options.action_mode:
        batch_inputs.update(
            foreign_action_catalog_sha256=options.action_catalog,
            foreign_action_ack=eligibility.ACTION_ACK)
    if options.swipe_mode:
        batch_inputs.update(swipe_catalog_sha256=options.swipe_catalog,
            swipe_ack=eligibility.SWIPE_ACK)
    if options.racial_mode:
        batch_inputs.update(racial_catalog_sha256=options.racial_catalog,
            racial_ack=eligibility.RACIAL_ACK)
    if options.config_contract is not None:
        batch_inputs['configuration_contract'] = options.config_contract
    if options.native_death_coil:
        batch_inputs['native_base_proofs'] = selection.native_base_proofs
    if options.specialization_mode:
        batch_inputs.update(
            specialization_reader_sha256=options.specialization_reader,
            specialization_catalog_sha256=options.specialization_catalog,
            profession_reader_sha256=options.profession_reader,
            profession_catalog_sha256=options.profession_catalog,
            equipment=specializations.restricted(
                selection.equipment, selection.guids),
            native_sources=selection.specialization_native_sources)
    if options.invalid_equipment:
        batch_inputs['specialization_item_catalog_sha256'] = sha(
            specializations.ITEM_CATALOG)
    if options.profession_mode:
        batch_inputs.update(profession_reader_sha256=options.profession_reader,
            profession_catalog_sha256=options.profession_catalog)
    if options.skill_teaching_mode:
        batch_inputs.update(
            skill_teaching_reader_sha256=options.teaching_reader,
            skill_teaching_catalog_sha256=options.teaching_catalog)
    if options.shaman_mode:
        batch_inputs.update(shaman_reader_sha256=options.shaman_reader,
            inventory_metadata=selection.inventory_meta,
            shaman_default_skills=selection.default_skills)
    if options.foreign_skill_mode:
        batch_inputs.update(retired_skills=selection.retired_skill_rows,
            foreign_items=selection.foreign_selected_items,
            foreign_equipment=selection.foreign_selected_equipment,
            foreign_defaults=selection.foreign_defaults,
            foreign_native_sources=selection.foreign_sources,
            foreign_readers=selection.foreign_readers)
    if options.dual_mode:
        batch_inputs.update(dual_reader_sha256=sha(
            ROOT / 'lib/cleanup_dual_spec_teacher.py'),
            dual_native_sources=options.dual_sources)
    if options.offhand_mode:
        batch_inputs.update(offhand_capture=selection.selected_offhand_capture,
            offhand_native_sources=selection.offhand_sources,
            offhand_reader_sha256=sha(ROOT / 'lib/cleanup_shaman_offhand.py'),
            inventory_moves=selection.inventory_moves)
    if options.riding_mode:
        batch_inputs.update(riding_reader_sha256=options.riding_reader,
            riding_catalog_sha256=options.riding_catalog,
            riding_items=riding.restricted(
                selection.riding_items, selection.guids),
            riding_default_skills=selection.riding_defaults,
            riding_native_sources=selection.riding_sources,
            starting_skill_reader_sha256=sha(
                ROOT / 'lib/cleanup_shaman_dual_wield.py'))
    if options.riding_invalid_items:
        batch_inputs['riding_item_catalog_sha256'] = (
            options.riding_item_catalog)
    if options.direct_mode:
        batch_inputs.update(direct_passive_reader_sha256=options.direct_reader,
            ownership_reader_sha256=options.direct_ownership_reader)
    if options.legacy_mode:
        batch_inputs['inactive_legacy_reader_sha256'] = options.legacy_reader
    if options.pet_mode:
        batch_inputs['pet_teaching_reader_sha256'] = options.pet_reader
    if options.reviewed_cower:
        batch_inputs['cower_native_contract'] = options.cower_proof
    if options.parent_mode:
        batch_inputs['specialization_parent_reader_sha256'] = (
            options.parent_reader)
    if options.rekey_mode:
        batch_inputs['rekeys'] = selection.rekeys
    batch = sha_json(batch_inputs)
    archive = (('tc_obsolete_riding_' if options.riding_mode
        else 'tc_specialization_' if options.specialization_mode
        else 'tc_profession_' if options.profession_mode
        else 'tc_skill_teacher_' if options.skill_teaching_mode
        else 'tc_shaman_dual_' if options.shaman_mode
        else 'tc_direct_passive_' if options.direct_mode
        else 'tc_inactive_legacy_' if options.legacy_mode
        else 'tc_pet_teaching_' if options.pet_mode else 'tc_eligibility_'
        if options.two_world_mode else 'tc_ownership_'
        if options.ownership_mode else 'tc_disabled_history_') + uuid.uuid4(
        ).hex[:20])
    return HistoryBatch(
        archive=archive,
        batch=batch,
        template=template,
    )


def build_history_manifest(
    options: HistoryOptions,
    batch: HistoryBatch,
    evidence: HistoryEvidence,
    snapshot: HistorySnapshot,
    selection: HistorySelection,
    policy: HistoryPolicy,
    values: Mapping[str, Any],
) -> dict[str, Any]:
    manifest = {'policy': policy.policy, 'archive_schema': batch.archive,
        'batch_key': batch.batch, 'selected_rows': len(selection.selected),
        'affected_characters': len(selection.guids),
        'character_guids': selection.guids,
        'inspection_id': evidence.path.name,
        'inspection_sha256': evidence.inspection_sha,
        'audit_id': evidence.report['audit'],
        'audit_sha256': evidence.audit['audited_results_sha256'],
        'dbc_sha256': evidence.audit['dbc_sha256'],
        'semantic_dbc_sha256': evidence.effective.hashes,
        'world_sha256': sha_json(evidence.world),
        'metadata_profile_sha256': sha(PROFILE / 'spell-metadata.json'),
        'expected_sha256': values['EXPECTED_HASH'],
        'archived_rows': snapshot.counts, 'excluded_rows': len(
            selection.excluded),
        'excluded_reason_counts': dict(Counter(row[2] for row
            in selection.excluded)),
        'template_sha256': sha(batch.template),
        'native_policy': 'Disabled direct talent ranks only; no selected family in either '
        'spec; no activation, talent reset or grants'}
    if options.config_contract is not None:
        manifest['configuration_contract'] = options.config_contract
    if options.training_prerequisites:
        manifest.update(training_prerequisite_proofs=selection.training_proofs,
            training_prerequisite_ack=ordinary_history.TRAINING_ACK,
            ordinary_reader_sha256=options.ordinary_reader,
            world_guard_reader_sha256=options.world_guard_reader,
            numeric_fingerprint='EXACT_FRACTIONAL_V1',
            numeric_reader_sha256=options.numeric_reader)
    if options.native_death_coil:
        manifest['native_base_proofs'] = selection.native_base_proofs
    if policy.include_scripts:
        manifest.update(reviewed_script_bindings=selection.reviewed,
            scripted_selected_rows=sum(row[1] in evidence.effective.talents
                and evidence.effective.talents[row[1]][0]
                in selection.scripted_families for row in selection.selected),
            script_contract='NO_SPELLBOOK_MUTATION; pinned TC AddSpell disabled path; no '
            'alternate routes/dependencies/skill effects')
    if options.selected_mode:
        manifest.update(review_disposition=selected_history.DISPOSITION,
            selected_rank_rows=len(selection.selected),
            native_policy='Archive only disabled direct ranks selected by neither '
            'spec; preserve exact existing character_talent selections '
            'in both groups and every selected spell row/flag, skills '
            'and login flags; no highest-rank inference, activation or '
            'reset',
            script_contract='NO_SPELLBOOK_MUTATION; no mixed ranks, '
            'teaching/prerequisite/skill/default routes or enabled '
            'unselected sibling')
    if policy.include_relations:
        manifest.update(selection.relation_summary)
        if options.ordinary_mode:
            manifest['scripted_selected_rows'] = sum(bool(
                evidence.effective.scripts[row[1]]) for row
                in selection.selected)
        manifest['relationship_state_sha256'] = sha_json(snapshot.live[
            'relation_spells'])
        manifest['script_contract'] = (
            'NO_SPELLBOOK_MUTATION on every related member; isolated '
            'wholly disabled group; no enabled availability, selected '
            'ownership, conflicting incoming routes or skill effects'
        )
        if policy.include_routes:
            manifest['script_contract'] = (
                'NO_SPELLBOOK_MUTATION; exact reviewed teaching '
                'wrappers; wholly disabled removals; shared 674 and '
                'skill 118 preserved for inert shaman 30798 root-only '
                'exception'
            )
    if options.foreign_mode:
        manifest.update(foreign_family_ack=ownership.FOREIGN_ACK,
            numeric_fingerprint='EXACT_FRACTIONAL_V1',
            numeric_reader_sha256=options.numeric_reader,
            world_guard_reader_sha256=options.world_guard_reader)
    if options.prefix_mode:
        manifest.update(native_prefix_ack=ownership.PREFIX_ACK,
            numeric_fingerprint='EXACT_FRACTIONAL_V1',
            numeric_reader_sha256=options.numeric_reader,
            world_guard_reader_sha256=options.world_guard_reader)
    if options.alias_mode:
        manifest.update(aura_alias_ack=ownership.AURA_ALIAS_ACK,
            numeric_fingerprint='EXACT_FRACTIONAL_V1',
            numeric_reader_sha256=options.numeric_reader,
            world_guard_reader_sha256=options.world_guard_reader)
    if options.rekey_mode:
        manifest.update(native_rekey_ack=ownership.REKEY_ACK,
            rekeys=selection.rekeys, rekeys_sha256=values['MAPPING_HASH'],
            numeric_fingerprint='EXACT_FRACTIONAL_V1',
            numeric_reader_sha256=options.numeric_reader,
            world_guard_reader_sha256=options.world_guard_reader)
    if options.ownership_mode:
        manifest['script_contract'] = (
            'Isolated verified TC talent families; selected runtime '
            'routes require correct existing anchors and reviewed native '
            'contracts; no skill/profession/default/shared routes'
        )
        manifest['ownership_ack'] = ownership.ACK
        manifest['ownership_reader_sha256'] = options.ownership_reader
        manifest['native_owner_proofs'] = selection.ownership_native_proofs
    if options.two_world_mode:
        manifest.update(eligibility_ack=eligibility.ACK,
            eligibility_reader_sha256=options.eligibility_reader,
            target_world_sha256=sha_json(policy.target_world),
            target_dbc_sha256=policy.target_effective.hashes,
            numeric_fingerprint='EXACT_FRACTIONAL_V1',
            numeric_reader_sha256=sha(
                ROOT / 'lib/cleanup_active_reset.py'),
            script_contract='No removed family script or dependency; both native skill '
            'catalogs agree')
    if options.specialization_mode:
        manifest.update(specialization_ack=specialization_parent.ACK
            if options.parent_mode else specializations.ACK,
            specialization_reader_sha256=options.specialization_reader,
            specialization_catalog_sha256=options.specialization_catalog,
            profession_reader_sha256=options.profession_reader,
            profession_catalog_sha256=options.profession_catalog,
            specialization_equipment=specializations.restricted(
                selection.equipment, selection.guids),
            specialization_native_sources=selection.specialization_native_sources, native_policy=selection.relation_summary['native_policy'],
            script_contract='Fixed inactive competitors only; retain verified active '
            'choice; exact equipped item requirements in both worlds')
    if options.invalid_equipment:
        manifest['specialization_item_catalog_sha256'] = sha(
            specializations.ITEM_CATALOG)
    if options.profession_mode:
        manifest.update(profession_activation_ack=professions.ACK,
            profession_reader_sha256=options.profession_reader,
            profession_catalog_sha256=options.profession_catalog,
            native_policy=selection.relation_summary['native_policy'],
            script_contract='Exact ordinary profession ranks only; explicit activation; '
            'no SQL spell effects or missing ranks')
    if options.skill_teaching_mode:
        manifest.update(skill_teaching_ack=skill_teaching.ACK,
            skill_teaching_reader_sha256=options.teaching_reader,
            skill_teaching_catalog_sha256=options.teaching_catalog,
            native_policy=selection.relation_summary['native_policy'],
            script_contract='Exact redundant skill-step teacher; every child has a '
            'retained enabled known anchor; skills and recipes preserved')
    if options.shaman_mode:
        manifest.update(shaman_ack=options.native_selector.ACK,
            shaman_reader_sha256=options.shaman_reader,
            inventory_metadata=selection.inventory_meta,
            shaman_default_skills=selection.default_skills,
            native_policy=selection.relation_summary[
                'native_policy'],
            script_contract='Paired unselected Shaman 674/118 retirement; no alternate '
            'native routes; empty off-hand required')
    if options.foreign_skill_mode:
        manifest.update(foreign_skill_ack=foreign_skills.policy_ack(
            policy.policy), foreign_skill_readers=selection.foreign_readers,
            foreign_skill_sources=selection.foreign_sources,
            foreign_skill_items=selection.foreign_selected_items,
            foreign_skill_equipment=selection.foreign_selected_equipment,
            foreign_skill_defaults=selection.foreign_defaults,
            retired_skills=selection.retired_skill_rows,
            skill_rows_removed=len(selection.retired_skill_rows),
            native_policy=selection.relation_summary['native_policy'])
    if options.foreign_inventory_mode:
        manifest.update(inventory_moves=selection.foreign_inventory_moves,
            inventory_rows_moved=len(selection.foreign_inventory_moves))
    if options.cast_script_mode:
        manifest['cast_script_ack'] = eligibility.CAST_SCRIPT_ACK
    if options.dual_mode:
        manifest.update(dual_teacher_ack=dual_teacher.ACK,
            dual_reader_sha256=sha(ROOT / 'lib/cleanup_dual_spec_teacher.py'),
            dual_native_sources=options.dual_sources,
            native_policy=selection.relation_summary['native_policy'])
    if options.offhand_mode:
        manifest.update(offhand_capture=selection.selected_offhand_capture,
            offhand_native_sources=selection.offhand_sources,
            offhand_reader_sha256=sha(ROOT / 'lib/cleanup_shaman_offhand.py'),
            inventory_moves=selection.inventory_moves,
            inventory_rows_moved=len(selection.inventory_moves),
            script_contract='Paired unselected Shaman spell/skill retirement; verified '
            'native placement; pending resets preserved')
    if options.parent_mode:
        manifest.update(
            specialization_parent_reader_sha256=options.parent_reader,
            parent_spells_inserted=len(selection.guids),
            script_contract='Explicit missing Weaponsmith parent restoration; retained '
            'active Master Axesmith; three inactive competitors retired; '
            'no native casts')
    if options.riding_mode:
        manifest.update(riding_ack=riding.HORSE_ACK if options.riding_horse
            else riding.INVALID_ITEMS_ACK if options.riding_invalid_items
            else riding.ACK, riding_reader_sha256=options.riding_reader,
            riding_catalog_sha256=options.riding_catalog,
            riding_items=riding.restricted(selection.riding_items,
                selection.guids),
            riding_default_skills=selection.riding_defaults,
            riding_native_sources=selection.riding_sources,
            starting_skill_reader_sha256=sha(
                ROOT / 'lib/cleanup_shaman_dual_wield.py'),
            native_policy=selection.relation_summary[
                'native_policy'],
            script_contract='Forbidden Wolf Riding pair only; retain verified modern '
            'Riding; item requirements and dependencies checked in both '
            'worlds')
    if options.riding_invalid_items:
        manifest.update(riding_item_catalog_sha256=options.riding_item_catalog,
            native_invalid_items_retained=sum(len(p[
                'native_invalid_items_retained']) for p
                in selection.eligibility_proofs),
            script_contract='Verified missing-instance references and zero-entry '
            'instances retained unchanged; both worlds lack template '
            'zero; all valid item requirements checked; unknown nonzero '
            'templates defer')
    if options.direct_mode:
        manifest.update(direct_passive_ack=direct_passive.ACK,
            direct_passive_reader_sha256=options.direct_reader,
            ownership_reader_sha256=options.direct_ownership_reader,
            ownership_ack=ownership.ACK,
            script_contract='Exact selected lower direct passive auras; wrong unselected '
            'higher ranks retired; no TC lower-rank reconstruction '
            'assumed')
    if options.legacy_mode:
        manifest.update(inactive_legacy_ack=inactive_legacy.ACK,
            inactive_legacy_reader_sha256=options.legacy_reader,
            script_contract='Exact scriptless singleton legacy catalog; only '
            'inactive/non-disabled removals; retained active spells and '
            'all native talent/skill data unchanged; no inferred ranks')
    if options.action_mode:
        manifest.update(foreign_action_ack=eligibility.ACTION_ACK,
            foreign_action_catalog_sha256=options.action_catalog,
            native_policy=selection.relation_summary[
                'native_policy'],
            script_contract='Fixed inactive foreign Lockpicking 1804; skill 633 and '
            'whole teacher chain 1809/1810/6460 absent; no grants')
    if options.swipe_mode:
        manifest.update(swipe_ack=eligibility.SWIPE_ACK,
            swipe_catalog_sha256=options.swipe_catalog,
            native_policy=selection.relation_summary[
                'native_policy'],
            script_contract='Fixed inactive foreign Swipe ranks; no Bear Form or Feral '
            'skill; no grants')
    if options.racial_mode:
        manifest.update(racial_ack=eligibility.RACIAL_ACK,
            racial_catalog_sha256=options.racial_catalog,
            native_policy=selection.relation_summary[
                'native_policy'],
            script_contract='Four fixed singleton stock racials; verified wrong race; no '
            'scripts, dependencies, stored racial skills or grants')
    if options.absent_teachers:
        manifest.update(absent_teacher_ack=eligibility.ABSENT_TEACHER_ACK,
            script_contract='No removed family scripts; exact single-child teachers '
            'absent in full books; no other dependency')
    if options.pet_mode:
        manifest.update(pet_teaching_ack=pet_teaching.ACK,
            pet_teaching_reader_sha256=options.pet_reader,
            script_contract='Verified pet-target teaching wrappers only; no scripts, '
            'skills, talents or player-learning routes')
    if options.reviewed_cower:
        manifest.update(cower_ack=pet_teaching.COWER_ACK,
            cower_native_contract=options.cower_proof,
            script_contract='Only exact reviewed Cower child amount callbacks; no '
            'wrapper or other child scripts')
    if options.trained_mode:
        manifest.update(migration_inspection_id=evidence.path.name,
            source_context_sha256=evidence.capture_report[
                'source_state_sha256'],
            reviewed_character_scope=len(evidence.context[
                'characters']))
    return manifest
