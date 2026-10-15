#!/usr/bin/env python3
"""Read-only core metadata and bounded character spell reconstruction.

MySQL is accessed through the runner's existing client arguments. Only SELECT
statements are executed here; generated control/target SQL is executed by the
transactional Bash loader. Character rows are streamed in GUID order.
"""
import argparse
from collections import defaultdict, deque
import hashlib
import itertools
import json
from pathlib import Path
import struct
import subprocess
import sys

POLICY = 'spell-state-v1'
LEARN, SKILL, SKILL_STEP, DUAL_WIELD = 36, 118, 44, 40
PASSIVE, HIDDEN = 0x40, 0x80


class Unsupported(ValueError):
    def __init__(self, reason, detail):
        super().__init__(detail)
        self.reason = reason


def reject(reason, detail):
    raise Unsupported(reason, detail)


def digest(value):
    return hashlib.sha256(value).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def sql_text(value):
    return "CONVERT(0x" + str(value).encode().hex() + " USING utf8mb4)"


class Database:
    def __init__(self, arguments):
        self.arguments = arguments
        self.fingerprints = {}

    def rows(self, label, query):
        hasher = hashlib.sha256()
        # Do not print arguments: option files may contain authentication data.
        # Escaped batch output keeps tabs/newlines in ignored localized DBC
        # strings from corrupting record boundaries. Script identifiers use
        # the protected ASCII names; numeric source rows need no decoding.
        with subprocess.Popen(['mysql', *self.arguments, '--batch', '--skip-raw',
                               '--skip-column-names', '--quick'], stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE) as process:
            try:
                process.stdin.write(query.encode())
                process.stdin.close()
                for line in process.stdout:
                    hasher.update(line)
                    yield line.decode().rstrip('\n').split('\t')
                error = process.stderr.read().decode()
                if process.wait():
                    reject('SPELL_METADATA_QUERY_FAILED', f'{label}: {error.strip()}')
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait()
        self.fingerprints[label] = hasher.hexdigest()

    def table(self, schema, table, columns, optional=False):
        present = list(self.rows(f'{schema}.{table}.present',
            "SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA="
            f"'{schema}' AND TABLE_NAME='{table}' AND TABLE_TYPE='BASE TABLE';"))
        if present != [['1']]:
            if optional:
                return []
            reject('MISSING_SPELL_METADATA_TABLE', f'{schema}.{table}')
        layout = list(self.rows(f'{schema}.{table}.layout',
            "SELECT COLUMN_NAME,COLUMN_TYPE,IS_NULLABLE,ORDINAL_POSITION FROM information_schema.COLUMNS "
            f"WHERE TABLE_SCHEMA='{schema}' AND TABLE_NAME='{table}' ORDER BY ORDINAL_POSITION;"))
        if table.endswith('_dbc') and [row[0] for row in layout] != columns:
            reject('INCOMPATIBLE_DBC_OVERLAY', f'{schema}.{table}: ordered columns differ from pinned AC reader')
        # Names come exclusively from the protected profile layout.
        selected = ','.join('`' + name + '`' for name in columns)
        return list(self.rows(f'{schema}.{table}',
            f'SELECT {selected} FROM `{schema}`.`{table}` ORDER BY {selected};'))


def read_dbc(path, fmt):
    data = path.read_bytes()
    if len(data) < 20:
        reject('INVALID_DBC', f'{path.name}: truncated header')
    magic, count, fields, size, strings = struct.unpack_from('<4s4I', data)
    if magic != b'WDBC' or fields != len(fmt) or size != 4 * fields or len(data) != 20 + count * size + strings:
        reject('INVALID_DBC', f'{path.name}: incompatible WDBC layout')
    records = {}
    string_start = 20 + count * size
    string_fields = [index for index, field in enumerate(fmt) if field == 's']
    for offset in range(20, 20 + count * size, size):
        record = list(struct.unpack_from('<' + 'I' * fields, data, offset))
        if not record[0] or record[0] in records:
            reject('INVALID_DBC', f'{path.name}: duplicate/zero ID {record[0]}')
        for index in string_fields:
            if record[index] >= strings or data.find(b'\0', string_start + record[index]) < 0:
                reject('INVALID_DBC', f'{path.name}: invalid string offset for ID {record[0]}')
        records[record[0]] = record
    return records, digest(data)


def signed(value):
    return value - 2**32 if value >= 2**31 else value


