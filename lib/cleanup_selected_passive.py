"""Retire higher direct passive ranks; existing selected lower talents are
authority.

Unlike non-talent passive rekeys, TC does NOT reconstruct these lower
ranks. AC restores their exact selected auras from character_talent.
This deliberately corrects the wrong passive effect; it never grants
trained or temporary children.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING

from cleanup_types import DatabaseState, Evidence, SelectionResult, SpellBook
from spells import Unsupported

if TYPE_CHECKING:
    from spell_metadata import Metadata


POLICY = 'tc-selected-direct-passive-authority-v1'
POLICIES = (POLICY,)
ACK = 'SELECTED_LOWER_DIRECT_PASSIVES_AUTHORITATIVE'
# Ordered DBC ranks, never numeric-ID ordering. Divine Intellect rank 4 is
# 20209 and rank 5 is 20208. These are reviewed contracts, not GUID exceptions.
RULES = {
    128: (1, (12295, 12676, 12677), [6, 6, 6], [4, 108, 108], [(4, 20, 20), (9,
        41, 41), (14, 62, 62)]),
    130: (1, (16462, 16463, 16464, 16465, 16466), [6, 0, 0], [47, 0, 0], [(i,
        0, 0) for i in range(5)]),
    1432: (2, (20205, 20206, 20207, 20209, 20208), [6, 0, 0], [108, 0, 0], [(i,
        0, 0) for i in (13, 27, 41, 55, 69)]),
    1638: (5, (27839, 27840), [6, 0, 0], [108, 0, 0], [(32, 0, 0), (66, 0,
        0)]),
    1938: (6, (48978, 49390, 49391, 49392, 49393), [6, 3, 0], [285, 0, 0], [(
        179, 0, 0), (89, 1, 0), (59, 2, 0), (44, 3, 0), (35, 4, 0)]),
}


def contract(
    tc: Metadata,
    ac: Metadata,
    family: int,
    nodes: Iterable[int],
    owned: Sequence[Sequence[int]],
    book: SpellBook,
    candidates: Iterable[int],
    cls: int,
    active: int,
) -> Evidence | None:
    rule = RULES.get(family)
    if rule is None or cls != rule[0] or nodes != set(rule[1]) or not owned:
        return None
    _, ranks, effects, auras, amounts = rule
    current = [s for s, k in owned if k == active]
    if len(current) != 1:
        return None
    chosen = current[0]
    retiring = {r[1] for r in candidates}
    # No selected rank from either spec is removed; only unselected HIGHER
    # direct ranks. A missing selected root is authorized by ownership, not by
    # TC predecessor expansion, and is left absent in SQL.
    if (not retiring or retiring & {s for s, _ in owned}
        or any(s not in ranks or ranks.index(s) <= ranks.index(chosen)
            for s in retiring)
        or any(book[s] != (1, 0) for s in retiring)):
        return None
    for meta in (tc, ac):
        for index, s in enumerate(ranks):
            row = meta.spells.get(s, [])
            talent = meta.talent_rows.get(s, [])
            attrs = [448 if family == 1638 else 464, 0, 0, 0, 0, 512 if family
                == 1938 else 0, 0, 0]
            gates = [0] * 16
            if family == 128:
                gates[0] = 131072
            expect = [0] * 48
            expect[:3] = effects
            expect[3:6] = [int(x != 0) for x in effects]
            expect[9:12] = amounts[index]
            expect[15:18] = [int(x == 6) for x in effects]
            expect[24:27] = auras
            if family == 128:
                expect[40:42] = [2, 2]
            elif family == 1432:
                expect[39] = 9
            elif family == 1638:
                expect[39] = 8
            elif family == 1938:
                expect[39] = 1
            if (len(row) < 212 or row[4:12] != attrs or row[12:28] != gates
                or row[71:119] != expect
                or meta.talents.get(s) != (family, index + 1)
                or meta.chain(s) != ranks
                or len(talent) != 23 or tuple(talent[4:9]) != ranks + (0,
                ) * (5 - len(ranks))
                or talent[9:13] != [0] * 4 or talent[13:19] != ([484, 0, 0,
                    0, 0, 0] if family == 1638 else[0] * 6)
                or talent[19:] != [0] * 4 or talent != tc.talent_rows[s]
                or not meta.stores['TalentTab'].get(talent[1], [0] * 21)[
                    20] & (1 << (cls - 1))
                or meta.scripts[s] or meta.learns[s] or meta.effect_learns[
                    s]
                or meta.learn_parents[s] or meta.requires[s]
                or meta.prerequisite_users[s]
                or meta.aura_owners[s] or s in meta.world_aura_owners or s
                in meta.additional
                or s in meta.trainer_taught or s in getattr(meta,
                    'history_default_spells', set())
                or set(meta.talent_learn_owners.get(s, ()))):
                return None
            # Only class-skill bookkeeping; no profession/riding/reward route.
            if meta.abilities[s] != tc.abilities[s] or not meta.abilities[s]:
                return None
            for ability in meta.abilities[s]:
                line = meta.stores['SkillLine'].get(ability[1], [])
                if (len(line) < 2 or line[1] != 7 or ability[9] != 0
                    or ability[8] != 0
                    or ability[3] != 0 or ability[4] not in (0, 1 << (cls
                        - 1))
                    or any(ability[5:7]) or ability[7] != 1):
                    return None
            try:
                meta.check_spell(s)
            except Unsupported: return None
    return {'contract': 'SELECTED_LOWER_DIRECT_PASSIVE_AUTHORITY_V1',
        'talent_family': family,
        'ordered_direct_ranks': list(ranks),
        'active_selected_spell': chosen,
        'retired_unselected_higher_ranks': sorted(retiring),
        'selected_spell_groups': [list(r) for r in owned],
        'source_lower_rank_reconstructed': False,
        'selected_aura_restored_by': 'AC addTalent/_addTalentAurasAndSpells',
        'availability_change': 'Wrong higher passive effects retired; exact selected lower aura '
        'restored natively',
        'sql_insertions': 0, 'sql_flag_changes': 0,
        'talent_rows_changed': 0, 'skill_rows_changed': 0}


def select(
    state: DatabaseState,
    tc: Metadata,
    ac: Metadata,
    expected: int | None = None,
    *,
    preview: bool = False,
) -> SelectionResult:
    from cleanup_ownership import select as ownership
    result, excluded, proof, summary, edges = ownership(state, tc, expected,
        preview=preview,
        selected_direct_passives=True, target=ac)
    summary['eligibility_proofs'] = summary.pop('native_owner_proofs')
    summary['native_policy'] = (
        'Retire only unselected enabled higher DIRECT passive ranks in five '
        'reviewed families; existing lower selected talents in both specs '
        'remain authoritative. TC does not reconstruct these direct lower '
        'ranks; AC restores exact selected auras natively. Deliberate effect '
        'correction; no trained ranks, temporary children, SQL insertion, '
        'flags, ownership, skills/caps, profession slots or login changes; '
        'pending resets and unsupported routes defer')
    return result, excluded, proof, summary, edges
