"""Opt-in repair of conflicting spell rows; selected talents are authoritative.

V1-v4 remove reviewed rows. V5 rekeys known higher passive anchors downward.
Active children require correct parents AND known child/prefix evidence;
TC load does not recast learn-effect talents.
"""
from collections import Counter, defaultdict, deque
import hashlib
from pathlib import Path
import re

from cleanup_console import fail
from cleanup_talent_relations import Relations, MAX_ROWS, validate_stored
from spells import Unsupported, native_passive_rule

POLICY = 'tc-selected-talent-ownership-repair-v1'
ACK = 'SELECTED_TALENTS_AUTHORITATIVE'
FOREIGN_POLICY = 'tc-unselected-foreign-talent-retirement-v2'
FOREIGN_ACK = 'UNSELECTED_FOREIGN_FAMILIES_ONLY'
PREFIX_POLICY = 'tc-selected-native-passive-prefix-repair-v3'
PREFIX_ACK = 'RETAIN_AUTHORIZED_HIGHER_ANCHORS'
AURA_ALIAS_POLICY = 'tc-unselected-reviewed-aura-alias-retirement-v4'
AURA_ALIAS_ACK = 'UNSELECTED_REVIEWED_AURA_ALIASES_ONLY'
REKEY_POLICY = 'tc-selected-known-passive-rank-rekey-v5'
REKEY_ACK = 'ONLY_ALREADY_KNOWN_SELECTED_LOWER_PASSIVES'
POLICIES = (POLICY, FOREIGN_POLICY, PREFIX_POLICY, AURA_ALIAS_POLICY, REKEY_POLICY)

# Literal registration aliases of a single protected implementation. No alias
# discovery, arbitrary constructor arguments or transitive script inference.
AURA_ALIASES = {
    'spell_pal_improved_devotion_aura': (1422, (20138,20139,20140), 'SPELL_PALADIN_IMPROVED_DEVOTION_AURA', 63514),
    'spell_pal_improved_concentraction_aura': (1450, (20254,20255,20256), 'SPELL_PALADIN_IMPROVED_CONCENTRACTION_AURA', 63510),
    'spell_pal_sanctified_retribution': (1756, (31869,), 'SPELL_PALADIN_SANCTIFIED_RETRIBUTION_AURA', 63531),
    'spell_pal_swift_retribution': (2148, (53379,53484,53648), 'SPELL_PALADIN_SANCTIFIED_RETRIBUTION_AURA', 63531),
}
AURA_HELPERS = {
    63510: ([151323008,0,17,1114112,2097152,0,0,4], [0,65,65], [1,1,1,0,0,0], [0,234,234]),
    63514: ([151323008,0,17,1114112,2097152,0,0,4], [0,65,0], [1,1,0,0,0,0], [0,118,0]),
    63531: ([151323008,0,17,1114112,2097152,0,0,0], [0,65,65], [0,1,1,0,0,0], [0,79,193]),
}


def registered_aura_aliases(text):
    if 'spell_pal_improved_aura' not in safe_script_classes(text):
        return set()
    bindings = defaultdict(list)
    for match in re.finditer(r'\bRegisterSpellScriptWithArgs\(\s*(\w+)\s*,\s*"(\w+)"\s*,\s*(\w+)\s*\)\s*;', text):
        bindings[match[2]].append((match[1],match[3]))
    return {name for name, (_,_,arg,spell) in AURA_ALIASES.items()
            if bindings[name] == [('spell_pal_improved_aura',arg)]
            and re.search(r'\b'+arg+r'\s*=\s*'+str(spell)+r'\b',text)}


