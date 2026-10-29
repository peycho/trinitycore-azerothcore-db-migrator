"""Explicit Weaponsmith parent restoration with inactive competitor
retirement.

The retained active Master Axesmith is authoritative only under the
fixed native catalog, valid existing Blacksmithing skill and complete
equipment/recipe guards.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from typing import Any, TYPE_CHECKING

from cleanup_files import fail
import cleanup_specializations as base
from cleanup_talent_relations import MAX_ROWS, validate_stored
from cleanup_types import DatabaseState, SelectionResult

if TYPE_CHECKING:
    from spell_metadata import Metadata


POLICY = 'tc-reviewed-weaponsmith-parent-repair-v2'
ACK = (
    'RESTORE_WEAPONSMITH_RETAIN_MASTER_AXESMITH_RETIRE_INACTIVE_COMPETITORS'
)
OLD = (9788, 17039, 17040)
PARENT = 9787
CHOICE = 17041


def select(
    state: DatabaseState,
    tc: Metadata,
    ac: Metadata,
    expected: int | None = None,
    *,
    preview: bool = False,
    equipment: Sequence[Sequence[Any]] | None,
    native_invalid_items: bool = False,
    zero_template_counts: Sequence[int] | None = None,
) -> SelectionResult:
    validate_stored(state['character_spell'])
    if (not 1 <= len(state['characters']) <= 40000 or sum(map(len,
        state.values())) > MAX_ROWS):
        fail('SPECIALIZATION_PARENT_BOUND',
            'Captured source scope exceeds reviewed bounds')
    books = defaultdict(dict)
    chars = {r[0]: r for r in state['characters']}
    for g, s, a, d in state['character_spell']:
        books[g][s] = (a, d)
    # Reuse every existing skill, class/talent, prerequisite, recipe-route and
    # equipment guard against an explicitly projected parent, never live data.
    candidates = ([g for g in sorted(chars) if books[g].get(9788) == (0, 0)
        and PARENT not in books[g]])
    candidate_ids = set(candidates)
    projected = {**state, 'character_spell': [r for r in state[
        'character_spell'] if not (r[0] in candidate_ids and r[1] == 9788)]}
    projected['character_spell'] += [[g, PARENT, 1, 0] for g in candidates]
    projected['character_spell'].sort()
    rows, excluded, _, _, _ = base.select(projected, tc, ac, preview=True,
        equipment=equipment,
        native_invalid_items=native_invalid_items,
        zero_template_counts=zero_template_counts)
    valid_equipment, inert = base.equipment_policy(equipment,
        native_invalid_items, zero_template_counts)
    allowed = {tuple(r[:2]) for r in rows}
    reasons = {(g, s): why for g, s, why in excluded}
    metadata_ok = all(base.contract(m, f) for m in (tc, ac) for f in ('smith',
        'weapon'))
    selected, deferred, proofs = [], [], []
    for g in candidates:
        book = books[g]
        reason = ''
        if chars[g][7] & 4:
            reason = 'DEFER_PENDING_NATIVE_RESET'
        elif not metadata_ok:
            reason = 'DEFER_SPECIALIZATION_PARENT_METADATA'
        elif (book.get(CHOICE) != (1, 0) or any(book.get(s) != (0, 0) for s
            in OLD)):
            reason = 'DEFER_PARENT_CHOICE_OR_COMPETITOR_FLAGS'
        elif not all((g, s) in allowed for s in (17039, 17040)):
            reason = next((reasons[g, s] for s in (17039, 17040) if (g, s)
                in reasons), 'DEFER_PARENT_NATIVE_CONTRACT')
        elif any(parent in book for m in (tc, ac) for s in (*OLD, PARENT,
            CHOICE) for parent in m.learn_parents[s]):
            reason = 'DEFER_KNOWN_SPECIALIZATION_TEACHER'
        elif any(user in book for m in (tc, ac) for s in OLD for user
            in m.prerequisite_users[s]):
            reason = 'DEFER_SPECIALIZATION_DEPENDENT_RECIPE'
        elif any(any(x is None for x in r) or r[2] != r[3] or r[4] != r[5]
            or r[4] != r[7] or not r[2] or not r[4]
            for r in valid_equipment if r[0] == g):
            reason = 'DEFER_UNKNOWN_EQUIPPED_ITEM_REQUIREMENT'
        elif any(r[6] in OLD or r[8] in OLD for r in valid_equipment if r[0]
            == g):
            reason = 'DEFER_EQUIPPED_SPECIALIZATION_REQUIREMENT'
        if reason:
            deferred.extend((g, s, reason) for s in OLD if s in book)
            continue
        selected.extend((g, s, 0, 0) for s in OLD)
        stored = next((r[2:] for r in state['character_skills'] if r[0] == g
            and r[1] == 164), None)
        proofs.append({'guid': g, 'retained_active_specialization': CHOICE,
            'retained_choice': 'MASTER_AXESMITH',
            'parent_restored': [PARENT, 1, 0], 'parent_absent_before': True,
            'retired_inactive': list(OLD),
            'preserved_blacksmith_skill': stored,
            'both_builds_preserved': True, 'recipes_preserved': True,
            'equipped_requirements_checked_both_worlds': True,
            'native_unlearn_casts': False})
    if not preview and (not selected or expected != len(selected)):
        fail('SPECIALIZATION_PARENT_SELECTION_MISMATCH',
            '--expect-rows must equal selected original rows ('
            f'{len(selected)})')
    summary = {'reviewed_candidate_rows': len(selected) + len(deferred),
        'selected_rows': len(selected),
        'selected_characters': len(proofs), 'selected_groups': len(proofs),
        'selected_direct_rows': 0,
        'selected_related_rows': len(selected), 'inactive_rows_removed': len(
            selected), 'enabled_rows_removed': len(selected),
        'active_rows_removed': 0, 'disabled_rows_removed': 0,
        'spell_rows_inserted': len(proofs), 'skill_rows_changed': 0,
        'deferred_candidate_rows': len(deferred), 'deferred': dict(Counter(r[
            2] for r in deferred)),
        'eligibility_proofs': proofs,
        'native_policy': 'Explicitly restore missing Weaponsmith 9787 from retained '
        'verified active Master Axesmith 17041, retire exact inactive '
        '9788/17039/17040; stock spell columns required; preserve '
        'existing skills/caps, recipes, both builds, all items and '
        'flags; known-specialization eligibility changes; no native '
        'unlearn or skill effects executed'}
    if native_invalid_items:
        retained = ([{'guid': r[0], 'item_guid': r[2], 'reason': kind} for r,
            kind in inert if kind and r[0] in {x[0] for x in selected}])
        summary.update(native_invalid_item_rows_retained=len(retained),
            native_invalid_item_reasons=dict(Counter(r['reason'] for r
                in retained)), native_invalid_items_retained=retained)
        summary['native_policy'] += (
            '; retain verified native-invalid item rows unchanged, check '
            'every valid equipped item and defer unknown nonzero '
            'templates'
        )
    return selected, deferred, [], summary, []
