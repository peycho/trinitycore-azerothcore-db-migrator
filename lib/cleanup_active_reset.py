"""Queue one native active-build reset; explicitly archive foreign talent spells.

Never delete active talent ownership before the native reset unlearns its
abilities. A populated inactive build needs a different, reviewed policy.
"""
import json
import re
import uuid

from cleanup_console import ROOT, fail
from cleanup_plans import (equality, finish, metadata, planner, ranks, render,
                           sha, sha_json, snapshot, write_json)

TABLES = ('characters', 'character_talent', 'character_spell', 'character_skills')
KEYS = {'characters':('guid',), 'character_talent':('guid','spell','talentGroup'),
        'character_spell':('guid','spell'), 'character_skills':('guid','skill')}


def columns(meta, table):
    return [row[1] for row in meta['columns'] if row[0] == table]


def row_key(table, alias='s'):
    return 'CONCAT_WS(\':\',' + ','.join(f'{alias}.`{key}`' for key in KEYS[table]) + ')'


def exact_hex(expression, sql_type):
    """Preserve fractions; HEX(number) itself rounds to an integer in MySQL.

    Promoting FLOAT to DOUBLE preserves its stored value before MySQL's
    round-trip text conversion. DECIMAL stays decimal, without a float cast.
    Binary/text/integer columns retain the historical byte representation.
    """
    kind = re.split(r'[ (]',sql_type.lower(),maxsplit=1)[0]
    if kind in ('float','double','real'):
        expression = f'CAST(CAST({expression} AS DOUBLE) AS CHAR)'
    elif kind in ('decimal','numeric'):
        expression = f'CAST({expression} AS CHAR)'
    return f'HEX({expression})'


def row_hash(meta, table, alias='s', *, exact_numeric=False):
    if exact_numeric:
        return "SHA2(CONCAT_WS('|'," + ','.join(
            f"IFNULL({exact_hex(alias+'.`'+r[1]+'`',r[2])},'N')"
            for r in meta['columns'] if r[0] == table) + '),256)'
    return 'SHA2(CONCAT_WS(\'|\',' + ','.join(
        f"IFNULL(HEX({alias}.`{name}`),'N')" for name in columns(meta,table)) + '),256)'


