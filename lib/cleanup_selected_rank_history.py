"""Archive unselected disabled direct ranks while preserving selected builds."""
from collections import Counter, defaultdict
import json

from cleanup_console import fail
from spells import Unsupported

POLICY = 'tc-disabled-other-selected-talent-rank-v5'
DISPOSITION = 'REVIEW_DISABLED_OTHER_SELECTED_RANK'


def select(rows, state, meta, expected):
    candidates = [r for r in rows if r[9]==DISPOSITION]
    if not 1<=expected<=500000 or len(candidates)!=expected:
        fail('HISTORY_SELECTION_MISMATCH','--expect-review-rows must equal the disabled/other-selected-rank inspection total')
    families = defaultdict(set)
    for spell,(family,_) in meta.talents.items():
        families[family].add(spell)
    owners = defaultdict(list)
    for guid,spell,group in state['talents']:
        if spell in meta.talents:
            family,rank = meta.talents[spell]
            owners[guid,family].append((spell,group,rank))
    stored = {(g,s):(a,d) for g,s,a,d in state['spells']}
    incoming = {child for links in (meta.learns,meta.effect_learns) for values in links.values() for child,_,_ in values}
    required = {parent for parents in meta.requires.values() for parent in parents}
    skill_rewards = {spell for spell,abilities in meta.abilities.items() if any(a[9] in (1,2) for a in abilities)}
    skills = meta.stores['SkillLine']
    unsafe_skill_routes = {spell for spell,abilities in meta.abilities.items()
                           if any(a[1] not in skills or a[1]==762 or skills[a[1]][1] in (9,11) for a in abilities)}
    family_reasons = {}
    for family in sorted({r[10] for r in candidates}):
        members = families[family]
        reason = ''
        if members & meta.invalid_talents:
            reason = 'DEFER_EFFECTIVE_TALENT_IDENTITY'
        elif any(set(meta.chain(spell))-members for spell in members):
            reason = 'DEFER_MIXED_RANK_CHAIN'
        elif members & incoming:
            reason = 'DEFER_INDEPENDENT_LEARN_ROUTE'
        elif members & (skill_rewards|unsafe_skill_routes) or members & getattr(meta,'history_default_spells',set()):
            reason = 'DEFER_SKILL_OR_DEFAULT_ROUTE'
        elif members & required or any(meta.learns[s] or meta.effect_learns[s] for s in members):
            reason = 'DEFER_SELECTED_FAMILY_DEPENDENCIES'
        elif any(set(meta.spells[s][71:74]) & {40,44,47,118} for s in members):
            reason = 'DEFER_TALENT_SKILL_EFFECT'
        else:
            for spell in sorted(members):
                if any(meta.script_policy.get(name)!='NO_SPELLBOOK_MUTATION' for name in meta.scripts[spell]):
                    reason = 'DEFER_SCRIPTED_TALENT_FAMILY';break
                try:
                    meta.check_spell(spell)
                except Unsupported as error:
                    reason = 'DEFER_SELECTED_RANK_'+error.reason;break
        family_reasons[family] = reason
    selected,excluded,proof = [],[],[]
    for row in candidates:
        guid,spell,active,disabled,cls,_,active_group,groups,at_login,_,family,rank,_ = row
        choices = sorted(owners[guid,family])
        reason = family_reasons[family]
        if (disabled!=1 or active not in (0,1) or stored.get((guid,spell))!=(active,disabled)
                or meta.talents.get(spell)!=(family,rank)):
            reason = 'DEFER_EFFECTIVE_TALENT_IDENTITY'
        elif (not choices or cls not in (1,2,3,4,5,6,7,8,9,11) or spell in {s for s,_,_ in choices} or len({g for _,g,_ in choices})!=len(choices)
              or groups not in (1,2) or not 0<=active_group<groups or at_login&4
              or any(not 0<=g<groups or meta.talents.get(s)!=(family,r) for s,g,r in choices)):
            reason = 'DEFER_SELECTED_RANK_OWNERSHIP'
        else:
            for member in families[family]:
                talent = meta.talent_rows[member]
                tab = meta.stores['TalentTab'].get(talent[1],[])
                if len(tab)<=20 or tab[20]!=(1<<(cls-1)):
                    reason = 'DEFER_SELECTED_RANK_CLASS';break
            owned = {s for s,_,_ in choices}
            if any(stored.get((guid,s),(0,1))[1]==0 for s in families[family]-owned):
                reason = 'DEFER_ENABLED_UNSELECTED_FAMILY_RANK'
            if any(any(flag not in (0,1) for flag in stored[guid,s]) for s in families[family] if (guid,s) in stored):
                reason = 'DEFER_INVALID_FAMILY_SPELL_FLAGS'
        if reason:
            excluded.append((guid,spell,reason));continue
        selected.append((guid,spell,active,disabled))
        # Counterpart spell rows (including absence) are evidence only. Never
        # choose the highest rank, merge specs, insert or rewrite these rows.
        flags = [(s,*(stored.get((guid,s)) or (None,None))) for s,_,_ in choices]
        proof.append((guid,spell,rank,active,disabled,family,
                      json.dumps(choices,separators=(',',':')),
                      json.dumps(flags,separators=(',',':')),'REMOVE_UNSELECTED_DISABLED_RANK'))
    if not selected:
        counts = ', '.join(f'{reason}={count}' for reason,count in sorted(Counter(r[2] for r in excluded).items()))
        fail('HISTORY_NO_ELIGIBLE_ROWS','No disabled unselected direct ranks with safe selected-family authority qualify: '+counts)
    return sorted(selected),sorted(excluded),sorted(proof)
