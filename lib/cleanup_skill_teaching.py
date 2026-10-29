"""Retire redundant, enabled skill-step teachers; never execute their
effects.

Only fixed reviewed wrappers qualify. Every taught child must already be
known from a retained enabled ordinary rank anchor, with compatible
native skill state.
"""

from __future__ import annotations

from collections import Counter, defaultdict
import json
from typing import TYPE_CHECKING

from cleanup_files import ROOT, fail
from cleanup_talent_relations import MAX_ROWS, validate_stored
from cleanup_types import DatabaseState, SelectionResult
from spells import Unsupported

if TYPE_CHECKING:
    from spell_metadata import Metadata


POLICY = 'tc-redundant-skill-teaching-wrapper-retirement-v1'
POLICIES = (POLICY,)
ACK = 'RETIRE_ONLY_REDUNDANT_KNOWN_SKILL_TEACHERS'
CATALOG = ROOT / 'lib/cleanup_skill_teaching_catalog.json'
RULES = json.loads(CATALOG.read_text())


def contract(meta: Metadata, spell: int) -> bool:
    rule = RULES['wrappers'][str(spell)]
    nodes = ({spell} | {s for child in rule['children'] for s in RULES[
        meta.core][str(child)]['chain']})
    for s in nodes:
        expected = RULES[meta.core][str(s)]
        row = meta.spells.get(s, [])
        if (len(row) < 212 or any(row[i] != expected['mechanics'].get(str(i),
            0) for i in (*range(4, 131), *range(208, 212)))
            or list(meta.chain(s)) != expected['chain'] or meta.abilities[
                s] != expected['abilities']
            or [list(r) for r in meta.learns[s]] != expected['learns']
            or [list(r) for r in meta.effect_learns[s]] != expected[
                'effect_learns']
            or sorted(meta.requires[s]) != expected['requires']
            or sorted(meta.prerequisite_users[s]) != expected[
                'prerequisite_users']
            or sorted(meta.learn_parents[s]) != expected['learn_parents']
            or meta.scripts[s] or s in meta.talents
            or meta.talent_learn_owners.get(s)
            or meta.aura_owners[s] or s in meta.world_aura_owners or s
            in meta.additional):
            return False
        try:
            meta.check_spell(s)
        except Unsupported: return False
    skill = rule['skill']
    expected = RULES['skill_metadata'][meta.core][str(skill)]
    infos = sorted(r for r in meta.stores['SkillRaceClassInfo'].values() if r[
        1] == skill)
    if (meta.stores['SkillLine'].get(skill, [0, 0])[1] != expected['category']
        or infos != expected['infos']
        or {str(r[6]): meta.stores['SkillTiers'][r[6]] for r in infos if r[
            6] in meta.stores['SkillTiers']} != expected['tiers']):
        return False
    # Reject added cast/trigger routes into the wrappers, even when they were
    # not classified as learn/requirement edges by the metadata loader.
    if any(spell in row[116:119] for row in meta.spells.values()):
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
    if (not 1 <= len(state['characters']) <= 40000 or sum(map(len,
        state.values())) > MAX_ROWS):
        fail('SKILL_TEACHER_BOUND', 'Captured scope exceeds reviewed bounds')
    chars = {r[0]: r for r in state['characters']}
    books = defaultdict(dict)
    skills = defaultdict(dict)
    for g, s, a, d in state['character_spell']:
        books[g][s] = (a, d)
    for g, s, v, m in state['character_skills']:
        skills[g][s] = (v, m)
    invalid, seen = set(), set()
    for g, s, k in state['character_talent']:
        c = chars.get(g)
        identity = tc.talents.get(s)
        row = tc.talent_rows.get(s, [])
        tab = tc.stores['TalentTab'].get(row[1], []) if identity else[]
        key = (g, identity[0] if identity else - 1, k)
        if (c is None or not identity or ac.talents.get(s) != identity or s
            in tc.invalid_talents or s in ac.invalid_talents
            or ac.talent_rows.get(s) != row or len(tab) <= 20 or not 1
            <= c[2] <= 32
            or ac.stores['TalentTab'].get(row[1], [0] * 21)[20] != tab[20]
            or not tab[20] & (1 << (c[2] - 1)) or k not in (0, 1) or k
            >= c[5] or key in seen):
            invalid.add(g)
        seen.add(key)
    safe = ({s: contract(tc, s) and contract(ac, s) for s in map(int, RULES[
        'wrappers'])})
    selected, excluded, proofs = [], [], []
    for g, c in sorted(chars.items()):
        for spell in sorted(s for s in books[g] if str(s) in RULES[
            'wrappers']):
            rule = RULES['wrappers'][str(spell)]
            reason = ''
            anchors = []
            if c[6]:
                reason = 'DEFER_ONLINE_CHARACTER'
            elif c[7] & 4:
                reason = 'DEFER_PENDING_NATIVE_RESET'
            elif (c[1] not in (1, 2, 3, 4, 5, 6, 7, 8, 10, 11) or c[2] not in (
                1, 2, 3, 4, 5, 6, 7, 8, 9, 11)
                or not 1 <= c[3] <= 80 or c[5] not in (1, 2) or not 0 <= c[
                    4] < c[5]):
                reason = 'DEFER_SKILL_TEACHER_CHARACTER_STATE'
            elif g in invalid:
                reason = 'DEFER_INVALID_TALENT_SELECTION'
            elif rule['class'] and c[2] != rule['class']:
                reason = 'DEFER_SKILL_TEACHER_CLASS'
            elif books[g][spell] != (1, 0):
                reason = 'DEFER_SKILL_TEACHER_FLAGS'
            elif not safe[spell]:
                reason = 'DEFER_SKILL_TEACHER_METADATA'
            else:
                skill = rule['skill']
                stored = skills[g].get(skill)
                if (not stored or not 0 < stored[0] <= stored[1] or stored[
                    1] not in (75, 150, 225, 300, 375, 450)
                    or stored[1] < rule['step'] * 75):
                    reason = 'DEFER_SKILL_TEACHER_SKILL_STATE'
                for child in rule['children']:
                    chain = tc.chain(child)
                    known = ([s for s in chain if books[g].get(s) == (1, 0)
                        and (child == s or child in tc.predecessors(s))])
                    if not known:
                        reason = reason or 'DEFER_MISSING_KNOWN_TAUGHT_SPELL'
                        break
                    # Do not authorize a higher stored anchor with insufficient
                    # skill, unsupported flags anywhere in its chain or a
                    # different native skill/cap route in the two catalogs.
                    if any(books[g][s] not in ((0, 0), (1, 0)) for s in chain
                        if s in books[g]):
                        reason = reason or 'DEFER_TAUGHT_FAMILY_FLAGS'
                        break
                    for anchor in known:
                        for meta in (tc, ac):
                            eff = meta.skill_effect(anchor)
                            if (eff and (eff[0] not in skills[g] or skills[g][
                                eff[0]][0] < eff[2] or skills[g][eff[0]][
                                    1] < eff[3])):
                                reason = (reason
                                    or 'DEFER_TAUGHT_ANCHOR_SKILL_STATE')
                    if rule['skill'] == 762 and child == 33388 and stored and not any(
                        stored[1] // 75 == len(tc.predecessors(anchor))
                        + 1 for anchor in known):
                        reason = reason or 'DEFER_RIDING_TIER_ANCHOR'
                    anchors.append({'child': child,
                        'retained_enabled_anchors': known})
                for meta in (tc, ac):
                    infos = [r for r in meta.stores[
                        'SkillRaceClassInfo'].values() if r[1] == skill
                        and (not r[2] or r[2] & (1 << (c[1] - 1))) and (
                            not r[3] or r[3] & (1 << (c[2] - 1)))]
                    if not infos:
                        reason = reason or 'DEFER_SKILL_TEACHER_RACE_CLASS'
            if reason:
                excluded.append((g, spell, reason))
                continue
            selected.append((g, spell, 1, 0))
            proofs.append({'guid': g, 'wrapper': spell,
                'known_children': anchors,
                'skill': rule['skill'], 'preserved_skill': list(skills[g][rule[
                    'skill']]),
                'retired_cast_step': rule['step'], 'retired_cast_cap': rule[
                    'step'] * 75,
                'native_cast_cap_would_change': skills[g][rule['skill']][1]
                != rule['step'] * 75,
                'effects_executed': False, 'spell_rows_inserted': 0,
                'skill_rows_changed': 0})
    if not preview and (not selected or expected != len(selected)):
        fail('SKILL_TEACHER_SELECTION_MISMATCH',
            '--expect-rows must equal preview selected_rows ('
            f'{len(selected)})')
    summary = {'reviewed_candidate_rows': len(selected) + len(excluded),
        'selected_rows': len(selected),
        'selected_characters': len({r[0] for r in selected}),
        'selected_groups': len(selected),
        'selected_direct_rows': 0, 'selected_related_rows': len(selected),
        'enabled_rows_removed': len(selected),
        'disabled_rows_removed': 0, 'deferred_candidate_rows': len(excluded),
        'spell_rows_inserted': 0, 'skill_rows_changed': 0,
        'eligibility_proofs': proofs, 'deferred': dict(Counter(r[2] for r
            in excluded)),
        'native_policy': 'Retire only verified enabled redundant skill-step teachers '
        'whose children are already known through retained enabled '
        'anchors; discard the old teaching action including its '
        'cap-reset effect; preserve all skills/caps, recipes, both '
        'talent builds, items and flags; no grants'}
    return selected, excluded, [], summary, []
