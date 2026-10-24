"""Explicit retirement of forbidden Wolf Riding 825 and skill 149 together.

Modern Riding 762 and its known ranks are mandatory retained anchors. This is
neither a mount migration nor a general race/class skill cleanup policy.
"""
from collections import Counter, defaultdict
from copy import copy
import hashlib
import json

from cleanup_console import ROOT, fail
from cleanup_talent_relations import MAX_ROWS, validate_stored
from cleanup_specializations import equipment_shape
from cleanup_shaman_dual_wield import defaults
from spells import Unsupported

POLICY = 'tc-obsolete-wolf-riding-spell-skill-retirement-v1'
POLICIES = (POLICY,)
ACK = 'RETIRE_FORBIDDEN_WOLF_RIDING_PAIR_RETAIN_MODERN_RIDING'
CATALOG = ROOT/'lib/cleanup_obsolete_riding_catalog.json'
RANKS = (33388, 33391, 34090, 34091)
RETIRED_SPELL, RETIRED_SKILL = 825, 149


def native_sources(paths):
    rules = json.loads(CATALOG.read_text())
    for core, files in rules['native_sources'].items():
        for name, expected in files.items():
            path = paths[core+'_source']/name
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                fail('OBSOLETE_RIDING_NATIVE_DRIFT', 'Reviewed skill consumer differs: '+core+':'+name)
    return rules['native_sources']


def info(meta, skill, race, cls):
    return [r for r in meta.stores['SkillRaceClassInfo'].values() if r[1] == skill
            and (not r[2] or r[2] & (1 << (race-1)))
            and (not r[3] or r[3] & (1 << (cls-1)))]


def contract(meta):
    rules = json.loads(CATALOG.read_text())[meta.core]
    for key, expected in rules['spells'].items():
        spell = int(key)
        row = meta.spells.get(spell, [])
        if (len(row) < 212 or any(row[i] != expected['mechanics'].get(str(i), 0)
                for i in (*range(4,131), *range(208,212)))
                or list(meta.chain(spell)) != expected['chain'] or meta.abilities[spell] != expected['abilities']
                or [list(r) for r in meta.learns[spell]] != expected['learns']
                or [list(r) for r in meta.effect_learns[spell]] != expected['effect_learns']
                or sorted(meta.requires[spell]) != expected['requires']
                or sorted(meta.prerequisite_users[spell]) != expected['prerequisite_users']
                or sorted(meta.learn_parents[spell]) != expected['learn_parents']
                or meta.scripts[spell] or spell in meta.talents or meta.talent_learn_owners.get(spell)
                or meta.aura_owners[spell] or spell in meta.world_aura_owners or spell in meta.additional):
            return False
        try:
            meta.check_spell(spell)
        except Unsupported:
            return False
    for key, expected in rules['skills'].items():
        skill = int(key)
        line = meta.stores['SkillLine'].get(skill, [])
        if (not line or any(line[int(i)] != v for i,v in expected['line'].items())
                or sorted(r for r in meta.stores['SkillRaceClassInfo'].values() if r[1] == skill) != expected['infos']
                or sorted(r for r in meta.stores['SkillLineAbility'].values() if r[1] == skill) != expected['abilities']
                or any(meta.stores['SkillTiers'].get(int(i)) != row for i,row in expected['tiers'].items())):
            return False
    # Only the exact absent teacher can recreate the old action; reject new
    # learn/requirement edges even when not reached by the current spellbook.
    if (meta.skill_effect(825) != (149,1,1,75) or meta.learn_parents[825] != {6746}
            or meta.learns[6746] != [(825,1,True)] or meta.effect_learns[6746] != [(825,1,True)]):
        return False
    for spell, row in meta.spells.items():
        if spell in (825,6746):
            continue
        if any(row[71+i] in (44,118) and row[110+i] == 149 for i in range(3)):
            return False
    return True


def default_blocks(capture, race, cls):
    for world in capture.values():
        fields = [r[1] for r in world['layout']['columns']]
        for row in world['rows']['playercreateinfo_skills']:
            r = dict(zip(fields,row))
            if (r['skill'] == 149 and (not r['raceMask'] or r['raceMask'] & (1 << (race-1)))
                    and (not r['classMask'] or r['classMask'] & (1 << (cls-1)))):
                return True
    return False