def aura_alias_contract(meta, family, nodes, owned, book):
    """Keep only exact unselected families and their inert area-aura helpers."""
    match = [(name,rule) for name,rule in AURA_ALIASES.items() if rule[0] == family]
    if len(match) != 1 or owned:
        return None
    name, (_,ranks,arg,helper) = match[0]
    if set(ranks) != nodes:
        return None
    for rank, spell in enumerate(ranks,1):
        if (meta.talents.get(spell) != (family,rank) or meta.scripts[spell] != {name}
                or meta.script_policy.get(name) != 'NO_SPELLBOOK_MUTATION'):
            return None
    attrs, effects, targets, auras = AURA_HELPERS[helper]
    row = meta.spells.get(helper, [])
    if (helper in book or len(row) < 212 or row[4:12] != attrs or row[71:74] != effects
            or row[86:92] != targets or row[95:98] != auras or row[116:119] != [0,0,0]
            or meta.chain(helper) != (helper,) or meta.scripts[helper] or meta.abilities[helper]
            or meta.learns[helper] or meta.effect_learns[helper] or meta.learn_parents[helper]
            or meta.requires[helper] or meta.prerequisite_users[helper]
            or helper in meta.talents or helper in meta.additional or meta.aura_owners[helper]
            or helper in meta.world_aura_owners):
        return None
    try:
        meta.check_spell(helper)
    except Unsupported:
        return None
    return {'contract':'UNSELECTED_REVIEWED_AURA_ALIAS_V1','script_alias':name,
            'implementation':'spell_pal_improved_aura','constructor_argument':arg,
            'area_aura_helper':helper,'helper_stored':False,'family_talent_spells':list(ranks),
            'native_action':'Cast/remove only the exact area aura; no spellbook, talent, skill or database mutation'}


def foreign_class_mask(meta, roots, cls):
    """A whole talent family must belong exclusively to one other player class."""
    tabs = [meta.stores['TalentTab'].get(meta.talent_rows[s][1], []) for s in roots]
    masks = {tab[20] if len(tab)>20 else 0 for tab in tabs}
    supported = {1 << (c-1) for c in (1,2,3,4,5,6,7,8,9,11)}
    return next(iter(masks)) if len(masks)==1 and masks <= supported and masks != {1 << (cls-1)} else 0


def safe_script_classes(text):
    """Additional skill/ownership guard; unknown aliases remain unsupported."""
    safe, unsafe = set(), set()
    writes = re.compile(r'\b(?:SetSkill|LearnDefaultSkill|RemoveSkill|SetFreePrimaryProfessions|'
                        r'LearnSkillRewardedSpells|UpdateSkillsForLevel|ResetTalents|AddTalent|'
                        r'RemoveTalent|SetUsedTalentCount|SetFreeTalentPoints|SetTalentGroupsCount|'
                        r'ActivateTalentGroup)\s*\(|\b(?:CharacterDatabase|WorldDatabase)\b')
    for match in re.finditer(r'\b(?:class|struct)\s+(spell_\w+)\b[^;{]*\{', text):
        start = end = match.end()
        depth = 1
        while depth and end < len(text):
            depth += (text[end] == '{') - (text[end] == '}')
            end += 1
        if depth or writes.search(text[start:end-1]):
            unsafe.add(match[1])
        else:
            safe.add(match[1])
    return safe - unsafe


def script_contracts(source_dir, *, reviewed_aura_aliases=False):
    """Inspect only protected pinned spell implementations, never guessed aliases."""
    if source_dir is None:
        return set()
    from cleanup_console import PROFILE
    safe, unsafe = set(), set()
    for line in (PROFILE/'trinitycore-semantic.sha256').read_text().splitlines():
        checksum, name = line.split(None, 1)
        name = name.strip().lstrip('*')
        if not name.startswith('src/server/scripts/Spells/') or not name.endswith('.cpp'):
            continue
        data = (Path(source_dir)/name).read_bytes()
        if hashlib.sha256(data).hexdigest() != checksum:
            fail('OWNERSHIP_SCRIPT_SOURCE_DRIFT', 'Protected source script content differs')
        text = data.decode()
        defined = set(re.findall(r'\b(?:class|struct)\s+(spell_\w+)\b[^;{]*\{', text))
        approved = safe_script_classes(text)
        safe.update(approved)
        unsafe.update(defined - approved)
        if reviewed_aura_aliases and name == 'src/server/scripts/Spells/spell_paladin.cpp':
            safe.update(registered_aura_aliases(text))
    if reviewed_aura_aliases:
        # The protected loader forwards the literal registration tuple to the
        # constructor. A script alias is not required to match its C++ class.
        header = 'src/server/game/Scripting/ScriptMgr.h'
        expected = {n.strip().lstrip('*'):h for h,n in (line.split(None,1) for line in
            (PROFILE/'trinitycore-semantic.sha256').read_text().splitlines())}
        if hashlib.sha256((Path(source_dir)/header).read_bytes()).hexdigest() != expected[header]:
            fail('OWNERSHIP_SCRIPT_SOURCE_DRIFT', 'Protected script registration loader differs')
    return safe - unsafe


