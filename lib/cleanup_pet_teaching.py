"""Retire reviewed player-side pet teachers; never touch or grant pet abilities."""
from collections import Counter, defaultdict
import hashlib
from pathlib import Path

from cleanup_console import PROFILE, fail
from cleanup_talent_relations import Relations, MAX_ROWS, validate_stored
from spells import Unsupported

POLICY = 'tc-pet-teaching-wrapper-retirement-v1'
ACK = 'RETIRE_VERIFIED_PET_TEACHERS'
COWER_POLICY = 'tc-pet-teaching-reviewed-cower-retirement-v2'
COWER_ACK = 'REVIEWED_COWER_CHILD_ONLY'
POLICIES = (POLICY,COWER_POLICY)

# Stock wrapper -> pet ability pairs, grouped by the complete reviewed rank list.
# No trainer, selected talent, or pet-owned record authorizes a new player spell.
CONTRACTS = {
    1747: ((1747,1742),(1748,1753),(1749,1754),(1750,1755),(1751,1756),(16698,16697),(27346,27048)),
    17254: ((17254,17253),(17262,17255),(17263,17256),(17264,17257),(17265,17258),(17266,17259),(17267,17260),(17268,17261),(27348,27050)),
    24478: ((24478,24449),),
    24641: ((24641,24640),(24584,24583),(24588,24586),(24589,24587),(27361,27060)),
    24845: ((24845,24844),(25013,25008),(25014,25009),(25015,25010),(25016,25011),(25017,25012)),
    27351: ((27351,27053),),
    27352: ((27352,27054),),
    35299: ((35299,35290),(35300,35291),(35302,35292),(35303,35293),(35304,35294),(35305,35295),(35306,35296),(35307,35297),(35308,35298)),
    35348: ((35348,35346),),
}
PAIRS = dict(pair for pairs in CONTRACTS.values() for pair in pairs)


# Full reviewed Unit.cpp versions; relevant getters are identical between the
# retained AC pin and staging reference even though the complete files differ.
UNIT_VERSIONS = {
    'tc': {'6a78d6b39a4b4abd93dbe6e99eac08d259ef8d632269426f7be3f707b504f16f':
           '92127cd6252edb96fbfa36540db0eba17d0031fa'},
    'ac': {'0da53efdcf6196633a3447c935aced77bb276d54412d587fe28d302dc28ce0f4':
           '1cd97629ed6ef49f5c70dec39316846381d2e450',
           '30f3d251831e00667b466cadeae8c9ec8b3989256ae0c05067449a62876f1c9d':
           'f089543d9dfb3aaba2615fbf9427ea3e54a346e3'},
}

COWER_FILES = {
    'tc': {'src/server/scripts/Spells/spell_hunter.cpp':'adaad3321096052f46b7d790dec90889ab03a686dfe0e49641a4b6b3100abf19',
           'src/server/game/Entities/Unit/Unit.h':'ada83b9d05ea7d554b0fdf7c499b7198a39f48ef2bafe0faeb1f0404cf7ca10f'},
    'ac': {'src/server/scripts/Spells/spell_hunter.cpp':'d4136428a7ac3f22545dad0be8109fbb395840228e587376eca55020759a51f7',
           'src/server/game/Entities/Unit/Unit.h':'f211e13871a94f34553129a113fbd49a7a853d0661e3e779e5f18508cb12c69b'},
}


def cower_sources(paths):
    """Read/verify native source only. Never run C++ or change a core/profile."""
    proof = {}
    for core,name in (('tc','trinitycore'),('ac','azerothcore')):
        directory = paths.get(core+'_source')
        if not directory:
            fail('COWER_NATIVE_SOURCE_REQUIRED','Both reviewed core source paths are required')
        manifest = {n.strip().lstrip('*'):h for h,n in (line.split(None,1) for line in
                    (PROFILE/(name+'-semantic.sha256')).read_text().splitlines())}
        files = {}
        for file in ('src/server/scripts/Spells/spell_hunter.cpp',
                     'src/server/game/Entities/Unit/Unit.h','src/server/game/Entities/Unit/Unit.cpp'):
            try:
                checksum = hashlib.sha256((Path(directory)/file).read_bytes()).hexdigest()
            except OSError:
                fail('COWER_NATIVE_SOURCE_REQUIRED','Cannot read reviewed native source: '+file)
            expected = UNIT_VERSIONS[core] if file.endswith('/Unit.cpp') else {COWER_FILES[core][file]}
            if not file.endswith('/Unit.cpp') and manifest.get(file) != COWER_FILES[core][file]:
                fail('COWER_NATIVE_PROFILE_DRIFT','Cower needs a new explicit review for changed protected source')
            if checksum not in expected:
                fail('COWER_NATIVE_SOURCE_DRIFT','Cower script/aura lookup source differs: '+core+': '+file)
            files[file] = checksum
        proof[core] = {'files':files,'unit_compatibility_reference':UNIT_VERSIONS[core][files['src/server/game/Entities/Unit/Unit.cpp']]}
    return {'contract':'COWER_CHILD_AMOUNT_ONLY_V1','child':1742,
            'bindings':{'tc':'spell_hun_pet_cower','ac':'spell_hun_cower'},'sources':proof,
            'scope':'Only the retired player teaching action changes; actual pet rows and native aura behavior are unchanged'}


