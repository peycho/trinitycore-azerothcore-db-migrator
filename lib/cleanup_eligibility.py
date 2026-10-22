"""Explicit retirement of ordinary spell families AC rejects for race/class.

Both effective catalogs must agree. No talent authority, skill repair, spell
insertion, flag rewrite or broader migration exception is implied.
"""
from collections import Counter, defaultdict
import json
import re

from cleanup_console import PROFILE, fail, identifier
from cleanup_talent_relations import Relations, MAX_ROWS, validate_stored
from spells import Metadata, Unsupported

POLICY = 'tc-ineligible-ordinary-spell-repair-v1'
ABSENT_TEACHER_POLICY = 'tc-ineligible-ordinary-absent-teacher-repair-v2'
POLICIES = (POLICY, ABSENT_TEACHER_POLICY)
ACK = 'RETIRE_VERIFIED_INELIGIBLE_SPELLS'
ABSENT_TEACHER_ACK = 'VERIFIED_TEACHERS_ABSENT'

# Only pure, single-child stock teaching actions. Multi-child stance teachers,
# skill teachers and arbitrary world learn links are deliberately not included.
ABSENT_TEACHERS = {5504: ((5507,5504), (5565,5505), (5566,5506), (6128,6127),
                         (10141,10138), (10142,10139), (10143,10140),
                         (42978,27090), (37421,37420)),
                   18540: ((20700,18540),)}


def absent_teacher_contract(tc, ac, graphs, root, book):
    """Prove inert incoming routes; never remove a known teacher or its child here."""
    pairs = ABSENT_TEACHERS.get(root)
    if not pairs:
        return None
    nodes = set(tc.chain(root))
    expected = {(p,c,kind) for p,c in pairs for kind in ('WORLD_LEARN','EFFECT_LEARN')}
    for meta, graph in zip((tc,ac), graphs):
        edges = {r for r in graph.edges if r[0] in nodes or r[1] in nodes}
        if edges != expected:
            return None
        for parent, child in pairs:
            row = meta.spells.get(parent, [])
            gates = [0]*16
            if parent != 10143:
                gates[4] = 256
            if (parent in book or parent not in meta.spells or meta.chain(parent) != (parent,)
                    or len(row) < 212 or row[4:12] != [262400,0,0,0,0,0,0,0]
                    or row[12:28] != gates or row[71:74] != [36,0,0]
                    or row[86:92] != ([25,0,0,0,0,0] if parent == 10143 else [0]*6)
                    or row[95:98] != [0,0,0] or row[116:119] != [child,0,0]
                    or row[208:212] != [0,0,0,0] or meta.abilities[parent]
                    or meta.scripts[parent] or meta.requires[parent]
                    or meta.learns[parent] != [(child,1,False)]
                    or meta.effect_learns[parent] != [(child,1,False)]
                    or graph.incoming[parent] or graph.next[parent] != {root}
                    or parent in meta.talents or parent in meta.talent_learn_owners
                    or parent in meta.aura_owners or parent in meta.world_aura_owners
                    or parent in meta.additional or parent in graph.unsupported):
                return None
            try:
                meta.check_spell(parent)
            except Unsupported:
                return None
    return {'contract':'ABSENT_SINGLE_CHILD_TEACHERS_V1',
            'pairs':[list(pair) for pair in pairs], 'all_teachers_absent':True,
            'native_route':'Only adding a known parent traverses its learn map; no incoming parent route',
            'custom_start_settings':[0,0], 'teacher_rows_removed':0, 'spell_rows_inserted':0}


def configuration_contract(settings):
    world = settings.get('target', 'world')
    if not world:
        fail('ELIGIBILITY_TARGET_REQUIRED', 'Set [target] world to the read-only AC world schema')
    world = identifier(world)
    if world in settings.schemas.values():
        fail('ELIGIBILITY_TARGET_OVERLAP', 'AC world must differ from every preparation source schema')
    if (settings.get('source', 'player_start_all_spells') != '0'
            or settings.get('target', 'player_start_custom_spells') != '0'):
        fail('ELIGIBILITY_CONFIG_REQUIRED',
             'This policy requires [source] player_start_all_spells = 0 and [target] player_start_custom_spells = 0',
             'Verify TC PlayerStart.AllSpells and AC PlayerStart.CustomSpells in their effective configurations; '
             'these values are operator assertions, not configuration changes.')
    if not settings.paths.get('ac_dbc') or not settings.paths.get('ac_source'):
        fail('ELIGIBILITY_TARGET_REQUIRED', 'Set [paths] ac_dbc and ac_source for the reviewed AC inputs')
    return {'target_world': world, 'source_player_start_all_spells': 0,
            'target_player_start_custom_spells': 0, 'evidence': 'OPERATOR_ASSERTION',
            'policy': 'No custom starting-spell route may reactivate retired rows'}