def native_family(meta, roots, cls):
    """Accept the existing reviewed passive contracts or exact Fiery Payback."""
    if all(not meta.learns[s] and not meta.effect_learns[s] for s in roots):
        return True
    if all(native_passive_rule(s, meta, meta, cls) for s in roots):
        return True
    if set(roots) <= {64353, 64357} and cls == 8:
        for s in (64353, 64357):
            children = [44440, 64350, 0] if s == 64353 else [44441, 64349, 0]
            row = meta.spells.get(s, [])
            if (len(row) < 119 or row[71:74] != [36, 36, 0]
                    or row[116:119] != children or row[12] or row[20]
                    or any(meta.spells[c][71:74] != [6, 6, 6] if c in (44440, 44441)
                           else meta.spells[c][71:74] != [6, 0, 0] for c in children if c)):
                return False
        return True
    return False


def native_masks(meta, choices, nodes):
    """TC-known prefix of selected roots; requirements are not spell grants."""
    masks = defaultdict(int)
    pending = deque((s, 1 << group) for s, group in choices)
    while pending:
        spell, mask = pending.popleft()
        new = mask & ~masks[spell]
        if not new:
            continue
        if spell not in nodes:
            fail('OWNERSHIP_RELATION_ESCAPE', 'Native selected route leaves its reviewed family')
        masks[spell] |= new
        if spell not in meta.talents:
            pending.extend((s, new) for s in meta.predecessors(spell))
        pending.extend((child, new) for child, _, _ in meta.learns[spell] + meta.effect_learns[spell])
    return masks


def passive_rekeys(meta, owned, book, nodes, candidates, cls, active):
    """Rekey single enabled child anchors downward, never infer a higher grant.

    TC loading reconstructs non-talent predecessors from the OLD enabled child;
    the selected learn-effect parent alone is deliberately insufficient evidence.
    Both selected builds remain intact. AC restores their exact children natively.
    """
    rules = [native_passive_rule(s, meta, meta, cls) for s, _ in owned]
    current = [s for s, group in owned if group == active]
    if not owned or not all(rules) or len(current) != 1:
        return [], 'DEFER_OUTSIDE_NATIVE_REKEY_POLICY'
    rule = rules[0]
    if any(r != rule for r in rules):
        return [], 'DEFER_NATIVE_REKEY_CONTRACT'
    children = set().union(*(set(chain) for chain in rule['chains']))
    if any(s in book and s not in current and s in meta.talents
           and s not in {owner for owner, _ in owned} for s in nodes):
        return [], 'DEFER_DIRECT_TALENT_CONFLICT'
    if set(book) & (nodes - children - set(rule['owners'])):
        return [], 'DEFER_NATIVE_REKEY_EXTRA_STATE'
    exact = set(rule['children'][rule['owners'].index(current[0])])
    mappings = []
    for chain in rule['chains']:
        targets = exact & set(chain)
        anchors = set(book) & set(chain)
        if len(targets) != 1 or len(anchors) != 1:
            return [], 'DEFER_NATIVE_REKEY_ANCHOR_COUNT'
        target, anchor = next(iter(targets)), next(iter(anchors))
        if book[anchor] != (1,0):
            return [], 'DEFER_NATIVE_REKEY_ANCHOR_FLAGS'
        if target == anchor:
            continue
        if target in book or target not in meta.predecessors(anchor):
            return [], 'DEFER_NATIVE_REKEY_NOT_KNOWN_LOWER'
        mappings.append((anchor,target))
    if not mappings or {s for s, _ in mappings} != {r[1] for r in candidates}:
        return [], 'DEFER_OUTSIDE_NATIVE_REKEY_POLICY'
    return sorted(mappings), None


