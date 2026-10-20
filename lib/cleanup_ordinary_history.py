"""Opt-in preparation retirement of isolated, wholly disabled ordinary ranks."""
from collections import defaultdict, deque

from cleanup_console import fail
from cleanup_talent_relations import Relations, validate_stored, MAX_ROWS
from spells import Unsupported
import cleanup_death_coil as death_coil

POLICY = 'tc-isolated-disabled-ordinary-spell-history-v1'
INACTIVE_DEFAULT_POLICY = 'tc-disabled-ordinary-inactive-custom-defaults-v2'


def configuration_contract(settings):
    """An explicit operator assertion, never inferred from missing config."""
    if settings.get('source','player_start_all_spells') != '0':
        fail('ORDINARY_HISTORY_CONFIG_REQUIRED',
             '--inactive-custom-defaults requires [source] player_start_all_spells = 0',
             'Verify PlayerStart.AllSpells in the effective stopped TC configuration. '
             'This setting is an operator assertion; the console cannot inspect the running server configuration.')
    return {'setting':'PlayerStart.AllSpells','value':0,'evidence':'OPERATOR_ASSERTION',
            'scope':'TC playercreateinfo_spell_custom only; all other learning routes retain their guards'}


def select(state, meta, expected, *, preview=False, inactive_custom_defaults=False, native_death_coil=False):
    if native_death_coil:
        inactive_custom_defaults = True  # Its separate config contract requires AllSpells=0.
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
    native_proofs = []
    native_skills = defaultdict(list)
    if native_death_coil:
        if len(state['character_skills']) > MAX_ROWS:
            fail('ORDINARY_HISTORY_BOUND','Skill evidence exceeds the verified row bound')
        for row in state['character_skills']:
            if len(row)!=4:
                fail('DEATH_COIL_SKILL_STATE','Malformed captured skill row')
            if row[1]==death_coil.SKILL:
                native_skills[row[0]].append(row)
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
        elif nodes & graph.skill_rewards and not (native_death_coil and root==death_coil.CHAIN[0]):
            reason = 'DEFER_SKILL_REWARD_ROUTE'
        elif nodes & graph.profession_spells or any(a[1] == 776 for s in nodes for a in meta.abilities[s]):
            reason = 'DEFER_PROFESSION_OR_RIDING_RELATION'
        elif nodes & graph.unknown_skill_spells or nodes & graph.unsupported:
            reason = 'DEFER_UNSUPPORTED_RELATION_METADATA'
        elif nodes & getattr(meta,'history_default_spells',set()) and not inactive_custom_defaults:
            reason = 'DEFER_CUSTOM_DEFAULT_ROUTE'
        if not reason and native_death_coil:
            reason = (death_coil.metadata_reason(meta,nodes) if root==death_coil.CHAIN[0]
                      else 'DEFER_OUTSIDE_NATIVE_DEATH_COIL')
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
        native_proof = None
        if not reason and native_death_coil:
            reason,native_proof = death_coil.character_contract(meta,char,books[guid],native_skills[guid])
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
        if native_proof is not None:
            native_proofs.append(native_proof)
        for spell in sorted(nodes):
            flags = present.get(spell)
            route = ('ORDINARY_RANK_INACTIVE_CUSTOM_DEFAULT' if inactive_custom_defaults
                     and nodes & meta.history_default_spells else 'ORDINARY_RANK')
            if native_death_coil:
                route = death_coil.ROLE
            disposition = ('NATIVE_BASE_FROM_EXISTING_SKILL' if native_death_coil and spell==death_coil.CHAIN[0]
                           else 'SELECTED_DISABLED' if flags else 'ABSENT_NO_GRANT')
            proof.append((guid,root,spell,route,
                          disposition,*(flags or ('',''))))
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
    if inactive_custom_defaults:
        summary['selected_custom_default_rows'] = sum(
            bool(graph.members.get(graph.component[row[1]],set()) & meta.history_default_spells)
            for row in selected)
        summary['native_policy'] += '; custom starting-spell route is inactive under explicitly asserted PlayerStart.AllSpells=0'
    if native_death_coil:
        summary.update(native_base_characters=len(native_proofs),native_base_spell=death_coil.CHAIN[0],
            spell_rows_inserted=0,skill_rows_changed=0,native_base_proofs=native_proofs,
            existing_native_skill_normalizations=sum(p['existing_native_skill_normalization'] for p in native_proofs),
            native_policy='Explicitly allow native Death Coil rank 1 from existing Unholy skill after archiving exact disabled higher history; no spell insertion, higher-rank grant, skill/cap, talent/spec or login-flag change; existing native skill normalization is independent')
    return sorted(selected), sorted(excluded), proof, summary, sorted(graph.edges)
