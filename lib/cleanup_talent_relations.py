"""Review isolated, wholly disabled talent/rank/dependency groups on TC only."""
from collections import Counter, defaultdict, deque

from cleanup_console import fail
from spells import Unsupported

POLICY = 'tc-disabled-unselected-talent-closure-v3'
ROUTE_POLICY = 'tc-disabled-reviewed-talent-routes-v4'
TEACHERS = {1927:(50334,51266,1024,(36,36,0),(50321,50334,0)),
            32:(11113,1831,128,(36,0,0),(11113,0,0))}
MAX_CLOSURE = 4096
MAX_ROWS = 5000000


def stored_query(source, guids):
    selector = ','.join(map(str, sorted(guids)))
    return (f'SELECT JSON_ARRAY(guid,spell,active,disabled) row_value FROM `{source}`.character_spell '
            f'WHERE guid IN ({selector}) ORDER BY guid,spell LIMIT {MAX_ROWS+1}')


def validate_stored(rows):
    if len(rows) > MAX_ROWS or len({(r[0],r[1]) for r in rows}) != len(rows):
        fail('HISTORY_RELATION_BOUND','Related-state snapshot exceeds its row bound or contains duplicate keys')
    if any(n > 10000 for n in Counter(r[0] for r in rows).values()):
        fail('HISTORY_RELATION_BOUND','More than 10000 spell rows per reviewed character')


