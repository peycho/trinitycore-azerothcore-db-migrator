"""Review disabled trained talent ranks even when their direct root is absent."""
from collections import Counter, defaultdict
import json

from cleanup_console import ROOT, PROFILE, fail, local_id, sha, verify
from cleanup_talent_relations import Relations, validate_stored, MAX_ROWS

POLICY = 'tc-disabled-unselected-trained-talent-history-v6'


def inspection(settings, work, inspection_id):
    """A semantic context snapshot is evidence, never an executable cleanup."""
    from cleanup_migration_evidence import FIELDS
    from cleanup_plans import sha_json
    path=work.session/'inspections'/local_id(inspection_id)
    contents=verify(path)
    required={'README.md','character-context.jsonl','groups.tsv','inspection.json','source-layout.json',
              'source-state.json','spell-metadata-profile.json','spell-state-blockers.tsv','tc-world.json'}
    if set(contents)!=required:fail('TRAINED_HISTORY_EVIDENCE_INVALID','Expected a complete migration blocker context inspection')
    report=json.loads(contents['inspection.json']);source=json.loads(contents['source-state.json'])
    raw=source.get('rows',{});world=json.loads(contents['tc-world.json'])
    layout=json.loads(contents['source-layout.json'])
    if (report.get('status')!='COMPLETE_REVIEW_ONLY' or report.get('source_schema')!=settings.schemas['characters']
            or report.get('source_uuid')!=work.current()['identity']['uuid']
            or source.get('fields')!=FIELDS or set(raw)!=set(FIELDS)
            or sha_json(raw)!=report.get('source_state_sha256') or sha_json(world)!=report.get('world_sha256')
            or report.get('tool_sha256')!=sha(ROOT/'lib/cleanup_migration_evidence.py')
            or contents['spell-metadata-profile.json']!=(PROFILE/'spell-metadata.json').read_bytes()):
        fail('TRAINED_HISTORY_EVIDENCE_INVALID','Context producer, source identity, profile or snapshot hash differs')
    if sum(map(len,raw.values()))>MAX_ROWS or not 1<=len(raw['characters'])<=40000:
        fail('HISTORY_RELATION_BOUND','Trained history context exceeds the captured row/character bounds')
    for table,fields in FIELDS.items():
        if any(not isinstance(r,list) or len(r)!=len(fields) or any(type(x)!=int or not 0<=x<=0xffffffff for x in r) for r in raw[table]):
            fail('TRAINED_HISTORY_EVIDENCE_INVALID','Invalid semantic fields in '+table)
        keys=[(r[0],) if table=='characters' else tuple(r[:3]) if table=='character_talent' else tuple(r[:2]) for r in raw[table]]
        if len(set(keys))!=len(keys):fail('TRAINED_HISTORY_EVIDENCE_INVALID','Duplicate source keys in '+table)
    guids={r[0] for r in raw['characters']}
    if 0 in guids or any(r[0] not in guids for table in FIELDS for r in raw[table]):
        fail('TRAINED_HISTORY_EVIDENCE_INVALID','Missing character or out-of-scope source row in context')
    state={'characters':sorted([g,r,c,a,n,o,f] for g,r,c,level,a,n,o,f in raw['characters']),
           'talents':sorted(raw['character_talent'])}
    # The normal history materializer also checks all direct talent rows.
    from cleanup_plans import ranks
    _,catalog,dbc=ranks(settings)
    direct_ids=set(catalog)
    state['spells']=sorted(r for r in raw['character_spell'] if r[1] in direct_ids)
    if any(report.get('dbc_sha256',{}).get('tc.'+name)!=checksum for name,checksum in dbc.items()):
        fail('DBC_DRIFT','Captured talent/DBC inputs differ from configured assets')
    scoped={k:[r for r in value if r[0] in ('characters','character_talent','character_spell')] for k,value in layout.items()}
    adapted={'audit':None,'metadata_sha256':sha_json(scoped)}
    audit={'audited_results_sha256':report['source_state_sha256'],
           'dbc_sha256':{name.removeprefix('tc.'):value for name,value in report['dbc_sha256'].items()}}
    return path,adapted,state,raw,audit,world,layout,report