def select(state, tc, ac, expected=None, *, preview=False, items, default_skills):
    validate_stored(state['character_spell'])
    if not 1 <= len(state['characters']) <= 40000 or sum(map(len,state.values())) > MAX_ROWS:
        fail('OBSOLETE_RIDING_BOUND', 'Captured scope exceeds reviewed bounds')
    chars = {r[0]:r for r in state['characters']}
    if (len(chars) != len(state['characters'])
            or len({(r[0],r[1]) for r in state['character_skills']}) != len(state['character_skills'])
            or any(r[0] not in chars for table in ('character_spell','character_skills','character_talent') for r in state[table])):
        fail('OBSOLETE_RIDING_STATE_INVALID', 'Duplicate keys or out-of-scope character state')
    books, skills, owned = defaultdict(dict), defaultdict(dict), defaultdict(list)
    for g,s,a,d in state['character_spell']: books[g][s] = (a,d)
    for g,s,v,c in state['character_skills']: skills[g][s] = (v,c)
    seen_items = set()
    for row in items:
        if (len(row) != 13 or row[0] not in chars or any(x is not None and
                (type(x) != int or not 0 <= x <= 0xffffffff) for x in row)
                or (row[0],row[1]) in seen_items):
            fail('OBSOLETE_RIDING_ITEMS_INVALID', 'Expected unique complete owned/inventory/mail item evidence')
        seen_items.add((row[0],row[1])); owned[row[0]].append(row)
    invalid, seen = set(), set()
    for g,s,k in state['character_talent']:
        c = chars.get(g); identity = tc.talents.get(s); rank = tc.talent_rows.get(s, [])
        tab = tc.stores['TalentTab'].get(rank[1], []) if identity else []
        key = (g,identity[0] if identity else -1,k)
        if (c is None or not identity or ac.talents.get(s) != identity
                or s in tc.invalid_talents or s in ac.invalid_talents or ac.talent_rows.get(s) != rank
                or len(tab) <= 20 or not 1 <= c[2] <= 32 or not tab[20] & (1 << (c[2]-1))
                or ac.stores['TalentTab'].get(rank[1],[0]*21)[20] != tab[20]
                or k not in (0,1) or k >= c[5] or key in seen): invalid.add(g)
        seen.add(key)
    safe = contract(tc) and contract(ac)
    selected, excluded, proofs = [], [], []
    for g,c in sorted(chars.items()):
        if 825 not in books[g]: continue
        book = books[g]; stored = skills[g].get(762); anchors = []
        reason = ''
        if c[6]: reason = 'DEFER_ONLINE_CHARACTER'
        elif c[7] & 4: reason = 'DEFER_PENDING_NATIVE_RESET'
        elif (c[1] not in (1,2,3,4,5,6,7,8,10,11) or c[2] not in (1,2,3,4,5,6,7,8,9,11)
                or not 1 <= c[3] <= 80 or c[5] not in (1,2) or not 0 <= c[4] < c[5]):
            reason = 'DEFER_RIDING_CHARACTER_STATE'
        elif g in invalid: reason = 'DEFER_INVALID_TALENT_SELECTION'
        elif not safe: reason = 'DEFER_OBSOLETE_RIDING_NATIVE_CONTRACT'
        elif any(info(m,149,c[1],c[2]) for m in (tc,ac)): reason = 'DEFER_LEGACY_RIDING_ELIGIBLE'
        elif book[825] != (1,0) or skills[g].get(149) != (1,75): reason = 'DEFER_OBSOLETE_RIDING_PAIR_STATE'
        elif any(not info(m,762,c[1],c[2]) for m in (tc,ac)): reason = 'DEFER_MODERN_RIDING_ELIGIBILITY'
        elif (stored is None or stored[0] != stored[1] or stored[1] not in (75,150,225,300)):
            reason = 'DEFER_MODERN_RIDING_SKILL_STATE'
        elif any(book[s] not in ((0,0),(1,0)) for s in RANKS if s in book): reason = 'DEFER_MODERN_RIDING_FLAGS'
        elif any(tc.skill_effect(s)[3] > stored[1] for s in RANKS if s in book):
            reason = 'DEFER_MODERN_RIDING_SKILL_STATE'
        else:
            anchors = [s for s in RANKS if book.get(s) == (1,0)
                       and tc.skill_effect(s) == ac.skill_effect(s) == (762,RANKS.index(s)+1,*stored)]
            if len(anchors) != 1: reason = 'DEFER_MODERN_RIDING_ANCHOR'
            elif any(s in book for s in tc.learn_parents[825] | ac.learn_parents[825]):
                reason = 'DEFER_STORED_LEGACY_RIDING_TEACHER'
            elif default_blocks(default_skills,c[1],c[2]): reason = 'DEFER_LEGACY_DEFAULT_SKILL_ROUTE'
            elif any(x is None for r in owned[g] for x in r[2:]): reason = 'DEFER_UNKNOWN_ITEM_REQUIREMENT'
            elif any(r[6] == 149 or r[8] == 825 or r[10] == 149 or r[12] == 825 for r in owned[g]):
                reason = 'DEFER_ITEM_REQUIRES_LEGACY_RIDING'
        if reason:
            excluded.append((g,825,reason)); continue
        selected.append((g,825,1,0))
        proofs.append({'guid':g,'retired_spell':825,'retired_skill':[149,1,75],
                       'retained_riding_skill':[762,*stored], 'retained_enabled_anchor':anchors[0],
                       'legacy_forbidden_both_cores':True,'owned_inventory_mail_items_checked':len(owned[g]),
                       'teacher_6746_absent':True,'items_changed':0,'mounts_granted':0})
    if not preview and (not selected or expected != len(selected)):
        fail('OBSOLETE_RIDING_SELECTION_MISMATCH', f'--expect-rows must equal selected spell/skill pairs ({len(selected)})')
    summary = {'reviewed_candidate_rows':len(selected)+len(excluded), 'selected_rows':len(selected),
        'selected_characters':len(selected),'selected_groups':len(selected),'selected_direct_rows':0,
        'selected_related_rows':len(selected),'enabled_rows_removed':len(selected),'disabled_rows_removed':0,
        'skill_rows_changed':len(selected),'skill_rows_removed':len(selected),'spell_rows_inserted':0,
        'deferred_candidate_rows':len(excluded),'deferred':dict(Counter(r[2] for r in excluded)),
        'eligibility_proofs':proofs,
        'native_policy':'Retire forbidden Wolf Riding 825 AND skill 149 together only with an existing enabled matching modern Riding 762 anchor; preserve modern riding, mounts/items, both builds, other skills/caps, profession slots and flags; defer unknown item requirements, legacy dependencies and pending resets; no grants'}
    return selected,excluded,[],summary,[]