class Relations:
    """Collapse verified rank chains, then follow directed learning/dependency edges.

    Bidirectional rank membership is not a dependency cycle. Dependency edges
    within a rank component, and cycles between components, are unsafe.
    """
    def __init__(self, meta):
        self.meta = meta
        self.families = defaultdict(set)
        for spell,(family,_) in meta.talents.items():
            self.families[family].add(spell)
        self.component = {}
        self.members = {}
        for spell in sorted(meta.spells):
            chain = tuple(meta.chain(spell))
            if not chain or spell not in chain or len(chain)>255 or len(set(chain))!=len(chain):
                fail('HISTORY_RELATION_METADATA','Malformed effective rank membership')
            key = chain[0]
            if key in self.members and self.members[key] != set(chain):
                fail('HISTORY_RELATION_METADATA','Conflicting effective rank membership')
            self.members[key] = set(chain)
            for member in chain:
                if member not in meta.spells or (member in self.component and self.component[member] != key):
                    fail('HISTORY_RELATION_METADATA','Unknown or multiply owned rank member')
                self.component[member] = key
        self.edges = set()
        for kind,links in (('WORLD_LEARN',meta.learns),('EFFECT_LEARN',meta.effect_learns)):
            for parent,values in links.items():
                for child,_,_ in values:
                    self.edges.add((parent,child,kind))
        for child,parents in meta.requires.items():
            for parent in parents:
                self.edges.add((parent,child,'REQUIRED_BY'))
        # Do not silently ignore malformed LEARN effect targets, including
        # pet learning. This policy handles player spellbook history only.
        self.unsupported = set()
        for spell,record in meta.spells.items():
            for index in range(3):
                if record[71+index] == 36 and (record[116+index] not in meta.spells or record[86+index] == 5):
                    self.unsupported.add(spell)
        self.next = defaultdict(set)
        self.incoming = defaultdict(set)
        for parent,child,_ in sorted(self.edges):
            if parent not in self.component or child not in self.component:
                fail('HISTORY_RELATION_METADATA','Unknown dependency endpoint')
            self.next[self.component[parent]].add(self.component[child])
            self.incoming[self.component[child]].add(self.component[parent])
        self.skill_rewards = {spell for spell,abilities in meta.abilities.items()
                              if any(row[9] in (1,2) for row in abilities)}
        skills = meta.stores['SkillLine']
        self.unknown_skill_spells = {spell for spell,abilities in meta.abilities.items()
                                    if any(row[1] not in skills for row in abilities)}
        self.profession_spells = {spell for spell,abilities in meta.abilities.items()
            if any(row[1]==762 or skills.get(row[1],[0,0])[1] in (9,11) for row in abilities)}

    def direct_contract(self, family, root, class_mask):
        if self.families[family]!={root} or self.meta.talents.get(root)!=(family,1):
            return False
        talent = self.meta.talent_rows[root]
        tab = self.meta.stores['TalentTab'].get(talent[1],[])
        return len(tab)>20 and tab[20]==class_mask

    def teacher(self, family):
        root,teacher,cls,effects,children = TEACHERS[family]
        row = self.meta.spells.get(teacher,[])
        if (not self.direct_contract(family,root,cls) or teacher in self.meta.talents
                or not row or tuple(row[71:74])!=effects or tuple(row[116:119])!=children
                or row[4]&0x40 or row[12] or self.meta.chain(teacher)!=(teacher,)):
            return None
        return teacher

    def dual_wield_contract(self):
        """Only the inert single-rank shaman root; never remove shared 674/118."""
        root,child = 30798,674
        if not self.direct_contract(1690,root,64):
            return False
        parent = self.meta.spells[root]
        shared = self.meta.spells.get(child,[])
        if (not shared or child in self.meta.talents or self.meta.chain(root)!=(root,)
                or self.meta.chain(child)!=(child,)
                or parent[71:74]!=[36,0,0] or parent[116:119]!=[child,0,0]
                or shared[71:74]!=[40,0,0] or shared[116:119]!=[0,0,0]
                or self.incoming[self.component[root]]
                or self.next[self.component[root]]!={self.component[child]}
                or root in self.skill_rewards or root in self.unknown_skill_spells
                or root in self.profession_spells or root in self.meta.invalid_talents or root in self.unsupported
                or root in getattr(self.meta,'history_default_spells',set())):
            return False
        for spell in (root,child):
            if any(self.meta.script_policy.get(name)!='NO_SPELLBOOK_MUTATION' for name in self.meta.scripts[spell]):
                return False
            try:
                self.meta.check_spell(spell)
            except Unsupported:
                return False
        return True

    def family(self, family, reviewed_routes=False):
        roots = {self.component[s] for s in self.families[family]}
        ignored = set()
        if reviewed_routes and family in TEACHERS:
            teacher = self.teacher(family)
            if teacher is None:
                return set(self.families[family]),'DEFER_REVIEWED_TEACHER_CONTRACT'
            if family==1927 and 50321 not in self.meta.spells:
                # Exact legacy 51266 has a missing LEARN target. Pinned TC
                # IsSpellValid rejects the WHOLE teacher, not just this effect.
                # Per-character selection additionally requires it absent.
                ignored.add(self.component[teacher])
            else:
                roots.add(self.component[teacher])
        queue,components = deque(sorted(roots)),set()
        nodes = set()
        while queue:
            component = queue.popleft()
            if component in components:
                continue
            components.add(component)
            nodes.update(self.members[component])
            if len(nodes)>MAX_CLOSURE:
                return nodes,'DEFER_RELATION_BOUND'
            queue.extend(sorted(self.next[component]-components))
        # Kahn's algorithm detects cycles without recursion or arbitrary cuts.
        degree = {c:len(self.incoming[c]&components) for c in components}
        ready = deque(sorted(c for c,n in degree.items() if n==0))
        visited = 0
        while ready:
            parent = ready.popleft();visited += 1
            for child in sorted(self.next[parent]&components):
                degree[child] -= 1
                if degree[child]==0:
                    ready.append(child)
        if visited != len(components):
            return nodes,'DEFER_RELATION_CYCLE'
        if any(self.incoming[c]-components-ignored for c in components):
            return nodes,'DEFER_INDEPENDENT_LEARN_ROUTE'
        if any(s in self.meta.talents and self.meta.talents[s][0]!=family for s in nodes):
            return nodes,'DEFER_SHARED_TALENT_RELATION'
        if nodes & self.meta.invalid_talents or nodes & self.unsupported:
            return nodes,'DEFER_UNSUPPORTED_RELATION_METADATA'
        if nodes & self.skill_rewards:
            return nodes,'DEFER_SKILL_REWARD_ROUTE'
        if nodes & self.profession_spells:
            return nodes,'DEFER_PROFESSION_OR_RIDING_RELATION'
        if nodes & self.unknown_skill_spells:
            return nodes,'DEFER_UNSUPPORTED_RELATION_METADATA'
        if nodes & getattr(self.meta,'history_default_spells',set()):
            return nodes,'DEFER_CUSTOM_DEFAULT_ROUTE'
        for spell in sorted(nodes):
            # No profession/riding/dual-wield state may change, including on
            # sibling removal. Check all members, even currently absent ones.
            if set(self.meta.spells[spell][71:74]) & {40,44,47,118}:
                return nodes,'DEFER_TALENT_SKILL_EFFECT'
            if any(self.meta.script_policy.get(name)!='NO_SPELLBOOK_MUTATION' for name in self.meta.scripts[spell]):
                return nodes,'DEFER_SCRIPTED_TALENT_FAMILY'
            try:
                self.meta.check_spell(spell)
            except Unsupported as error:
                return nodes,'DEFER_RELATION_'+error.reason
        return nodes,''


