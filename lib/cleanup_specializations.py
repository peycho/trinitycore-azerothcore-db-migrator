"""Retire inactive competing specializations; never infer a chosen specialty.

The current active choice is authoritative only after ordinary and specialization
prerequisites, native catalogs, skill state and live equipped-item checks pass.
"""
from collections import Counter,defaultdict
from copy import copy
import hashlib,json,re
from cleanup_console import ROOT,fail
from cleanup_talent_relations import MAX_ROWS,validate_stored
import cleanup_professions as professions
from spells import Unsupported

POLICY='tc-inactive-competing-specialization-retirement-v1'
POLICIES=(POLICY,)
ACK='RETIRE_INACTIVE_COMPETITORS_RETAIN_VERIFIED_ACTIVE_CHOICE'
CATALOG=ROOT/'lib/cleanup_specialization_catalog.json'
RULES=json.loads(CATALOG.read_text())
FAMILIES=RULES['families']
EQUIPPED_SLOTS=set(range(23))|set(range(67,74))
FIELDS=('guid','slot','item','item_guid','entry','tc_entry','tc_required','ac_entry','ac_required')


def native_sources(paths):
    for core,files in RULES['native_sources'].items():
        for name,expected in files.items():
            path=paths[core+'_source']/name
            if not path.is_file()or hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
                fail('SPECIALIZATION_NATIVE_SOURCE_DRIFT','Pinned specialization/equipment consumer differs: '+core+':'+name)
    return RULES['native_sources']


def contract(meta,family):
    rule=FAMILIES[family]
    if not professions.contract(meta,rule['root']):return False
    members=set(rule['members'])|({rule['specialization_prerequisite']}if rule.get('specialization_prerequisite')else set())
    nodes=members|{s for member in members for s in meta.learn_parents[member]}
    for spell in nodes:
        expected=RULES[meta.core].get(str(spell));row=meta.spells.get(spell,[])
        if (not expected or len(row)<212
                or any(row[i]!=expected['mechanics'].get(str(i),0)for i in (*range(4,131),*range(208,212)))
                or list(meta.chain(spell))!=expected['chain'] or meta.abilities[spell]!=expected['abilities']
                or [list(r)for r in meta.learns[spell]]!=expected['learns']
                or [list(r)for r in meta.effect_learns[spell]]!=expected['effect_learns']
                or sorted(meta.requires[spell])!=expected['requires']
                or sorted(meta.prerequisite_users[spell])!=expected['prerequisite_users']
                or sorted(meta.learn_parents[spell])!=expected['learn_parents']
                or meta.scripts[spell] or spell in meta.talents or meta.talent_learn_owners.get(spell)
                or meta.aura_owners[spell] or spell in meta.world_aura_owners or spell in meta.additional):return False
        try:meta.check_spell(spell)
        except Unsupported:return False
    return True


def ordinary_anchors(book,skills,tc,ac,rule):
    required=rule['ordinary_prerequisite'];anchors=[]
    chain=tc.chain(rule['root'])
    for s in chain:
        if book.get(s)!=(1,0)or(required!=s and required not in tc.predecessors(s)):continue
        effects=tc.skill_effect(s);stored=skills.get(rule['skill'])
        if (effects and effects==ac.skill_effect(s) and stored and stored[0]>=effects[2]and stored[1]>=effects[3]
                and all(book[x]in ((0,0),(1,0))for x in chain if x in book)):anchors.append(s)
    return anchors


