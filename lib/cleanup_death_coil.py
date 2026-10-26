"""Reviewed exception: retire disabled Death Coil training history for native rank 1."""

from cleanup_console import fail

POLICY = 'tc-native-death-coil-base-repair-v3'
PENDING_POLICY = 'tc-pending-reset-native-death-coil-v5'
POLICIES=(POLICY,PENDING_POLICY)
PENDING_ACK='RETAIN_PENDING_RESET_ALLOW_ONLY_NATIVE_DEATH_COIL_BASE'
CHAIN = (47541,49892,49893,49894,49895)
SKILL = 772
ROLE = 'NATIVE_DEATH_COIL_BASE_ROUTE'


def configuration_contract(settings):
    if settings.get('source','player_start_all_spells') != '0':
        fail('DEATH_COIL_CONFIG_REQUIRED',
             '--native-death-coil requires [source] player_start_all_spells = 0',
             'Verify the effective stopped TC PlayerStart.AllSpells setting. '
             'Custom starting spells must not regrant higher ranks; this is an operator assertion.')
    return {'setting':'PlayerStart.AllSpells','value':0,'evidence':'OPERATOR_ASSERTION',
            'scope':'Native Death Coil rank 1 from existing Unholy skill only; custom starting-spell grants inactive'}


def metadata_reason(meta, nodes):
    if set(nodes) != set(CHAIN) or any(tuple(meta.chain(s)) != CHAIN for s in CHAIN):
        return 'DEFER_NATIVE_DEATH_COIL_METADATA'
    line = meta.stores['SkillLine'].get(SKILL,[])
    if len(line)<2 or line[1] != 7:
        return 'DEFER_NATIVE_DEATH_COIL_METADATA'
    for index,spell in enumerate(CHAIN):
        record = meta.spells[spell]
        abilities = meta.abilities[spell]
        successor = CHAIN[index+1] if index+1<len(CHAIN) else 0
        expected = [SKILL,spell,0,32,0,0,1,successor,2 if index==0 else 0,0,0,0,0]
        if (len(abilities)!=1 or abilities[0][1:] != expected
                or record[71:74] != [3,0,0] or record[4] & 0xc0
                or meta.scripts[spell] != {'spell_dk_death_coil'}
                or meta.script_policy.get('spell_dk_death_coil') != 'NO_SPELLBOOK_MUTATION'):
            return 'DEFER_NATIVE_DEATH_COIL_METADATA'
    return ''


def character_contract(meta, char, book, skills):
    guid,race,cls,level,active,groups,_,_ = char
    if cls!=6 or race not in (1,2,3,4,5,6,7,8,10,11):
        return 'DEFER_NATIVE_DEATH_COIL_CLASS',None
    if CHAIN[0] in book:
        return 'DEFER_STORED_NATIVE_BASE',None
    if any(book[s]!=(1,1) for s in CHAIN[1:] if s in book):
        return 'DEFER_NATIVE_DEATH_COIL_FLAGS',None
    infos = [r for r in meta.stores['SkillRaceClassInfo'].values()
             if r[1]==SKILL and (not r[2] or r[2] & (1<<(race-1)))
             and (not r[3] or r[3] & 32)]
    if len(infos)!=1 or infos[0][1:] != [SKILL,0xffffffff,32,0x410,0,0,0]:
        return 'DEFER_NATIVE_DEATH_COIL_METADATA',None
    if (len(skills)!=1 or any(type(x)!=int for x in skills[0])
            or not 1<=skills[0][2]<=skills[0][3]<=400):
        return 'DEFER_NATIVE_DEATH_COIL_SKILL',None
    value,cap = skills[0][2:]
    return '',{'guid':guid,'race':race,'class':cls,'level':level,'active_spec':active,
        'spec_count':groups,'skill':SKILL,'stored_skill_value':value,'stored_skill_cap':cap,
        'native_skill_value_and_cap':level*5,
        'existing_native_skill_normalization':(value,cap)!=(level*5,level*5),
        'skill_rows_changed':False,'base_spell':CHAIN[0],'base_stored':'ABSENT_PRESERVED',
        'source_load_path_before':'SKILL_REWARD_THEN_DISABLED_RANK_PREFIX',
        'native_load_after':'RANK_1_FROM_EXISTING_SKILL','native_mask':3,
        'higher_rank_grants':[],'spell_rows_inserted':0}