def select(state, meta, expected=None, *, preview=False, source_dir=None, foreign_class_families=False,
           native_passive_prefixes=False, reviewed_aura_aliases=False, native_passive_rekey=False,
           selected_direct_passives=False, target=None):
    """Return deterministic old rows and proofs, never mutate source inputs."""
    stored = state['character_spell']
    if sum((foreign_class_families,native_passive_prefixes,reviewed_aura_aliases,native_passive_rekey,selected_direct_passives)) > 1:
        fail('OWNERSHIP_POLICY_CONFLICT', 'Ownership extensions are separate policies')
    validate_stored(stored)
    if len(stored) > MAX_ROWS or not 1 <= len(state['characters']) <= 40000:
        fail('OWNERSHIP_BOUND', 'Captured source scope exceeds reviewed bounds')
    chars = {r[0]: r for r in state['characters']}
    if len(chars) != len(state['characters']):
        fail('OWNERSHIP_INPUT_INVALID', 'Duplicate character keys')
    graph = Relations(meta)
    safe_scripts = script_contracts(source_dir,reviewed_aura_aliases=reviewed_aura_aliases)
    catalog, related = {}, defaultdict(set)
    for family in sorted(graph.families):
        nodes, reason = graph.family(family, True)
        catalog[family] = (nodes, reason)
        for spell in nodes:
            related[spell].add(family)
    if sum(len(nodes) for nodes, _ in catalog.values()) > MAX_ROWS:
        fail('OWNERSHIP_BOUND', 'Relationship catalog exceeds reviewed bounds')
    books, choices = defaultdict(dict), defaultdict(list)
    for g, s, a, d in stored:
        if g not in chars:
            fail('OWNERSHIP_INPUT_INVALID', 'Out-of-scope spell row')
        books[g][s] = (a, d)
    invalid, seen = set(), set()
    for g, s, group in state['character_talent']:
        c = chars.get(g)
        identity = meta.talents.get(s)
        if c is None:
            fail('OWNERSHIP_INPUT_INVALID', 'Out-of-scope talent row')
        tab = meta.stores['TalentTab'].get(meta.talent_rows[s][1], []) if identity else []
        key = (g, identity[0] if identity else -1, group)
        if (not identity or s in meta.invalid_talents or len(tab) <= 20
                or selected_direct_passives and (target is None or target.talents.get(s)!=identity or s in target.invalid_talents
                    or target.talent_rows.get(s)!=meta.talent_rows.get(s)
                    or target.stores['TalentTab'].get(meta.talent_rows[s][1],[0]*21)[20]!=tab[20])
                or not 1 <= c[2] <= 32 or not tab[20] & (1 << (c[2]-1))
                or c[5] not in (1,2) or group not in (0,1) or group >= c[5] or key in seen):
            invalid.add(g)
        elif identity:
            choices[g, identity[0]].append((s, group))
        seen.add(key)
    grouped, native_cache = defaultdict(list), {}
    relation_work = native_work = prefix_work = 0
    for g, s, a, d in stored:
        for family in sorted(related[s]):
            relation_work += 1
            if relation_work > MAX_ROWS:
                fail('OWNERSHIP_BOUND', 'Source relationship review exceeds the bounded work budget')
            nodes, _ = catalog[family]
            if (g, family) not in native_cache:
                native_work += len(nodes)
                if native_work > MAX_ROWS:
                    fail('OWNERSHIP_BOUND', 'Native derivation review exceeds the bounded work budget')
                native_cache[g, family] = native_masks(meta, choices[g, family], nodes)
            masks = native_cache[g, family]
            # Trained ranks are preserved when their selected direct root owns
            # them. This is ownership evidence only, never a higher-rank grant.
            root = meta.first(s)
            for owner, group in choices[g, family]:
                if s not in meta.talents and root == owner:
                    masks[s] |= 1 << group
            active_mask = 1 << chars[g][4] if chars[g][4] in (0,1) else 1
            if not masks.get(s) or d != int(not masks[s] & active_mask):
                grouped[g, family].append((g, s, a, d))
    selected, excluded, proof, accepted, native_proofs, rekeys = {}, {}, [], [], [], []
    for (g, family), candidates in sorted(grouped.items()):
        c = chars[g]
        nodes, reason = catalog[family]
        owned = sorted(choices[g, family])
        candidate_spells = {row[1] for row in candidates}
        foreign_mask = foreign_class_mask(meta,graph.families[family],c[2]) if c[2] in (1,2,3,4,5,6,7,8,9,11) else 0
        if c[2] not in (1,2,3,4,5,6,7,8,9,11) or c[1] not in (1,2,3,4,5,6,7,8,10,11) or not 1 <= c[3] <= 80 or c[5] not in (1,2) or not 0 <= c[4] < c[5]:
            reason = 'DEFER_OWNERSHIP_CHARACTER_STATE'
        elif c[6]:
            reason = 'DEFER_ONLINE_CHARACTER'
        elif c[7] & 4:
            reason = 'DEFER_PENDING_NATIVE_RESET'
        elif g in invalid:
            reason = 'DEFER_INVALID_TALENT_SELECTION'
        elif any(len(related[s]) != 1 for s in nodes):
            reason = 'DEFER_AMBIGUOUS_TALENT_DERIVATION'
        elif foreign_class_families and (not foreign_mask or owned):
            reason = 'DEFER_OUTSIDE_FOREIGN_TALENT_POLICY'
        elif not foreign_class_families and any(meta.stores['TalentTab'].get(meta.talent_rows[s][1], [0]*21)[20] != 1 << (c[2]-1) for s in graph.families[family]):
            reason = 'DEFER_FOREIGN_CLASS_TALENT'
        elif any(a not in (0,1) or d not in (0,1) for s, (a,d) in books[g].items() if s in nodes):
            reason = 'DEFER_INVALID_RELATED_FLAGS'
        elif any(set(meta.spells[s][95:98]) & {30,98} for s in nodes):
            reason = 'DEFER_TALENT_SKILL_AURA'
        elif any(not meta.scripts[s] <= safe_scripts for s in nodes):
            reason = 'DEFER_OWNERSHIP_SCRIPT_CONTRACT'
        masks = native_masks(meta, owned, nodes)
        prefix_anchors = {}
        family_rekeys = []
        alias_proof = None
        direct_proof = None
        if not reason and selected_direct_passives:
            from cleanup_selected_passive import contract
            try:
                direct_proof = contract(meta,target,family,nodes,owned,books[g],candidates,c[2],c[4]) if target is not None else None
            except Unsupported:
                direct_proof = None
            if direct_proof is None:
                reason = 'DEFER_SELECTED_DIRECT_PASSIVE_CONTRACT'
            elif any(not any(meta.talents.get(s,(None,0))[0]==parent and k==group and meta.talents[s][1]>=minimum+1
                             for s,k in choices[g,parent])
                     for owner,group in owned for parent,minimum in zip(meta.talent_rows[owner][13:16],meta.talent_rows[owner][16:19]) if parent):
                reason = 'DEFER_SELECTED_DIRECT_PREREQUISITE'
        if not reason and reviewed_aura_aliases:
            alias_proof = aura_alias_contract(meta,family,nodes,owned,books[g])
            if alias_proof is None:
                reason = 'DEFER_OUTSIDE_REVIEWED_AURA_ALIAS_POLICY'
        if not reason and native_passive_prefixes:
            try:
                if not owned or not all(native_passive_rule(s, meta, meta, c[2]) for s, _ in owned):
                    reason = 'DEFER_OUTSIDE_NATIVE_PREFIX_POLICY'
                elif candidate_spells & set(meta.talents):
                    reason = 'DEFER_DIRECT_TALENT_CONFLICT'
            except Unsupported:
                reason = 'DEFER_OUTSIDE_NATIVE_PREFIX_POLICY'
        if not reason and owned:
            if any(meta.requires[s] for s in nodes):
                reason = 'DEFER_SELECTED_PREREQUISITE_CONTRACT'
            try:
                if not reason and not native_family(meta, [s for s, _ in owned], c[2]):
                    reason = 'DEFER_SELECTED_NATIVE_CONTRACT'
            except Unsupported:
                reason = 'DEFER_SELECTED_NATIVE_CONTRACT'
            if not reason:
                for s, group in owned:
                    flags = books[g].get(s)
                    if group == c[4] and flags != (1,0) and not (direct_proof and flags is None):
                        reason = 'DEFER_SELECTED_ACTIVE_ANCHOR'
                    elif flags and flags[1] != int(not masks[s] & (1 << c[4])):
                        reason = 'DEFER_SELECTED_OWNER_FLAGS'
            if not reason and native_passive_rekey:
                try:
                    family_rekeys, reason = passive_rekeys(meta,owned,books[g],nodes,candidates,c[2],c[4])
                except Unsupported:
                    reason = 'DEFER_NATIVE_REKEY_CONTRACT'
            if family_rekeys and not reason:
                rekeys.extend((g,old,new) for old,new in family_rekeys)
            # This separate opt-in policy changes keys, not flags or ownership.
            # Its enabled old anchors prove every mapped lower child was known.
            if native_passive_rekey and not reason and not family_rekeys:
                reason = 'DEFER_OUTSIDE_NATIVE_REKEY_POLICY'
            if not reason:
                if native_passive_prefixes:
                    prefix_work += len(masks) * len(books[g])
                    if prefix_work > MAX_ROWS:
                        fail('OWNERSHIP_BOUND', 'Native prefix anchor review exceeds the bounded work budget')
                for s, mask in (() if native_passive_rekey else masks.items()):
                    if s in books[g] and books[g][s][1] != int(not mask & (1 << c[4])):
                        # Remove only disabled non-talent predecessors which
                        # an authorized, retained ENABLED higher rank restores.
                        # Never use a retiring/unowned/inactive anchor or infer
                        # a missing exact child from its learn-effect parent.
                        anchors = sorted(anchor for anchor, (_, disabled) in books[g].items()
                            if native_passive_prefixes and s not in meta.talents
                            and books[g][s][1] == 1 and mask & (1 << c[4])
                            and anchor in nodes and anchor != s and not disabled
                            and anchor not in meta.talents and masks.get(anchor, 0) & (1 << c[4])
                            and anchor not in candidate_spells
                            and s in meta.predecessors(anchor))
                        if anchors:
                            prefix_anchors[s] = anchors
                        else:
                            reason = 'DEFER_OWNED_CHILD_FLAGS'
            if not reason and not native_passive_rekey:
                retiring = {r[1] for r in candidates}
                retained_known = set()
                for s, (_, disabled) in books[g].items():
                    if not disabled and s not in retiring:
                        retained_known.add(s)
                        if s not in meta.talents:
                            retained_known.update(meta.predecessors(s))
                # TC _LoadSpells passes loading=true: learn-effect talents
                # are not recast merely because their parent row is retained.
                # AC's native restoration is not proof of TC source availability.
                if any(mask & (1 << c[4]) and s not in meta.talents and s not in retained_known
                       for s, mask in masks.items()):
                    reason = 'DEFER_MISSING_NATIVE_CHILD_ANCHOR'
        if not reason and native_passive_rekey and not owned:
            reason = 'DEFER_OUTSIDE_NATIVE_REKEY_POLICY'
        if not reason and native_passive_prefixes and not prefix_anchors:
            reason = 'DEFER_NO_NATIVE_PREFIX_CONFLICT'
        if reason:
            for row in candidates:
                excluded[row[0], row[1]] = (*row[:2], reason)
            continue
        accepted.append((g, family))
        for row in candidates:
            selected[row[0], row[1]] = row
        if len(proof) + len(nodes) > MAX_ROWS:
            fail('OWNERSHIP_BOUND', 'Ownership provenance exceeds the bounded row budget')
        retiring = {r[1] for r in candidates}
        retained = {s: flags for s, flags in books[g].items() if s in nodes and s not in retiring}
        native_proofs.append({'guid': g, 'talent_family': family, 'active_spec': c[4],
            **({'contract':'SELECTED_ALREADY_KNOWN_LOWER_PASSIVE_V1',
                'rekeys': [{'from_spell':old,'to_spell':new,
                           'known_source_predecessors':list(meta.predecessors(old)),
                           'active_owner':next(s for s,k in owned if k==c[4])}
                          for old,new in family_rekeys],
                'native_source_rule':'TC loading recursively knows the mapped lower non-talent rank from the existing enabled higher child; selected parents alone never prove availability'}
               if native_passive_rekey else {}),
            **(alias_proof or {}),
            **(direct_proof or {}),
            **({'contract':'UNSELECTED_FOREIGN_CLASS_FAMILY','character_class':c[2],
                'foreign_class_mask':foreign_mask,'family_talent_spells':sorted(graph.families[family])}
               if foreign_class_families else {}),
            **({'contract':'RETAINED_NATIVE_PASSIVE_PREFIX_V1',
                'prefix_restore_anchors': [[s, anchors] for s, anchors in sorted(prefix_anchors.items())],
                'retired_prefix_flags': [[s, *books[g][s]] for s in sorted(prefix_anchors)],
                'native_source_rule':'Non-talent AddSpell recursively restores predecessors from retained enabled anchors; no talent load recast assumed'}
               if native_passive_prefixes else {}),
            'selected_spell_groups': [list(row) for row in owned],
            'native_authorization_masks': [[s, mask] for s, mask in sorted(masks.items()) if mask],
            'retained_source_flags': [[s, *flags] for s, flags in sorted(retained.items())],
            'active_child_anchors': [[s, sorted(anchor for anchor, (_, disabled) in retained.items()
                if not disabled and (anchor == s or anchor not in meta.talents and s in meta.predecessors(anchor)))]
                for s, mask in sorted(masks.items()) if s not in meta.talents and mask & (1 << c[4])],
            'sql_insertions': 0, 'sql_flag_changes': 0,
            **({'sql_key_changes':len(family_rekeys),'post_rekey_source_flags':[[new,1,0] for _,new in family_rekeys]} if native_passive_rekey else {})})
        for s in sorted(nodes):
            flags = books[g].get(s)
            action = ('REKEY_KNOWN_SELECTED_LOWER' if native_passive_rekey else 'REMOVE_CONFLICTING_ENABLED' if flags and not flags[1] else 'REMOVE_CONFLICTING_DISABLED') if (g,s) in selected else 'PRESERVED_AUTHORIZED' if flags else 'AUTHORIZED_NATIVE_DIRECT_PASSIVE' if direct_proof and s in meta.talents and masks[s] else 'AUTHORIZED_NATIVE_CHILD' if masks[s] else 'ABSENT_NO_GRANT'
            proof.append((g, family, s, 'SELECTED_TALENT_AUTHORITY', action, *(flags or ('',''))))
    # A shared row can never be accepted through one family and deferred by another.
    for key in excluded:
        selected.pop(key, None)
    result = sorted(selected.values())
    if len(result) > 500000:
        fail('OWNERSHIP_BOUND', 'More than 500000 exact selected spell rows')
    if native_passive_rekey and len(result) > 50000:
        fail('OWNERSHIP_BOUND', 'More than 50000 exact passive rekeys')
    if not preview and (not result or expected != len(result)):
        fail('OWNERSHIP_SELECTION_MISMATCH', f'--expect-rows must equal the preview selected_rows ({len(result)})')
    summary = {'selected_rows': len(result), 'selected_characters': len({r[0] for r in result}),
               'enabled_rows_removed': sum(not r[3] for r in result),
               'disabled_rows_removed': sum(bool(r[3]) for r in result),
               'reviewed_candidate_rows': len({(r[0],r[1]) for rows in grouped.values() for r in rows}),
               'deferred_candidate_rows': len(excluded), 'spell_rows_inserted': 0, 'skill_rows_changed': 0,
               'selected_groups': len(accepted), 'selected_direct_rows': sum(r[1] in meta.talents for r in result),
               'selected_related_rows': sum(r[1] not in meta.talents for r in result),
               'native_owner_proofs': native_proofs,
               'native_policy': 'Existing selected talents in both specs are authoritative; retire conflicting rows including enabled history; active native children require correct parents and retained known child/prefix anchors; no insertion, flag rewrite, ownership, skill or login change',
               'deferred': dict(Counter(r[2] for r in excluded.values()))}
    if foreign_class_families:
        summary['foreign_family_rows'] = len(result)
        summary['native_policy'] = ('Retire only wholly unselected isolated families belonging exclusively to another class, including enabled rows; '
                                   'all skill/reward/default/shared/script guards remain; preserve both selected builds, skills/caps, profession slots and login flags; no grants')
    if native_passive_prefixes:
        summary['restorable_disabled_prefix_rows'] = sum(len(p['prefix_restore_anchors']) for p in native_proofs)
        summary['native_policy'] = ('Retire conflicting rows only in reviewed native passive families with disabled lower prefixes '
            'restored by retained enabled authorized higher anchors; stale unowned higher history may also be retired, including enabled rows; '
            'no new anchor, SQL insertion, flag rewrite, talent/spec, skill/cap, profession or login change')
    if reviewed_aura_aliases:
        summary['reviewed_aura_alias_rows'] = len(result)
        summary['native_policy'] = ('Retire only isolated unselected paladin talent families with exact protected area-aura aliases; '
            'helpers must match reviewed mechanics and be absent from the stored spellbook; enabled availability is retired; '
            'no talent/spec, skill/cap, profession, login, SQL insertion or flag change')
    if native_passive_rekey:
        summary.update(rekeys=sorted(rekeys),spell_rows_rekeyed=len(result),
            enabled_rows_removed=0,disabled_rows_removed=0,
            native_policy='Rekey only enabled higher non-talent passive children to already-known lower ranks authorized by the active selected talent; exact reviewed native families only; both builds, flags, skills/caps, profession slots and unrelated state preserved; no higher grants or inserted/deleted rows')
    return result, sorted(excluded.values()), proof, summary, sorted(graph.edges)