class Metadata:
    def __init__(self, core, dbc_dir, world, profile, db):
        self.core, self.world = core, world
        self.stores, self.hashes = {}, {}
        for name, layout in profile['stores'].items():
            path = Path(dbc_dir) / (name + '.dbc')
            try:
                records, sha = read_dbc(path, layout['formats'][core])
            except OSError:
                reject('MISSING_DBC', f'{core}: {name}.dbc')
            self.hashes[f'{core}.{name}.dbc'] = sha
            if core == 'ac':
                rows = db.table(world, layout['table'], layout['columns'])
                for row in rows:
                    # Only numeric fields affect this transform. Float bits are
                    # kept for layout fidelity; strings are deliberately ignored.
                    record = [0] * len(row)
                    for i, (value, fmt) in enumerate(zip(row, layout['formats'][core])):
                        if fmt == 'f':
                            record[i] = struct.unpack('<I', struct.pack('<f', float(value)))[0]
                        elif fmt not in 'sxX':
                            record[i] = int(value) & 0xffffffff
                    records[record[0]] = record
            elif name == 'Spell':
                # TC custom entries are additions, never replacements (its
                # DBCDatabaseLoader aborts on duplicate DBC IDs).
                sql_fmt = profile['tc_spell_sql_format']
                positions = [i for i, value in enumerate(sql_fmt) if value == 'p']
                # SELECT * matches the pinned TC reader; validate its width.
                list(db.rows('tc.spell_dbc.layout',
                    "SELECT COLUMN_NAME,COLUMN_TYPE,IS_NULLABLE,ORDINAL_POSITION FROM information_schema.COLUMNS "
                    f"WHERE TABLE_SCHEMA='{world}' AND TABLE_NAME='spell_dbc' ORDER BY ORDINAL_POSITION;"))
                rows = list(db.rows(f'{core}.spell_dbc', f'SELECT * FROM `{world}`.spell_dbc ORDER BY Id;'))
                for row in rows:
                    if len(row) != len(positions):
                        reject('INCOMPATIBLE_DBC_OVERLAY', 'TC spell_dbc column count')
                    record = [0] * len(sql_fmt)
                    for i, value in zip(positions, row):
                        if layout['formats'][core][i] == 'f':
                            record[i] = struct.unpack('<I', struct.pack('<f', float(value)))[0]
                        elif layout['formats'][core][i] != 's':
                            record[i] = int(value) & 0xffffffff
                    if record[0] in records:
                        reject('TC_DBC_OVERLAY_COLLISION', str(record[0]))
                    records[record[0]] = record
            self.stores[name] = records
        self.spells = self.stores['Spell']
        self.talents, self.talent_rows, self.invalid_talents = {}, {}, set()
        for _, talent in sorted(self.stores['Talent'].items()):
            ranks = talent[4:9]
            nonzero = [x for x in ranks if x]
            malformed = ranks[:len(nonzero)] != nonzero or any(spell not in self.spells for spell in nonzero)
            for rank, spell in enumerate(nonzero):
                if spell in self.talents:
                    # Stock pet talent tabs share rank IDs. They cannot be
                    # inferred as player talent ownership; reject if reached.
                    self.invalid_talents.add(spell)
                self.talents[spell] = (talent[0], rank + 1)
                self.talent_rows[spell] = talent
                if malformed:
                    self.invalid_talents.add(spell)
        self.correction_guards = defaultdict(list)
        for rule in profile['corrections'][core]['guards']:
            for spell in rule['ids']:
                self.correction_guards[spell].extend(rule['fields'])
        for rule in profile['corrections'][core]['operations']:
            for spell in rule['ids']:
                if spell in self.spells:
                    record = self.spells[spell]
                    for field, op, value in rule['changes']:
                        record[field] = {'=': lambda: value, '|=': lambda: record[field] | value,
                                         '&=': lambda: record[field] & value}[op]() & 0xffffffff
        # Reviewed global correction in both pinned cores.
        for record in self.spells.values():
            if record[134] == 2158:
                record[4] |= PASSIVE
        self.chains, self.position = {}, {}
        for talent in self.stores['Talent'].values():
            ranks = tuple(x for x in talent[4:9] if x)
            if len(ranks) > 1 and not any(spell in self.invalid_talents for spell in ranks):
                self.add_chain(ranks)
        rank_rows = db.table(world, 'spell_ranks', ['first_spell_id', 'spell_id', 'rank'])
        for first, rows in itertools.groupby(rank_rows, key=lambda r: int(r[0])):
            ranks = sorted((int(rank), int(spell)) for _, spell, rank in rows)
            if not ranks or len(ranks) > 255 or [r for r, _ in ranks] != list(range(1, len(ranks) + 1)) or ranks[0][1] != first:
                reject('MALFORMED_SPELL_CHAIN', f'{core}: first={first}')
            chain = tuple(spell for _, spell in ranks)
            if len(chain) > 1:
                self.add_chain(chain)
            elif chain[0] not in self.spells:
                reject('MISSING_CHAIN_SPELL', f'{core}: {chain[0]}')
        self.requires = defaultdict(set)
        for spell, required in db.table(world, 'spell_required', ['spell_id', 'req_spell']):
            spell, required = int(spell), int(required)
            if spell not in self.spells or required not in self.spells or self.first(spell) == self.first(required):
                reject('INVALID_SPELL_REQUIREMENT', f'{core}: {spell}:{required}')
            self.requires[spell].add(required)
        self.learns, self.effect_learns = defaultdict(list), defaultdict(list)
        world_learns = []
        if core == 'tc':
            world_learns = db.table(world, 'spell_learn_spell', ['entry', 'SpellID', 'Active'])
            for parent, child, active in world_learns:
                parent, child, active = int(parent), int(child), int(active)
                if parent not in self.spells or child not in self.spells or child in self.talents or active not in (0, 1):
                    reject('INVALID_LEARNED_SPELL', f'{parent}:{child}')
                self.learns[parent].append((child, active, False))
        for spell, record in self.spells.items():
            for i in range(3):
                child = record[116 + i]
                if record[71 + i] == LEARN and child in self.spells:
                    auto = record[86 + i] == 5 or spell in self.talents or bool(record[4] & PASSIVE) or SKILL_STEP in record[71:74]
                    self.effect_learns[spell].append((child, 1, auto))
                    # TC returns early, before scanning DBC learn effects,
                    # when spell_learn_spell is empty. Cast learn effects
                    # still exist independently of that loader map.
                    if (core == 'ac' or world_learns) and not any(row[0] == child for row in self.learns[spell]):
                        self.learns[spell].append((child, 1, auto))
        self.additional = set()
        for talent in self.talents:
            for child, _, _ in self.effect_learns[talent]:
                if child in self.position and not self.spells[child][4] & (PASSIVE | HIDDEN):
                    self.additional.add(child)
        for spell, prerequisites in self.requires.items():
            if any(parent in self.talents for parent in prerequisites):
                self.additional.add(spell)
        self.abilities = defaultdict(list)
        for ability in self.stores['SkillLineAbility'].values():
            self.abilities[ability[2]].append(ability)
        # A script may learn spells outside DBC/world relationships. Native
        # combat-only scripts are accepted; unreviewed learning scripts block.
        self.scripts = defaultdict(set)
        for spell, name in db.table(world, 'spell_script_names', ['spell_id', 'ScriptName']):
            spell = int(spell)
            if spell < 0:
                for member in self.chain(abs(spell)):
                    self.scripts[member].add(name)
            else:
                self.scripts[spell].add(name)
        self.script_policy = profile.get('scripts', {}).get(core, {})
        # World custom attributes can change the TC AutoLearned classification.
        custom_columns = ['entry', 'attributes'] if core == 'tc' else ['spell_id', 'attributes']
        for spell, attributes in db.table(world, 'spell_custom_attr', custom_columns):
            if core == 'tc' and int(attributes) & 0x00800000 and int(spell) not in self.talents:
                reject('CUSTOM_TALENT_CLASSIFICATION', spell)

    def add_chain(self, chain):
        for index, spell in enumerate(chain):
            if spell not in self.spells:
                reject('MISSING_CHAIN_SPELL', f'{self.core}: {spell}')
            if spell in self.position and self.chain(spell) != chain:
                reject('CONFLICTING_SPELL_CHAINS', f'{self.core}: {spell}')
            self.position[spell] = (chain[0], index)
        self.chains[chain[0]] = chain

    def chain(self, spell):
        return self.chains.get(self.first(spell), (spell,))

    def first(self, spell):
        return self.position.get(spell, (spell, 0))[0]

    def predecessors(self, spell):
        return self.chain(spell)[:self.position.get(spell, (spell, 0))[1]]

    def stackable(self, spell):
        record = self.spells[spell]
        effects = record[71:74]
        profession = any(self.stores['SkillLine'].get(row[1], [0, 0])[1] in (9, 11) or row[1] == 762
                         for row in self.abilities[spell])
        if record[4] & PASSIVE or signed(record[41]) not in (0, -2) or profession:
            return False
        if record[208] == 10 and (65 in effects or (self.core == 'tc' and record[210] & 0x20000000)):
            return False
        if record[208] == 7 and any(effects[i] == 6 and record[95 + i] == 36 for i in range(3)):
            return False
        return True

    def check_spell(self, spell):
        if spell not in self.spells:
            reject('UNKNOWN_SPELL_ID', f'{self.core}: {spell}')
        if spell in self.invalid_talents:
            reject('MALFORMED_TALENT_CHAIN', f'{self.core}: {spell}')
        record = self.spells[spell]
        for field in self.correction_guards[spell]:
            if field == 'visibility':
                reject('UNSUPPORTED_CORE_CORRECTION', f'{self.core}: {spell}: {field}')
            index, name = field.split(':')
            effect = record[71 + int(index)]
            if name == 'Effect' or effect in (LEARN, SKILL, SKILL_STEP, DUAL_WIELD, 65) or (effect == 6 and name == 'ApplyAuraName'):
                reject('UNSUPPORTED_CORE_CORRECTION', f'{self.core}: {spell}: {field}')
        for name in self.scripts[spell]:
            if self.script_policy.get(name) != 'NO_SPELLBOOK_MUTATION':
                reject('UNSUPPORTED_LEARNING_SCRIPT', f'{self.core}: {spell}: {name}')

    def skill_effect(self, spell):
        record = self.spells[spell]
        for i in range(3):
            if record[71 + i] == SKILL:
                if record[74 + i] not in (0, 1):
                    reject('NONDETERMINISTIC_SKILL_EFFECT', str(spell))
                step = signed(record[80 + i]) + (1 if record[74 + i] else 0)
                return record[110 + i], step, step * 75 if record[110 + i] == 762 else 1, step * 75
            if record[71 + i] == DUAL_WIELD:
                return 118, 1, 1, 1
        return None