def cower_binding(tc, ac, child):
    if child != 1742:
        return False
    for meta,name in ((tc,'spell_hun_pet_cower'),(ac,'spell_hun_cower')):
        row = meta.spells[child]
        if (meta.scripts[child] != {name} or meta.script_policy.get(name) != 'NO_SPELLBOOK_MUTATION'
                or row[4:12] != [65536,0,67108864,0,0,0,0,0] or any(row[12:28])
                or row[71:74] != [6,6,0] or row[86:92] != [1,1,0,0,0,0]
                or row[95:98] != [87,33,0] or row[116:119] != [0,0,0]
                or row[133] != 958 or row[208:212] != [9,0,268435456,0]):
            return False
    return True


def protected(meta, spell):
    return (spell in meta.talents or spell in meta.invalid_talents or spell in meta.talent_learn_owners
            or spell in meta.aura_owners or spell in meta.world_aura_owners or spell in meta.additional)


def contract(tc, ac, root, present, *, reviewed_cower=False):
    """Check full rank identity and only the prefix TC could restore from storage.

    Unlearned higher targets need not exist (legacy Avoidance has three such
    references); they are never inferred, inserted, executed or selected.
    """
    pairs = CONTRACTS.get(root)
    if not pairs:
        return (), 'DEFER_UNREVIEWED_PET_TEACHER'
    chain = tuple(s for s, _ in pairs)
    if any(m.chain(s) != chain for m in (tc,ac) for s in chain):
        return (), 'DEFER_INCOMPATIBLE_PET_TEACHER_CHAIN'
    reached = chain[:1+max(chain.index(s) for s in present)]
    for s in reached:
        child = PAIRS[s]
        for m in (tc,ac):
            r = m.spells[s]
            if (len(r) < 119 or r[4:12] != [262400,0,0,0,0,0,0,0]
                    or any(r[12:28]) or r[71:74] != [36,0,0]
                    or r[86:92] != [5,0,0,0,0,0] or r[95:98] != [0,0,0]
                    or r[116:119] != [child,0,0] or child not in m.spells):
                return (), 'DEFER_PET_TEACHER_EFFECT_CONTRACT'
            if protected(m,s) or protected(m,child):
                return (), 'DEFER_TALENT_OR_AURA_ROUTE'
            if m.scripts[s] or (m.scripts[child] and not (reviewed_cower and cower_binding(tc,ac,child))):
                return (), 'DEFER_SCRIPTED_PET_TEACHER'
            if (m.abilities[s] or m.skill_effect(s) or m.skill_effect(child)
                    or set(m.spells[child][71:74]) & {36,40,44,47,118}
                    or set(m.spells[child][95:98]) & {30,98}):
                return (), 'DEFER_PET_TEACHER_SKILL_ROUTE'
            if (m.requires[s] or m.prerequisite_users[s] or m.learn_parents[s]
                    or m.requires[child] or m.prerequisite_users[child]
                    or m.learns[child] or m.effect_learns[child]
                    or m.effect_learns[s] != [(child,1,True)]
                    or m.learns[s] not in ([],[(child,1,True)])):
                return (), 'DEFER_PET_TEACHER_LEARNING_ROUTE'
            if child in reached or m.chain(child) == chain:
                return (), 'DEFER_PET_TEACHER_CYCLE'
            try:
                m.check_spell(s)
                m.check_spell(child)
            except Unsupported as error:
                return (), 'DEFER_PET_TEACHER_' + error.reason
        if tc.spells[s] != ac.spells[s] or tc.spells[child] != ac.spells[child]:
            return (), 'DEFER_INCOMPATIBLE_PET_TEACHER_METADATA'
    return reached, ''


