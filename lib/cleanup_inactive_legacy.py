"""Explicit retirement of uncastable legacy Bloodthirst book history.

This is a retirement catalog, NEVER an inferred rank/learning relationship.
Current selected talent 23881 and every active stored spell stay untouched.
"""
from collections import Counter,defaultdict

from cleanup_console import fail
from cleanup_talent_relations import Relations,MAX_ROWS,validate_stored
from spells import Unsupported

POLICY='tc-inactive-legacy-bloodthirst-retirement-v1'
POLICIES=(POLICY,)
ACK='RETIRE_ONLY_INACTIVE_LEGACY_BLOODTHIRST'
LEGACY=(23892,23893,23894,25251,30335)


def contract(tc,ac):
    """No guessed historical chain, profession, skill, script or talent route."""
    for meta in (tc,ac):
        graph=Relations(meta)
        if any(set(row[116:119]) & set(LEGACY) for row in meta.spells.values()):
            return False
        for spell in LEGACY:
            row=meta.spells.get(spell,[])
            effects=[0]*48
            for offset,value in ((0,2),(3,1),(9,44),(15,6)):effects[offset]=value
            gates=[0]*16;gates[7]=1
            if (len(row)<212 or row[4:12]!=[327696,134218240,0,0,0,0,0,0]
                    or row[12:28]!=gates or row[41]!=1 or row[71:119]!=effects
                    or row[208:212]!=[4,0,1024,0] or meta.chain(spell)!=(spell,)
                    or meta.abilities[spell] or meta.scripts[spell]
                    or meta.learns[spell] or meta.effect_learns[spell] or meta.requires[spell]
                    or meta.prerequisite_users[spell] or meta.learn_parents[spell]
                    or meta.aura_owners[spell] or spell in meta.world_aura_owners
                    or spell in meta.talents or spell in meta.talent_learn_owners
                    or spell in meta.additional or spell in meta.trainer_taught
                    or graph.incoming[spell] or graph.next[spell] or spell in graph.unsupported
                    or spell in getattr(meta,'history_default_spells',set())):
                return False
            try:meta.check_spell(spell)
            except Unsupported:return False
    return True


def select(state,tc,ac,expected=None,*,preview=False):
    validate_stored(state['character_spell'])
    if not 1<=len(state['characters'])<=40000 or sum(map(len,state.values()))>MAX_ROWS:
        fail('INACTIVE_LEGACY_BOUND','Captured scope exceeds the reviewed bound')
    chars={r[0]:r for r in state['characters']}
    if len(chars)!=len(state['characters']):fail('INACTIVE_LEGACY_INPUT_INVALID','Duplicate character keys')
    books=defaultdict(dict)
    for g,s,a,d in state['character_spell']:
        if g not in chars:fail('INACTIVE_LEGACY_INPUT_INVALID','Out-of-scope spell row')
        books[g][s]=(a,d)
    invalid,seen=set(),set()
    for g,s,k in state['character_talent']:
        c=chars.get(g);identity=tc.talents.get(s)
        tab=tc.stores['TalentTab'].get(tc.talent_rows[s][1],[]) if identity else []
        key=(g,identity[0] if identity else -1,k)
        if (c is None or not identity or s in tc.invalid_talents or ac.talents.get(s)!=identity
                or len(tab)<=20 or c[2] not in (1,2,3,4,5,6,7,8,9,11)
                or not tab[20]&(1<<(c[2]-1)) or k not in (0,1) or k>=c[5] or key in seen):invalid.add(g)
        seen.add(key)
    safe=contract(tc,ac)
    selected,excluded,proof,native=[],[],[],[]
    reviewed=0
    for g,book in sorted(books.items()):
        candidates=sorted(s for s in LEGACY if book.get(s)==(0,0))
        if not candidates:continue
        reviewed+=len(candidates);c=chars[g]
        retained=sorted(s for s in LEGACY if book.get(s)==(1,0))
        reason=''
        if (c[1] not in (1,2,3,4,5,6,7,8,10,11) or not 1<=c[3]<=80
                or c[5] not in (1,2) or not 0<=c[4]<c[5]):reason='DEFER_LEGACY_CHARACTER_STATE'
        elif c[2]!=1:reason='DEFER_LEGACY_WRONG_CLASS'
        elif c[6]:reason='DEFER_ONLINE_CHARACTER'
        elif c[7]&4:reason='DEFER_PENDING_NATIVE_RESET'
        elif g in invalid:reason='DEFER_INVALID_TALENT_SELECTION'
        elif not safe:reason='DEFER_LEGACY_CATALOG_CONTRACT'
        elif any(book[s] not in ((0,0),(1,0)) for s in LEGACY if s in book):reason='DEFER_LEGACY_MIXED_FLAGS'
        elif not retained:reason='DEFER_NO_RETAINED_ACTIVE_LEGACY_SPELL'
        if reason:
            excluded.extend((g,s,reason)for s in candidates);continue
        selected.extend((g,s,0,0)for s in candidates)
        native.append({'guid':g,'contract':'UNCASTABLE_LEGACY_BLOODTHIRST_CATALOG_V1',
            'retirement_catalog':list(LEGACY),'removed_inactive_spells':candidates,
            'retained_active_spells':[[s,1,0]for s in retained],
            'source_client_castable':False,'target_client_castable_after_removal':False,
            'known_history_discarded':True,'rank_links_inferred':False,
            'selected_talent_23881_changed':False,'spell_rows_inserted':0,'skill_rows_changed':0})
        proof.extend((g,LEGACY[0],s,'LEGACY_RETIREMENT_CATALOG',
            'RETIRE_UNCASTABLE_HISTORY' if s in candidates else 'RETAIN_ACTIVE_LEGACY' if s in retained else 'ABSENT_NO_GRANT',
            *book.get(s,('','')))for s in LEGACY)
    selected.sort();excluded.sort()
    if len(selected)>500000:fail('INACTIVE_LEGACY_BOUND','More than 500000 exact retired rows')
    if not preview and (not selected or expected!=len(selected)):
        fail('INACTIVE_LEGACY_SELECTION_MISMATCH',f'--expect-rows must equal preview selected_rows ({len(selected)})')
    summary={'reviewed_candidate_rows':reviewed,'selected_rows':len(selected),
        'selected_characters':len(native),'selected_groups':len(native),'selected_direct_rows':0,
        'selected_related_rows':len(selected),'inactive_rows_removed':len(selected),
        'active_rows_removed':0,'disabled_rows_removed':0,'enabled_rows_removed':len(selected),
        'deferred_candidate_rows':len(excluded),'deferred':dict(Counter(r[2]for r in excluded)),
        'spell_rows_inserted':0,'skill_rows_changed':0,'eligibility_proofs':native,
        'native_policy':'Explicitly retire only inactive/non-disabled, client-uncastable legacy Bloodthirst catalog rows while retaining an existing active catalog spell; discard unavailable known history; infer no rank links; preserve all active spells, current talent 23881, both builds, skills/caps, profession slots and flags; no grants'}
    return selected,excluded,proof,summary,[]
