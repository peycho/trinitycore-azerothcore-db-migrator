"""Small WDBC assets with real Wrath spell IDs and rank ordering."""
import json
from pathlib import Path
import re
import struct

CHAINS = [
    [465,10290,643,10291,1032,10292,10293,27149,48941,48942],
    [635,639,647,1026,1042,3472,10328,10329,25292,27135,27136,48781,48782],
    [853,5588,5589,10308],
    [17,592,600,3747,6065,6066,10898,10899,10900,10901,25217,25218,48065,48066],
    [589,594,970,992,2767,10892,10893,10894,25367,25368,48124,48125],
    [172,6222,6223,7648,11671,11672,25311,27216,47812,47813],
    [686,695,705,1088,1106,7641,11659,11660,11661,25307,27209,47808,47809],
    [20473,20929,20930,27174,33072,48824,48825],
    [34914,34916,34917,48159,48160],
    [17877,18867,18868,18869,18870,18871,27263,30546,47826,47827],
    [2259,3101,3464,11611,28596,51304],
    [33388,33391,34090,34091],
    [900001,900002,900003],
    [5487,9634],
    [33943,40120],
]
CLASS_SKILLS = {skill:(400,400) for skill in [183,267,594,613,78,355,593,134]}
RUNEFORGING = [53323,53331,53341,53342,53343,53344,54446,54447,62158,70164]
NATIVE_PASSIVE_CHAINS = [[16958,16961],[16952,16954],[52284,52285,52286],
                         [51983,51986],[51969,51970],
                         [50096,50108,50109,50110,50111],[61274,61275,61276,61277,61278]]
NATIVE_PASSIVE_TALENTS = [(801,11,[37116,37117],[[16958,16952],[16961,16954]]),
    (1959,6,[49189,50149,50150],[[52284],[52285],[52286]]),
    (2039,6,[49146,51267],[[51983,51969],[51986,51970]]),
    (2034,6,[61154,61155,61156,61157,61158],[[50096,61274],[50108,61275],[50109,61276],[50110,61277],[50111,61278]])]