def assert_acyclic(metadata, seeds):
    # Iterative DFS; traverses each reachable vertex once, without recursion.
    done, visiting = set(), set()
    for root in seeds:
        stack = [(root, False)]
        while stack:
            spell, leaving = stack.pop()
            if leaving:
                visiting.discard(spell)
                done.add(spell)
                continue
            if spell in visiting:
                reject('CYCLIC_SPELL_RELATIONSHIP', str(spell))
            if spell in done:
                continue
            metadata.check_spell(spell)
            visiting.add(spell)
            stack.append((spell, True))
            previous = metadata.predecessors(spell)[-1:]
            edges = list(previous) + [row[0] for row in metadata.learns[spell]] + sorted(metadata.requires[spell])
            stack.extend((child, False) for child in reversed(edges))
            if len(visiting) > len(metadata.spells):
                reject('SPELL_TRAVERSAL_BOUND', str(root))


def reconstruct(character, stored, talents, skills, source, target, direction):
    """Return one deterministic result per spell, retaining all derivations."""
    race, cls, active_group, groups = character
    if not (1 <= race <= 32 and 1 <= cls <= 32 and groups in (1, 2) and 0 <= active_group < groups):
        reject('INVALID_SPELL_CHARACTER_STATE', str(character))
    tc, ac = (source, target) if direction == 'tc-to-ac' else (target, source)
    class_mask, race_mask = 1 << (cls - 1), 1 << (race - 1)
    owners = defaultdict(int)
    for spell, mask in talents.items():
        if spell not in source.talents or spell not in target.talents or source.talents[spell] != target.talents[spell]:
            reject('INVALID_TALENT_OWNERSHIP', str(spell))
        for metadata in (source, target):
            row = metadata.talent_rows[spell]
            tab = metadata.stores['TalentTab'].get(row[1])
            if not tab or not tab[20] & class_mask or not mask or mask & ~((1 << groups) - 1):
                reject('INVALID_TALENT_OWNERSHIP', f'{metadata.core}: {spell}: mask={mask}')
        owners[spell] |= mask
    selected = defaultdict(list)
    for spell, mask in owners.items():
        for group in range(groups):
            if mask & (1 << group):
                selected[(tc.talents[spell][0], group)].append(spell)
    if any(len(values) > 1 for values in selected.values()):
        reject('CONFLICTING_TALENT_RANKS', 'multiple selected ranks of one talent in one specialization')
    seeds = set(stored) | set(owners)
    for metadata in (tc, ac):
        assert_acyclic(metadata, seeds)
    # Every reached relationship must agree on rank ordering. Comparing the
    # predecessor prefix allows additional *unlearned* higher target ranks.
    def compatible(spell):
        tc.check_spell(spell)
        ac.check_spell(spell)
        if tc.predecessors(spell) != ac.predecessors(spell):
            reject('INCOMPATIBLE_SPELL_CHAIN', str(spell))
        if (spell in tc.talents) != (spell in ac.talents):
            reject('INCOMPATIBLE_TALENT_CLASSIFICATION', str(spell))
        if tc.skill_effect(spell) != ac.skill_effect(spell):
            reject('INCOMPATIBLE_SKILL_EFFECT', str(spell))
        if (tc.spells[spell][4] & (PASSIVE | HIDDEN)) != (ac.spells[spell][4] & (PASSIVE | HIDDEN)):
            reject('INCOMPATIBLE_SPELL_VISIBILITY', str(spell))

    # Roots are authorized by selected talent ranks, their learn effects and
    # explicit prerequisites. Requirements constrain masks; they do not grant
    # otherwise unlearned ranks.
    authorization = defaultdict(int)
    authorization_owners = defaultdict(dict)
    queue = deque((spell,mask,spell) for spell,mask in sorted(owners.items()))
    while queue:
        spell, mask, owner = queue.popleft()
        new = mask & ~authorization_owners[spell].get(owner,0)
        if not new:
            continue
        authorization[spell] |= new
        authorization_owners[spell][owner] = authorization_owners[spell].get(owner,0) | new
        for child, _, _ in tc.effect_learns[spell]:
            queue.append((child, new, owner))
    def eligible(spell):
        root = tc.first(spell)
        if spell in tc.talents:
            return owners[spell]
        mask = authorization.get(root, 0) or authorization.get(spell, 0)
        dependencies = tc.requires[spell] | ac.requires[spell]
        if dependencies:
            required_mask = 3
            for prerequisite in dependencies:
                if prerequisite in tc.talents or authorization.get(tc.first(prerequisite), 0):
                    required_mask &= authorization.get(prerequisite, 0) or authorization.get(tc.first(prerequisite), 0)
                else:
                    # A prerequisite may be a trained spell, but it may not
                    # manufacture authorization for a talent-based ability.
                    required_mask &= 3 if prerequisite in stored else 0
            mask = (mask or 3) & required_mask
        talent_based = root in tc.talents or root in ac.additional or spell in ac.additional or bool(authorization.get(root, 0))
        return mask if talent_based or dependencies else 3

    result = {}
    temporary_spells = set()
    temporary_queue = deque(child for owner in owners for child, _, _ in ac.effect_learns[owner]
                            if child not in ac.additional)
    while temporary_queue:
        child = temporary_queue.popleft()
        if child in temporary_spells:
            continue
        temporary_spells.add(child)
        effects = [effect for effect in ac.spells[child][71:74] if effect]
        if LEARN in effects:
            if any(effect != LEARN for effect in effects):
                reject('UNSUPPORTED_TEMPORARY_LEARN_EFFECT', str(child))
            temporary_queue.extend(row[0] for row in ac.effect_learns[child])
        elif tc.predecessors(child):
            reject('UNSUPPORTED_TEMPORARY_RANK_CHAIN', str(child))
    def add(spell, mask, anchor, path, reason):
        compatible(spell)
        allowed = eligible(spell)
        # All sources of provenance may be unioned, but no source can widen
        # the verified specialization authorization.
        mask &= allowed
        if not mask:
            reject('UNAUTHORIZED_TALENT_SPELL', f'{spell}: anchor={anchor}')
        def race_class_rows(metadata, skill):
            return [r for _, r in sorted(metadata.stores['SkillRaceClassInfo'].items())
                    if r[1] == skill and (not r[2] or r[2] & race_mask) and (not r[3] or r[3] & class_mask)]
        target_skill_abilities = [ability for ability in ac.abilities[spell]
                                  if ability[1] in ac.stores['SkillLine']]
        if target_skill_abilities and not any(race_class_rows(ac, ability[1]) for ability in target_skill_abilities):
            reject('AC_WOULD_DELETE_SPELL', f'{spell}: no eligible race/class skill ability')
        effect = ac.skill_effect(spell)
        if effect:
            skill, _, minimum, maximum = effect
            if skill not in skills or skills[skill][0] < minimum or skills[skill][1] < maximum:
                reject('SPELL_WOULD_CHANGE_SKILL', f'{spell}: skill={skill}; minimum={minimum}; cap={maximum}')
            rows, source_rows = race_class_rows(ac, skill), race_class_rows(tc, skill)
            if not rows or not source_rows:
                reject('SPELL_SKILL_NOT_ELIGIBLE', f'{spell}: skill={skill}')
            if rows[0][6] and rows[0][6] not in ac.stores['SkillTiers']:
                reject('MISSING_SKILL_TIER', f'{spell}: skill={skill}')
            source_line, target_line = tc.stores['SkillLine'].get(skill), ac.stores['SkillLine'].get(skill)
            source_tier = tc.stores['SkillTiers'].get(source_rows[0][6], [0]*33)[17:33]
            target_tier = ac.stores['SkillTiers'].get(rows[0][6], [0]*33)[17:33]
            if (not source_line or not target_line or source_line[1] != target_line[1]
                    or source_rows[0][4:7] != rows[0][4:7] or source_tier != target_tier):
                reject('INCOMPATIBLE_SKILL_METADATA', f'{spell}: skill={skill}; category/flags/tier differ')
        if SKILL_STEP in ac.spells[spell][71:74]:
            reject('UNSUPPORTED_SKILL_STEP_SPELL', str(spell))
        direct = spell in tc.talents
        runtime = False
        if direct:
            row = ac.talent_rows[spell]
            persistent = bool(row[19]) and not ac.spells[spell][4] & PASSIVE and LEARN not in ac.spells[spell][71:74]
            disposition = 'PERSISTENT' if persistent else 'TALENT'
        else:
            runtime = spell in temporary_spells
            disposition = 'RUNTIME' if runtime else 'PERSISTENT'
        if disposition == 'PERSISTENT' and LEARN in ac.spells[spell][71:74]:
            reject('UNSUPPORTED_PERSISTENT_LEARN_EFFECT', str(spell))
        if direction == 'ac-to-tc':
            # TC removes alternate direct talent ranks when AddSpell runs.
            # Only the active selected rank belongs in its stored spellbook;
            # character_talent retains the other specialization's selection.
            if direct and not mask & (1 << active_group):
                disposition = 'TALENT'
            else:
                disposition = 'PERSISTENT'
        row = result.setdefault(spell, {'mask': 0, 'disposition': disposition, 'proofs': []})
        if row['disposition'] != disposition:
            reject('CONFLICTING_SPELL_REPRESENTATION', str(spell))
        row['mask'] |= mask
        proof = [anchor, path, reason]
        if proof not in row['proofs']:
            row['proofs'].append(proof)

    # Selected direct talents are legitimate ownership, not evidence that
    # their trainable higher ability ranks have been learned.
    for spell, mask in sorted(owners.items()):
        add(spell, mask, spell, [spell], 'SELECTED_TALENT')
    pending = deque()
    for spell, flags in sorted(stored.items()):
        mask = eligible(spell)
        if not mask:
            reject('UNAUTHORIZED_TALENT_SPELL', str(spell))
        if direction == 'tc-to-ac':
            active, disabled = flags
            if active not in (0, 1) or disabled not in (0, 1):
                reject('INVALID_TC_SPELL_FLAGS', str(spell))
            if disabled:
                if mask == 3 or mask & (1 << active_group) or not mask:
                    reject('UNREPRESENTABLE_DISABLED_SPELL', str(spell))
            elif not mask & (1 << active_group):
                reject('TC_SPELL_OWNERSHIP_CONFLICT', str(spell))
            if not active:
                higher = [s for s in stored if spell in tc.predecessors(s) and stored[s][0]
                          and stored[s][1] == disabled and eligible(s) & mask == mask]
                if tc.stackable(spell) or ac.stackable(spell) or not higher:
                    # Direct hidden/passive talent rows are represented by
                    # AC's talent loader, not an inferred active spell.
                    if spell not in owners or not ac.spells[spell][4] & (PASSIVE | HIDDEN):
                        reject('UNREPRESENTABLE_INACTIVE_SPELL', str(spell))
        else:
            original_mask = flags[0]
            if not original_mask or original_mask & ~3 or original_mask != mask:
                reject('UNREPRESENTABLE_AC_SPELL_MASK', f'{spell}: stored={original_mask}; eligible={mask}')
        pending.append((spell, mask, spell, [spell], 'STORED_SPELL'))
    # TC non-autolearned dependencies and active talents' learn effects are
    # legitimate runtime roots. AC either persists them or delegates them.
    for owner, mask in sorted(owners.items()):
        if {row[0] for row in tc.effect_learns[owner]} != {row[0] for row in ac.effect_learns[owner]}:
            reject('INCOMPATIBLE_TALENT_LEARN_EFFECT', str(owner))
        for child, _, _ in tc.effect_learns[owner]:
            if any(tc.spells[owner][71+i] == LEARN and tc.spells[owner][116+i] == child and tc.spells[owner][86+i] == 5
                   for i in range(3)):
                # Pet teaching effects cannot authorize a player spell.
                continue
            pending.append((child, mask, owner, [owner, child], 'TALENT_LEARN_EFFECT'))
    visited = set()
    while pending:
        spell, mask, anchor, path, reason = pending.popleft()
        key = (spell, mask, anchor)
        if key in visited:
            continue
        visited.add(key)
        add(spell, mask, anchor, path, reason)
        # Direct talent rank lists must never be expanded.
        if spell not in tc.talents:
            for previous in tc.predecessors(spell)[-1:]:
                pending.append((previous, mask, anchor, path + [previous], 'LOWER_RANK'))
        for child, child_active, auto in tc.learns[spell]:
            if not auto:
                if not any(row[0] == child for row in ac.effect_learns[spell]) and child not in tc.predecessors(spell):
                    reject('UNSUPPORTED_DEPENDENT_LEARN', f'{spell}:{child}: no verified native AC dependency')
                if not child_active and child not in tc.talents and not ac.spells[child][4] & HIDDEN:
                    reject('UNREPRESENTABLE_INACTIVE_DEPENDENCY', f'{spell}:{child}')
                pending.append((child, mask, anchor, path + [child], 'TC_DEPENDENT_LEARN'))
        # Passive non-talent learn effects run during TC loading even when
        # its world learn map is empty. Conditional aura/stance casts cannot
        # be inferred from a stored spell row alone.
        if spell not in tc.talents and tc.spells[spell][4] & PASSIVE:
            for child, _, _ in tc.effect_learns[spell]:
                if tc.spells[spell][12] or tc.spells[spell][20]:
                    reject('CONDITIONAL_DEPENDENT_LEARN', str(spell))
                if child not in {row[0] for row in ac.effect_learns[spell]}:
                    reject('UNSUPPORTED_DEPENDENT_LEARN', f'{spell}:{child}')
                if any(tc.spells[spell][71+i] == LEARN and tc.spells[spell][116+i] == child and tc.spells[spell][86+i] == 5 for i in range(3)):
                    continue
                pending.append((child,mask,anchor,path+[child],'PASSIVE_LEARN_EFFECT'))
        if len(visited) > len(tc.spells) * max(len(seeds), 1) * 3:
            reject('SPELL_TRAVERSAL_BOUND', str(spell))
    # Do not create professions/skills through skill-ability autolearning.
    for spell, row in result.items():
        for ability in ac.abilities[spell]:
            skill = ability[1]
            if (ability[9] == 2 or (skill in (633, 776) and ability[10] == 0)) and skill not in skills:
                reject('SPELL_WOULD_ADD_SKILL', f'{spell}: skill={skill}')
        row['proofs'].sort()
        row['original'] = list(stored.get(spell, ()))
        authorized_by = dict(authorization_owners.get(tc.first(spell),{}))
        authorized_by.update(authorization_owners.get(spell,{}))
        requirements = sorted(tc.requires[spell] | ac.requires[spell])
        for prerequisite in requirements:
            authorized_by.update(authorization_owners.get(prerequisite,{}))
            authorized_by.update(authorization_owners.get(tc.first(prerequisite),{}))
        row['authorization'] = {
            'policy': 'TALENT_AND_REQUIREMENT_AUTHORIZATION' if authorized_by or requirements else 'ORDINARY_BOTH_SPECS',
            'rank_root': tc.first(spell), 'owner_masks': sorted(authorized_by.items()),
            'required_spells': requirements,
        }
        row['derived'] = spell not in stored
        row['active'] = 1
        row['disabled'] = int(not row['mask'] & (1 << active_group))
        if direction == 'ac-to-tc' and not tc.stackable(spell):
            if any(spell in tc.predecessors(other) and other_row['mask'] & (1 << active_group)
                   for other, other_row in result.items()):
                row['active'] = 0
    return result