def select(state,tc,ac,expected=None,*,preview=False,equipment):
    validate_stored(state['character_spell'])
    if not 1<=len(state['characters'])<=40000 or sum(map(len,state.values()))>MAX_ROWS:
        fail('SPECIALIZATION_BOUND','Captured scope exceeds reviewed bounds')
    chars={r[0]:r for r in state['characters']};books=defaultdict(dict);skills=defaultdict(dict);equipped=defaultdict(list)
    for g,s,a,d in state['character_spell']:books[g][s]=(a,d)
    for g,s,v,m in state['character_skills']:skills[g][s]=(v,m)
    for row in equipment:
        if (len(row)!=len(FIELDS)or any(x is not None and(type(x)!=int or not 0<=x<=0xffffffff)for x in row)
                or row[0]not in chars or row[1]is None or row[1]not in EQUIPPED_SLOTS):
            fail('SPECIALIZATION_EQUIPMENT_INVALID','Expected complete scoped equipment and item requirement evidence')
        equipped[row[0]].append(row)
    invalid,seen=set(),set()
    for g,s,k in state['character_talent']:
        c=chars.get(g);identity=tc.talents.get(s);row=tc.talent_rows.get(s,[])
        tab=tc.stores['TalentTab'].get(row[1],[])if identity else []
        key=(g,identity[0]if identity else -1,k)
        if (c is None or not identity or ac.talents.get(s)!=identity or s in tc.invalid_talents or s in ac.invalid_talents
                or ac.talent_rows.get(s)!=row or len(tab)<=20 or not 1<=c[2]<=32
                or ac.stores['TalentTab'].get(row[1],[0]*21)[20]!=tab[20]
                or not tab[20]&(1<<(c[2]-1)) or k not in (0,1)or k>=c[5]or key in seen):invalid.add(g)
        seen.add(key)
    safe={f:contract(tc,f)and contract(ac,f)for f in FAMILIES}
    selected,excluded,proofs=[],[],[]
    for g,c in sorted(chars.items()):
        book=books[g]
        for family,rule in FAMILIES.items():
            members=rule['members'];candidates=sorted(s for s in members if book.get(s)==(0,0))
            if not candidates:continue
            active=[s for s in members if book.get(s)==(1,0)];reason='';anchors=[]
            if c[6]:reason='DEFER_ONLINE_CHARACTER'
            elif c[7]&4:reason='DEFER_PENDING_NATIVE_RESET'
            elif (c[1]not in (1,2,3,4,5,6,7,8,10,11)or c[2]not in (1,2,3,4,5,6,7,8,9,11)
                    or not 1<=c[3]<=80 or c[5]not in (1,2)or not 0<=c[4]<c[5]):reason='DEFER_SPECIALIZATION_CHARACTER_STATE'
            elif c[3]<rule['minimum_level']:reason='DEFER_SPECIALIZATION_LEVEL'
            elif g in invalid:reason='DEFER_INVALID_TALENT_SELECTION'
            elif not safe[family]:reason='DEFER_SPECIALIZATION_METADATA'
            elif len(active)!=1 or any(book[s]not in ((0,0),(1,0))for s in members if s in book):reason='DEFER_AMBIGUOUS_ACTIVE_SPECIALIZATION'
            else:
                skill=rule['skill'];stored=skills[g].get(skill)
                if (not stored or not rule['minimum']<=stored[0]<=stored[1]or stored[1]not in (75,150,225,300,375,450)):
                    reason='DEFER_SPECIALIZATION_SKILL_STATE'
                elif not (anchors:=ordinary_anchors(book,skills[g],tc,ac,rule)):
                    reason='DEFER_SPECIALIZATION_ORDINARY_PREREQUISITE'
                elif rule.get('specialization_prerequisite')and book.get(rule['specialization_prerequisite'])!=(1,0):
                    reason='DEFER_SPECIALIZATION_PARENT'
                else:
                    # Explicit ordinary prerequisite covers stock missing AC
                    # requirement rows; additional/custom requirements cannot pass
                    # the frozen metadata contract above.
                    known=set(s for s,flags in book.items()if flags==(1,0))
                    for anchor in anchors:known.update(tc.predecessors(anchor))
                    for m in (tc,ac):
                        if not m.requires[active[0]]<=known:reason='DEFER_SPECIALIZATION_CHOICE_PREREQUISITE'
                    if any(parent in book for m in (tc,ac)for s in candidates for parent in m.learn_parents[s]):
                        reason=reason or 'DEFER_KNOWN_SPECIALIZATION_TEACHER'
                    if any(user in book for m in (tc,ac)for s in candidates for user in m.prerequisite_users[s]):
                        reason=reason or 'DEFER_SPECIALIZATION_DEPENDENT_SPELL'
                    for m in (tc,ac):
                        infos=[r for r in m.stores['SkillRaceClassInfo'].values()if r[1]==skill
                               and(not r[2]or r[2]&(1<<(c[1]-1)))and(not r[3]or r[3]&(1<<(c[2]-1)))]
                        if not infos:reason=reason or 'DEFER_SPECIALIZATION_RACE_CLASS'
                    rows=equipped[g]
                    if len(rows)>30 or len({r[1]for r in rows})!=len(rows):reason=reason or 'DEFER_DUPLICATE_EQUIPMENT_SLOT'
                    for row in rows:
                        if (any(x is None for x in row)or row[2]!=row[3]or row[4]!=row[5]or row[4]!=row[7]
                                or row[2]==0 or row[4]==0):reason=reason or 'DEFER_UNKNOWN_EQUIPPED_ITEM_REQUIREMENT'
                        elif row[6]in candidates or row[8]in candidates:reason=reason or 'DEFER_EQUIPPED_SPECIALIZATION_REQUIREMENT'
            if reason:
                excluded.extend((g,s,reason)for s in candidates);continue
            for spell in candidates:
                selected.append((g,spell,0,0));proofs.append({'guid':g,'removed_inactive_specialization':spell,
                    'retained_active_specialization':active[0],'family':family,'ordinary_known_anchors':anchors,
                    'preserved_skill':list(stored),'skill':skill,'known_eligibility_change':True,
                    'stored_recipes_preserved':True,'equipment_requirements_checked_in_both_worlds':True,
                    'spell_rows_inserted':0,'skill_rows_changed':0,'native_unlearn_effects_executed':False})
    selected.sort();excluded.sort()
    if not preview and(not selected or expected!=len(selected)):
        fail('SPECIALIZATION_SELECTION_MISMATCH',f'--expect-rows must equal preview selected_rows ({len(selected)})')
    summary={'reviewed_candidate_rows':len(selected)+len(excluded),'selected_rows':len(selected),
        'selected_characters':len({r[0]for r in selected}),'selected_groups':len({(p['guid'],p['family'])for p in proofs}),
        'selected_direct_rows':0,'selected_related_rows':len(selected),'inactive_rows_removed':len(selected),
        'enabled_rows_removed':len(selected),'active_rows_removed':0,'disabled_rows_removed':0,'spell_rows_inserted':0,'skill_rows_changed':0,
        'deferred_candidate_rows':len(excluded),'eligibility_proofs':proofs,'deferred':dict(Counter(r[2]for r in excluded)),
        'native_policy':'Retire only inactive/non-disabled competitors to one retained enabled verified specialization; explicit known-specialization eligibility correction; preserve stored recipes, skills/caps, talents, items and login flags; defer ambiguity, missing prerequisites and affected/unknown equipped item requirements; no grants or native unlearn casts'}
    return selected,excluded,[],summary,[]