def stores(profile):
    data = {name: {} for name in profile['stores']}
    def record(store, ident):
        row = [0] * len(profile['stores'][store]['columns'])
        row[0] = ident
        data[store][ident] = row
        return row
    for chain in CHAINS:
        for spell in chain:
            row = record('Spell', spell)
            row[71] = 10
    for spell in [6603,12282,12663,12664,12300,12301,12296,5209,38795,53407,34074,
                  51466,51470,54347,54348,54349,20911,25899,900000,900010,900011,900012,
                  38796,53736,40251,51726,64353,64357,44440,44441,64350,64349,
                  37116,37117,16958,16961,12308,12810,12811,60893,61177,61288,674,30798,
                  53428,33872,33873,47179,47180,7744,37377,40081,40326]:
        row = record('Spell', spell)
        row[71] = 3
    for spell,flags,effects,auras in [(7744,16,[6,6,6],[77,77,77]),
                                      (37377,192,[6,0,0],[4,0,0]),
                                      (40081,536936448,[77,6,0],[0,147,0]),
                                      (40326,384,[6,0,0],[4,0,0])]:
        data['Spell'][spell][4]=flags
        data['Spell'][spell][71:74]=effects
        data['Spell'][spell][95:98]=auras
    record('SkillLine',220)[1]=9
    info=record('SkillRaceClassInfo',72)
    info[1:7]=[220,16,1535,1170,0,0]
    ability=record('SkillLineAbility',4350)
    ability[1:10]=[220,7744,16,0,0,0,1,0,2]
    # Match the stock class skill associations and relevant effect/family
    # fields. Devotion is non-stackable; mana-based healing/damage ranks are
    # separately available. Holy Light / Shadow Bolt rank 1 learn class skills.
    for index, cls, skill, family, effects in [
        (0,2,267,10,[65,0,0]),(1,2,594,10,[10,0,0]),(2,2,267,10,[6,0,0]),
        (3,5,613,6,[6,0,0]),(4,5,78,6,[6,0,0]),(5,9,355,5,[6,3,0]),
        (6,9,593,5,[2,0,0]),(7,2,594,10,[3,0,0]),(8,5,78,6,[6,6,6]),
        (9,9,593,5,[64,2,0]),
        (13,11,134,7,[6,0,0]),
    ]:
        line = data['SkillLine'].get(skill) or record('SkillLine',skill)
        line[1] = 7
        info = data['SkillRaceClassInfo'].get(skill) or record('SkillRaceClassInfo',skill)
        info[1],info[3],info[4] = skill,1<<(cls-1),0x410
        for spell in CHAINS[index]:
            data['Spell'][spell][208] = family
            data['Spell'][spell][71:74] = effects
            ability = record('SkillLineAbility',spell)
            ability[1],ability[2],ability[4] = skill,spell,1<<(cls-1)
            if spell == CHAINS[index][0] and index in (1,6):
                ability[9] = 2
    for spell in CHAINS[13]:
        data['Spell'][spell][95] = 36  # shapeshift aura: ranks supersede
    for spell in CHAINS[14]:
        data['Spell'][spell][71:74] = [6,6,6]
        data['Spell'][spell][95:98] = [36,77,201]
        data['Spell'][spell][208] = 7
        ability = record('SkillLineAbility',spell)
        ability[1],ability[2],ability[4] = 134,spell,1024
    for ident, cls, ranks, spellbook in [
        (1,1,[12282,12663,12664],0),(2,1,[12300,12301],0),
        (3,2,[20473],1),(4,5,[34914],1),(5,9,[17877],1),(6,2,[20911],1),
        (7,5,[900000],0),
        (137,1,[12296],0),
        (146,1,[12308,12810,12811],0),
        (2049,7,[51466,51470],0),(1882,9,[54347,54348,54349],0),
        (2001,8,[64353,64357],0),
        (1690,7,[30798],1),
        (1792,11,[33872,33873],0),
    ]:
        tab = record('TalentTab', ident)
        tab[20] = 1 << (cls-1)
        talent = record('Talent', ident)
        talent[1], talent[19] = ident, spellbook
        talent[4:4+len(ranks)] = ranks
        for spell in ranks:
            if not spellbook:
                data['Spell'][spell][4] |= 0x40
                data['Spell'][spell][71] = 6
    data['Spell'][53407][71] = 77
    data['Spell'][34074][71:74] = [6,6,0]
    data['Spell'][34074][95:98] = [21,79,0]
    for spell in [51466,51470]:
        data['Spell'][spell][71],data['Spell'][spell][95] = 65,57
    for spell in [54347,54348,54349]:
        data['Spell'][spell][95],data['Spell'][spell][86] = 4,1
    # Native hidden/passive children of Fiery Payback and Primal Fury.
    # Fiery Payback has an AC-only child rank chain; Primal Fury has one in TC too.
    for owner,children in [(64353,[44440,64350]),(64357,[44441,64349]),
                           (37116,[16958]),(37117,[16961])]:
        data['Spell'][owner][71:74]=[0,0,0]
        for index,child in enumerate(children):
            data['Spell'][owner][71+index]=36
            data['Spell'][owner][116+index]=child
            data['Spell'][child][4]|=0xc0
            data['Spell'][child][71]=6
    record('SkillLine',770)[1]=7
    info=record('SkillRaceClassInfo',770)
    info[1],info[3],info[4]=770,32,0x410
    for family,cls,owners,children in NATIVE_PASSIVE_TALENTS:
        record('TalentTab',family)[20]=1<<(cls-1)
        talent=record('Talent',family)
        talent[1],talent[4:4+len(owners)]=family,owners
        for owner,learned in zip(owners,children):
            row=record('Spell',owner)
            row[4]={801:8651136,1959:400,2039:16777616,2034:400}[family]
            for i,child in enumerate(learned):
                slot=1 if family==1959 else 2 if family==2034 and i==1 else i
                row[71+slot],row[86+slot],row[116+slot]=36,1,child
                row=record('Spell',child)
                row[4],row[71],row[86]=464,6,1
                ability=record('SkillLineAbility',child)
                ability[1],ability[2],ability[4]=134 if cls==11 else 770,child,1<<(cls-1)
                row=data['Spell'][owner]
            if family==1959:
                row[71],row[86],row[80]=3,1,35
    for chain,auras,stances,state,trigger in [
        ([16958,16961],[42,0,0],144,0,16959),([16952,16954],[42,0,0],1,0,16953),
        ([52284,52285,52286],[69,0,0],0,0,0),([51983,51986],[172,232,232],0,0,0),
        ([51969,51970],[211,0,0],0,0,0),
        ([50096,50108,50109,50110,50111],[79,0,0],0,23,0),
        ([61274,61275,61276,61277,61278],[280,0,0],0,0,0)]:
        for spell in chain:
            row=data['Spell'][spell]
            row[95:98],row[12],row[20],row[116]=auras,stances,state,trigger
            row[71:74]=[6 if aura else 0 for aura in auras]
    for trigger in (16953,16959):
        record('Spell',trigger)[71]=30
    # A ranked additional talent spell is persistent, a hidden unranked
    # dependent is runtime temporary; neither is granted in an unowned spec.
    data['Spell'][900000][71] = 36
    data['Spell'][900000][116] = 900001
    data['Spell'][900000][72] = 36
    data['Spell'][900000][117] = 900010
    data['Spell'][900010][4] = 0x80
    for spell in (33872,33873):
        data['Spell'][spell][4]=464
        data['Spell'][spell][71:74]=[6,0,0]
        data['Spell'][spell][95]=175
        ability=record('SkillLineAbility',spell)
        ability[1],ability[2],ability[4]=134,spell,1024
    for spell in (47179,47180):
        data['Spell'][spell][4],data['Spell'][spell][12]=400,1
        data['Spell'][spell][71:74]=[6,0,0]
        data['Spell'][spell][95]=118
    # Dual Wield is ordinary for warriors/hunters/rogues/death knights, but
    # talent-owned for shamans. Match the supplied stock DBC relationships.
    data['Spell'][674][4],data['Spell'][674][71] = 80,40
    data['Spell'][30798][71],data['Spell'][30798][116] = 36,674
    record('SkillLine',118)[1] = 6
    ability=record('SkillLineAbility',674)
    ability[1:10]=[118,674,0,109,0,0,1,0,2]
    for ident,races,classes,flags,level in [(131,32767,8,146,1),(132,32767,5,146,20),
                                          (883,32767,64,402,0),(913,262143,32,146,0)]:
        info=record('SkillRaceClassInfo',ident)
        info[1:6]=[118,races,classes,flags,level]
    for skill, chain in [(171,CHAINS[10]),(762,CHAINS[11])]:
        row = record('SkillLine', skill)
        row[1] = 11 if skill == 171 else 7
        tier = record('SkillTiers', skill)
        race = record('SkillRaceClassInfo', skill)
        race[1],race[6] = skill,skill
        for step, spell in enumerate(chain,1):
            row = data['Spell'][spell]
            row[71],row[110],row[80],row[74] = 118,skill,step-1,1
            ability = record('SkillLineAbility', spell)
            ability[1],ability[2] = skill,spell
            tier[16+step] = step*75
    # Native riding spells have a harmless dummy effect before SKILL.
    for step,spell in enumerate(CHAINS[11],1):
        row = data['Spell'][spell]
        row[4],row[71:74] = 16777424,[3,118,0]
        row[110:113],row[80:83],row[74:77] = [0,762,0],[0,step-1,0],[0,1,0]
    record('SkillLine',773)[1]=11
    record('SkillRaceClassInfo',773)[1]=773
    for spell,skill in [(60893,171),(61177,773),(61288,773)]:
        data['Spell'][spell][71:74]=[157,77,0]
        ability=record('SkillLineAbility',spell)
        ability[1],ability[2]=skill,spell
    record('SkillLine',776)[1]=7
    info=record('SkillRaceClassInfo',776)
    info[1],info[3],info[4]=776,32,0x80
    data['Spell'][53428][4],data['Spell'][53428][71:74]=16842768,[47,0,0]
    ability=record('SkillLineAbility',53428)
    ability[1],ability[2],ability[4],ability[7]=776,53428,32,1
    for spell in RUNEFORGING:
        row=record('Spell',spell)
        row[4],row[71:74]=65952,[53,3,0]
        ability=record('SkillLineAbility',spell)
        ability[1],ability[2],ability[4]=776,spell,32
        ability[7],ability[10],ability[11]=1,510,500
        ability[9]=int(spell in (53341,53343))
    return data


