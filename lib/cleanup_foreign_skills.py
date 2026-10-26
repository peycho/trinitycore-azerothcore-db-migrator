"""Review complete foreign player skill families, not isolated failing spells.

Selected talents remain authoritative. Only native skill families forbidden for
the character in both catalogs qualify. No profession, racial or riding skill,
item move, native unlearn cast, skill insertion or talent mutation is allowed.
"""
from collections import Counter,defaultdict
from cleanup_console import fail
from cleanup_talent_relations import validate_stored,MAX_ROWS
from spells import Unsupported
import cleanup_native_actions as native_actions
import cleanup_obsolete_riding as riding
import cleanup_shaman_dual_wield as defaults_reader
import cleanup_shaman_offhand as equipment_reader

POLICY='tc-forbidden-player-skill-family-retirement-v1'
TRAINING_POLICY='tc-forbidden-player-training-family-retirement-v2'
TRAINING_ACK='RETIRE_FOREIGN_FAMILIES_AND_VERIFIED_ABSENT_CHILD_TRAINING_ACTIONS'
POLICIES=(POLICY,TRAINING_POLICY,*(v[0]for v in native_actions.POLICIES.values()))

def policy_ack(policy):
    return next((ack for key,ack in native_actions.POLICIES.values()if key==policy),TRAINING_ACK if policy==TRAINING_POLICY else ACK)
ACK='RETIRE_VERIFIED_FOREIGN_SKILL_AND_COMPLETE_PLAYERBOOK_FAMILY'
PET_SKILLS={188,189,204,205,761}
CATEGORIES={6,7,8,10}  # Weapon, class, armor, language. No professions/racials/riding.


def native_sources(paths):
    result=riding.native_sources(paths,native_invalid_items=True)
    for core,files in equipment_reader.native_sources(paths).items():result[core].update(files)
    from cleanup_console import PROFILE,sha
    for core,prefix in (('tc','trinitycore'),('ac','azerothcore')):
        manifest={n.strip():h for h,n in(line.split(None,1)for line in(PROFILE/(prefix+'-semantic.sha256')).read_text().splitlines())}
        for name in ('src/server/game/Spells/Auras/SpellAuras.cpp','src/server/game/Spells/SpellMgr.cpp','src/server/game/Spells/SpellEffects.cpp'):
            if sha(paths[core+'_source']/name)!=manifest[name]:fail('NATIVE_ACTION_SOURCE_DRIFT','Protected action consumer differs: '+core+':'+name)
            result[core][name]=manifest[name]
    return result


def reader_hashes():
    from cleanup_console import ROOT,sha
    names=('lib/cleanup_foreign_skills.py','lib/cleanup_obsolete_riding.py','lib/cleanup_shaman_offhand.py',
           'lib/cleanup_shaman_dual_wield.py','lib/cleanup_native_actions.py','lib/cleanup_native_action_catalog.json','lib/cleanup_obsolete_riding_catalog.json','lib/cleanup_obsolete_riding_item_catalog.json')
    return {n:sha(ROOT/n)for n in names}


class Catalog:
    def __init__(self,tc,ac,*,training_actions=False):
        self.training_actions=training_actions
        self.metas=(tc,ac);self.infos={};self.associations={};self.safe={};self.invalid_effects=set()
        for m in self.metas:
            infos=defaultdict(list)
            for r in m.stores['SkillRaceClassInfo'].values():infos[r[1]].append(r)
            self.infos[m.core]=infos
        self.forbidden_cache={}

    def forbidden(self,skill,race,cls):
        key=(skill,race,cls)
        if key not in self.forbidden_cache:
            lines=[m.stores['SkillLine'].get(skill,[])for m in self.metas]
            infos=[sorted(r[1:]for r in self.infos[m.core][skill])for m in self.metas]
            self.forbidden_cache[key]=(all(len(r)>1 for r in lines)and lines[0][1]==lines[1][1]in CATEGORIES
                and infos[0]==infos[1]and(bool(infos[0])or skill in PET_SKILLS)
                and not any((not r[1]or r[1]&(1<<(race-1)))and(not r[2]or r[2]&(1<<(cls-1)))for r in infos[0]))
        return self.forbidden_cache[key]

    def associated(self,m,spell):
        key=(m.core,spell)
        if key not in self.associations:
            skills={r[1]for r in m.abilities[spell]}
            try:effect=m.skill_effect(spell)if spell in m.spells else None
            except Unsupported:
                self.invalid_effects.add(spell);effect=None
                row=m.spells[spell]
                skills.update(row[110+i]for i in range(3)if row[71+i]in(44,118))
            if effect:skills.add(effect[0])
            self.associations[key]=skills
        return self.associations[key]

    def supported(self,spell):
        if spell not in self.safe:
            ok=spell not in self.invalid_effects
            for m in self.metas:
                row=m.spells.get(spell,[])
                if (not ok or len(row)<212 or spell in m.additional or spell in m.invalid_talents
                        or m.aura_owners.get(spell)or spell in m.world_aura_owners
                        or any(m.script_policy.get(n)!='NO_SPELLBOOK_MUTATION'for n in m.scripts[spell])):
                    ok=False;break
                if set(row[71:74])&{36,40,44,118}and(
                        not set(row[71:74])<={0,36,40,44,118}
                        or any(row[86+i]not in((0,1,25)if self.training_actions else(0,1))or row[89+i]not in((0,1,25)if self.training_actions else(0,1))for i in range(3)if row[71+i])):
                    ok=False;break
                try:m.check_spell(spell)
                except Unsupported:ok=False;break
            self.safe[spell]=ok
        return self.safe[spell]