def equipment_query(settings,scope):
    source=settings.schemas['characters'];tc=settings.schemas['world'];ac=settings.get('target','world')
    expressions=['i.guid','i.slot','i.item','x.guid','x.itemEntry','t.entry','t.requiredspell','a.entry','a.requiredspell']
    query=(f'FROM `{source}`.character_inventory i LEFT JOIN `{source}`.item_instance x ON x.guid=i.item '
           f'LEFT JOIN `{tc}`.item_template t ON t.entry=x.itemEntry LEFT JOIN `{ac}`.item_template a ON a.entry=x.itemEntry '
           f'WHERE {scope} AND i.bag=0 AND (i.slot<23 OR i.slot BETWEEN 67 AND 73)')
    return expressions,query


def equipment_shape(meta,table,fields):
    # MySQL column identifiers are case insensitive. Resolve their semantic
    # names here only; keep the original metadata untouched for exact sealing.
    rows=[r for r in meta['columns']if r[0]==table]
    actual={r[1].lower():r for r in rows}
    missing=set(fields)-actual.keys()
    if missing or len(actual)!=len(rows):
        message=(table+' missing required columns: '+', '.join(sorted(missing)))if missing else table+' has ambiguous column names'
        fail('SPECIALIZATION_EQUIPMENT_LAYOUT',message,
             'Expected native inventory/item identifiers and item_template.entry, requiredspell in both worlds; compare the actual table definitions.')
    if any(not re.match(r'^(?:tiny|small|medium|big)?int(?:\(|\b)',actual[f][2])for f in fields):
        fail('SPECIALIZATION_EQUIPMENT_LAYOUT','Native integer equipment/item identifiers and requirements required: '+table)