def items_query(settings, scope):
    source, tc, ac = settings.schemas['characters'], settings.schemas['world'], settings.get('target','world')
    fields = ['l.guid','l.item','x.guid','x.owner_guid','x.itemEntry', 't.entry',
              't.RequiredSkill','t.RequiredSkillRank','t.requiredspell', 'a.entry',
              'a.RequiredSkill','a.RequiredSkillRank','a.requiredspell']
    # UNION removes duplicate ownership/location references to the same item.
    query = (f'FROM (SELECT guid,item FROM `{source}`.character_inventory '
             f'UNION SELECT receiver,item_guid FROM `{source}`.mail_items '
             f'UNION SELECT m.receiver,mi.item_guid FROM `{source}`.mail m JOIN `{source}`.mail_items mi ON mi.mail_id=m.id '
             f'UNION SELECT owner_guid,guid FROM `{source}`.item_instance) l '
             f'LEFT JOIN `{source}`.item_instance x ON x.guid=l.item '
             f'LEFT JOIN `{tc}`.item_template t ON t.entry=x.itemEntry '
             f'LEFT JOIN `{ac}`.item_template a ON a.entry=x.itemEntry WHERE {scope}')
    return fields, query


def read_items(settings, guids):
    from cleanup_plans import metadata, snapshot
    names = [('source',settings.schemas['characters'],['character_inventory','mail','mail_items','item_instance']),
             ('tc',settings.schemas['world'],['item_template']),('ac',settings.get('target','world'),['item_template'])]
    shapes = {'character_inventory':{'guid','bag','slot','item'}, 'mail':{'id','receiver'}, 'mail_items':{'mail_id','receiver','item_guid'},
              'item_instance':{'guid','owner_guid','itementry'},
              'item_template':{'entry','requiredskill','requiredskillrank','requiredspell'}}
    layouts = {}
    for key,schema,tables in names:
        view = copy(settings); view.schemas = {**settings.schemas,'characters':schema}
        meta = metadata(view,tables)
        for table in tables: equipment_shape(meta,table,shapes[table])
        layouts[key] = {'schema':schema,'meta':dict(meta)}
    ids = ','.join(map(str,sorted(guids))) or '0'
    fields,query = items_query(settings,f'l.guid IN ({ids})')
    rows = snapshot(settings,[('items', f"SELECT JSON_ARRAY({','.join(fields)}) row_value {query} ORDER BY l.guid,l.item LIMIT 400001")])['items']
    if len(rows) > 400000 or any(n > 10000 for n in Counter(r[0] for r in rows).values()):
        fail('OBSOLETE_RIDING_ITEM_BOUND', 'More than 10000 items per character or 400000 scoped items')
    for key,schema,tables in names:
        view = copy(settings); view.schemas = {**settings.schemas,'characters':schema}
        if dict(metadata(view,tables)) != layouts[key]['meta']:
            fail('OBSOLETE_RIDING_ITEM_DRIFT', 'Item requirement layout changed during capture')
    return {'layouts':layouts,'rows':rows}