def selection(character, talents, spells, stores, requested, expected_talents):
    if len(character) != 1:
        fail('CHARACTER_MISSING', 'Exactly one existing character is required')
    guid,account,name,level,cls,active,groups,online = character[0]
    if not 10 <= level <= 80 or cls not in (1,2,3,4,5,6,7,8,9,11) or groups not in (1,2) or not 0 <= active < groups or online != 0:
        fail('ACTIVE_RESET_STATE_UNSUPPORTED','Requires a supported offline character and valid active specialization')
    if not isinstance(name,str) or not name or len(name.encode()) > 256:
        fail('RESET_NAME_UNSUPPORTED','Character name is outside the reviewed byte bound')
    if not 1 <= expected_talents <= 1000 or len(talents) != expected_talents:
        fail('RESET_TALENT_COUNT_CHANGED','Current talent count differs from --expect-talent-rows')
    if any(row[0] != guid or row[2] != active for row in talents):
        fail('INACTIVE_BUILD_NOT_EMPTY','This policy requires every inactive build to be empty; it never discards another build')
    catalog = {}
    for row in stores['Talent'].values():
        tab = stores['TalentTab'].get(row[1])
        for rank,spell in enumerate(row[4:9],1):
            if spell:
                catalog.setdefault(spell,[]).append((row[0],rank,tab[20] if tab else 0))
    families = set()
    points = 0
    for _,spell,_ in talents:
        matches = catalog.get(spell,[])
        if len(matches) != 1 or not matches[0][2] & (1 << (cls-1)) or spell not in stores['Spell']:
            fail('RESET_RANK_UNSUPPORTED','Selected ownership is not an unambiguous class talent rank: '+str(spell))
        family,rank,_ = matches[0]
        if family in families:
            fail('RESET_RANK_UNSUPPORTED','Multiple selected ranks of one talent family require separate review')
        families.add(family)
        points += rank
    selected_ids = {row[1] for row in talents}
    if not any(row[1] in selected_ids and row[3] == 0 for row in spells):
        fail('RESET_ENABLED_TALENT_REQUIRED','Native TC reset requires an enabled selected talent spell; unsupported empty runtime state')
    if not re.fullmatch(r'[0-9]+(?:,[0-9]+)*',requested):
        fail('INVALID_SPELL_SELECTION','--remove-spells requires explicit comma-separated foreign talent spell IDs')
    ids = [int(value) for value in requested.split(',')]
    if len(set(ids)) != len(ids) or not 1 <= len(ids) <= 32 or any(not 1 <= value <= 16777215 for value in ids):
        fail('INVALID_SPELL_SELECTION','Select 1 to 32 distinct native spell IDs')
    book = {row[1]:tuple(row) for row in spells}
    selected = []
    for spell in sorted(ids):
        matches = catalog.get(spell,[])
        if len(matches) != 1 or matches[0][2] & (1 << (cls-1)) or spell not in stores['Spell']:
            fail('FOREIGN_TALENT_REQUIRED','Explicit spell must be one unambiguous talent rank for another class: '+str(spell))
        record = stores['Spell'][spell]
        # Narrow reviewed case: no teaching, skill, specialization or pet spells.
        if (spell != 12284 or matches[0] != (125,1,1) or record[71:74] != [6,0,0]
                or record[95:98] != [280,0,0] or not record[4] & 64
                or record[12] or record[20] or any(record[116:119])):
            fail('FOREIGN_TALENT_UNREVIEWED','Only reviewed foreign warrior talent 12284 is supported by this policy')
        if spell not in book or book[spell][2:] != (1,0):
            fail('FOREIGN_TALENT_STATE_CHANGED','Explicit foreign spell must exist as active=1, disabled=0')
        selected.append(book[spell])
    others = sorted(row[1] for row in spells if row[3] == 0 and row[1] not in ids
        and len(catalog.get(row[1],[])) == 1 and not catalog[row[1]][0][2] & (1 << (cls-1)))
    if others:
        fail('OTHER_FOREIGN_TALENTS_ENABLED','Additional enabled foreign talent spells need review: '+','.join(map(str,others)))
    return selected,points