def read_equipment(settings,guids):
    from cleanup_plans import metadata,snapshot
    names=[('source',settings.schemas['characters'],['character_inventory','item_instance']),
           ('tc',settings.schemas['world'],['item_template']),('ac',settings.get('target','world'),['item_template'])]
    layouts={}
    for key,schema,tables in names:
        view=copy(settings);view.schemas={**settings.schemas,'characters':schema}
        meta=metadata(view,tables)
        for table in tables:
            fields={'guid','bag','slot','item'}if table=='character_inventory'else {'guid','itementry'}if table=='item_instance'else {'entry','requiredspell'}
            equipment_shape(meta,table,fields)
        layouts[key]={'schema':schema,'meta':dict(meta)}
    ids=','.join(map(str,sorted(guids)))or '0';fields,query=equipment_query(settings,f'i.guid IN ({ids})')
    rows=snapshot(settings,[('equipment',f"SELECT JSON_ARRAY({','.join(fields)}) row_value {query} ORDER BY i.guid,i.slot,i.item LIMIT 1200001")])['equipment']
    if len(rows)>1200000:fail('SPECIALIZATION_EQUIPMENT_BOUND','Equipment capture exceeds native scope bound')
    for key,schema,tables in names:
        view=copy(settings);view.schemas={**settings.schemas,'characters':schema}
        if dict(metadata(view,tables))!=layouts[key]['meta']:fail('SPECIALIZATION_EQUIPMENT_DRIFT','Equipment or item template layout changed during capture')
    return {'layouts':layouts,'rows':rows}


def restricted(capture,guids):
    ids=set(guids)
    return {'layouts':capture['layouts'],'rows':[r for r in capture['rows']if r[0]in ids]}


def equipment_guard(settings,capture,guids):
    from cleanup_plans import planner
    checks=[]
    for entry in capture['layouts'].values():
        schema=entry['schema'];meta=entry['meta'];tables=','.join("'"+r[0]+"'"for r in meta['tables'])
        checks.append(f"""IF (SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA='{schema}' AND TABLE_NAME IN ({tables})
 AND ENGINE='InnoDB' AND TABLE_TYPE='BASE TABLE')<>{len(meta['tables'])}
 OR (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA='{schema}' AND TABLE_NAME IN ({tables}))<>{len(meta['columns'])}
 OR NOT ((SELECT SHA2(GROUP_CONCAT(CONCAT_WS(':',TABLE_NAME,COLUMN_NAME,COLUMN_TYPE,IS_NULLABLE,COLUMN_KEY,EXTRA,
 COALESCE(GENERATION_EXPRESSION,''),ORDINAL_POSITION) ORDER BY BINARY TABLE_NAME,ORDINAL_POSITION SEPARATOR '|'),256)
 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA='{schema}' AND TABLE_NAME IN ({tables}))<=>'{planner.key_hash(meta['columns'])}') THEN
 SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Specialization equipment/item layout or engine changed'; END IF;""")
    fields,query=equipment_query(settings,'i.guid IN (SELECT guid FROM affected)')
    hashed="SHA2(CONCAT_WS('|',"+','.join(f"IFNULL(CAST({f} AS CHAR),'N')"for f in fields)+'),256)'
    rows=defaultdict(list)
    for r in capture['rows']:rows[r[0]].append(r)
    fingerprints=[]
    for g in sorted(guids):
        hashes=''.join(hashlib.sha256('|'.join('N'if x is None else str(x)for x in r).encode()).hexdigest()for r in sorted(rows[g],key=lambda r:(r[1],r[2])))
        fingerprints.append([g,len(rows[g]),hashlib.sha256(hashes.encode()).hexdigest()])
    expected=json.dumps(fingerprints,separators=(',',':'))
    actual=f"SELECT i.guid,COUNT(*) n,SHA2(GROUP_CONCAT({hashed} ORDER BY i.slot,i.item SEPARATOR ''),256) h {query} GROUP BY i.guid"
    empty=hashlib.sha256(b'').hexdigest()
    checks.append(f"""IF EXISTS(SELECT 1 FROM JSON_TABLE('{expected}','$[*]' COLUMNS(
 guid INT UNSIGNED PATH '$[0]',n INT UNSIGNED PATH '$[1]',h CHAR(64) PATH '$[2]')) e
 LEFT JOIN ({actual}) a ON a.guid=e.guid
 WHERE COALESCE(a.n,0)<>e.n OR NOT (BINARY COALESCE(a.h,'{empty}')<=>BINARY e.h)) THEN
 SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Specialization equipped item or required-spell evidence changed'; END IF;""")
    return '\n'.join(checks)