def read_target(settings):
    """Capture all AC Metadata inputs, including database DBC overlays, read-only."""
    from cleanup_plans import snapshot
    from cleanup_active_reset import exact_hex
    contract = configuration_contract(settings)
    schema = contract['target_world']
    profile = json.loads((PROFILE/'spell-metadata.json').read_text())
    names = sorted({layout['table'] for layout in profile['stores'].values()} |
                   {'spell_ranks', 'spell_required', 'spell_script_names', 'spell_custom_attr', 'trainer_spell'})
    quoted = ','.join("'"+name+"'" for name in names)
    layout_queries = [('columns',
        "SELECT JSON_ARRAY(TABLE_NAME,COLUMN_NAME,COLUMN_TYPE,IS_NULLABLE,ORDINAL_POSITION,EXTRA) row_value "
        f"FROM information_schema.COLUMNS WHERE TABLE_SCHEMA='{schema}' AND TABLE_NAME IN ({quoted}) "
        "ORDER BY BINARY TABLE_NAME,ORDINAL_POSITION"), ('tables',
        f"SELECT JSON_ARRAY(TABLE_NAME,ENGINE,TABLE_TYPE) row_value FROM information_schema.TABLES WHERE TABLE_SCHEMA='{schema}' "
        f"AND TABLE_NAME IN ({quoted}) ORDER BY BINARY TABLE_NAME")]
    layout = snapshot(settings, layout_queries)
    if layout['tables'] != [[name, 'InnoDB', 'BASE TABLE'] for name in names]:
        fail('ELIGIBILITY_TARGET_METADATA', 'Required AC metadata tables must exist and use InnoDB')
    queries = []
    for table in names:
        fields = [identifier(r[1]) for r in layout['columns'] if r[0] == table]
        if not fields or len(fields) > 256:
            fail('ELIGIBILITY_TARGET_METADATA', 'Missing or oversized AC metadata layout: '+table)
        columns = ','.join('`'+name+'`' for name in fields)
        types = {r[1]:r[2] for r in layout['columns'] if r[0] == table}
        hashed = "SHA2(CONCAT_WS('|',"+','.join(f"IFNULL({exact_hex('`'+name+'`',types[name])},'N')" for name in fields)+'),256)'
        queries.append((table, f'SELECT JSON_ARRAY({columns}) row_value FROM `{schema}`.`{table}` LIMIT 100001'))
        queries.append(('digests', f"SELECT JSON_ARRAY('{table}',COUNT(*),SHA2(COALESCE(GROUP_CONCAT({hashed} "
                        f"ORDER BY BINARY {hashed} SEPARATOR ''),''),256)) row_value FROM `{schema}`.`{table}`"))
    original_sql = settings.sql
    def bounded_sql(query, *args, **kwargs):
        return original_sql("SET SESSION time_zone='+00:00';\nSET SESSION group_concat_max_len=6400001;\n"+query, *args, **kwargs)
    settings.sql = bounded_sql
    try:
        captured = snapshot(settings, queries)
    finally:
        settings.sql = original_sql
    if any(len(captured[name]) > 100000 for name in names):
        fail('ELIGIBILITY_TARGET_BOUND', 'AC metadata exceeds the 100000-row per-table bound')
    if any(not isinstance(r[2], str) or not re.fullmatch('[a-f0-9]{64}', r[2]) for r in captured['digests']):
        fail('ELIGIBILITY_TARGET_METADATA', 'AC content digest could not be computed')
    if snapshot(settings, layout_queries) != layout:
        fail('ELIGIBILITY_TARGET_DRIFT', 'AC metadata layout changed during capture')
    rows = {name: sorted(captured[name], key=lambda r: json.dumps(r, separators=(',', ':'))) for name in names}
    class Captured:
        def table(self, world, table, fields, optional=False):
            columns = [r[1] for r in layout['columns'] if r[0] == table]
            positions = {name.lower(): i for i, name in enumerate(columns)}
            if (world != schema or table not in rows
                    or any(f.lower() not in positions for f in fields)
                    or table.endswith('_dbc') and columns != fields):
                fail('ELIGIBILITY_TARGET_METADATA', 'AC overlay/relationship fields differ: '+table)
            selected = [[r[positions[f.lower()]] for f in fields] for r in rows[table]]
            return sorted(selected, key=lambda r: tuple(str(v) for v in r))
    try:
        effective = Metadata('ac', settings.paths['ac_dbc'], schema, profile, Captured())
    except Unsupported as error:
        fail(error.reason, 'AC eligibility metadata: '+str(error))
    return effective, {'layout': dict(layout), 'rows': rows, 'digests': sorted(captured['digests'])}