def restricted(capture, guids):
    ids = set(guids)
    return {'layouts':capture['layouts'],'rows':[r for r in capture['rows'] if r[0] in ids]}


def items_guard(settings, capture, guids):
    from cleanup_plans import planner
    checks = []
    for entry in capture['layouts'].values():
        schema,meta = entry['schema'],entry['meta']
        tables = ','.join("'"+r[0]+"'" for r in meta['tables'])
        checks.append(f"""IF (SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA='{schema}' AND TABLE_NAME IN ({tables})
 AND ENGINE='InnoDB' AND TABLE_TYPE='BASE TABLE')<>{len(meta['tables'])}
 OR (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA='{schema}' AND TABLE_NAME IN ({tables}))<>{len(meta['columns'])}
 OR NOT ((SELECT SHA2(GROUP_CONCAT(CONCAT_WS(':',TABLE_NAME,COLUMN_NAME,COLUMN_TYPE,IS_NULLABLE,COLUMN_KEY,EXTRA,
 COALESCE(GENERATION_EXPRESSION,''),ORDINAL_POSITION) ORDER BY BINARY TABLE_NAME,ORDINAL_POSITION SEPARATOR '|'),256)
 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA='{schema}' AND TABLE_NAME IN ({tables}))<=>'{planner.key_hash(meta['columns'])}') THEN
 SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Obsolete riding item requirement layout or engine changed'; END IF;""")
    grouped = defaultdict(list)
    for r in capture['rows']: grouped[r[0]].append(r)
    fingerprints = []
    for g in sorted(guids):
        hashes = ''.join(hashlib.sha256('|'.join('N' if x is None else str(x) for x in r).encode()).hexdigest()
                         for r in sorted(grouped[g],key=lambda r:r[1]))
        fingerprints.append([g,len(grouped[g]),hashlib.sha256(hashes.encode()).hexdigest()])
    expected = json.dumps(fingerprints,separators=(',',':'))
    fields,query = items_query(settings,'l.guid IN (SELECT guid FROM affected)')
    hashed = "SHA2(CONCAT_WS('|',"+','.join(f"IFNULL(CAST({f} AS CHAR),'N')" for f in fields)+'),256)'
    actual = f"SELECT l.guid,COUNT(*) n,SHA2(GROUP_CONCAT({hashed} ORDER BY l.item SEPARATOR ''),256) h {query} GROUP BY l.guid"
    empty = hashlib.sha256(b'').hexdigest()
    checks.append(f"""IF EXISTS(SELECT 1 FROM JSON_TABLE('{expected}','$[*]' COLUMNS(
 guid INT UNSIGNED PATH '$[0]',n INT UNSIGNED PATH '$[1]',h CHAR(64) PATH '$[2]')) e
 LEFT JOIN ({actual}) a ON a.guid=e.guid
 WHERE COALESCE(a.n,0)<>e.n OR NOT (BINARY COALESCE(a.h,'{empty}')<=>BINARY e.h)) THEN
 SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Obsolete riding owned/inventory/mail item requirements changed'; END IF;""")
    return '\n'.join(checks)