def select(rows, state, meta, stored, expected, reviewed_routes=False):
    candidates = [r for r in rows if r[9]=='REVIEW_DISABLED_NO_SELECTED_FAMILY']
    if not 1<=expected<=500000 or len(candidates)!=expected:
        fail('HISTORY_SELECTION_MISMATCH','--expect-review-rows must equal the inspection disabled/no-selected-family total')
    validate_stored(stored)
    live = {(r[0],r[1]):tuple(r[2:]) for r in stored}
    # This supplement must agree with the sealed direct-history inspection.
    guids = {r[0] for r in candidates}
    direct = {(g,s):(a,d) for g,s,a,d in state['spells'] if g in guids}
    current = {key:flags for key,flags in live.items() if key[1] in meta.talents}
    if current != direct:
        fail('HISTORY_INPUT_DRIFT','Related-state snapshot differs from inspected direct spell keys/flags')
    graph = Relations(meta)
    by_family = {}
    node_count = 0
    for family in sorted({r[10] for r in candidates}):
        if reviewed_routes and family==1690:
            by_family[family] = ({30798,674},'' if graph.dual_wield_contract() else 'DEFER_REVIEWED_DUAL_WIELD_CONTRACT')
        else:
            by_family[family] = graph.family(family,reviewed_routes)
        node_count += len(by_family[family][0])
        if node_count>MAX_ROWS:
            fail('HISTORY_RELATION_BOUND','Relationship catalog review exceeds 5000000 node visits')
    selected_talents = defaultdict(set)
    for guid,spell,_ in state['talents']:
        selected_talents[guid].add(spell)
    stored_by_guid = defaultdict(dict)
    for (guid,spell),flags in live.items():
        stored_by_guid[guid][spell] = flags
    roots = defaultdict(list)
    for row in candidates:
        roots[row[0],row[10]].append(row)
    selected,excluded,proof,accepted = {},[],[],[]
    for (guid,family),root_rows in sorted(roots.items()):
        nodes,reason = by_family[family]
        dual_root_only = reviewed_routes and family==1690 and not reason
        invalid_teacher = reviewed_routes and family==1927 and 50321 not in meta.spells and not reason
        if invalid_teacher and any(spell in stored_by_guid[guid] for spell in (51266,50321)):
            reason = 'DEFER_INVALID_TEACHER_STORED'
        removal_nodes = {30798} if dual_root_only else nodes
        if dual_root_only and any(r[4]!=7 for r in root_rows):
            reason = 'DEFER_REVIEWED_DUAL_WIELD_CONTRACT'
        if not reason and selected_talents[guid]&nodes:
            reason = 'DEFER_SELECTED_RELATED_TALENT'
        present = {s:flags for s,flags in stored_by_guid[guid].items() if s in nodes}
        if not reason and any(flags[0] not in (0,1) or flags[1] not in (0,1) for flags in present.values()):
            reason = 'DEFER_INVALID_RELATED_FLAGS'
        if not reason and any(flags[1]!=1 for spell,flags in present.items() if spell in removal_nodes):
            reason = 'DEFER_ENABLED_RELATED_SPELL'
        if not reason and any(r[1] not in meta.talents or meta.talents[r[1]]!=(r[10],r[11])
                              or (r[2],r[3])!=live.get((guid,r[1])) or r[3]!=1 for r in root_rows):
            reason = 'DEFER_EFFECTIVE_TALENT_IDENTITY'
        if reason:
            excluded.extend((guid,r[1],reason) for r in root_rows)
            continue
        if len(proof)+len(nodes)+(2 if invalid_teacher else 0)>MAX_ROWS:
            fail('HISTORY_RELATION_BOUND','Relationship evidence exceeds 5000000 per-character node rows')
        accepted.extend((guid,r[1]) for r in root_rows)
        if invalid_teacher:
            proof.extend([(guid,family,51266,'REJECTED_NATIVE_TEACHER','ABSENT_INVALID_TEACHER','',''),
                          (guid,family,50321,'MISSING_LEARN_TARGET','ABSENT_METADATA_NO_GRANT','','')])
        for spell in sorted(nodes):
            flags = present.get(spell)
            direct_rank = spell in graph.families[family]
            teacher = TEACHERS[family][1] if reviewed_routes and family in TEACHERS else None
            role = 'DIRECT_TALENT' if direct_rank else 'REVIEWED_TEACHER' if spell==teacher else 'RANK_OR_DEPENDENT'
            disposition = ('PRESERVED_SHARED_SKILL_ROUTE' if dual_root_only and spell==674 and flags
                           else 'SELECTED_DISABLED' if flags else 'ABSENT_NO_GRANT')
            proof.append((guid,family,spell,role,disposition,*(flags if flags else ('',''))))
            if flags and spell in removal_nodes:
                selected[guid,spell] = (guid,spell,*flags)
    if not selected:
        counts = ', '.join(f'{reason}={count}' for reason,count in sorted(Counter(r[2] for r in excluded).items()))
        fail('HISTORY_NO_ELIGIBLE_ROWS','No reviewed talent history groups satisfy the selected policy: '+counts)
    if len(selected)>500000:
        fail('HISTORY_RELATION_BOUND','More than 500000 exact spell removals; no truncation was performed')
    root_keys = {tuple(key) for key in accepted}
    result = sorted(selected.values())
    summary = {'selected_root_rows':len(root_keys),
               'selected_related_rows':len(selected)-len(root_keys),
               'selected_groups':len({(row[0],row[1]) for row in proof}),
               'max_group_spells':MAX_CLOSURE,
               'native_policy':'Archive isolated wholly disabled direct talent/rank/dependency groups; no selected ownership or enabled related spells; no grants, skill changes or resets'}
    if reviewed_routes:
        summary.update(reviewed_teacher_pairs=[(root,teacher) for family,(root,teacher,*_) in sorted(TEACHERS.items())
                                                if any(row[1]==family for row in proof)],
                       preserved_shared_route_rows=sum(row[4]=='PRESERVED_SHARED_SKILL_ROUTE' for row in proof),
                       rejected_missing_target_teachers=[(50334,51266,50321)] if any(row[4]=='ABSENT_INVALID_TEACHER' for row in proof) else [],
                       native_policy='Reviewed teacher groups remain wholly disabled; only inert shaman talent 30798 may be removed with shared 674/skill 118 preserved; no ownership, activation, grants, skills or resets change')
    edges = set(graph.edges)
    if any(row[4]=='ABSENT_INVALID_TEACHER' for row in proof):
        edges.add((51266,50321,'REJECTED_MISSING_LEARN_TARGET'))
    return result,sorted(excluded),proof,summary,sorted(edges)