def select(state, tc, ac, expected=None, *, preview=False, reviewed_cower=False):
    stored = state['character_spell']
    validate_stored(stored)
    if not 1 <= len(state['characters']) <= 40000 or sum(map(len,state.values())) > MAX_ROWS:
        fail('PET_TEACHING_BOUND','Captured source scope exceeds reviewed bounds')
    chars = {r[0]:r for r in state['characters']}
    if len(chars) != len(state['characters']):
        fail('PET_TEACHING_INPUT_INVALID','Duplicate character keys')
    books = defaultdict(dict)
    for g,s,a,d in stored:
        if g not in chars or s not in tc.spells or s not in ac.spells:
            fail('PET_TEACHING_INPUT_INVALID','Unknown or out-of-scope player spell')
        books[g][s] = (a,d)
    if any(r[0] not in chars for r in state['character_skills']):
        fail('PET_TEACHING_INPUT_INVALID','Out-of-scope skill row')
    invalid, seen = set(), set()
    for g,s,group in state['character_talent']:
        if g not in chars:
            fail('PET_TEACHING_INPUT_INVALID','Out-of-scope talent row')
        c, identity = chars[g], tc.talents.get(s)
        tab = tc.stores['TalentTab'].get(tc.talent_rows[s][1],[]) if identity else []
        key = (g,identity[0] if identity else -1,group)
        if (not identity or s in tc.invalid_talents or len(tab) <= 20 or c[2] != 3
                or not tab[20] & 4 or c[5] not in (1,2) or group not in (0,1)
                or group >= c[5] or key in seen or ac.talents.get(s) != identity):
            invalid.add(g)
        seen.add(key)
    # Verify structural bounds/unique membership even in unrelated rank chains.
    graphs = (Relations(tc),Relations(ac))
    selected, excluded, proof, native = [], [], [], []
    reviewed = groups = 0
    cache = {}
    for g,book in sorted(books.items()):
        c = chars[g]
        candidates = [s for s in book if s in PAIRS or any(
            m.spells[s][71+i] == 36 and m.spells[s][86+i] == 5 for m in (tc,ac) for i in range(3))]
        for root in sorted({tc.first(s) for s in candidates}):
            present = sorted(set(tc.chain(root)) & book.keys())
            reviewed += len(present)
            reason = ''
            if (c[1] not in (1,2,3,4,5,6,7,8,10,11) or c[2] != 3 or not 1 <= c[3] <= 80
                    or c[5] not in (1,2) or not 0 <= c[4] < c[5]):
                reason = 'DEFER_PET_TEACHER_CHARACTER_STATE'
            elif c[6]:
                reason = 'DEFER_ONLINE_CHARACTER'
            elif c[7] & 4:
                reason = 'DEFER_PENDING_NATIVE_RESET'
            elif g in invalid:
                reason = 'DEFER_INVALID_TALENT_SELECTION'
            elif any(a not in (0,1) or d not in (0,1) for a,d in (book[s] for s in present)):
                reason = 'DEFER_INVALID_RELATED_FLAGS'
            reached = ()
            if not reason:
                key = (root,tuple(present))
                if key not in cache:
                    cache[key] = contract(tc,ac,root,present,reviewed_cower=reviewed_cower)
                reached, reason = cache[key]
            if not reason and any(PAIRS[s] in book for s in reached):
                reason = 'DEFER_PET_ABILITY_IN_PLAYER_BOOK'
            if reason:
                excluded.extend((g,s,reason) for s in present)
                continue
            groups += 1
            selected.extend((g,s,*book[s]) for s in present)
            native.append({'guid':g,'rank_root':root,'stored_wrappers':present,'known_prefix':list(reached),
                           'pet_pairs':[[s,PAIRS[s]] for s in reached], 'pet_rows_changed':0,
                           'source_load':'Non-passive pet-target learn effects are auto-learned; no player child cast on load',
                           'target_load':'AC refuses persistent LEARN wrappers; no temporary fallback permitted'})
            for s in tc.chain(root):
                proof.append((g,root,s,'PET_TEACHING_WRAPPER',
                              'REMOVE_ENABLED_WRAPPER' if s in book and not book[s][1] else
                              'REMOVE_DISABLED_WRAPPER' if s in book else 'ABSENT_NO_GRANT',*book.get(s,('',''))))
            if len(proof) > MAX_ROWS:
                fail('PET_TEACHING_BOUND','Pet-teaching proof exceeds reviewed bounds')
    selected.sort();excluded.sort()
    if len(selected) > 500000:
        fail('PET_TEACHING_BOUND','More than 500000 selected player rows')
    if not preview and (not selected or expected != len(selected)):
        fail('PET_TEACHING_SELECTION_MISMATCH',f'--expect-rows must equal preview selected_rows ({len(selected)})')
    summary = {'reviewed_candidate_rows':reviewed,'selected_rows':len(selected),
               'selected_characters':len({r[0] for r in selected}),'selected_groups':groups,
               'selected_direct_rows':0,'selected_related_rows':len(selected),
               'enabled_rows_removed':sum(not r[3] for r in selected),
               'disabled_rows_removed':sum(bool(r[3]) for r in selected),
               'deferred_candidate_rows':len(excluded),'deferred':dict(Counter(r[2] for r in excluded)),
               'spell_rows_inserted':0,'skill_rows_changed':0,'pet_rows_changed':0,
               'eligibility_proofs':native,
               'native_policy':'Retire only verified player-side pet-teaching wrappers, including enabled rows; '
               'discard old pet-training actions; preserve actual pets/pet spells, talent selections, skills/caps, '
               'profession slots and login flags; no grants or temporary fallback'}
    if reviewed_cower:
        summary['reviewed_cower_rows'] = sum(tc.first(r[1])==1747 for r in selected)
        summary['native_policy'] += '; exact reviewed Cower pet-child amount callbacks allowed; all other scripts defer'
    return selected,excluded,proof,summary,sorted(graphs[0].edges | graphs[1].edges)
