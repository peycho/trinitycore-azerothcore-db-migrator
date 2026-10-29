"""Candidate selection and captured review reporting."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from typing import Literal, TYPE_CHECKING

from cleanup_disabled_history import (
    MAX_GUIDS,
    check_retained_scripts,
    script_bindings,
    select,
)
from cleanup_files import fail, write_json
import cleanup_foreign_skills as foreign_skills
from cleanup_history_models import (
    HistoryEvidence,
    HistoryOptions,
    HistoryPolicy,
    HistorySelection,
)
import cleanup_obsolete_riding as riding
import cleanup_ordinary_history as ordinary_history
import cleanup_ownership as ownership
from cleanup_plans import sha_json, snapshot
import cleanup_selected_rank_history as selected_history
import cleanup_shaman_dual_wield as shaman
import cleanup_shaman_offhand as offhand_repair
import cleanup_specializations as specializations
import cleanup_talent_relations as relations
import cleanup_trained_history as trained_history
from cleanup_types import Evidence

if TYPE_CHECKING:
    from cleanup_config import Settings
    from cleanup_workspace import Workspace


def select_history_candidates(
    settings: Settings,
    work: Workspace,
    args: argparse.Namespace,
    options: HistoryOptions,
    evidence: HistoryEvidence,
    policy: HistoryPolicy,
) -> HistorySelection | Literal[False]:
    default_skills = None
    eligibility_proofs = None
    equipment = None
    excluded = None
    foreign_defaults = None
    foreign_equipment = None
    foreign_inventory_moves = None
    foreign_items = None
    foreign_readers = None
    foreign_scope = None
    foreign_selected_equipment = None
    foreign_selected_items = None
    foreign_sources = None
    inventory_meta = None
    inventory_moves = None
    offhand_capture = None
    offhand_rows = None
    offhand_sources = None
    retired_skill_rows = None
    riding_defaults = None
    riding_items = None
    riding_scope = None
    riding_sources = None
    selected = None
    selected_offhand_capture = None
    specialization_native_sources = None
    relation_rows, relation_proof, relation_summary, relation_edges = [], [], {
    }, []
    rank_proof = []
    native_base_proofs = []
    training_proofs = []
    ownership_native_proofs = []
    rekeys = []
    if options.specialization_mode:
        specialization_native_sources = specializations.native_sources(
            settings.paths, native_invalid_items=options.invalid_equipment)
        equipment = specializations.read_equipment(settings, [r[0] for r
            in evidence.context['characters']],
            native_invalid_items=options.invalid_equipment)
    if options.foreign_skill_mode:
        foreign_scope = foreign_skills.scope(evidence.context,
            evidence.effective, policy.target_effective,
            training_actions=options.foreign_training,
            native_action=options.native_action)
        foreign_items = riding.read_items(settings, foreign_scope,
            native_invalid_items=True)
        foreign_equipment = offhand_repair.read(settings, foreign_scope,
            equipment_slots=range(19))
        foreign_defaults = shaman.defaults(settings)
        foreign_sources = foreign_skills.native_sources(settings.paths)
        foreign_readers = foreign_skills.reader_hashes()
    if options.riding_mode:
        riding_sources = riding.native_sources(settings.paths,
            native_invalid_items=options.riding_invalid_items,
            legacy_horse=options.riding_horse)
        riding_scope = riding.candidate_guids(evidence.context,
            legacy_horse=options.riding_horse)
        riding_items = riding.read_items(settings, riding_scope,
            native_invalid_items=options.riding_invalid_items)
        riding_defaults = riding.defaults(settings)
    if options.shaman_mode:
        inventory_meta, offhand_rows = shaman.inventory(settings,
            evidence.context)
        default_skills = shaman.defaults(settings)
        if options.offhand_mode:
            offhand_sources = offhand_repair.native_sources(settings.paths)
            offhand_capture = offhand_repair.read(settings,
                offhand_repair.candidate_guids(evidence.context))
    if options.trained_mode:
        check_retained_scripts(evidence.state, evidence.effective)
        relation_rows = evidence.context['character_spell']
        if options.two_world_mode:
            (selected, excluded, relation_proof, relation_summary,
                relation_edges) = options.native_selector.select(
                    evidence.context, evidence.effective,
                    policy.target_effective,
                    args.expect_review_rows, preview=options.preview,
                    ** ({'items': foreign_items,
                        'equipment': foreign_equipment,
                        'default_skills': foreign_defaults,
                        'training_actions': options.foreign_training,
                        'native_action': options.native_action}
                        if options.foreign_skill_mode else {
                            'items': riding_items[
                                'rows'], 'default_skills': riding_defaults,
                            'native_invalid_items': options.riding_invalid_items,
                            'zero_template_counts': riding_items.get(
                                'zero_template_counts'),
                            'legacy_horse': options.riding_horse}
                        if options.riding_mode else {
                            'pending_reset': options.pending_professions}
                        if options.profession_mode else {
                            'equipment': equipment[
                                'rows'],
                            'native_invalid_items': options.invalid_equipment,
                            'zero_template_counts': equipment.get(
                                'zero_template_counts')}
                        if options.specialization_mode else {
                            'capture': offhand_capture,
                            'default_skills': default_skills}
                        if options.offhand_mode else {'offhand': {r[0] for r
                            in offhand_rows}, 'default_skills': default_skills}
                        if options.shaman_mode else {'reviewed_cower': True}
                        if options.reviewed_cower else {
                            'reviewed_cast_scripts': True}
                        if options.cast_script_mode else {
                            'absent_teachers': True}
                        if options.absent_teachers else {
                            'reviewed_racials': True}
                        if options.racial_mode else {
                            'inactive_foreign_swipes': True}
                        if options.swipe_mode else {
                            'inactive_foreign_actions': True}
                        if options.action_mode else {}))
            eligibility_proofs = relation_summary.pop('eligibility_proofs')
        elif options.ownership_mode:
            (selected, excluded, relation_proof, relation_summary,
                relation_edges) = ownership.select(
                    evidence.context, evidence.effective,
                    args.expect_review_rows,
                    preview=options.preview, source_dir=settings.paths[
                        'tc_source'],
                    foreign_class_families=options.foreign_mode,
                    native_passive_prefixes=options.prefix_mode,
                    reviewed_aura_aliases=options.alias_mode,
                    native_passive_rekey=options.rekey_mode,
                    pending_ownership=options.pending_ownership,
                    overlevel_unselected=options.overlevel_unselected)
            ownership_native_proofs = relation_summary.pop(
                'native_owner_proofs')
            rekeys = relation_summary.pop('rekeys', [])
            if options.rekey_mode:
                relation_summary['rekeys'] = rekeys
        elif options.ordinary_mode:
            (selected, excluded, relation_proof, relation_summary,
                relation_edges) = ordinary_history.select(
                    evidence.context, evidence.effective,
                    args.expect_review_rows,
                    preview=options.preview,
                    inactive_custom_defaults=options.inactive_defaults,
                    native_death_coil=options.native_death_coil,
                    training_prerequisites=options.training_prerequisites,
                    pending_death_coil=options.pending_death_coil,
                    pending_defaults=options.pending_defaults)
            native_base_proofs = relation_summary.pop('native_base_proofs', [])
            training_proofs = relation_summary.pop(
                'training_prerequisite_proofs', [])
        else:
            (selected, excluded, relation_proof, relation_summary,
                relation_edges) = trained_history.select(
                    evidence.context, evidence.effective,
                    args.expect_review_rows,
                    orphan_children=options.child_mode,
                    preview=options.preview,
                    pending_history=options.pending_history)
        if (options.child_mode or options.ordinary_mode
            or options.ownership_mode or options.two_world_mode):
            review_name = ('native-action-review.json'
                if options.native_action else 'foreign-skill-review.json'
                if options.foreign_skill_mode
                else 'dual-spec-teacher-review.json' if options.dual_mode
                else 'specialization-parent-review.json'
                if options.parent_mode else 'obsolete-riding-review.json'
                if options.riding_mode
                else 'specialization-retirement-review.json'
                if options.specialization_mode
                else 'profession-activation-review.json'
                if options.profession_mode else 'skill-teaching-review.json'
                if options.skill_teaching_mode
                else 'shaman-dual-wield-review.json' if options.shaman_mode
                else 'selected-passive-review.json' if options.direct_mode
                else 'inactive-legacy-review.json' if options.legacy_mode
                else 'pet-teaching-review.json' if options.pet_mode
                else 'spell-eligibility-review.json' if options.two_world_mode
                else 'talent-ownership-review.json' if options.ownership_mode
                else 'ordinary-spell-review.json' if options.ordinary_mode
                else 'talent-child-review.json')
            review_label = ('Native action' if options.native_action
                else 'Forbidden skill family' if options.foreign_skill_mode
                else 'Unavailable dual-spec teacher' if options.dual_mode
                else 'Weaponsmith parent-specialization'
                if options.parent_mode else 'Obsolete riding spell/skill'
                if options.riding_mode
                else 'Inactive specialization retirement'
                if options.specialization_mode
                else 'Ordinary profession activation'
                if options.profession_mode else 'Redundant skill-teaching'
                if options.skill_teaching_mode
                else 'Coupled Shaman spell/skill' if options.shaman_mode
                else 'Selected direct passive' if options.direct_mode
                else 'Inactive legacy' if options.legacy_mode
                else 'Pet-teaching' if options.pet_mode
                else 'Spell-eligibility' if options.two_world_mode
                else 'Talent-ownership' if options.ownership_mode
                else 'Ordinary-spell' if options.ordinary_mode
                else 'Talent-child')
            review = {'policy': policy.policy,
                'migration_inspection': evidence.path.name,
                'scope_characters': len(evidence.context['characters']),
                'summary': relation_summary, 'selected': selected,
                'excluded': excluded,
                'deferred': dict(Counter(row[2] for row in excluded)),
                'limitations': [
                    'Captured-state review, not a live full-row '
                    'verification or cleanup approval',
                    'Planning rechecks the complete captured semantic '
                    'scope and full affected originals']}
            if options.config_contract is not None:
                review['configuration_contract'] = options.config_contract
            if options.ownership_mode:
                review['native_owner_proofs'] = ownership_native_proofs
            if options.two_world_mode:
                review['eligibility_proofs'] = eligibility_proofs
                review['target_world_sha256'] = sha_json(policy.target_world)
                review['target_dbc_sha256'] = policy.target_effective.hashes
            if options.specialization_mode:
                review['equipment'] = equipment
            if options.riding_mode:
                review['items'] = riding_items
                review['starting_skills'] = riding_defaults
            if options.reviewed_cower:
                review['cower_native_contract'] = options.cower_proof
            if options.training_prerequisites:
                review['training_prerequisite_proofs'] = training_proofs
            if options.native_death_coil:
                review['native_base_proofs'] = native_base_proofs
            write_json(work.operation / review_name, review)
            print(review_label + ' review (read-only): ' + json.dumps({
                **relation_summary, 'deferred': review['deferred']},
                sort_keys=True), flush=True)
            if options.preview:
                print(
                    'PREVIEW: captured evidence only; no SQL package, active '
                    'batch or source changes. Details: ' + str(
                        work.operation / review_name),
                    flush=True)
                return False
            if not selected:
                fail('OWNERSHIP_SELECTION_MISMATCH',
                    'No eligible ownership repair rows')
    elif options.selected_mode:
        check_retained_scripts(evidence.state, evidence.effective)
        selected, excluded, rank_proof = selected_history.select(evidence.rows,
            evidence.state, evidence.effective, args.expect_review_rows)
    elif policy.include_relations:
        review_guids = sorted({r[0] for r in evidence.rows if r[9]
            == 'REVIEW_DISABLED_NO_SELECTED_FAMILY'})
        if not review_guids or len(review_guids) > MAX_GUIDS:
            fail('HISTORY_RELATION_BOUND',
                'No review characters or more than 40000 characters')
        print(
            'Reviewing complete related spell state per character (read-only)',
            flush=True)
        relation_rows = (snapshot(settings, [('rows', relations.stored_query(
            settings.schemas['characters'], review_guids))])['rows'])
        check_retained_scripts(evidence.state, evidence.effective)
        (selected, excluded, relation_proof, relation_summary,
            relation_edges) = relations.select(
                evidence.rows, evidence.state, evidence.effective,
                relation_rows,
                args.expect_review_rows, policy.include_routes)
    else:
        selected, excluded = select(evidence.rows, evidence.state,
            evidence.effective, args.expect_review_rows,
            policy.include_scripts)
    bindings = (script_bindings(evidence.effective) if policy.include_scripts
        and not options.ordinary_mode else[])
    if policy.include_relations:
        bindings = sorted(set(bindings) | {(family, spell, name, '') for _,
            family, spell, *_ in relation_proof
            for name
            in evidence.effective.scripts[spell]})
    selected_families = ({evidence.effective.talents[row[1]][0] for row
        in selected if row[1] in evidence.effective.talents})
    if (options.child_mode or options.ordinary_mode or options.ownership_mode
        or options.two_world_mode):
        selected_families |= {row[1] for row in relation_proof}
    reviewed = [row[:3] for row in bindings if row[0] in selected_families]
    scripted_families = {entry[0] for entry in reviewed}
    guids = sorted({row[0] for row in selected})
    guid_set = set(guids)
    if options.foreign_skill_mode:
        retired_skill_rows = relation_summary['retired_skills']
        foreign_inventory_moves = relation_summary.get('inventory_moves', [])
        foreign_selected_items = riding.restricted(foreign_items, guids)
        foreign_selected_equipment = offhand_repair.restrict(foreign_equipment,
            guids)
    if options.offhand_mode:
        selected_offhand_capture = offhand_repair.restrict(offhand_capture,
            guids)
        inventory_moves = relation_summary['inventory_moves']
    return HistorySelection(
        bindings=bindings,
        default_skills=default_skills,
        eligibility_proofs=eligibility_proofs,
        equipment=equipment,
        excluded=excluded,
        foreign_defaults=foreign_defaults,
        foreign_equipment=foreign_equipment,
        foreign_inventory_moves=foreign_inventory_moves,
        foreign_items=foreign_items,
        foreign_readers=foreign_readers,
        foreign_scope=foreign_scope,
        foreign_selected_equipment=foreign_selected_equipment,
        foreign_selected_items=foreign_selected_items,
        foreign_sources=foreign_sources,
        guid_set=guid_set,
        guids=guids,
        inventory_meta=inventory_meta,
        inventory_moves=inventory_moves,
        native_base_proofs=native_base_proofs,
        offhand_capture=offhand_capture,
        offhand_rows=offhand_rows,
        offhand_sources=offhand_sources,
        ownership_native_proofs=ownership_native_proofs,
        rank_proof=rank_proof,
        rekeys=rekeys,
        relation_edges=relation_edges,
        relation_proof=relation_proof,
        relation_rows=relation_rows,
        relation_summary=relation_summary,
        retired_skill_rows=retired_skill_rows,
        reviewed=reviewed,
        riding_defaults=riding_defaults,
        riding_items=riding_items,
        riding_scope=riding_scope,
        riding_sources=riding_sources,
        scripted_families=scripted_families,
        selected=selected,
        selected_offhand_capture=selected_offhand_capture,
        specialization_native_sources=specialization_native_sources,
        training_proofs=training_proofs,
    )


def report_history_selection(
    args: argparse.Namespace,
    options: HistoryOptions,
    selection: HistorySelection,
    policy: HistoryPolicy,
    manifest: Evidence,
) -> None:
    if options.riding_mode:
        print('Reviewed '
            f"{selection.relation_summary['reviewed_candidate_rows']} "
            f'obsolete riding candidates; selected {len(selection.selected)} '
            f'spell/skill pairs; deferred {len(selection.excluded)}; no '
            'source changes')
    elif options.specialization_mode:
        print('Reviewed '
            f"{selection.relation_summary['reviewed_candidate_rows']} "
            'inactive specialization rows; selected '
            f'{len(selection.selected)} exact competitors; deferred '
            f'{len(selection.excluded)}; no source changes')
    elif options.profession_mode:
        print('Reviewed '
            f"{selection.relation_summary['reviewed_candidate_rows']} "
            'inactive profession candidates; selected '
            f'{len(selection.selected)} existing rows for activation; '
            f'deferred {len(selection.excluded)}; no source changes')
    elif options.skill_teaching_mode:
        print('Reviewed '
            f"{selection.relation_summary['reviewed_candidate_rows']} "
            f'skill-teaching candidates; selected {len(selection.selected)} '
            f'exact redundant wrappers; deferred {len(selection.excluded)}; '
            'no source changes')
    elif options.direct_mode:
        print('Reviewed '
            f"{selection.relation_summary['reviewed_candidate_rows']} talent "
            f'conflicts; selected {len(selection.selected)} direct passive '
            f'rows; deferred {len(selection.excluded)}; no source changes')
    elif options.legacy_mode:
        print('Reviewed '
            f"{selection.relation_summary['reviewed_candidate_rows']} "
            f'inactive legacy rows; selected {len(selection.selected)} exact '
            f'rows; deferred {len(selection.excluded)}; no source changes')
    elif options.pet_mode:
        print('Reviewed '
            f"{selection.relation_summary['reviewed_candidate_rows']} "
            f'pet-teaching candidates; selected {len(selection.selected)} '
            f'exact player rows; deferred {len(selection.excluded)}; no '
            'source changes')
    elif options.two_world_mode:
        print('Reviewed '
            f"{selection.relation_summary['reviewed_candidate_rows']} "
            f'ineligible stored rows; selected {len(selection.selected)} '
            f'exact rows; deferred {len(selection.excluded)}; no source '
            'changes')
    elif options.ownership_mode:
        print('Reviewed '
            f"{selection.relation_summary['reviewed_candidate_rows']} "
            'conflicting spell candidates; selected '
            f'{len(selection.selected)} exact rows; deferred '
            f'{len(selection.excluded)}; no source changes')
    elif options.ordinary_mode:
        print(f'Reviewed {args.expect_review_rows} disabled ordinary '
            f'candidates; selected {len(selection.selected)} exact rows; '
            f'deferred {len(selection.excluded)} candidate rows; no source '
            'changes')
    elif options.child_mode:
        print(f'Reviewed {args.expect_review_rows} disabled talent-child '
            f'candidates; selected {len(selection.selected)} exact rows; '
            f'deferred {len(selection.excluded)} candidate rows; no source '
            'changes')
    elif options.trained_mode:
        print(f'Reviewed {args.expect_review_rows} disabled trained rows; '
            f'selected {len(selection.selected)} exact rows; deferred '
            f'{len(selection.excluded)} trained rows; no source changes')
    elif policy.include_relations:
        print(f'Reviewed {args.expect_review_rows} disabled direct rows; '
            f"selected {selection.relation_summary['selected_root_rows']} "
            'direct and '
            f"{selection.relation_summary['selected_related_rows']} related "
            f'rows; deferred {len(selection.excluded)} direct rows; no '
            'source changes')
    else:
        print(f'Reviewed {len(selection.selected) + len(selection.excluded)} '
            f'disabled rows; selected {len(selection.selected)}; deferred '
            f'{len(selection.excluded)}; no source changes')
    for reason, count in sorted(Counter(row[2] for row
        in selection.excluded).items()):
        print(reason + '\t' + str(count))
    if policy.include_scripts:
        print('SELECTED_REVIEWED_SCRIPT_HISTORY\t' + str(manifest[
            'scripted_selected_rows']))
