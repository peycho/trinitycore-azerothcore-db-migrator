"""Explicit activation of existing, known ordinary crafting ranks.

This policy changes usable availability. It never learns a missing rank, casts
an effect, chooses a specialization, or alters a skill value/cap.
"""
from collections import Counter,defaultdict
import json
from cleanup_console import ROOT,fail
from cleanup_talent_relations import MAX_ROWS,validate_stored
from spells import Unsupported

POLICY='tc-inactive-ordinary-profession-activation-v1'
PENDING_POLICY='tc-pending-reset-ordinary-profession-activation-v2'
POLICIES=(POLICY,PENDING_POLICY)
PENDING_ACK='ACTIVATE_EXISTING_PROFESSIONS_KEEP_NATIVE_RESET_PENDING'
ACK='ACTIVATE_ONLY_EXISTING_ORDINARY_PROFESSION_RANKS'
CATALOG=ROOT/'lib/cleanup_profession_catalog.json'
RULES=json.loads(CATALOG.read_text())


def contract(meta,root):
    """Require the fixed reviewed ordinary chain, skill and learning catalog."""
    skill=RULES['roots'][str(root)]
    for spell in RULES[meta.core][str(root)]['chain']:
        expected=RULES[meta.core][str(spell)];row=meta.spells.get(spell,[])
        if (len(row)<212 or any(row[i]!=expected['mechanics'].get(str(i),0)for i in (*range(4,131),*range(208,212)))
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
    expected=RULES['skill_metadata'][meta.core][str(skill)]
    infos=sorted(r for r in meta.stores['SkillRaceClassInfo'].values()if r[1]==skill)
    return (meta.stores['SkillLine'].get(skill,[0,0])[1]==expected['category'] and infos==expected['infos']
            and {str(r[6]):meta.stores['SkillTiers'][r[6]]for r in infos if r[6]in meta.stores['SkillTiers']}==expected['tiers'])


def select(state,tc,ac,expected=None,*,preview=False,pending_reset=False):
    validate_stored(state['character_spell'])
    if not 1<=len(state['characters'])<=40000 or sum(map(len,state.values()))>MAX_ROWS:
        fail('PROFESSION_BOUND','Captured scope exceeds reviewed bounds')
    chars={r[0]:r for r in state['characters']};books=defaultdict(dict);skills=defaultdict(dict)
    for g,s,a,d in state['character_spell']:books[g][s]=(a,d)
    for g,s,v,m in state['character_skills']:skills[g][s]=(v,m)
    invalid,seen=set(),set()
    for g,s,k in state['character_talent']:
        c=chars.get(g);identity=tc.talents.get(s);row=tc.talent_rows.get(s,[])
        tab=tc.stores['TalentTab'].get(row[1],[])if identity else []
        key=(g,identity[0]if identity else -1,k)
        if (c is None or not identity or ac.talents.get(s)!=identity or s in tc.invalid_talents or s in ac.invalid_talents
                or ac.talent_rows.get(s)!=row or len(tab)<=20 or not 1<=c[2]<=32
                or ac.stores['TalentTab'].get(row[1],[0]*21)[20]!=tab[20]
                or not tab[20]&(1<<(c[2]-1)) or k not in (0,1) or k>=c[5] or key in seen):invalid.add(g)
        seen.add(key)
    safe={root:contract(tc,root)and contract(ac,root)for root in map(int,RULES['roots'])}
    selected,excluded,proofs=[],[],[]
    for g,c in sorted(chars.items()):
        if pending_reset and not c[7]&4:continue
        for spell in sorted(s for s,flags in books[g].items()if flags==(0,0)):
            row=tc.spells.get(spell,[])
            # Report unsupported crafting/specialization rows as deferred rather
            # than silently broadening to every inactive spell in the scope.
            if len(row)<74 or 47 not in row[71:74]:continue
            chain=tc.chain(spell);root=chain[0];reason=''
            if c[6]:reason='DEFER_ONLINE_CHARACTER'
            elif c[7]&4 and not pending_reset:reason='DEFER_PENDING_NATIVE_RESET'
            elif (c[1]not in (1,2,3,4,5,6,7,8,10,11)or c[2]not in (1,2,3,4,5,6,7,8,9,11)
                    or not 1<=c[3]<=80 or c[5]not in (1,2)or not 0<=c[4]<c[5]):reason='DEFER_PROFESSION_CHARACTER_STATE'
            elif g in invalid:reason='DEFER_INVALID_TALENT_SELECTION'
            elif root not in safe:reason='DEFER_SPECIALIZATION_OR_UNREVIEWED_PROFESSION'
            elif not safe[root]:reason='DEFER_PROFESSION_METADATA'
            elif sum(s in books[g]for s in chain)!=1:reason='DEFER_MULTIPLE_STORED_PROFESSION_RANKS'
            else:
                skill=RULES['roots'][str(root)];stored=skills[g].get(skill)
                effects=tc.skill_effect(spell)
                if (not stored or not 0<stored[0]<=stored[1] or stored[1]not in (75,150,225,300,375,450)
                        or not effects or effects!=ac.skill_effect(spell)or effects[0]!=skill
                        or stored[0]<effects[2]or stored[1]<effects[3]):reason='DEFER_PROFESSION_SKILL_STATE'
                for meta in (tc,ac):
                    infos=[r for r in meta.stores['SkillRaceClassInfo'].values()if r[1]==skill
                           and(not r[2]or r[2]&(1<<(c[1]-1)))and(not r[3]or r[3]&(1<<(c[2]-1)))]
                    if not infos:reason=reason or 'DEFER_PROFESSION_RACE_CLASS'
            if reason:excluded.append((g,spell,reason));continue
            selected.append((g,spell,0,0));proofs.append({'guid':g,'spell':spell,'ordinary_root':root,
                'skill':skill,'preserved_skill':list(stored),'before_flags':[0,0],'after_flags':[1,0],
                'known_before':True,'active_before':False,'active_after':True,
                'missing_higher_rank_inference':False,'sql_effects_executed':False})
    if not preview and(not selected or expected!=len(selected)):
        fail('PROFESSION_SELECTION_MISMATCH',f'--expect-rows must equal preview selected_rows ({len(selected)})')
    summary={'reviewed_candidate_rows':len(selected)+len(excluded),'selected_rows':len(selected),
        'selected_characters':len({r[0]for r in selected}),'selected_groups':len(selected),
        'selected_direct_rows':0,'selected_related_rows':len(selected),'spell_rows_activated':len(selected),
        'enabled_rows_removed':0,'disabled_rows_removed':0,'spell_rows_removed':0,
        'deferred_candidate_rows':len(excluded),'spell_rows_inserted':0,'skill_rows_changed':0,
        'eligibility_proofs':proofs,'deferred':dict(Counter(r[2]for r in excluded)),
        'native_policy':'Activate only existing inactive/non-disabled ordinary crafting ranks backed by preserved native skills; explicit usable-availability correction; no missing-rank grant, specialization choice, spell insertion/deletion, skill/cap, recipe, talent/spec, item or login change'}
    if pending_reset:
        summary.update(pending_native_reset_preserved=True,reset_executed=False)
        summary['native_policy']+='; pending-reset characters only, retain reset flag and all selected ownership; no reset/login executed'
    return selected,excluded,[],summary,[]
