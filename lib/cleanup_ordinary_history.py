"""Opt-in preparation retirement of isolated, wholly disabled ordinary ranks."""
from collections import defaultdict, deque

from cleanup_console import fail
from cleanup_talent_relations import Relations, validate_stored, MAX_ROWS
from spells import Unsupported

POLICY = 'tc-isolated-disabled-ordinary-spell-history-v1'


def select(state, meta, expected, *, preview=False):
    stored = state['character_spell']
    validate_stored(stored)
    graph = Relations(meta)
    # Protect every talent-reachable component even when its family fails a
    # cleanup contract. A rejected talent route never becomes ordinary history.
    protected = set()
    pending = deque(sorted({graph.component[s] for s in meta.talents}))
    while pending:
        component = pending.popleft()
        if component in protected:
            continue
        protected.add(component)
        pending.extend(sorted(graph.next[component] - protected))
        if len(protected) > len(graph.members):
            fail('ORDINARY_HISTORY_BOUND', 'Talent ancestry exceeds the verified catalog')
    candidates = [r for r in stored if r[3] == 1 and r[1] not in meta.talents
                  and graph.component.get(r[1]) not in protected]
    if preview:
        expected = len(candidates)
    if (expected is None or len(candidates) != expected or expected > 500000
            or expected < (0 if preview else 1)):
        fail('ORDINARY_HISTORY_SELECTION_MISMATCH',
             '--expect-review-rows must equal reviewed_candidate_rows from this ordinary-history preview')
    chars = {r[0]: r for r in state['characters']}
    invalid, ownership = set(), set()
    for guid, spell, group in state['character_talent']:
        char, identity = chars.get(guid), meta.talents.get(spell)
        if char is None or identity is None:
            invalid.add(guid)
            continue
        tab = meta.stores['TalentTab'].get(meta.talent_rows[spell][1], [])
        key = (guid, identity[0], group)
        if (char[2] not in (1,2,3,4,5,6,7,8,9,11) or len(tab) <= 20
                or not tab[20] & (1 << (char[2]-1)) or not 0 <= group < char[5]
                or key in ownership):
            invalid.add(guid)
        ownership.add(key)
    books = defaultdict(dict)
    for guid, spell, active, disabled in stored:
        books[guid][spell] = (active, disabled)
    groups = defaultdict(list)
    for row in candidates:
        groups[row[0], graph.component.get(row[1], row[1])].append(row)
    selected, excluded, proof, bindings = [], [], [], set()
    catalog = {}
    for root in sorted({r for _,r in groups}):
        nodes = graph.members.get(root, set())
        reason = ''
        if not nodes:
            reason = 'DEFER_UNKNOWN_SPELL'
        elif graph.incoming[root] or graph.next[root]:
            reason = 'DEFER_LEARNING_OR_REQUIREMENT_ROUTE'
        elif (nodes & set(getattr(meta,'aura_owners',{}))
              or nodes & set(getattr(meta,'world_aura_owners',{}))
              or nodes & set(getattr(meta,'additional',set()))):
            reason = 'DEFER_TALENT_OR_AURA_ROUTE'
        elif nodes & graph.skill_rewards:
            reason = 'DEFER_SKILL_REWARD_ROUTE'
        elif nodes & graph.profession_spells or any(a[1] == 776 for s in nodes for a in meta.abilities[s]):
            reason = 'DEFER_PROFESSION_OR_RIDING_RELATION'
        elif nodes & graph.unknown_skill_spells or nodes & graph.unsupported:
            reason = 'DEFER_UNSUPPORTED_RELATION_METADATA'
        elif nodes & getattr(meta,'history_default_spells',set()):
            reason = 'DEFER_CUSTOM_DEFAULT_ROUTE'
        for spell in sorted(nodes) if not reason else ():
            if set(meta.spells[spell][71:74]) & {36,40,44,47,118}:
                reason = 'DEFER_LEARN_OR_SKILL_EFFECT'
                break
            if any(meta.script_policy.get(name) != 'NO_SPELLBOOK_MUTATION' for name in meta.scripts[spell]):
                reason = 'DEFER_SCRIPTED_SPELL_FAMILY'
                break
            try:
                meta.check_spell(spell)
            except Unsupported as error:
                reason = 'DEFER_RELATION_' + error.reason
                break
        catalog[root] = (nodes, reason)
    for (guid,root), anchors in sorted(groups.items()):
        nodes, reason = catalog[root]
        char = chars.get(guid)
        if (char is None or char[2] not in (1,2,3,4,5,6,7,8,9,11)
                or not 1 <= char[1] <= 32 or not 1 <= char[3] <= 80
                or char[5] not in (1,2) or not 0 <= char[4] < char[5]):
            reason = 'DEFER_INVALID_CHARACTER_STATE'
        elif char[6]:
            reason = 'DEFER_ONLINE_CHARACTER'
        elif char[7] & 4:
            reason = 'DEFER_PENDING_NATIVE_RESET'
        elif guid in invalid:
            reason = 'DEFER_INVALID_TALENT_SELECTION'
        present = {s:flags for s,flags in books[guid].items() if s in nodes}
        if not reason and any(a not in (0,1) or d not in (0,1) for a,d in present.values()):
            reason = 'DEFER_INVALID_RELATED_FLAGS'
        if not reason and any(d != 1 for a,d in present.values()):
            reason = 'DEFER_ENABLED_RELATED_SPELL'
        if not reason:
            race_mask, class_mask = 1 << (char[1]-1), 1 << (char[2]-1)
            for spell in sorted(nodes):
                abilities = meta.abilities[spell]
                infos = meta.stores.get('SkillRaceClassInfo',{}).values()
                if abilities and not any(info[1] == a[1]
                    and (not a[3] or a[3] & race_mask) and (not a[4] or a[4] & class_mask)
                    and (not info[2] or info[2] & race_mask) and (not info[3] or info[3] & class_mask)
                    for a in abilities for info in infos):
                    reason = 'DEFER_SPELL_RACE_CLASS'
                    break
        if reason:
            excluded.extend((guid,row[1],reason) for row in anchors)
            continue
        for spell in sorted(nodes):
            flags = present.get(spell)
            proof.append((guid,root,spell,'ORDINARY_RANK',
                          'SELECTED_DISABLED' if flags else 'ABSENT_NO_GRANT',*(flags or ('',''))))
            if flags:
                selected.append((guid,spell,*flags))
            bindings.update((root,spell,name) for name in meta.scripts[spell])
        if len(proof) > MAX_ROWS or len(selected) > 500000:
            fail('ORDINARY_HISTORY_BOUND','Ordinary history selection or evidence exceeds its bound')
    if not selected and not preview:
        fail('HISTORY_NO_ELIGIBLE_ROWS','No isolated wholly disabled ordinary spell family qualifies')
    summary = {'reviewed_candidate_rows':len(candidates),'selected_rows':len(selected),
        'selected_characters':len({r[0] for r in selected}),
        'selected_groups':len({(r[0],r[1]) for r in proof}),
        'selected_direct_rows':0,'selected_related_rows':len(selected),
        'deferred_candidate_rows':len(excluded),
        'reviewed_script_binding_count':len(bindings),
        'native_policy':'Archive isolated wholly disabled ordinary rank families; no talent, enabled spell, skill, grant or login-flag change; stored future reactivation/retraining history is discarded'}
    return sorted(selected), sorted(excluded), proof, summary, sorted(graph.edges)