def character_rows(db, schema, direction):
    forward = direction == 'tc-to-ac'
    # Tagged records avoid large JSON aggregates and keep all three child
    # tables streamed. Strings/credentials are never selected.
    spell_fields = 'active,disabled' if forward else 'specMask,0'
    talent_mask = '(1 << talentGroup)' if forward else 'specMask'
    query = f'''
        SELECT guid,kind,a,b,c,d FROM (
          SELECT guid,0 kind,race a,class b,activeTalentGroup c,talentGroupsCount d FROM `{schema}`.characters
          UNION ALL SELECT guid,1,spell,{talent_mask},0,0 FROM `{schema}`.character_talent
          UNION ALL SELECT guid,2,skill,value,max,0 FROM `{schema}`.character_skills
          UNION ALL SELECT guid,3,spell,{spell_fields},0 FROM `{schema}`.character_spell
        ) rows_for_spells ORDER BY guid,kind,a,b,c,d;
    '''
    return db.rows('character-spell-inputs', query)


def main(args):
    db = Database(args.mysql)
    profile_bytes = Path(args.profile).read_bytes()
    profile = json.loads(profile_bytes)
    if profile.get('version') != 1:
        reject('UNSUPPORTED_SPELL_PROFILE', 'version')
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    blockers = output / 'spell-state-blockers.tsv'
    blockers.write_text('guid\tspell\treason_code\tdetail\n')
    metadata = None
    expected_hasher = hashlib.sha256()
    expected_sql = output / 'spell-expected.sql'
    expected_tsv = output / 'spell-expected.tsv'
    with expected_sql.open('w') as sql, expected_tsv.open('w') as tsv:
        tsv.write('guid\tspell\tspec_mask\tactive\tdisabled\tdisposition\tderived\tprovenance\n')
        for guid, group in itertools.groupby(character_rows(db, args.source_characters, args.direction), lambda row: int(row[0])):
            character, stored, talents, skills = None, {}, defaultdict(int), {}
            for _, kind, a, b, c, d in group:
                a, b, c, d = map(int, (a, b, c, d))
                if kind == '0':
                    character = (a, b, c, d)
                elif kind == '1':
                    talents[a] |= b
                elif kind == '2':
                    skills[a] = (b, c)
                else:
                    stored[a] = (b, c)
            if not stored and not talents:
                continue
            if character is None:
                # These rows are already covered by target orphan policy.
                # No unverifiable spell grant is made for a nonexistent player.
                continue
            try:
                if metadata is None:
                    if not args.source_world or not args.target_world or not args.tc_dbc or not args.ac_dbc:
                        reject('MISSING_SPELL_METADATA_INPUT', 'both worlds and both DBC directories are required')
                    tc_world, ac_world = ((args.source_world, args.target_world) if args.direction == 'tc-to-ac'
                                          else (args.target_world, args.source_world))
                    tc = Metadata('tc', args.tc_dbc, tc_world, profile, db)
                    ac = Metadata('ac', args.ac_dbc, ac_world, profile, db)
                    metadata = (tc, ac)
                source, target = metadata if args.direction == 'tc-to-ac' else metadata[::-1]
                rows = reconstruct(character, stored, talents, skills, source, target, args.direction)
                for spell, row in sorted(rows.items()):
                    proof = json.dumps({'original': row['original'], 'derivations': row['proofs'],
                                        'authorization': row['authorization']}, sort_keys=True, separators=(',', ':'))
                    line = '\t'.join(map(str, [guid, spell, row['mask'], row['active'], row['disabled'],
                                               row['disposition'], int(row['derived']), proof])) + '\n'
                    expected_hasher.update(line.encode())
                    tsv.write(line)
                    sql.write(f'INSERT INTO `{args.control}`.spell_expected '
                              '(run_id,guid,spell,spec_mask,active,disabled,disposition,derived,provenance) VALUES '
                              f"('{args.run_id}',{guid},{spell},{row['mask']},{row['active']},{row['disabled']},"
                              f"'{row['disposition']}',{int(row['derived'])},{sql_text(proof)});\n")
            except Unsupported as error:
                with blockers.open('a') as report:
                    report.write(f'{guid}\t*\t{error.reason}\t{str(error).replace(chr(9), " ").replace(chr(10), " ")}\n')
                # Metadata failures affect every character; repeating the
                # expensive read cannot recover and would obscure the cause.
                if metadata is None:
                    for _ in group:
                        pass
                    # Drain to finish the source digest / terminate client.
                    # The entire run is rejected; no expected SQL is imported.
                    raise
    fingerprints = {'policy': digest(POLICY.encode()), 'profile': digest(profile_bytes), **db.fingerprints}
    if metadata:
        for core in metadata:
            fingerprints.update(core.hashes)
    input_hash = digest(canonical(fingerprints))
    expected_hash = expected_hasher.hexdigest()
    (output / 'spell-fingerprints.tsv').write_text('input\tsha256\n' + ''.join(f'{key}\t{value}\n' for key, value in sorted(fingerprints.items())))
    (output / 'spell-digests.tsv').write_text(f'{input_hash}\t{expected_hash}\n')
    if len(blockers.read_text().splitlines()) > 1:
        return 1
    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for name in ['profile', 'output', 'source-characters', 'control', 'run-id', 'direction']:
        parser.add_argument('--' + name, required=True)
    for name in ['source-world', 'target-world', 'tc-dbc', 'ac-dbc']:
        parser.add_argument('--' + name, default='')
    parser.add_argument('--mysql', nargs=argparse.REMAINDER, required=True)
    options = parser.parse_args()
    try:
        sys.exit(main(options))
    except (Unsupported, ValueError, OSError, struct.error) as error:
        print(f'Spell reconstruction failed: {error}', file=sys.stderr)
        sys.exit(1)