def world_checks(schema, world):
    """SQL checks protect direct calls as well as the shell console."""
    from cleanup_plans import planner
    from cleanup_active_reset import exact_hex
    names = ','.join("'"+r[0]+"'" for r in world['layout']['tables'])
    checks = [f"""IF (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA='{schema}' AND TABLE_NAME IN ({names}))<>{len(world['layout']['columns'])}
 OR NOT ((SELECT SHA2(COALESCE(GROUP_CONCAT(CONCAT_WS(':',TABLE_NAME,COLUMN_NAME,COLUMN_TYPE,IS_NULLABLE,ORDINAL_POSITION,EXTRA)
 ORDER BY BINARY TABLE_NAME,ORDINAL_POSITION SEPARATOR '|'),''),256) FROM information_schema.COLUMNS
 WHERE TABLE_SCHEMA='{schema}' AND TABLE_NAME IN ({names}))<=>'{planner.key_hash(world['layout']['columns'])}')
 OR (SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA='{schema}' AND TABLE_NAME IN ({names}))<>{len(world['layout']['tables'])}
 OR NOT ((SELECT SHA2(COALESCE(GROUP_CONCAT(CONCAT_WS(':',TABLE_NAME,ENGINE,TABLE_TYPE) ORDER BY BINARY TABLE_NAME SEPARATOR '|'),''),256)
 FROM information_schema.TABLES WHERE TABLE_SCHEMA='{schema}' AND TABLE_NAME IN ({names}))<=>'{planner.key_hash(world['layout']['tables'])}') THEN
 SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Eligibility world layout or engine drift'; END IF;"""]
    for table, count, checksum in world['digests']:
        fields = [r[1] for r in world['layout']['columns'] if r[0] == table]
        types = {r[1]:r[2] for r in world['layout']['columns'] if r[0] == table}
        hashed = "SHA2(CONCAT_WS('|',"+','.join(f"IFNULL({exact_hex('`'+name+'`',types[name])},'N')" for name in fields)+'),256)'
        checks.append(f"""IF (SELECT COUNT(*) FROM `{schema}`.`{table}`)<>{count}
 OR NOT ((SELECT SHA2(COALESCE(GROUP_CONCAT({hashed} ORDER BY BINARY {hashed} SEPARATOR ''),''),256)
 FROM `{schema}`.`{table}`)<=>'{checksum}') THEN
 SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Eligibility world content drift: {table}'; END IF;""")
    return '\n'.join(checks)


def eligibility(meta, spell, race, cls, *, infos_by_skill=None):
    """Match AC CheckSkillLearnedBySpell, not the ability's own class masks."""
    skills = sorted({a[1] for a in meta.abilities[spell] if a[1] in meta.stores['SkillLine']})
    infos = sorted(r for r in meta.stores['SkillRaceClassInfo'].values() if r[1] in skills) if infos_by_skill is None else sorted(
        r for skill in skills for r in infos_by_skill.get(skill, ()))
    matches = [r for r in infos if (not r[2] or r[2] & (1 << (race-1)))
               and (not r[3] or r[3] & (1 << (cls-1)))]
    return {'passes': not skills or bool(matches), 'skills': skills, 'skill_info': infos}


