"""Retire an unavailable dual-spec purchase wrapper without purchasing a
spec.

Only the narrow one-spec, pending-reset state with no Generic skill or
stored switch buttons qualifies. This discards the wrapper's future
learning action; it does not emulate a cast, login or reset.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import TYPE_CHECKING

from cleanup_files import fail
from cleanup_talent_relations import validate_stored
from cleanup_types import DatabaseState, SelectionResult
from spells import Unsupported

if TYPE_CHECKING:
    from spell_metadata import Metadata


POLICY = 'tc-unavailable-dual-spec-teacher-retirement-v1'
POLICIES = (POLICY,)
ACK = 'RETIRE_DUAL_SPEC_TEACHER_KEEP_ONE_SPEC_NO_BUTTON_GRANTS'


WRAPPERS = (63680, 63706, 63707)


def contract(tc: Metadata, ac: Metadata) -> bool:
    for wrapper in WRAPPERS:
        rule = tc.consumed_teachers.get(str(wrapper))
        expected_children = ({63645, 63644} if wrapper == 63680 else {63645}
            if wrapper == 63706 else {63644})
        if (not rule or rule != ac.consumed_teachers.get(str(wrapper)) or rule[
            'spec_count'] != 2 or set(rule['children']) != expected_children
            or rule['skill'] != 183):
            return False
        for m in (tc, ac):
            for s in (wrapper, *rule['children']):
                row = m.spells.get(s, [])
                shape = rule['mechanics'][str(s)]
                if (len(row) < 212 or any(row[i] != shape.get(str(i), 0) for i
                    in (*range(4, 131), *range(208, 212)))
                    or m.chain(s) != (s,) or s in m.talents or s
                    in m.additional or m.scripts[s]
                    or m.requires[s] or m.prerequisite_users[s]
                    or m.talent_learn_owners.get(s)
                    or m.aura_owners[s] or s in m.world_aura_owners):
                    return False
                try:
                    m.check_spell(s)
                except Unsupported: return False
            if (m.abilities[wrapper] or m.learn_parents[wrapper]
                or m.learns[wrapper] != [(child, 1, False) for child
                    in rule['children']]
                or m.effect_learns[wrapper] != [(child, 1, False)
                    for child in rule['children']]):
                return False
            for child in rule['children']:
                expected = [183, child, rule['race_mask'], rule['class_mask'],
                    0, 0, 1, 0, 2, 0, 0, 0, 0]
                if (len(m.abilities[child]) != 1 or m.abilities[child][0][1:]
                    != expected
                    or m.learns[child] or m.effect_learns[child]):
                    return False
    return True


def select(
    state: DatabaseState,
    tc: Metadata,
    ac: Metadata,
    expected: int | None = None,
    *,
    preview: bool = False,
) -> SelectionResult:
    validate_stored(state['character_spell'])
    books = defaultdict(dict)
    skills = defaultdict(dict)
    talents = defaultdict(list)
    for g, s, a, d in state['character_spell']:
        books[g][s] = (a, d)
    for g, s, v, m in state['character_skills']:
        skills[g][s] = (v, m)
    for g, s, k in state['character_talent']:
        talents[g].append((s, k))
    safe = contract(tc, ac)
    selected = []
    excluded = []
    proofs = []
    for c in state['characters']:
        g, race, cls, level, active, groups, online, flags = c
        present = [s for s in WRAPPERS if s in books[g]]
        if not present:
            continue
        reason = ''
        if (online or race not in (1, 2, 3, 4, 5, 6, 7, 8, 10, 11) or cls not
            in (1, 2, 3, 4, 5, 6, 7, 8, 9, 11) or not 40 <= level <= 80):
            reason = 'DEFER_DUAL_TEACHER_CHARACTER_STATE'
        elif not flags & 4:
            reason = 'DEFER_NOT_PENDING_NATIVE_RESET'
        elif groups != 1 or active != 0:
            reason = 'DEFER_CONFIGURED_SECOND_SPEC'
        elif any(books[g][s] != (1, 0) for s in present):
            reason = 'DEFER_DUAL_TEACHER_FLAGS'
        elif not safe:
            reason = 'DEFER_DUAL_TEACHER_METADATA'
        elif 183 in skills[g] or any(s in books[g] for s in (63644, 63645)):
            reason = 'DEFER_EXISTING_GENERIC_OR_SWITCH_ROUTE'
        else:
            seen = set()
            for s, k in talents[g]:
                identity = tc.talents.get(s)
                row = tc.talent_rows.get(s, [])
                tab = tc.stores['TalentTab'].get(row[1], []) if identity else[]
                key = (identity[0] if identity else - 1, k)
                if ((not identity or ac.talents.get(s) != identity
                    or ac.talent_rows.get(s) != row or s in tc.invalid_talents
                    or s in ac.invalid_talents or len(tab) <= 20 or not tab[
                        20] & (1 << (cls - 1)) or ac.stores['TalentTab'].get(
                            row[
                                1], [0] * 21)[20] != tab[20] or k != 0 or key
                    in seen)):
                    reason = 'DEFER_DUAL_TEACHER_TALENT_STATE'
                    break
                seen.add(key)
        if reason:
            excluded.extend((g, s, reason) for s in present)
            continue
        selected.extend((g, s, 1, 0) for s in present)
        proofs.append({'guid': g, 'retired_wrappers': present,
            'configured_specs_retained': 1, 'generic_skill_absent': True,
            'stored_buttons_absent': [63644, 63645],
            'native_reset_pending_preserved': True,
            'future_teacher_learning_action_discarded': True,
            'buttons_granted': False, 'effects_executed': False})
    if not preview and (not selected or expected != len(selected)):
        fail('DUAL_TEACHER_SELECTION_MISMATCH',
            f'Expected {expected} rows, selected {len(selected)}')
    return selected, excluded, [], {'reviewed_candidate_rows': len(selected)
        + len(excluded), 'selected_rows': len(selected),
        'selected_characters': len(proofs), 'selected_groups': len(proofs),
        'selected_direct_rows': 0, 'selected_related_rows': len(selected),
        'enabled_rows_removed': len(selected), 'disabled_rows_removed': 0,
        'deferred_candidate_rows': len(excluded), 'deferred': dict(Counter(r[
            2] for r in excluded)), 'skill_rows_changed': 0,
        'spell_rows_inserted': 0, 'eligibility_proofs': proofs,
        'native_policy': 'Retire only enabled native dual-spec teaching wrappers '
        '63680/63706/63707 on verified one-spec pending-reset characters '
        'with absent Generic skill and switch buttons; discard its '
        'future learning action. Preserve configured spec, all selected '
        'talents, skills, items and login flags; no second spec, '
        'buttons, login or reset granted'}, []