def plan_active_reset(settings, work, args, output):
    guid = args.guid
    if not 1 <= guid <= 4294967295:
        fail('INVALID_GUID','Character GUID must fit the native unsigned domain')
    source = settings.schemas['characters']
    meta = metadata(settings,TABLES)
    for row in meta['columns']:
        if 'on update' in row[5].lower():
            fail('UNSUPPORTED_COLUMN','Automatic update columns require separate review')
    for table in TABLES:
        if not set(KEYS[table]) <= set(columns(meta,table)):
            fail('UNSUPPORTED_SCHEMA','Required native keys are missing: '+table)
        if set(KEYS[table]) != {row[1] for row in meta['columns'] if row[0]==table and row[4]=='PRI'}:
            fail('UNSUPPORTED_SCHEMA','Native primary key differs: '+table)
    queries = [('character',f'SELECT JSON_ARRAY(guid,account,name,level,class,activeTalentGroup,talentGroupsCount,online) row_value FROM `{source}`.characters WHERE guid={guid}'),
        ('talents',f'SELECT JSON_ARRAY(guid,spell,talentGroup) row_value FROM `{source}`.character_talent WHERE guid={guid} ORDER BY spell,talentGroup'),
        ('spells',f'SELECT JSON_ARRAY(guid,spell,active,disabled) row_value FROM `{source}`.character_spell WHERE guid={guid} ORDER BY spell')]
    for table in TABLES:
        queries.append(('cells',f"SELECT JSON_ARRAY('{table}',{row_key(table)},{row_hash(meta,table)}) row_value FROM `{source}`.`{table}` s WHERE s.guid={guid} ORDER BY {row_key(table)}"))
    state = snapshot(settings,queries)
    write_json(work.operation/'evidence.json',{'state':state,'metadata':meta})
    stores,_,dbc = ranks(settings)
    selected,points = selection(state['character'],state['talents'],state['spells'],stores,args.remove_spells,args.expect_talent_rows)
    cells = sorted(tuple(row) for row in state['cells'])
    if not 1 <= len(cells) <= 50000:
        fail('RESET_SNAPSHOT_BOUND','Single-character snapshot exceeds the reviewed 50000-row bound')
    if len({(row[0],row[1]) for row in cells}) != len(cells):
        fail('RESET_SNAPSHOT_BOUND','Duplicate source snapshot keys')
    template = ROOT/'tools/active-talent-reset.sql.in'
    batch = sha_json({'session':work.session.name,'id':output.name,'state':state,'meta':meta,'dbc':dbc,'template':sha(template)})
    archive = 'tc_active_reset_'+uuid.uuid4().hex[:20]
    counts = {table:sum(row[0]==table for row in cells) for table in TABLES}
    values = {'SOURCE':source,'ARCHIVE':archive,'GUID':guid,'UUID':work.current()['identity']['uuid'],
        'BATCH':batch,'AUDIT':sha_json(state),'COUNT':len(selected), 'POINTS':points,
        'EXPECTED_INSERT':planner.insert_values('expected_spells',selected),
        'SNAPSHOT_INSERT':planner.insert_values('expected_snapshot',cells),
        'SNAPSHOT_HASH':planner.key_hash(cells),'SNAPSHOT_COUNT':len(cells),
        'COLUMN_INSERT':planner.insert_values('reviewed_columns',meta['columns']),
        'COLUMN_HASH':planner.key_hash(meta['columns']),'COLUMN_COUNT':len(meta['columns']),
        'CONCAT_LIMIT':max(8192,len(cells)*256,len(meta['columns'])*2048),
        'EXPECTED_HASH':planner.key_hash(selected)}
    for table in TABLES:
        values['HASH_'+table.upper()] = row_hash(meta,table)
        values['KEY_'+table.upper()] = row_key(table)
        values['COUNT_'+table.upper()] = counts[table]
        values['EQUAL_'+table.upper()] = equality(meta,table)
    values['CHAR_AFTER_EQUAL'] = ' AND '.join(
        '(s.at_login <=> (a.at_login | 4))' if name=='at_login' else
        f'(BINARY s.`{name}` <=> BINARY a.`{name}`)' for name in columns(meta,'characters'))
    if metadata(settings,TABLES) != meta:
        fail('SCHEMA_DRIFT','Source metadata changed while planning')
    if any(sha(settings.paths['tc_dbc']/name)!=expected for name,expected in dbc.items()):
        fail('DBC_DRIFT','DBC assets changed while planning')
    manifest = {'policy':'tc-active-build-native-reset-v1','archive_schema':archive,'batch_key':batch,
        'selected_rows':len(selected),'affected_characters':1,'character':state['character'][0],
        'before_talent_rows':len(state['talents']),'retained_pending_native_reset':len(state['talents']),
        'selected_talent_points':points,'inactive_builds':'EMPTY','evidence_sha256':sha_json(state),
        'snapshot_sha256':values['SNAPSHOT_HASH'],'dbc_sha256':dbc,'template_sha256':sha(template),
        'native_reset':'PENDING NEXT LOGIN after apply; active ownership retained for native unlearning',
        'explicit_foreign_spells':selected}
    archived_columns = ','.join(f'HEX(`{name}`) AS `{name}_hex`' for name in columns(meta,'character_spell'))
    status = f'''SELECT * FROM `{archive}`.batch;
SELECT guid,level,class,activeTalentGroup,talentGroupsCount,at_login,(at_login & 4)<>0 AS native_reset_pending FROM `{source}`.characters WHERE guid={guid};
SELECT talentGroup,COUNT(*) AS retained_for_native_reset FROM `{source}`.character_talent WHERE guid={guid} GROUP BY talentGroup;
SELECT {archived_columns} FROM `{archive}`.character_spell_before WHERE spell IN ({','.join(str(row[1]) for row in selected)});
'''
    finish(settings,work,output,manifest,render(template,values),
        'guid\tspell\tactive\tdisabled\n'+''.join('\t'.join(map(str,row))+'\n' for row in selected),status)