def select(state, tc, ac, expected=None, *, preview=False, absent_teachers=False):
    stored = state['character_spell']
    validate_stored(stored)
    if not 1 <= len(state['characters']) <= 40000 or sum(map(len, state.values())) > MAX_ROWS:
        fail('ELIGIBILITY_BOUND', 'Captured scope exceeds reviewed bounds')
    chars = {r[0]: r for r in state['characters']}
    if len(chars) != len(state['characters']):
        fail('ELIGIBILITY_INPUT_INVALID', 'Duplicate character keys')
    books, skills = defaultdict(dict), defaultdict(set)
    for g, s, a, d in stored:
        if g not in chars or s not in tc.spells or s not in ac.spells:
            fail('ELIGIBILITY_INPUT_INVALID', 'Unknown or out-of-scope spell row')
        books[g][s] = (a, d)
    for g, s, _, _ in state['character_skills']:
        if g not in chars:
            fail('ELIGIBILITY_INPUT_INVALID', 'Out-of-scope skill row')
        skills[g].add(s)
    invalid, seen = set(), set()
    for g, s, group in state['character_talent']:
        c, identity = chars.get(g), tc.talents.get(s)
        tab = tc.stores['TalentTab'].get(tc.talent_rows[s][1], []) if identity else []
        key = (g, identity[0] if identity else -1, group)
        if (c is None or not identity or s in tc.invalid_talents or len(tab) <= 20
                or not 1 <= c[2] <= 32 or not tab[20] & (1 << (c[2]-1))
                or c[5] not in (1, 2) or group not in (0, 1) or group >= c[5] or key in seen
                or ac.talents.get(s) != identity):
            invalid.add(g)
        seen.add(key)
    graphs = (Relations(tc), Relations(ac))
    indexes, cache, teacher_catalog = {}, {}, {}
    for m in (tc, ac):
        index = defaultdict(list)
        for r in m.stores['SkillRaceClassInfo'].values():
            index[r[1]].append(r)
        indexes[id(m)] = index
    def check(m, s, c):
        key = (id(m), s, c[1], c[2])
        if key not in cache:
            cache[key] = eligibility(m, s, c[1], c[2], infos_by_skill=indexes[id(m)])
        return cache[key]
    selected, excluded, proof, native = [], [], [], []
    reviewed = groups = 0
    for g, book in sorted(books.items()):
        c = chars[g]
        valid = (c[1] in (1,2,3,4,5,6,7,8,10,11) and c[2] in (1,2,3,4,5,6,7,8,9,11)
                 and 1 <= c[3] <= 80 and c[5] in (1,2) and 0 <= c[4] < c[5])
        if not 1 <= c[1] <= 32 or not 1 <= c[2] <= 32:
            reviewed += len(book)
            for s in sorted(book):
                excluded.append((g, s, 'DEFER_ELIGIBILITY_CHARACTER_STATE'))
            continue
        roots = sorted({tc.first(s) for s in book if not check(ac, s, c)['passes']})
        for root in roots:
            nodes = tc.chain(root)
            present = sorted(set(nodes) & book.keys())
            reviewed += len(present)
            reason = ''
            teacher_proof = None
            if absent_teachers and any(graph.incoming[root] or graph.next[root] for graph in graphs):
                # Review catalog edges once per root, then prove absence in each
                # complete character book. Never rescan the catalog per row.
                if root not in teacher_catalog:
                    teacher_catalog[root] = absent_teacher_contract(tc,ac,graphs,root,{})
                candidate = teacher_catalog[root]
                if candidate and not any(parent in book for parent,_ in candidate['pairs']):
                    teacher_proof = candidate
            if not valid:
                reason = 'DEFER_ELIGIBILITY_CHARACTER_STATE'
            elif c[6]:
                reason = 'DEFER_ONLINE_CHARACTER'
            elif c[7] & 4:
                reason = 'DEFER_PENDING_NATIVE_RESET'
            elif g in invalid:
                reason = 'DEFER_INVALID_TALENT_SELECTION'
            elif any(a not in (0,1) or d not in (0,1) for a,d in (book[s] for s in present)):
                reason = 'DEFER_INVALID_RELATED_FLAGS'
            elif any(ac.chain(s) != nodes for s in nodes):
                reason = 'DEFER_INCOMPATIBLE_RANK_CHAIN'
            elif any(check(m, s, c)['passes'] for m in (tc, ac) for s in nodes):
                reason = 'DEFER_ELIGIBLE_OR_DISAGREEING_RANK'
            elif any(not any(r[1] == skill for r in check(m,s,c)['skill_info'])
                     for m in (tc,ac) for s in nodes for skill in check(m,s,c)['skills']):
                reason = 'DEFER_MISSING_NATIVE_SKILL_INFO'
            elif any(s in m.talents or s in m.talent_learn_owners or s in m.aura_owners
                     or s in m.world_aura_owners or s in m.additional for m in (tc, ac) for s in nodes):
                reason = 'DEFER_TALENT_OR_AURA_ROUTE'
            elif any(graph.incoming[root] or graph.next[root] for graph in graphs) and teacher_proof is None:
                reason = 'DEFER_LEARNING_OR_REQUIREMENT_ROUTE'
            elif any(s in graph.unsupported or s in graph.unknown_skill_spells for graph in graphs for s in nodes):
                reason = 'DEFER_UNSUPPORTED_RELATION_METADATA'
            elif any(a[1] in skills[g] for m in (tc, ac) for s in nodes for a in m.abilities[s]):
                reason = 'DEFER_EXISTING_ASSOCIATED_SKILL'
            elif any(m.stores['SkillLine'][a[1]][1] not in (6,7)
                     for m in (tc, ac) for s in nodes for a in m.abilities[s]):
                reason = 'DEFER_PROFESSION_RIDING_OR_NONPLAYER_SKILL'
            elif any(set(m.spells[s][71:74]) & {36,40,44,47,118}
                     or set(m.spells[s][95:98]) & {30,98} for m in (tc, ac) for s in nodes):
                reason = 'DEFER_LEARN_OR_SKILL_EFFECT'
            elif any(m.scripts[s] for m in (tc, ac) for s in nodes):
                reason = 'DEFER_SCRIPTED_SPELL_FAMILY'
            else:
                for s in nodes:
                    left, right = check(tc, s, c), check(ac, s, c)
                    if (left != right or sorted(tc.abilities[s]) != sorted(ac.abilities[s])
                            or any(tc.stores['SkillLine'][k][1] != ac.stores['SkillLine'][k][1] for k in left['skills'])):
                        reason = 'DEFER_INCOMPATIBLE_ELIGIBILITY_METADATA'
                        break
                    try:
                        tc.check_spell(s)
                        ac.check_spell(s)
                    except Unsupported as error:
                        reason = 'DEFER_ELIGIBILITY_' + error.reason
                        break
            if reason:
                excluded.extend((g, s, reason) for s in present)
                continue
            groups += 1
            selected.extend((g, s, *book[s]) for s in present)
            native.append({'guid': g, 'rank_root': root, 'race': c[1], 'class': c[2],
                           'stored_spells': present, 'native_skill_grants': False,
                           **({'absent_teacher_contract':teacher_proof} if teacher_proof else {}),
                           'ranks': [{'spell': s, **check(ac, s, c)} for s in nodes]})
            proof.extend((g, root, s, 'INELIGIBLE_ORDINARY_RANK',
                          'REMOVE_INELIGIBLE_ENABLED' if s in book and not book[s][1]
                          else 'REMOVE_INELIGIBLE_DISABLED' if s in book else 'ABSENT_NO_GRANT',
                          *(book.get(s, ('','')))) for s in nodes)
            if len(proof) > MAX_ROWS:
                fail('ELIGIBILITY_BOUND', 'Eligibility proof exceeds reviewed bounds')
    selected.sort()
    excluded.sort()
    if len(selected) > 500000:
        fail('ELIGIBILITY_BOUND', 'More than 500000 exact selected spell rows')
    if not preview and (not selected or expected != len(selected)):
        fail('ELIGIBILITY_SELECTION_MISMATCH', f'--expect-rows must equal preview selected_rows ({len(selected)})')
    summary = {'reviewed_candidate_rows': reviewed, 'selected_rows': len(selected),
               'selected_characters': len({r[0] for r in selected}), 'selected_groups': groups,
               'selected_direct_rows': 0, 'selected_related_rows': len(selected),
               'enabled_rows_removed': sum(not r[3] for r in selected),
               'disabled_rows_removed': sum(bool(r[3]) for r in selected),
               'deferred_candidate_rows': len(excluded), 'deferred': dict(Counter(r[2] for r in excluded)),
               'spell_rows_inserted': 0, 'skill_rows_changed': 0,
               'eligibility_proofs': native,
               'native_policy': 'Retire exact ordinary rank families ineligible in both catalogs, including enabled rows; '
               'no associated stored skill, talent/aura/dependency/script/riding/profession route or pending reset; '
               'preserve all talents, skills/caps, profession slots, flags and unrelated data; no grants'}
    if absent_teachers:
        summary['reviewed_absent_teacher_rows'] = sum(len(p['stored_spells']) for p in native if 'absent_teacher_contract' in p)
        summary['native_policy'] += '; only exact reviewed absent single-child teachers may supply inert incoming routes'
    return selected, excluded, proof, summary, sorted(graphs[0].edges | graphs[1].edges)