def select(state, meta, expected):
    stored=state['character_spell'];validate_stored(stored)
    candidates=[r for r in stored if r[3]==1 and r[1] not in meta.talents and meta.first(r[1]) in meta.talents]
    if not 1<=expected<=500000 or len(candidates)!=expected:
        fail('TRAINED_HISTORY_SELECTION_MISMATCH','--expect-review-rows must equal all disabled trained talent-rank rows in the captured character scope')
    graph=Relations(meta)
    chars={r[0]:r for r in state['characters']}
    owners=defaultdict(set);invalid=set();group_owners=set()
    for guid,spell,group in state['character_talent']:
        char=chars.get(guid);identity=meta.talents.get(spell)
        if char is None or identity is None:
            invalid.add(guid);continue
        tab=meta.stores['TalentTab'].get(meta.talent_rows[spell][1],[])
        key=(guid,identity[0],group)
        if (char[2] not in (1,2,3,4,5,6,7,8,9,11) or len(tab)<=20
                or not tab[20] & (1<<(char[2]-1)) or not 0<=group<char[5] or key in group_owners):
            invalid.add(guid)
        group_owners.add(key);owners[guid].add(spell)
    by_guid=defaultdict(dict)
    for g,s,a,d in stored:by_guid[g][s]=(a,d)
    grouped=defaultdict(list)
    for row in candidates:grouped[row[0],meta.talents[meta.first(row[1])][0]].append(row)
    catalog={family:graph.family(family,True) for family in sorted({f for _,f in grouped})}
    if sum(len(nodes) for nodes,_ in catalog.values())>MAX_ROWS:
        fail('HISTORY_RELATION_BOUND','Trained talent relationship review exceeds its node bound')
    selected={};excluded=[];proof=[];accepted=[]
    for (guid,family),anchors in sorted(grouped.items()):
        nodes,reason=catalog[family];char=chars.get(guid)
        if char is None or char[2] not in (1,2,3,4,5,6,7,8,9,11) or char[5] not in (1,2) or not 0<=char[4]<char[5]:
            reason='DEFER_INVALID_CHARACTER_STATE'
        elif char[6]:reason='DEFER_ONLINE_CHARACTER'
        elif char[7]&4:reason='DEFER_PENDING_NATIVE_RESET'
        elif guid in invalid:reason='DEFER_INVALID_TALENT_SELECTION'
        else:
            for root in graph.families[family]:
                tab=meta.stores['TalentTab'].get(meta.talent_rows[root][1],[])
                if len(tab)<=20 or tab[20]!=(1<<(char[2]-1)):
                    reason='DEFER_FOREIGN_CLASS_TALENT';break
        if not reason and owners[guid]&nodes:reason='DEFER_SELECTED_RELATED_TALENT'
        present={s:flags for s,flags in by_guid[guid].items() if s in nodes}
        if not reason and any(a not in (0,1) or d not in (0,1) for a,d in present.values()):
            reason='DEFER_INVALID_RELATED_FLAGS'
        if not reason and any(d!=1 for a,d in present.values()):reason='DEFER_ENABLED_RELATED_SPELL'
        # V4's exact missing-teacher exception still requires the entire
        # rejected teacher/target pair to be absent, not just the direct root.
        invalid_teacher=family==1927 and 50321 not in meta.spells
        if not reason and invalid_teacher and any(s in by_guid[guid] for s in (51266,50321)):
            reason='DEFER_INVALID_TEACHER_STORED'
        if reason:
            excluded.extend((guid,r[1],reason) for r in anchors);continue
        accepted.extend((guid,r[1]) for r in anchors)
        for spell in sorted(nodes):
            flags=present.get(spell)
            role='DIRECT_TALENT' if spell in graph.families[family] else 'TRAINED_OR_DEPENDENT'
            proof.append((guid,family,spell,role,'SELECTED_DISABLED' if flags else 'ABSENT_NO_GRANT',*(flags or ('',''))))
            if flags:selected[guid,spell]=(guid,spell,*flags)
        if len(proof)>MAX_ROWS or len(selected)>500000:
            fail('HISTORY_RELATION_BOUND','Trained talent history selection/evidence exceeds its bound')
    if not selected:
        counts=', '.join(f'{r}={n}' for r,n in sorted(Counter(r[2] for r in excluded).items()))
        fail('HISTORY_NO_ELIGIBLE_ROWS','No disabled trained talent history group qualifies: '+counts)
    summary={'reviewed_trained_rows':len(candidates),'selected_anchor_rows':len(accepted),
             'selected_groups':len({(r[0],r[1]) for r in proof}),
             'selected_direct_rows':sum(s in meta.talents for _,s in selected),
             'selected_related_rows':sum(s not in meta.talents for _,s in selected),
             'native_policy':'Archive wholly disabled unselected trained talent rank/dependency groups even with absent direct roots; no enabled spells, selected owners, skill changes, grants or resets'}
    return sorted(selected.values()),sorted(excluded),proof,summary,sorted(graph.edges)
