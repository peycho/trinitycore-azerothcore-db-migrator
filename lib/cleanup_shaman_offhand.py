"""Coupled Dual Wield retirement with explicit, reversible item placement.

Use stock native storage slots; never delete an item, mail it, stack it
or cast an unlearn spell. A shield can remain equipped. Pending talent
resets remain pending and both selected builds remain authoritative.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from copy import copy
import hashlib
import json
from pathlib import Path
from typing import Any, TYPE_CHECKING

from cleanup_files import PROFILE, fail, sha
from cleanup_plans import metadata, planner, snapshot
import cleanup_shaman_dual_wield as base
from cleanup_specializations import equipment_shape
from cleanup_types import DatabaseState, Evidence, SelectionResult

if TYPE_CHECKING:
    from cleanup_config import Settings
    from spell_metadata import Metadata


POLICY = 'tc-unselected-shaman-offhand-reconciliation-v2'
ACK = 'RETIRE_UNSELECTED_DUAL_WIELD_STOW_WEAPON_RETAIN_SHIELD'
POLICIES = (POLICY,)
SLOTS = range(23,
    67)  # Backpack first, then ordinary bank slots. No bank bags.
TABLES = {'character_inventory': {'guid', 'bag', 'slot', 'item'},
    'item_instance': {'guid', 'owner_guid', 'itementry', 'count'},
    'mail_items': {'item_guid'}, 'guild_bank_item': {'item_guid'},
    'auctionhouse': {'itemguid'}, 'character_aura': {'itemguid'}}


def native_sources(paths: Mapping[str, Path | None]) -> dict[str, str]:
    result = {}
    for core, prefix in (('tc', 'trinitycore'), ('ac', 'azerothcore')):
        manifest = ({n.strip(): h for h, n in (line.split(None, 1) for line
            in (PROFILE / (prefix + '-semantic.sha256')).read_text(
            ).splitlines())})
        names = ['src/server/game/Entities/Player/Player.cpp',
            'src/server/game/Entities/Player/Player.h']
        result[core] = {}
        for name in set(names):
            if (name not in manifest or sha(paths[core + '_source'] / name)
                != manifest[name]):
                fail('SHAMAN_OFFHAND_NATIVE_DRIFT',
                    'Pinned native equipment/storage consumer differs: '
                    + core + ':' + name)
            result[core][name] = manifest[name]
    return result


def candidate_guids(state: DatabaseState) -> list[int]:
    books = defaultdict(dict)
    for g, s, a, d in state['character_spell']:
        books[g][s] = (a, d)
    return sorted(g for g, r, c, *rest in state['characters'] if c == 7
        and books[g].get(674) == (1, 0))


def item_query(
    settings: Settings,
    ids: Sequence[int],
) -> tuple[list[str], str]:
    s = settings.schemas['characters']
    tc = settings.schemas['world']
    ac = settings.get('target', 'world')
    fields = ['x.guid', 'x.owner_guid', 'x.itemEntry', 'x.count']
    fields += ([p + '.' + c for p in ('t', 'a') for c in ('entry', 'class',
        'subclass', 'InventoryType', 'RequiredSkill', 'requiredspell')])
    fields += [
        f'(SELECT COUNT(*) FROM `{s}`.{table} q WHERE q.{field}=x.guid)'
        for table, field in
        (('character_inventory', 'item'), ('mail_items', 'item_guid'), (
            'guild_bank_item', 'item_guid'), ('auctionhouse', 'itemguid'))]
    fields += [
        f'(SELECT COUNT(*) FROM `{s}`.character_aura q WHERE (q.itemGuid & '
        '4294967295)=x.guid)']
    query = (
        f'FROM `{s}`.item_instance x LEFT JOIN `{tc}`.item_template t ON '
        f't.entry=x.itemEntry LEFT JOIN `{ac}`.item_template a ON '
        f'a.entry=x.itemEntry WHERE x.guid IN ({ids})'
    )
    return fields, query


def read(
    settings: Settings,
    guids: Sequence[int],
    *,
    equipment_slots: Iterable[int] | None = (15, 16),
) -> Evidence:
    ids = ','.join(map(str, sorted(set(guids)))) or 'NULL'
    s = settings.schemas['characters']
    layouts = {}
    for core, schema, tables in (('source', s, TABLES), ('tc',
        settings.schemas['world'], {'item_template': {'entry', 'class',
            'subclass', 'inventorytype', 'requiredskill', 'requiredspell'}}), (
                'ac', settings.get('target', 'world'), {'item_template': {
                    'entry',
                    'class', 'subclass', 'inventorytype', 'requiredskill',
                    'requiredspell'}})):
        view = copy(settings)
        view.schemas = {**settings.schemas, 'characters': schema}
        meta = metadata(view, list(tables))
        for table, fields in tables.items():
            equipment_shape(meta, table, fields)
        layouts[core] = {'schema': schema, 'meta': meta}
    invmeta = layouts['source']['meta']
    columns = [r for r in invmeta['columns'] if r[0] == 'character_inventory']
    if ({r[1] for r in columns} != {'guid', 'bag', 'slot', 'item'} or any(r[5]
        or r[6] for r in columns)):
        fail('SHAMAN_OFFHAND_INVENTORY_LAYOUT',
            'Only stock four-column inventory supported; '
            'custom/automatic columns require review')
    slots = sorted(set(equipment_slots))
    if any(type(s) is not int or not 0 <= s <= 255 for s in slots):
        fail('EQUIPMENT_SCOPE_INVALID', 'Invalid native equipment slot')
    rows = snapshot(settings, [('inventory',
        f'SELECT JSON_ARRAY(guid,bag,slot,item) row_value FROM `{s}'
        f'`.character_inventory WHERE guid IN ({ids}) ORDER BY '
        'guid,bag,slot,item LIMIT 40001')])['inventory']
    if len(rows) > 40000:
        fail('SHAMAN_OFFHAND_BOUND', 'Inventory scope exceeds 40000 rows')
    items = sorted({r[3] for r in rows if r[1] == 0 and r[2] in slots})
    fields, query = item_query(settings, ','.join(map(str, items)) or 'NULL')
    facts = (snapshot(settings, [('items', 'SELECT JSON_ARRAY(' + ','.join(
        fields) + ') row_value ' + query + ' ORDER BY x.guid')])['items'])
    return {'layouts': layouts, 'inventory': rows, 'items': facts,
        'item_ids': items, 'equipment_slots': slots}


def restrict(capture: Evidence, guids: Sequence[int]) -> Evidence:
    slots = capture.get('equipment_slots', (15, 16))
    guids = set(guids)
    rows = [r for r in capture['inventory'] if r[0] in guids]
    items = sorted({r[3] for r in rows if r[1] == 0 and r[2] in slots})
    return {**capture, 'inventory': rows, 'items': [r for r in capture[
        'items'] if r[0] in items], 'item_ids': items}


def placement(
    state: DatabaseState,
    capture: Evidence,
    *,
    candidate_ids: Sequence[int] | None = None,
) -> Evidence:
    inventories = defaultdict(list)
    facts = {r[0]: r for r in capture['items']}
    skills = defaultdict(dict)
    for g, s, v, m in state['character_skills']:
        skills[g][s] = (v, m)
    for r in capture['inventory']:
        inventories[r[0]].append(r)
    decisions = {}
    for g in candidate_guids(state) if candidate_ids is None else sorted(set(
        candidate_ids)):
        rows = inventories[g]
        reason = ''
        moves = []
        off = [r for r in rows if r[1] == 0 and r[2] == 16]
        if (len({(r[1], r[2]) for r in rows}) != len(rows) or len({r[3] for r
            in rows}) != len(rows)):
            reason = 'DEFER_DUPLICATE_ITEM_PLACEMENT'
        elif len(off) > 1:
            reason = 'DEFER_DUPLICATE_ITEM_PLACEMENT'
        else:
            hands = [r for r in rows if r[1] == 0 and r[2] in (15, 16)]
            for row in hands:
                f = facts.get(row[3])
                if (not f or len(f) != 21 or any(v is None for v in f) or f[1]
                    != g or f[2] <= 0 or f[3] != 1
                    or f[4:10] != f[10:16] or f[4] != f[2] or f[16:] != [1,
                        0, 0, 0, 0]):
                    reason = 'DEFER_UNVERIFIED_HAND_ITEM'
                    break
                # Valid singleton one-handed native gear; no item dependency
                # on the retired skill or spell in either world.
                if f[8] == 118 or f[9] in (674, 30798):
                    reason = 'DEFER_ITEM_DUAL_WIELD_REQUIREMENT'
                    break
                if (row[2] == 15 and (f[5] != 2 or f[7] not in (13, 21) or f[
                    6] in (6, 10, 20))):
                    reason = 'DEFER_MAINHAND_CONTRACT'
                    break
            if not reason and off:
                f = facts[off[0][3]]
                if f[5:8] == [4, 6, 14] and skills[g].get(433) == (1, 1):
                    pass
                elif f[5] == 2 and f[7] in (13, 22):
                    occupied = {r[2] for r in rows if r[1] == 0}
                    slot = next((s for s in SLOTS if s not in occupied), None)
                    if slot is None:
                        reason = 'DEFER_NO_NATIVE_STORAGE_SLOT'
                    else:
                        moves = [[g, off[0][3], 16, slot]]
                else:
                    reason = 'DEFER_OFFHAND_CONTRACT'
        decisions[g] = {'reason': reason, 'moves': moves, 'offhand': off[0][3]
            if off else None,
            'action': 'STOW_WEAPON' if moves else 'RETAIN_SHIELD'
            if off else 'EMPTY'}
    return decisions


def select(
    state: DatabaseState,
    tc: Metadata,
    ac: Metadata,
    expected: int | None = None,
    *,
    preview: bool = False,
    capture: Evidence,
    default_skills: Evidence | None,
) -> SelectionResult:
    decisions = placement(state, capture)
    rows, excluded, proof, summary, edges = base.select(state, tc, ac,
        preview=True,
        offhand={g for g, p in decisions.items() if p['reason']},
        default_skills=default_skills, allow_pending=True)
    excluded = ([(g, s, decisions[g]['reason'] if why
        == 'DEFER_OCCUPIED_OFFHAND' else why) for g, s, why in excluded])
    moves = sorted(move for g, *rest in rows for move in decisions[g]['moves'])
    for p in summary['eligibility_proofs']:
        g = p['guid']
        p.update(offhand=decisions[g], pending_native_reset_preserved=bool(
            next(c[7] for c in state['characters'] if c[0] == g) & 4))
    summary.update(deferred=dict(Counter(r[2] for r in excluded)),
        inventory_moves=moves,
        inventory_rows_moved=len(moves), item_rows_changed=0,
        native_policy='Retire unselected Shaman 674 and skill 118 together; stow '
        'verified off-hand weapons in the first empty backpack slot '
        '(23..38), then ordinary bank slot (39..66); retain verified '
        'shield. Archive complete inventory and exact placement inverse. '
        'Preserve item instances, both talent builds, every other skill '
        'and all pending reset flags; no grants or reset execution')
    if not preview and expected != len(rows):
        fail('SHAMAN_OFFHAND_SELECTION_MISMATCH',
            f'Expected {expected} pairs, selected {len(rows)}')
    return rows, excluded, proof, summary, edges


def digest(rows: Sequence[Sequence[Any]]) -> str:
    return hashlib.sha256(''.join(hashlib.sha256('|'.join('N' if v is None
        else str(v) for v in r).encode()).hexdigest() for r in rows).encode(
        )).hexdigest()


def inventory_check(
    schema: str,
    table: str,
    rows: Sequence[Sequence[Any]],
    guids: Sequence[int],
    label: str,
) -> str:
    groups = defaultdict(list)
    for r in rows:
        groups[r[0]].append(r)
    expected = ([[g, len(groups[g]), digest(sorted(groups[g], key=lambda r: (r[
        1], r[2], r[3])))] for g in guids])
    fields = ','.join(f'CAST(i.`{c}` AS CHAR)' for c in ('guid', 'bag', 'slot',
        'item'))
    actual = (
        "SELECT i.guid,COUNT(*) n,SHA2(GROUP_CONCAT(SHA2(CONCAT_WS('|',"
        f"{fields}),256) ORDER BY i.bag,i.slot,i.item SEPARATOR ''),256) "
        f'h FROM `{schema}`.`{table}` i JOIN affected g ON g.guid=i.guid '
        'GROUP BY i.guid'
    )
    return f"""IF EXISTS(SELECT 1 FROM JSON_TABLE('{json.dumps(expected,separators=(',',':'))}','$[*]' COLUMNS(guid INT PATH '$[0]',n INT PATH '$[1]',h CHAR(64) PATH '$[2]')) e
 LEFT JOIN ({actual}) a ON a.guid=e.guid WHERE COALESCE(a.n,0)<>e.n OR NOT(BINARY COALESCE(a.h,'{digest([])}')<=>BINARY e.h)) THEN
 SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='{label} inventory fingerprint changed'; END IF;"""


def evidence_guard(settings: Settings, capture: Evidence) -> str:
    """Seal read-only equipment/placement inputs independently of a
    mutation.
    """
    checks = []
    for entry in capture['layouts'].values():
        schema = entry['schema']
        m = entry['meta']
        names = ','.join("'" + r[0] + "'" for r in m['tables'])
        checks.append(
            f"""IF (SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA='{schema}' AND TABLE_NAME IN ({names}) AND ENGINE='InnoDB' AND TABLE_TYPE='BASE TABLE')<>{len(m['tables'])}
 OR (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA='{schema}' AND TABLE_NAME IN ({names}))<>{len(m['columns'])}
 OR NOT((SELECT SHA2(GROUP_CONCAT(CONCAT_WS(':',TABLE_NAME,COLUMN_NAME,COLUMN_TYPE,IS_NULLABLE,COLUMN_KEY,EXTRA,COALESCE(GENERATION_EXPRESSION,''),ORDINAL_POSITION) ORDER BY BINARY TABLE_NAME,ORDINAL_POSITION SEPARATOR '|'),256) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA='{schema}' AND TABLE_NAME IN ({names}))<=>'{planner.key_hash(m['columns'])}') THEN
 SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Shaman inventory/item evidence layout changed'; END IF;""")
    fields, query = item_query(settings, ','.join(map(str, capture[
        'item_ids'])) or 'NULL')
    hashed = ("SHA2(CONCAT_WS('|'," + ','.join(
        f"IFNULL(CAST({f} AS CHAR),'N')" for f in fields) + '),256)')
    checks.append(f"""IF (SELECT COUNT(*) {query})<>{len(capture['items'])}
 OR NOT((SELECT SHA2(COALESCE(GROUP_CONCAT({hashed} ORDER BY x.guid SEPARATOR ''),''),256) {query})<=>'{digest(capture['items'])}') THEN
 SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Shaman hand item, template, placement or aura evidence changed'; END IF;""")
    return '\n'.join(checks)


