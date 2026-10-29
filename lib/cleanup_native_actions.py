"""Fixed native action retirement with full item and selected-build
protection.

These separate policies discard teaching actions or invalid spellbook
history. They never cast an unlearn, mutate character auras, choose a
build or grant a spell.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
import json
from typing import Any, TYPE_CHECKING

from cleanup_files import ROOT, fail
from cleanup_talent_relations import MAX_ROWS, validate_stored
from cleanup_types import DatabaseState, Evidence, SelectionResult
from spells import Unsupported

if TYPE_CHECKING:
    from spell_metadata import Metadata


CATALOG = ROOT / 'lib/cleanup_native_action_catalog.json'
POLICIES = {
    'forbidden-pairs-stowing': ('tc-forbidden-dual-wield-native-stowing-v5',
        'RETIRE_FORBIDDEN_DUAL_WIELD_STOW_VERIFIED_WEAPON_EXACT_INVERSE'),
    'forbidden-pairs': ('tc-reviewed-forbidden-native-pair-retirement-v4',
        'RETIRE_FIXED_FORBIDDEN_NATIVE_PAIRS_PRESERVE_ITEMS_AND_MODERN_RIDING'),
    'redundant-teachers': ('tc-redundant-native-training-actions-v2',
        'RETIRE_FIXED_REDUNDANT_NATIVE_TEACHERS_KEEP_SKILLS'),
    'obsolete-teachers': ('tc-obsolete-native-training-action-retirement-v1',
        'RETIRE_FIXED_OBSOLETE_TRAINING_KEEP_MODERN_RIDING'),
    'unusable-specializations': (
        'tc-unusable-specialization-history-retirement-v3',
        'RETIRE_UNUSABLE_SPECIALIZATIONS_AND_TEACHERS_KEEP_RECIPES'),
    'transient-combat': ('tc-transient-combat-spellbook-retirement-v1',
        'RETIRE_FIXED_COMBAT_AURA_IDS_FROM_SPELLBOOK_ONLY'),
}


def rules() -> Evidence:
    return json.loads(CATALOG.read_text())


def candidates(action: str, r: Evidence) -> set[int]:
    if action == 'forbidden-pairs-stowing':
        return {42459, 674}
    if action == 'forbidden-pairs':
        return set(map(int, r['forbidden_pairs']))
    if action == 'redundant-teachers':
        return set(map(int, r['teachers']))
    if action == 'obsolete-teachers':
        return set(map(int, r['obsolete_teachers']))
    if action == 'transient-combat':
        return set(r['transient'])
    if action == 'unusable-specializations':
        return ({s for f in r['specializations'].values() for s in f[
            'members']} | set(map(int, r['specialization_teachers'])))
    fail('NATIVE_ACTION_POLICY', 'Unknown native action policy')


def scope(
    state: DatabaseState,
    tc: Metadata,
    ac: Metadata,
    action: str,
) -> list[int]:
    r = rules()
    ids = candidates(action, r)
    chars = {c[0]: c for c in state['characters']}
    if action.startswith('forbidden-pairs'):
        from cleanup_obsolete_riding import info
        return sorted({g for g, sp, a, d in state['character_spell'] if sp
            in ids and g in chars and 1 <= chars[g][1] <= 32 and 1 <= chars[g][
                2] <= 32
            and not any(info(m, r[
                'forbidden_pairs'][str(sp)]['skill'], chars[g][1], chars[g][2])
                for m in (tc, ac))})
    if action == 'unusable-specializations':
        books = defaultdict(dict)
        skills = defaultdict(dict)
        for g, sp, a, d in state['character_spell']:
            books[g][sp] = (a, d)
        for g, sk, v, cap in state['character_skills']:
            skills[g][sk] = (v, cap)
        eligible = set()
        for g, book in books.items():
            for rule in r['specializations'].values():
                stored = skills[g].get(rule['skill'])
                members = set(rule['members'])
                if stored and 0 < stored[0] < rule['minimum'] and (any(
                    book.get(sp) == (0, 0) for sp in members)
                    or any(int(sp) in book and child in members
                        and child not in book for sp, child in r[
                            'specialization_teachers'].items())):
                    eligible.add(g)
        return sorted(eligible)
    return sorted({g for g, s, a, d in state['character_spell'] if s in ids})


def contract(meta: Metadata, sp: int, r: Evidence) -> bool:
    expected = r[meta.core].get(str(sp))
    row = meta.spells.get(sp, [])
    if (not expected or len(row) < 212 or any(row[i] != expected[
        'mechanics'].get(str(i), 0) for i in (*range(4, 131), *range(208,
            212)))
        or list(meta.chain(sp)) != expected['chain']
        or meta.abilities[sp] != expected['abilities']
        or [list(x) for x in meta.learns[sp]] != expected[
            'learns'] or [list(x) for x in meta.effect_learns[sp]] != expected[
                'effect_learns']
        or sorted(meta.requires[sp]) != expected['requires']
        or sorted(meta.prerequisite_users[sp]) != expected['required_by']
        or sorted(meta.learn_parents[sp]) != expected['parents']
        or sorted(meta.scripts[sp]) != expected['scripts']
        or meta.scripts[sp] or sp in meta.talents or (sp != 674
            and meta.talent_learn_owners.get(sp))
        or meta.aura_owners.get(sp) or sp
        in meta.world_aura_owners or sp in meta.additional):
        return False
    try:
        meta.check_spell(sp)
    except Unsupported: return False
    return True


def skill_contract(meta: Metadata, sk: int, r: Evidence) -> bool:
    expected = r['skills'][meta.core][str(sk)]
    infos = sorted(x for x in meta.stores['SkillRaceClassInfo'].values() if x[
        1] == sk)
    return ((meta.stores['SkillLine'][sk][:2] if sk in meta.stores[
        'SkillLine'] else None) == expected['line'] and infos == expected[
            'infos']
        and {str(x[6]): meta.stores['SkillTiers'][
            x[6]] for x in infos if x[6] in meta.stores['SkillTiers']}
        == expected[
            'tiers'])


def select(
    state: DatabaseState,
    tc: Metadata,
    ac: Metadata,
    expected: int | None = None,
    *,
    preview: bool = False,
    items: Evidence | None,
    equipment: Sequence[Sequence[Any]] | None,
    default_skills: Evidence | None,
    action: str,
) -> SelectionResult:
    from cleanup_foreign_skills import valid_talents
    from cleanup_obsolete_riding import native_invalid_item
    validate_stored(state['character_spell'])
    if (not 1 <= len(state['characters']) <= 40000 or sum(map(len,
        state.values())) > MAX_ROWS):
        fail('NATIVE_ACTION_BOUND', 'Captured scope exceeds native limits')
    if items.get('zero_template_counts') != {'tc': 0, 'ac': 0}:
        fail('NATIVE_ACTION_ZERO_TEMPLATE',
            'Both worlds must lack template zero')
    policy_action = action
    stowing = action == 'forbidden-pairs-stowing'
    r = rules()
    ids = candidates(action, r)
    action = 'forbidden-pairs' if stowing else action
    books = defaultdict(dict)
    skills = defaultdict(dict)
    talents = defaultdict(list)
    owned = defaultdict(list)
    for g, s, a, d in state['character_spell']:
        books[g][s] = (a, d)
    for g, s, v, c in state['character_skills']:
        skills[g][s] = (v, c)
    for g, s, k in state['character_talent']:
        talents[g].append((s, k))
    for row in items['rows']:
        owned[row[0]].append(row)
    safe = {sp: all(contract(m, sp, r) for m in (tc, ac)) for sp in ids}
    if stowing:
        from cleanup_shaman_offhand import placement
        placements = placement(state, equipment, candidate_ids= [g for g, sp,
            a, d in state['character_spell'] if sp in ids])
    selected = []
    excluded = []
    proofs = []
    retired_skills = []
    inventory_moves = []
    for c in state['characters']:
        g, race, cls, level, active, groups, online, flags = c
        book = books[g]
        groups_to_review = []
        if action == 'forbidden-pairs':
            by_skill = defaultdict(set)
            for sp in ids & book.keys():
                from cleanup_obsolete_riding import info
                sk = r['forbidden_pairs'][str(sp)]['skill']
                if (1 <= race <= 32 and 1 <= cls <= 32 and not any(info(m, sk,
                    race, cls) for m in (tc, ac))):
                    by_skill[sk].add(sp)
            groups_to_review = ([(nodes, {'skill': sk}) for sk, nodes
                in sorted(by_skill.items())])
        elif action == 'unusable-specializations':
            for family, rule in r['specializations'].items():
                members = set(rule['members'])
                teachers = ({int(sp) for sp, ch in r[
                    'specialization_teachers'].items() if ch in members})
                nodes = ({sp for sp in members if book.get(sp) == (0, 0)} | {
                    sp for sp in teachers if sp in book and r[
                        'specialization_teachers'][str(sp)] not in book})
                if nodes:
                    groups_to_review.append((nodes, rule))
        else:
            groups_to_review = ([({sp}, None) for sp in sorted(ids & book.keys(
            ))])
        for nodes, family_rule in groups_to_review:
            reason = ''
            anchors = []
            logical = set(nodes)
            if (online or race not in (1, 2, 3, 4, 5, 6, 7, 8, 10, 11)
                or cls not in (1, 2, 3, 4, 5, 6, 7, 8, 9, 11) or not 1
                <= level <= 255 or groups not in (1, 2) or not 0
                <= active < groups):
                reason = 'DEFER_NATIVE_ACTION_CHARACTER_STATE'
            elif not valid_talents(c, talents[g], tc, ac):
                reason = 'DEFER_INVALID_SELECTED_TALENT'
            elif not all(safe.get(sp, False) for sp in nodes):
                reason = 'DEFER_NATIVE_ACTION_METADATA'
            elif any(book[sp] not in ((0, 0), (1, 0)) for sp in nodes):
                reason = 'DEFER_NATIVE_ACTION_FLAGS'
            elif any(s in nodes for s, k in talents[g]):
                reason = 'DEFER_SELECTED_TALENT_FAMILY'
            if (not reason and action in ('redundant-teachers',
                'obsolete-teachers')):
                sp = next(iter(nodes))
                rule = (r['teachers' if action == 'redundant-teachers'
                    else 'obsolete_teachers'][str(sp)])
                logical.update(rule['children'])
                sk = rule['skill']
                stored = skills[g].get(sk)
                if book[sp] != (1, 0):
                    reason = 'DEFER_NATIVE_TEACHER_FLAGS'
                elif not all(skill_contract(m, sk, r) for m in (tc, ac)):
                    reason = 'DEFER_NATIVE_TEACHER_SKILL_METADATA'
                elif action == 'obsolete-teachers':
                    # Discard the old training action only; its missing child
                    # stays absent.
                    if any(ch in book for ch in rule['children']):
                        reason = 'DEFER_EXISTING_LEGACY_RIDING_STATE'
                    elif (skills[g].get(rule['retained_skill']) != (rule[
                        'retained_cap'], rule['retained_cap']) or book.get(
                            rule['retained_anchor']) != (1, 0)):
                        reason = 'DEFER_MODERN_RIDING_ANCHOR'
                    elif (not all(contract(m, rule['retained_anchor'], r)
                        and skill_contract(m, rule['retained_skill'], r) for m
                        in (tc, ac))):
                        reason = 'DEFER_MODERN_RIDING_METADATA'
                    else:
                        anchors = [rule['retained_anchor']]
                else:
                    if not stored or not 0 < stored[0] <= stored[1] <= 1275:
                        reason = 'DEFER_NATIVE_TEACHER_SKILL_STATE'
                    for child in rule['children']:
                        chain = tc.chain(child)
                        known = ([a for a in chain if book.get(a) == (1, 0)
                            and (a == child or child in tc.predecessors(a))])
                        if not known:
                            reason = (reason
                                or 'DEFER_MISSING_KNOWN_TAUGHT_SPELL')
                            continue
                        for m in (tc, ac):
                            if (any(not contract(m, a, r) for a in chain)
                                or m.chain(child) != chain):
                                reason = (reason
                                    or 'DEFER_NATIVE_CHILD_METADATA')
                            for anchor in known:
                                effect = m.skill_effect(anchor)
                                if (effect and (effect[0] not in skills[g]
                                    or skills[g][effect[0]][0] < effect[2]
                                    or skills[g][effect[0]][1] < effect[3])):
                                    reason = (reason
                                        or 'DEFER_NATIVE_CHILD_SKILL_STATE')
                            step_skills = ([(m.spells[sp][110 + i], m.spells[
                                sp][80 + i] + 1) for i in range(3)
                                if m.spells[sp][71 + i] == 44])
                            for step_skill, step in step_skills:
                                if step_skill == rule.get('inert_step_skill'):
                                    # Fixed obsolete Lockpicking 242 has no
                                    # SkillLine entry in either
                                    # catalog. Never reinterpret it as modern
                                    # skill 633 or grant it.
                                    if (step_skill in skills[g]
                                        or not skill_contract(m, step_skill,
                                            r) or m.stores['SkillLine'].get(
                                                step_skill)):
                                        reason = (reason
                                            or 'DEFER_OBSOLETE_STEP_STATE')
                                elif (step_skill != sk or not stored or stored[
                                    1] < step * 75):
                                    reason = (reason
                                        or 'DEFER_NATIVE_TEACHER_CAP')
                        if any(book[a] not in ((0, 0), (1, 0)) for a in chain
                            if a in book):
                            reason = reason or 'DEFER_NATIVE_CHILD_FLAGS'
                        anchors += known
            elif not reason and action == 'unusable-specializations':
                sk = family_rule['skill']
                stored = skills[g].get(sk)
                # Retire unusable inactive history or an absent-child teacher;
                # retain
                # every active specialty, ordinary rank, recipe and stored
                # skill.
                if (stored is None or not 0 < stored[0] < family_rule[
                    'minimum'] or stored[0] > stored[1]):
                    reason = 'DEFER_SPECIALIZATION_NOT_PROVEN_UNUSABLE'
                elif not all(skill_contract(m, sk, r) for m in (tc, ac)):
                    reason = 'DEFER_SPECIALIZATION_SKILL_METADATA'
                logical.update(family_rule['members'])
            elif not reason and action == 'forbidden-pairs':
                from cleanup_obsolete_riding import info, default_blocks
                sk = family_rule['skill']
                stored = skills[g].get(sk)
                if any(book[sp] != (1, 0) for sp in nodes):
                    reason = 'DEFER_NATIVE_PAIR_FLAGS'
                elif not all(skill_contract(m, sk, r) for m in (tc, ac)):
                    reason = 'DEFER_FORBIDDEN_PAIR_METADATA'
                elif any(info(m, sk, race, cls) for m in (tc, ac)):
                    reason = 'DEFER_NATIVE_PAIR_ELIGIBLE'
                elif (stored is not None and (not 0 < stored[0] <= stored[1]
                    or stored[1] > 1275)):
                    reason = 'DEFER_FORBIDDEN_PAIR_SKILL_STATE'
                elif default_blocks(default_skills, race, cls, sk):
                    reason = 'DEFER_NATIVE_PAIR_DEFAULT'
                elif any(r['forbidden_pairs'][str(sp)]['teacher'] in book
                    for sp in nodes if r['forbidden_pairs'][str(sp)][
                        'teacher']):
                    reason = 'DEFER_NATIVE_PAIR_KNOWN_TEACHER'
                elif any(other not in nodes and any(a[1] == sk for a
                    in m.abilities[other]) for m in (tc, ac) for other
                    in book):
                    reason = 'DEFER_NATIVE_PAIR_RETAINED_FAMILY'
                elif any(r['forbidden_pairs'][str(sp)]['modern'] for sp
                    in nodes):
                    modern = skills[g].get(762)
                    if (modern not in ((75, 75), (150, 150), (225, 225), (300,
                        300))):
                        reason = 'DEFER_MODERN_RIDING_ANCHOR'
                    else:
                        anchors = ([sp for sp in (33388, 33391, 34090, 34091)
                            if book.get(sp) == (1, 0) and tc.skill_effect(sp)
                            == ac.skill_effect(sp) == (762, (33388, 33391,
                                34090, 34091).index(sp) + 1, *modern)])
                        if (len(anchors) != 1 or not all(contract(m, sp, r)
                            and skill_contract(m, 762, r) for m in (tc, ac)
                            for sp in (33388, 33391, 34090, 34091))):
                            reason = 'DEFER_MODERN_RIDING_METADATA'
                if sk == 118:
                    if stowing:
                        reason = reason or placements[g]['reason']
                    else:
                        facts = {row[0]: row for row in equipment['items']}
                        offhands = ([row for row in equipment['inventory']
                            if row[0] == g and row[1] == 0 and row[2] == 16])
                        if len(offhands) > 1:
                            reason = reason or 'DEFER_DUPLICATE_OFFHAND'
                        for row in offhands:
                            fact = facts.get(row[3])
                            if fact and fact[2] != 0:
                                reason = (reason
                                    or 'DEFER_OCCUPIED_NATIVE_PAIR_OFFHAND')
            elif not reason and action == 'transient-combat':
                if any(m.abilities[sp] or m.learns[sp] or m.effect_learns[sp]
                    or m.requires[sp] or m.learn_parents[sp] for m in (tc, ac)
                    for sp in nodes):
                    reason = 'DEFER_TRANSIENT_PLAYER_LEARNING_ROUTE'
            if not reason:
                # Retained known requirements and teachers must not depend on
                # removed IDs.
                for m in (tc, ac):
                    for sp in nodes:
                        if any(other in book and other not in nodes for other
                            in m.learn_parents[sp] | m.prerequisite_users[sp]):
                            reason = 'DEFER_RETAINED_NATIVE_ACTION_DEPENDENCY'
                valid = ([row for row in owned[g] if not native_invalid_item(
                    row)])
                if any(any(v is None for v in row[2:]) for row in valid):
                    reason = reason or 'DEFER_UNKNOWN_OWNED_ITEM_REQUIREMENT'
                elif any(row[8] in logical or row[12] in logical or (action
                    == 'forbidden-pairs' and (row[6] == family_rule['skill']
                        or row[10] == family_rule['skill'])) for row in valid):
                    reason = reason or 'DEFER_OWNED_ITEM_REQUIRES_ACTION'
            if reason:
                excluded.extend((g, sp, reason) for sp in sorted(nodes))
                continue
            if stowing:
                inventory_moves += placements[g]['moves']
            if (action == 'forbidden-pairs' and family_rule['skill'] in skills[
                g]):
                retired_skills.append([g, family_rule['skill'], *skills[g][
                    family_rule['skill']]])
            selected.extend((g, sp, *book[sp]) for sp in sorted(nodes))
            proofs.append({'guid': g, 'retired_spell_rows': sorted(nodes),
                'retained_native_anchors': sorted(set(anchors)),
                'preserved_skills': {str(sk): list(value) for sk, value
                    in skills[g].items()}, 'selected_talents_preserved': True,
                'pending_reset_preserved': bool(flags & 4),
                'owned_items_checked': len(owned[g]),
                'character_auras_changed': False,
                'native_casts_executed': False, 'policy': action})
    selected.sort()
    excluded.sort()
    if not preview and (not selected or expected != len(selected)):
        fail('NATIVE_ACTION_SELECTION_MISMATCH',
            f'Expected {expected} spell rows, selected {len(selected)}')
    summary = {'reviewed_candidate_rows': len(selected) + len(excluded),
        'selected_rows': len(selected), 'selected_characters': len({x[0] for x
            in selected}), 'selected_groups': len(proofs),
        'selected_direct_rows': 0, 'selected_related_rows': len(selected),
        'enabled_rows_removed': sum(not x[3] for x in selected),
        'disabled_rows_removed': sum(bool(x[3]) for x in selected),
        'skill_rows_changed': len(retired_skills), 'skill_rows_removed': len(
            retired_skills), 'retired_skills': sorted(retired_skills),
        'spell_rows_inserted': 0, 'deferred_candidate_rows': len(excluded),
        'deferred': dict(Counter(x[2] for x in excluded)),
        'eligibility_proofs': proofs, 'inventory_moves': sorted(
            inventory_moves), 'inventory_rows_moved': len(inventory_moves),
        'native_policy': POLICIES[policy_action][1]
        + ': retire exact reviewed actions and only explicitly listed '
        'forbidden skill keys; preserve all other skills/caps, stored '
        'recipes, selected talents in both specs, items, character auras '
        'and login flags; no spell grants, casts, resets or missing-rank '
        'inference'}
    return selected, excluded, [], summary, []