def family_groups(book,race,cls,catalog):
    """Connect invalid native skills, rank siblings and pure teaching routes."""
    metas=catalog.metas;assign={};exposures=defaultdict(set);parent={}
    def find(s):
        parent.setdefault(s,s)
        if parent[s]!=s:parent[s]=find(parent[s])
        return parent[s]
    def union(skills):
        skills=sorted(skills)
        for s in skills[1:]:parent[find(s)]=find(skills[0])
    for spell in book:
        sides=[catalog.associated(m,spell)for m in metas]
        for sk in set.union(*sides):exposures[sk].add(spell)
        if sides[0]and sides[0]==sides[1]and all(catalog.forbidden(k,race,cls)for k in sides[0]):
            assign[spell]=set(sides[0]);union(sides[0])
    # Include only known, pure self-teachers whose complete children are already
    # in a forbidden family. A mixed teacher remains a guarded boundary.
    for _ in range(16):
        added=False
        for spell in book.keys()-assign.keys():
            sides=[]
            for m in metas:
                row=m.spells.get(spell,[]);children={ch for ch,_,_ in m.learns[spell]}
                raw_children={row[116+i]for i in range(3)if row[71+i]==36}if len(row)>=119 else set()
                if (not children or children!={ch for ch,_,_ in m.effect_learns[spell]}or children!=raw_children
                        or len(row)<119 or not set(row[71:74])<={0,36,44,118}
                        or any(row[86+i]not in((0,1,25)if catalog.training_actions else(0,1))or row[89+i]not in((0,1,25)if catalog.training_actions else(0,1))for i in range(3)if row[71+i])):break
                child_skills=[]
                for child in children:
                    if child in assign:child_skills.append(assign[child]);continue
                    associated=catalog.associated(m,child)
                    if (not catalog.training_actions or not associated or not all(catalog.forbidden(k,race,cls)for k in associated)
                            or not catalog.supported(child)or any(other.learns[child]or other.effect_learns[child]for other in metas)):
                        break
                    child_skills.append(associated)
                if len(child_skills)!=len(children):break
                sides.append(set.union(*child_skills))
            if len(sides)==2 and sides[0]==sides[1]:
                assign[spell]=sides[0];union(sides[0]);added=True
        if not added:break
    for spell,skills in assign.items():
        for m in metas:
            for related in set(m.chain(spell))|m.requires[spell]|m.prerequisite_users[spell]|m.learn_parents[spell]|{ch for ch,_,_ in m.learns[spell]}:
                if related in assign:union(skills|assign[related])
    groups=defaultdict(lambda:{'spells':set(),'skills':set()})
    for spell,skills in assign.items():
        root=find(min(skills));groups[root]['spells'].add(spell);groups[root]['skills'].update(skills)
    return list(groups.values()),exposures


def valid_talents(c,rows,tc,ac):
    seen=set();cls=c[2]
    for spell,group in rows:
        identity=tc.talents.get(spell);row=tc.talent_rows.get(spell,[])
        tab=tc.stores['TalentTab'].get(row[1],[])if identity else[];key=(identity[0]if identity else -1,group)
        if (not identity or ac.talents.get(spell)!=identity or ac.talent_rows.get(spell)!=row
                or spell in tc.invalid_talents or spell in ac.invalid_talents or len(tab)<=20
                or not tab[20]&(1<<(cls-1))or ac.stores['TalentTab'].get(row[1],[0]*21)[20]!=tab[20]
                or not 0<=group<c[5]or key in seen):return False
        seen.add(key)
    return True