def write_assets(directory, profile):
    data = stores(profile)
    for core in ['tc','ac']:
        root = directory / (core+'-dbc')
        root.mkdir()
        for name, records in data.items():
            fields = len(profile['stores'][name]['columns'])
            body = b''.join(struct.pack('<'+'I'*fields,*row) for _,row in sorted(records.items()))
            (root/(name+'.dbc')).write_bytes(struct.pack('<4s4I',b'WDBC',len(records),fields,fields*4,1)+body+b'\0')


def seed_worlds(sql, tc, ac, tc_world, ac_world, profile):
    sql('CREATE TABLE trainer_spell (TrainerId INT UNSIGNED,SpellId INT UNSIGNED);'
        'INSERT INTO trainer_spell VALUES (1,6603);',ac_world)
    for name, layout in profile['stores'].items():
        source = (ac/f'data/sql/base/db_world/{layout["table"]}.sql').read_text()
        ddl = re.search(r'CREATE TABLE `[^`]+` \(.*?\) ENGINE=[^;]+;',source,re.S)[0]
        sql(ddl, ac_world)
    tc_ddl = (tc/'sql/base/dev/world_database.sql').read_text()
    ddl = re.search(r'CREATE TABLE `spell_dbc` \(.*?\) ENGINE=[^;]+;',tc_ddl,re.S)[0]
    sql(ddl,tc_world)
    for world in [tc_world,ac_world]:
        sql('CREATE TABLE spell_ranks (first_spell_id INT UNSIGNED,spell_id INT UNSIGNED,`rank` TINYINT UNSIGNED);'
            'CREATE TABLE spell_required (spell_id INT UNSIGNED,req_spell INT UNSIGNED);'
            'CREATE TABLE spell_script_names (spell_id INT,ScriptName VARCHAR(128));'
            'CREATE TABLE spell_custom_attr ('+('entry' if world==tc_world else 'spell_id')+' INT,attributes INT UNSIGNED);',world)
        values = ','.join(f'({chain[0]},{spell},{rank})' for chain in CHAINS+NATIVE_PASSIVE_CHAINS for rank,spell in enumerate(chain,1))
        sql('INSERT INTO spell_ranks VALUES '+values,world)
        sql('INSERT INTO spell_ranks VALUES (47179,47179,1),(47179,47180,2)',world)
        sql('INSERT INTO spell_required VALUES (25899,20911),(5209,5487)',world)
        sql("INSERT INTO spell_script_names VALUES (38795,'spell_murmur_sonic_boom_effect'),"
            "(53407,'spell_pal_judgement_of_justice'),(53736,'spell_pal_seal_of_corruption'),"
            "(40251,'spell_teron_gorefiend_shadow_of_death'),"
            "(60893,'spell_gen_profession_research')",world)
        sql('INSERT INTO spell_custom_attr VALUES (6603,0)',world)
        sql("INSERT INTO spell_script_names VALUES (-33872,'spell_dru_nurturing_instinct')",world)
        sql("INSERT INTO spell_script_names VALUES (-52284,'spell_dk_will_of_the_necropolis')",world)
    sql('CREATE TABLE spell_learn_spell (entry INT,SpellID INT,Active TINYINT);'
        'INSERT INTO spell_learn_spell VALUES (900011,900012,1),(53428,53341,1),(53428,53343,1),(33943,34090,1)',tc_world)
    sql('INSERT INTO spell_script_names VALUES '+','.join(
        f"({spell},'spell_chapter1_runeforging_credit')" for spell in RUNEFORGING),tc_world)
    sql('INSERT INTO spell_ranks VALUES (44440,44440,1),(44440,44441,2)',ac_world)
    sql("INSERT INTO spell_script_names VALUES (38796,'spell_murmur_sonic_boom'),"
        "(7744,'spell_wotf_shared_cd'),(37377,'spell_warl_t4_2p_bonus_shadow')",tc_world)
    sql("INSERT INTO spell_script_names VALUES (40081,'spell_black_template_free_friend'),(40326,'spell_teron_gorefiend_shadowy_construct')",ac_world)