def sql_parts(
    settings: Settings,
    capture: Evidence,
    guids: Sequence[int],
    moves: Sequence[Sequence[int]],
    archive: str,
) -> Evidence:
    """Guard direct SQL calls and exact archive/source inventory states."""
    source = settings.schemas['characters']
    checks = [evidence_guard(settings, capture)]
    # Inventory is the only additional source table changed. Refuse automatic
    # columns and any incoming/outgoing FK; template already rejects triggers.
    checks.append(
        f"""IF EXISTS(SELECT 1 FROM information_schema.KEY_COLUMN_USAGE WHERE REFERENCED_TABLE_NAME IS NOT NULL AND ((TABLE_SCHEMA='{source}' AND TABLE_NAME='character_inventory') OR (REFERENCED_TABLE_SCHEMA='{source}' AND REFERENCED_TABLE_NAME='character_inventory'))) THEN
 SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Shaman inventory foreign key requires review'; END IF;
 IF (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA='{archive}' AND TABLE_NAME='inventory_before')<>4
 OR (SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA='{archive}' AND TABLE_NAME='inventory_before' AND ENGINE='InnoDB' AND TABLE_TYPE='BASE TABLE')<>1
 OR EXISTS(SELECT 1 FROM information_schema.COLUMNS s LEFT JOIN information_schema.COLUMNS a ON a.TABLE_SCHEMA='{archive}' AND a.TABLE_NAME='inventory_before' AND a.ORDINAL_POSITION=s.ORDINAL_POSITION
 WHERE s.TABLE_SCHEMA='{source}' AND s.TABLE_NAME='character_inventory' AND (a.COLUMN_NAME IS NULL OR NOT(BINARY a.COLUMN_NAME<=>BINARY s.COLUMN_NAME) OR NOT(BINARY a.COLUMN_TYPE<=>BINARY s.COLUMN_TYPE) OR NOT(a.IS_NULLABLE<=>s.IS_NULLABLE) OR NOT(a.EXTRA<=>s.EXTRA) OR NOT(a.COLUMN_KEY<=>s.COLUMN_KEY))) THEN
 SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Shaman inventory archive layout changed'; END IF;""")
    rows = capture['inventory']
    mapping = {(g, item): new for g, item, old, new in moves}
    after = ([[g, bag, mapping.get((g, item), slot), item] for g, bag, slot,
        item in rows])
    return {'guard': '\n'.join(checks),
        'original': inventory_check(source, 'character_inventory', rows, guids,
            'Original'),
        'archive': inventory_check(archive, 'inventory_before', rows, guids,
            'Archive')
        + f'\nIF (SELECT COUNT(*) FROM inventory_before)<>{len(rows)} '
        "THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Unexpected "
        "inventory archive rows'; END IF;",
        'applied': inventory_check(source, 'character_inventory', after, guids,
            'Applied'),
        'moves': moves}