def scope(state,tc,ac,*,training_actions=False,native_action=None):
    if native_action:return native_actions.scope(state,tc,ac,native_action)
    catalog=Catalog(tc,ac,training_actions=training_actions);books=defaultdict(dict)
    for g,s,a,d in state['character_spell']:books[g][s]=(a,d)
    return sorted(c[0]for c in state['characters']if 1<=c[1]<=32 and 1<=c[2]<=32 and family_groups(books[c[0]],c[1],c[2],catalog)[0])


def select(state,tc,ac,expected=None,*,preview=False,items,equipment,default_skills,training_actions=False,native_action=None):
    if native_action:return native_actions.select(state,tc,ac,expected,preview=preview,items=items,equipment=equipment,default_skills=default_skills,action=native_action)
    validate_stored(state['character_spell'])
    if not 1<=len(state['characters'])<=40000 or sum(map(len,state.values()))>MAX_ROWS:fail('FOREIGN_SKILL_BOUND','Captured scope exceeds native limits')
    if items.get('zero_template_counts')!={'tc':0,'ac':0}:fail('FOREIGN_SKILL_ZERO_TEMPLATE','Both worlds must lack template zero')
    books=defaultdict(dict);stored_skills=defaultdict(dict);talents=defaultdict(list);owned=defaultdict(list);inv=defaultdict(list)
    for g,s,a,d in state['character_spell']:books[g][s]=(a,d)
    for g,s,v,c in state['character_skills']:stored_skills[g][s]=(v,c)
    for g,s,k in state['character_talent']:talents[g].append((s,k))
    for r in items['rows']:owned[r[0]].append(r)
    for r in equipment['inventory']:inv[r[0]].append(r)
    facts={r[0]:r for r in equipment['items']};catalog=Catalog(tc,ac,training_actions=training_actions)
    selected=[];excluded=[];skill_rows=[];proofs=[]
    for c in state['characters']:
        g,race,cls,level,active,groups,online,flags=c
        if not 1<=race<=32 or not 1<=cls<=32:continue
        candidates,exposures=family_groups(books[g],race,cls,catalog)
        for group in candidates:
            nodes=group['spells'];skills=group['skills'];reason=''
            logical_nodes=nodes|{ch for m in(tc,ac)for sp in nodes for ch,_,_ in m.learns[sp]}
            selected_ids={s for s,k in talents[g]};known_authority=books[g].keys()|selected_ids
            selected_families={tc.talents[s][0]for s in selected_ids if s in tc.talents}
            if online or race not in(1,2,3,4,5,6,7,8,10,11)or cls not in(1,2,3,4,5,6,7,8,9,11)or not 1<=level<=255 or groups not in(1,2)or not 0<=active<groups:reason='DEFER_FOREIGN_SKILL_CHARACTER_STATE'
            elif not valid_talents(c,talents[g],tc,ac):reason='DEFER_INVALID_SELECTED_TALENT'
            elif any(s in logical_nodes for s,k in talents[g])or any(m.talents.get(owner,(None,))[0]in selected_families for m in(tc,ac)for s in logical_nodes for owner in m.talent_learn_owners.get(s,())):reason='DEFER_SELECTED_TALENT_FAMILY'
            elif any(books[g][s][0]not in(0,1)or books[g][s][1]not in(0,1)for s in nodes):reason='DEFER_FOREIGN_SKILL_FLAGS'
            elif any(not catalog.supported(s)for s in nodes):reason='DEFER_FOREIGN_SKILL_NATIVE_CONTRACT'
            elif any(not exposures[k]<=nodes for k in skills):reason='DEFER_FOREIGN_SKILL_SHARED_EXPOSURE'
            elif any(any(other in known_authority and other not in nodes for other in m.learn_parents[s]|m.requires[s]|m.prerequisite_users[s])for m in(tc,ac)for s in nodes):reason='DEFER_FOREIGN_SKILL_KNOWN_BOUNDARY'
            elif any(any(ch not in nodes and(ch in known_authority or not catalog.associated(tc,ch)or catalog.associated(tc,ch)!=catalog.associated(ac,ch)or not catalog.associated(tc,ch)<=skills)
                         for ch in {v for v,_,_ in m.learns[s]}|{v for v,_,_ in m.effect_learns[s]}|{m.spells[s][116+i]for i in range(3)if m.spells[s][71+i]==36})for m in(tc,ac)for s in nodes):reason='DEFER_FOREIGN_SKILL_OUTGOING_BOUNDARY'
            elif any(any(other in books[g]and other not in nodes for other in m.chain(s))for m in(tc,ac)for s in nodes):reason='DEFER_FOREIGN_SKILL_RETAINED_RANK'
            else:
                for world in default_skills.values():
                    fields=[r[1]for r in world['layout']['columns']]
                    for row in world['rows']['playercreateinfo_skills']:
                        r=dict(zip(fields,row))
                        if r['skill']in skills and(not r['raceMask']or r['raceMask']&(1<<(race-1)))and(not r['classMask']or r['classMask']&(1<<(cls-1))):reason='DEFER_FOREIGN_SKILL_DEFAULT_ROUTE'
                valid=[r for r in owned[g]if not riding.native_invalid_item(r)]
                if any(any(v is None for v in r[2:])for r in valid):reason=reason or'DEFER_UNKNOWN_OWNED_ITEM_REQUIREMENT'
                elif any(r[6]in skills or r[10]in skills or r[8]in logical_nodes or r[12]in logical_nodes for r in valid):reason=reason or'DEFER_OWNED_ITEM_REQUIRES_FAMILY'
                proficiency={(m.spells[s][68],m.spells[s][69])for m in(tc,ac)for s in logical_nodes if s in m.spells and 60 in m.spells[s][71:74]}
                if proficiency:
                    gear=[r for r in inv[g]if r[1]==0 and r[2]<19]
                    if len({r[2]for r in gear})!=len(gear):reason=reason or'DEFER_DUPLICATE_EQUIPMENT_SLOT'
                    for row in gear:
                        f=facts.get(row[3])
                        # Missing instances/entry zero were sealed above in the
                        # complete owned-item proof, and remain unchanged.
                        if not f or f[2]==0:continue
                        if any(v is None for v in f[4:16])or f[4:10]!=f[10:16]:reason=reason or'DEFER_UNKNOWN_EQUIPPED_PROFICIENCY'
                        elif any(f[5]==item_class and mask&(1<<f[6])for item_class,mask in proficiency):reason=reason or'DEFER_EQUIPPED_RETIRED_PROFICIENCY'
            if reason:excluded.extend((g,s,reason)for s in sorted(nodes));continue
            selected.extend((g,s,*books[g][s])for s in sorted(nodes))
            removed_skills=[[g,k,*stored_skills[g][k]]for k in sorted(skills)if k in stored_skills[g]];skill_rows+=removed_skills
            proofs.append({'guid':g,'retired_playerbook_family':sorted(nodes),'catalog_family_including_absent_children':sorted(logical_nodes),'absent_child_training_actions':training_actions,'forbidden_native_skills':sorted(skills),'retired_stored_skills':removed_skills,'source_target_eligibility_agrees':True,'all_selected_talents_preserved':True,'pending_native_reset_preserved':bool(flags&4),'owned_items_checked':len(owned[g]),'native_invalid_items_retained':[{'item_guid':r[1],'reason':riding.native_invalid_item(r)}for r in owned[g]if riding.native_invalid_item(r)],'items_changed':False,'effects_executed':False})
    selected.sort();excluded.sort();skill_rows.sort()
    if not preview and(not selected or expected!=len(selected)):fail('FOREIGN_SKILL_SELECTION_MISMATCH',f'Expected {expected} spell rows, selected {len(selected)}')
    summary={'reviewed_candidate_rows':len(selected)+len(excluded),'selected_rows':len(selected),'selected_characters':len({r[0]for r in selected}),'selected_groups':len(proofs),'selected_direct_rows':0,'selected_related_rows':len(selected),'enabled_rows_removed':sum(not r[3]for r in selected),'disabled_rows_removed':sum(bool(r[3])for r in selected),'skill_rows_changed':len(skill_rows),'skill_rows_removed':len(skill_rows),'spell_rows_inserted':0,'deferred_candidate_rows':len(excluded),'deferred':dict(Counter(r[2]for r in excluded)),'retired_skills':skill_rows,'eligibility_proofs':proofs,'native_policy':'Retire complete verified playerbook families and their stored native skills only when forbidden for the character in both catalogs. Pure teaching routes are reviewed together; selected talents, professions, racial/riding skills, all other skills, items and reset flags stay unchanged. Reject shared routes, unreviewed callbacks, dependencies and item/proficiency conflicts. No grants, item moves, native unlearn, login or reset executed'}
    if training_actions:summary['native_policy']+='; separate training-action extension: discard verified pure trainer actions whose complete children are forbidden for the caster in both catalogs, even if child rows are absent; no missing child grants or teaching casts'
    return selected,excluded,[],summary,[]
