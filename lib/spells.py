#!/usr/bin/env python3
"""Read-only core metadata and bounded character spell reconstruction.

MySQL is accessed through the runner's existing client arguments. Only SELECT
statements are executed here; generated control/target SQL is executed by the
transactional Bash loader. Character rows are streamed in GUID order.
"""
import argparse
from collections import Counter, defaultdict, deque
import hashlib
import itertools
import json
from pathlib import Path
import struct
import subprocess
import sys

POLICY = 'spell-state-v12'
LEARN, SKILL, SKILL_STEP, DUAL_WIELD = 36, 118, 44, 40
PASSIVE, HIDDEN = 0x40, 0x80


class Unsupported(ValueError):
    def __init__(self, reason, detail):
        super().__init__(detail)
        self.reason = reason


class MetadataQueryError(RuntimeError):
    """Database access failed before spell compatibility could be established."""
    def __init__(self, label, detail):
        super().__init__(f'{label}: {detail}')
        self.label, self.detail = label, detail


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
                    raise MetadataQueryError(label, error.strip())
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
        label = f'{schema}.{table}'
        # Metadata is already materialized for relationship checks. Sort it
        # here rather than asking MySQL to filesort every column, including
        # the wide localized text fields in spell_dbc. Fingerprint the full
        # canonical rows so physical order and database collation do not affect
        # checkpoints, while same-count changes (including text) still do.
        rows = sorted(self.rows(label, f'SELECT {selected} FROM `{schema}`.`{table}`;'))
        self.fingerprints[label] = digest(canonical(rows))
        return rows


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
                        operand = record[value['field']] if isinstance(value, dict) else value
                        record[field] = {'=': lambda: operand, '|=': lambda: record[field] | operand,
                                         '&=': lambda: record[field] & operand}[op]() & 0xffffffff
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
        # Classify ownership from the complete catalog, independently of the
        # character's selections. Otherwise an unselected hidden talent child
        # can incorrectly fall through to the ordinary mask-3 policy.
        self.talent_learn_owners = defaultdict(set)
        for owner in self.talents:
            pending,visited = deque([owner]),set()
            while pending:
                parent = pending.popleft()
                if parent in visited:
                    continue
                visited.add(parent)
                pet_children = {self.spells[parent][116+i] for i in range(3)
                                if self.spells[parent][71+i] == LEARN and self.spells[parent][86+i] == 5}
                children = {row[0] for row in self.effect_learns[parent] + self.learns[parent]} - pet_children
                for child in children:
                    self.talent_learn_owners[child].add(owner)
                    pending.append(child)
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
        self.cast_only_scripts = profile.get('cast_only_scripts', {}).get(core, {})
        self.aura_talent_scripts = profile.get('aura_talent_scripts', {}).get(core, {})
        self.skill_reward_dependencies = profile.get('skill_reward_dependencies', {})
        self.persistent_world_dependencies = profile.get('persistent_world_dependencies', {})
        self.native_passive_ranks = profile.get('native_passive_ranks', {})
        self.world_talent_auras = profile.get('world_talent_auras', {})
        self.world_ranked_talent_auras = profile.get('world_ranked_talent_auras', {})
        self.consumed_teachers = profile.get('consumed_teachers', {})
        self.world_aura_owners = {child: owner for rule in (*self.world_talent_auras.values(),
                                                          *self.world_ranked_talent_auras.values())
                                  for owner,child in zip(rule['owners'],rule['children'])}
        # Trainers are exclusion evidence only, never spell-grant sources.
        self.trainer_taught = set()
        if core == 'ac':
            pending_trainers = deque()
            for row in db.table(world,'trainer_spell',['SpellId']):
                try:
                    spell = int(row[0])
                except (ValueError,TypeError,IndexError):
                    reject('INVALID_TRAINER_SPELL_METADATA',f'{world}.trainer_spell: invalid SpellId')
                if not 0 <= spell <= 0xffffffff:
                    reject('INVALID_TRAINER_SPELL_METADATA',f'{world}.trainer_spell: SpellId outside unsigned domain')
                pending_trainers.append(spell)
            while pending_trainers:
                spell = pending_trainers.popleft()
                if spell not in self.spells or spell in self.trainer_taught:
                    continue
                self.trainer_taught.add(spell)
                pending_trainers.extend(child for child,_,_ in self.effect_learns.get(spell,()))
        self.learn_parents, self.prerequisite_users = defaultdict(set), defaultdict(set)
        for parent in self.learns.keys() | self.effect_learns.keys():
            for child,_,_ in self.learns[parent] + self.effect_learns[parent]:
                self.learn_parents[child].add(parent)
        for dependent,requirements in self.requires.items():
            for required in requirements:
                self.prerequisite_users[required].add(dependent)
        self.aura_owners = defaultdict(set)
        for name,rule in self.aura_talent_scripts.items():
            for parent,entry in rule['parents'].items():
                if name in self.scripts[int(parent)]:
                    self.aura_owners[entry['child']].add(int(parent))
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
        for name in sorted(self.scripts[spell]):
            self.check_script(spell, name)

    def check_script(self, spell, name):
        """One binding's metadata contract, independent of character ownership."""
        if spell not in self.spells:
            reject('UNKNOWN_SPELL_ID', f'{self.core}: {spell}')
        record = self.spells[spell]
        if name in self.aura_talent_scripts:
            rule = self.aura_talent_scripts[name]
            entry = rule['parents'].get(str(spell),{})
            helper = self.spells.get(entry.get('child'),[])
            if (not entry or spell not in self.talents or self.talents[spell][1] != entry['rank']
                    or record[71:74] != rule['effects'] or record[95] != rule['aura']
                    or not record[4] & PASSIVE or record[12] or record[20]
                    or not helper or entry['child'] in self.talents
                    or helper[71:74] != rule['helper_effects'] or helper[95] != rule['helper_aura']
                    or helper[12] != rule['helper_stances'] or helper[20]
                    or helper[4] & (PASSIVE|HIDDEN) != HIDDEN):
                reject('UNSUPPORTED_TALENT_AURA_SCRIPT',f'{self.core}: {spell}: {name}')
        elif self.script_policy.get(name) != 'NO_SPELLBOOK_MUTATION':
            rule = self.cast_only_scripts.get(name,{})
            skill = rule.get('spell_skills',{}).get(str(spell))
            # Both native loaders leave this exact non-passive research
            # spell uncast. Passive/stance, talent and teaching variants
            # require a separate review even if they use the same script.
            if (not skill or spell in self.talents or record[4] & PASSIVE
                    or (record[4] & HIDDEN and record[12])
                    or record[71:74] != rule.get('effects')
                    or self.stores['SkillLine'].get(skill,[0,0])[1] != 11
                    or not any(row[1] == skill for row in self.abilities[spell])):
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


def script_review(metadata, stored_counts, talent_counts):
    """Inventory every binding on stored/selected IDs, including later failures.

    This is not a grant set or a source cleanup selection. Counts are per
    character, with selected groups merged. Derived-only IDs are outside scope.
    """
    rows = []
    for core in sorted(metadata, key=lambda item: item.core):
        for spell in sorted(stored_counts.keys() | talent_counts.keys()):
            for name in sorted(core.scripts.get(spell, ())):
                row = {'core': core.core, 'spell': spell, 'script': name,
                       'stored_characters': stored_counts[spell],
                       'talent_characters': talent_counts[spell],
                       'status': 'REVIEWED', 'reason_code': '', 'detail': ''}
                try:
                    core.check_script(spell, name)
                except Unsupported as error:
                    row.update(status='REVIEW_REQUIRED', reason_code=error.reason, detail=str(error))
                rows.append(row)
    return rows


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


def native_passive_rule(owner, tc, ac, cls):
    """Prove a reviewed exact-child contract; an unknown chain gets no exception."""
    family = str(tc.talents[owner][0])
    rule = tc.native_passive_ranks.get(family)
    if not rule:
        return None
    def blocked(detail):
        reject('UNSUPPORTED_NATIVE_PASSIVE_RANK',f'{owner}: {detail}')
    if rule != ac.native_passive_ranks.get(family) or cls != rule['class'] or owner not in rule['owners']:
        blocked('profile/class/selected owner contract differs')
    children = rule['children'][rule['owners'].index(owner)]
    for metadata in (tc,ac):
        for rank,parent in enumerate(rule['owners'],1):
            record = metadata.spells.get(parent,[])
            expected = rule['children'][rank-1]
            if (metadata.talents.get(parent) != (int(family),rank) or not record or record[20]
                    or sorted(r[0] for r in metadata.effect_learns[parent]) != sorted(expected)
                    or record[71:74] != rule['parent_effects']
                    or any(record[71+i] == LEARN and record[86+i] != 1 for i in range(3))):
                blocked(f'{metadata.core}: parent={parent}: talent rank, learn effect or self-target differs')
        for chain in rule['chains']:
            if metadata.chain(chain[0]) != tuple(chain):
                blocked(f'{metadata.core}: chain={chain[0]}: rank membership/order differs')
            for spell in chain:
                record = metadata.spells[spell]
                parents = {p for p,items in zip(rule['owners'],rule['children']) if spell in items}
                if (spell in metadata.talents or spell in metadata.additional
                        or record[4] & (PASSIVE|HIDDEN) != PASSIVE|HIDDEN
                        or not any(record[71:74]) or any(effect not in (0,6) for effect in record[71:74])
                        or metadata.requires[spell] or metadata.prerequisite_users[spell]
                        or spell in metadata.trainer_taught
                        or metadata.learns[spell] or metadata.effect_learns[spell]
                        or metadata.learn_parents[spell] != parents):
                    blocked(f'{metadata.core}: child={spell}: passive visibility, ownership, incoming route or dependency differs')
                trigger = rule['triggers'].get(str(chain[0]),0)
                if any(value != (trigger if i==0 else 0) for i,value in enumerate(record[116:119])):
                    blocked(f'{metadata.core}: child={spell}: proc trigger differs')
                if trigger:
                    metadata.check_spell(trigger)
                    proc = metadata.spells[trigger]
                    if (any(effect in (LEARN,SKILL,SKILL_STEP,DUAL_WIELD) for effect in proc[71:74])
                            or metadata.learns[trigger] or metadata.effect_learns[trigger]):
                        blocked(f'{metadata.core}: child={spell}: proc={trigger}: unsupported learned/skill effect')
                for ability in metadata.abilities[spell]:
                    if (ability[9] or ability[1] in (633,762,776)
                            or metadata.stores['SkillLine'].get(ability[1],[0,0])[1] != 7):
                        blocked(f'{metadata.core}: child={spell}: ability={ability[0]}: unsafe skill route')
    # The selected exact children must retain their effect/stance/state data.
    # Superseded predecessors remain uncast in AC's approved representation.
    for child in children:
        left,right = tc.spells[child],ac.spells[child]
        if left[71:119] != right[71:119] or left[12] != right[12] or left[20] != right[20]:
            blocked(f'child={child}: source/target selected effects, stance or aura state differ')
    if tc.spells[owner][71:119] != ac.spells[owner][71:119]:
        blocked('source/target selected parent effect data differ')
    for trigger in rule['triggers'].values():
        if tc.spells[trigger][71:119] != ac.spells[trigger][71:119]:
            blocked(f'proc={trigger}: source/target effect data differ')
    return rule


def world_talent_aura_rule(owner, tc, ac, cls):
    """Reviewed TC inactive known helper -> AC selected-talent aura contract.

    No spell, skill or talent ownership is inferred. Verify the entire small
    family, including Bear form callbacks and exclusion routes, before allowing
    any exact helper to be delegated. A different world relationship blocks.
    """
    family = str(tc.talents[owner][0])
    rule = tc.world_talent_auras.get(family)
    if not rule:
        return None
    def blocked(detail):
        reject('INCOMPATIBLE_WORLD_TALENT_AURA', f'{owner}: {detail}')
    if rule != ac.world_talent_auras.get(family) or cls != rule['class'] or owner not in rule['owners']:
        blocked('profile/class/selected owner differs')
    expected_bindings = set(rule['owners'] + rule['forms'])
    for metadata in (tc, ac):
        bindings = {s for s,names in metadata.scripts.items() if rule['script'] in names}
        if bindings != (expected_bindings if metadata.core == 'ac' else set()):
            blocked(f'{metadata.core}: selected-talent/form script bindings differ')
        for index,(parent,child) in enumerate(zip(rule['owners'],rule['children'])):
            p,h = metadata.spells.get(parent,[]),metadata.spells.get(child,[])
            if (metadata.talents.get(parent) != (int(family),index+1)
                    or metadata.chain(parent) != tuple(rule['owners'])
                    or not p or p[4] != rule['parent_flags'] or p[12] != rule['parent_stances']
                    or p[20] or p[71:74] != [6,0,0] or p[95:98] != [rule['parent_aura'],0,0]
                    or signed(p[80]) != rule['parent_basepoints'][index] or p[86:92] != [1,0,0,0,0,0]
                    or p[116:119] != [0,0,0] or metadata.effect_learns[parent]
                    or metadata.learns[parent] != ([(child,0,False)] if metadata.core == 'tc' else [])
                    or metadata.requires[parent] or metadata.learn_parents[parent]
                    or child in metadata.talents or metadata.chain(child) != (child,)
                    or not h or h[4] != rule['helper_flags'] or h[12] != rule['helper_stances']
                    or h[20] or h[71:74] != [6,0,0] or h[95:98] != [rule['helper_aura'],0,0]
                    or signed(h[80]) != rule['helper_basepoints'][index] or h[86:92] != [1,0,0,0,0,0]
                    or h[116:119] != [0,0,0] or metadata.scripts[child]
                    or metadata.requires[child] or metadata.prerequisite_users[child]
                    or metadata.learns[child] or metadata.effect_learns[child]
                    or metadata.learn_parents[child] != ({parent} if metadata.core == 'tc' else set())
                    or metadata.abilities[child] or child in metadata.trainer_taught
                    or parent in metadata.trainer_taught):
                blocked(f'{metadata.core}: parent={parent}, helper={child}: effects/ownership/routes differ')
            for spell,record in ((parent,p),(child,h)):
                metadata.check_spell(spell)
                if (record[74:80] != [1,0,0,0,0,0] or record[81:86] != [0,0,0,0,0]
                        or any(record[98:116]) or record[92:95] != [0,0,0]
                        or record[5:12] != (rule['parent_attributes_ex'][index] if spell == parent else rule['helper_attributes_ex'])
                        or any(record[13:20])
                        or any(record[20:28]) or any(record[31:35]) or record[36] or record[49]
                        or record[40] != rule['parent_duration' if spell == parent else 'helper_duration']
                        or record[68:71] != [0xffffffff,0,0] or any(record[119:131])
                        or metadata.scripts[spell] != ({rule['script']} if metadata.core == 'ac' and spell == parent else set())):
                    blocked(f'{metadata.core}: spell={spell}: unreviewed effect magnitude, target or script')
            # Parent skill associations are passive class associations only;
            # they must not add a skill or profession on either core.
            if any(row[1] != 134 or row[9] or row[8] for row in metadata.abilities[parent]):
                blocked(f'{metadata.core}: parent={parent}: unsafe skill route')
        for form in rule['forms']:
            r = metadata.spells.get(form,[])
            metadata.check_spell(form)
            if (not r or form in metadata.talents or r[71:74] != [6,6,0]
                    or r[95:98] != [36,77,0] or r[12] or r[20]
                    or r[110] != (5 if form == rule['forms'][0] else 8)
                    or metadata.skill_effect(form) or metadata.effect_learns[form]):
                blocked(f'{metadata.core}: form={form}: native shapeshift contract differs')
    for spell in rule['owners'] + rule['children'] + rule['forms']:
        left,right = tc.spells[spell],ac.spells[spell]
        if left[71:119] != right[71:119] or left[12] != right[12] or left[20] != right[20]:
            blocked(f'{spell}: source/target effects, stance or aura state differ')
    return rule


def ranked_world_talent_aura_rule(owner, tc, ac, cls):
    """Optional TC known-helper edges plus the reviewed exact AC aura script.

    A script-only world retains its cast-only semantics. Once a world learning
    route exists, verify the entire ranked family, including the TC prefix
    that AC deliberately does not learn. Never use that prefix as AC ownership.
    """
    family = str(tc.talents[owner][0])
    rule = tc.world_ranked_talent_auras.get(family)
    if not rule or not any(tc.learns[parent] for parent in rule['owners']):
        return None
    def blocked(detail):
        reject('INCOMPATIBLE_WORLD_TALENT_AURA', f'{owner}: {detail}')
    if rule != ac.world_ranked_talent_auras.get(family) or cls != rule['class']:
        blocked('ranked profile/class differs')
    # Attributes, stances, aura gates, proc/interrupt state, duration, item
    # requirements, effect values/targets/masks and family flags are protected.
    fields = (*range(4,28), *range(31,35), 36,40,49, *range(68,131), *range(208,212))
    for metadata in (tc,ac):
        bindings = {s for s,names in metadata.scripts.items() if rule['script'] in names}
        if bindings != set(rule['owners']):
            blocked(f'{metadata.core}: ranked script bindings differ')
        if metadata.chain(rule['children'][0]) != tuple(rule['children']):
            blocked(f'{metadata.core}: helper chain membership/order differs')
        for index,(parent,child) in enumerate(zip(rule['owners'],rule['children'])):
            if (metadata.talents.get(parent) != (int(family),index+1)
                    or metadata.chain(parent) != tuple(rule['owners'])
                    or metadata.learns[parent] != ([(child,0,False)] if metadata.core == 'tc' else [])
                    or metadata.effect_learns[parent] or metadata.learn_parents[parent]
                    or metadata.requires[parent] or parent in metadata.trainer_taught):
                blocked(f'{metadata.core}: parent={parent}: selected ownership/world route differs')
            for spell in (parent,child):
                metadata.check_spell(spell)
                record = metadata.spells[spell]
                shape = rule['mechanics'][str(spell)]
                if any(record[field] != shape.get(str(field),0) for field in fields):
                    blocked(f'{metadata.core}: spell={spell}: ranked aura mechanics differ')
                if metadata.scripts[spell] != ({rule['script']} if spell == parent else set()):
                    blocked(f'{metadata.core}: spell={spell}: unexpected script')
            if (child in metadata.talents or child in metadata.additional
                    or metadata.learn_parents[child] != ({parent} if metadata.core == 'tc' else set())
                    or metadata.learns[child] or metadata.effect_learns[child]
                    or metadata.requires[child] or metadata.prerequisite_users[child]
                    or metadata.abilities[child] or child in metadata.trainer_taught
                    or any(row[1] != 134 or row[9] or row[8] for row in metadata.abilities[parent])):
                blocked(f'{metadata.core}: helper={child}: unreviewed incoming/outgoing/skill route')
    return rule


def consumed_teacher_rule(spell, character, flags, skills, tc, ac, direction, level):
    """A verified TC wrapper becomes its load-derived buttons, without casting.

    Its original stock row remains control provenance. Reverse conversion
    preserves buttons without inventing an absent TC wrapper.
    """
    rule = tc.consumed_teachers[str(spell)]
    if direction != 'tc-to-ac' or character[3] != rule['spec_count'] or flags != (1,0):
        reject('UNREPRESENTABLE_TEACHER_STATE',
               f'{spell}: requires enabled TC stored anchor and existing {rule["spec_count"]} specs; '
               f'direction={direction}; flags={flags}; groups={character[3]}')
    def blocked(detail):
        reject('INCOMPATIBLE_CONSUMED_TEACHER',f'{spell}: {detail}')
    if rule != ac.consumed_teachers.get(str(spell)):
        blocked('source/target profile differs')
    fields = (*range(4,131), *range(208,212))
    race_mask, class_mask = 1 << (character[0]-1), 1 << (character[1]-1)
    skill_layouts = []
    for metadata in (tc,ac):
        if metadata.learns[spell] != [(child,1,False) for child in rule['children']]:
            blocked(f'{metadata.core}: effective load dependencies differ')
        if metadata.effect_learns[spell] != [(child,1,False) for child in rule['children']]:
            blocked(f'{metadata.core}: self-target teaching effects differ')
        if metadata.abilities[spell] or metadata.learn_parents[spell]:
            blocked(f'{metadata.core}: wrapper has a skill or incoming learning route')
        for member in [spell,*rule['children']]:
            metadata.check_spell(member)
            record = metadata.spells[member]
            shape = rule['mechanics'][str(member)]
            for field in fields:
                if record[field] != shape.get(str(field),0):
                    blocked(f'{metadata.core}: spell={member}: mechanic field={field} differs')
            if (member in metadata.talents or member in metadata.additional
                    or metadata.chain(member) != (member,) or metadata.scripts[member]
                    or metadata.requires[member] or metadata.prerequisite_users[member]
                    or metadata.talent_learn_owners.get(member)):
                blocked(f'{metadata.core}: spell={member}: rank/talent/script/prerequisite differs')
        for child in rule['children']:
            if metadata.learns[child] or metadata.effect_learns[child]:
                blocked(f'{metadata.core}: button={child}: unexpected outgoing learning route')
            expected = [rule['skill'],child,rule['race_mask'],rule['class_mask'],0,0,1,0,2,0,0,0,0]
            if (len(metadata.abilities[child]) != 1 or metadata.abilities[child][0][1:] != expected
                    or metadata.stores['SkillLine'].get(rule['skill'],[0,0])[1] != rule['skill_category']):
                blocked(f'{metadata.core}: button={child}: native Generic skill association differs')
        infos = sorted(tuple(row[1:7]) for row in metadata.stores['SkillRaceClassInfo'].values()
                       if row[1] == rule['skill'] and (not row[2] or row[2] & race_mask)
                       and (not row[3] or row[3] & class_mask))
        if not infos or any(row[3:] != (1170,0,0) for row in infos):
            blocked(f'{metadata.core}: native always-max Generic skill range differs')
        skill_layouts.append(infos)
    if skill_layouts[0] != skill_layouts[1]:
        blocked('source/target Generic race/class ranges differ')
    if rule['skill'] not in skills:
        reject('SPELL_WOULD_ADD_SKILL',f'{spell}: skill={rule["skill"]}; existing native Generic skill required')
    if level is None or not 1 <= level <= 80:
        reject('UNREPRESENTABLE_TEACHER_STATE',f'{spell}: verified character level in 1..80 required')
    native_skill = level * 5
    if tuple(skills[rule['skill']]) != (native_skill,native_skill):
        reject('SPELL_WOULD_CHANGE_SKILL',f'{spell}: skill={rule["skill"]}; stored={skills[rule["skill"]]}; '
               f'native level={level} requires {native_skill}/{native_skill}')
    return {'policy':'TC_KNOWN_DUAL_SPEC_TEACHER', 'children':rule['children'],
            'spec_count':rule['spec_count'], 'skill':rule['skill'],
            'level':level, 'native_skill':native_skill,
            'stored_skill':list(skills[rule['skill']]), 'source_flags':list(flags),
            'target_representation':'PERSISTENT_BUTTONS_WITH_RECORDED_WRAPPER',
            'effects_executed':False}


def reconstruct(character, stored, talents, skills, source, target, direction, level=None):
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
    consumed_teachers = {}
    aura_helpers = defaultdict(dict)
    for spell in stored:
        if (tc.aura_owners.get(spell) or ac.aura_owners.get(spell)
                or spell in tc.world_aura_owners or spell in ac.world_aura_owners):
            reject('UNSUPPORTED_AURA_HELPER_SPELL_ROW',f'{spell}: native aura/temporary state must not be persisted')
    world_aura_helpers = {}
    for owner,mask in sorted(owners.items()):
        rule = world_talent_aura_rule(owner,tc,ac,cls)
        if rule:
            child = rule['children'][rule['owners'].index(owner)]
            aura_helpers[child][owner] = mask
            world_aura_helpers[child] = {'parent':owner, 'tc_active':0, 'tc_dependent':True,
                'ac_script':rule['script'], 'form_callbacks':rule['forms'],
                'target_representation':'AC_SELECTED_TALENT_AURA' if direction == 'tc-to-ac'
                                        else 'TC_NATIVE_DEPENDENT_RESTORE',
                'native_lifetime':'SELECTED_TALENT_ACTIVE_SPEC_AND_MATCHING_FORM'}
    ranked_aura_helpers = {}
    for owner,mask in sorted(owners.items()):
        ranked_rule = ranked_world_talent_aura_rule(owner,tc,ac,cls)
        bindings = []
        for metadata in (tc,ac):
            metadata.check_spell(owner)
            bindings.append({name: metadata.aura_talent_scripts[name]['parents'][str(owner)]
                             for name in metadata.scripts[owner] if name in metadata.aura_talent_scripts})
        if bindings[0] != bindings[1]:
            reject('INCOMPATIBLE_TALENT_AURA_SCRIPT',f'{owner}: source/target bindings differ')
        for name,entry in bindings[0].items():
            child=entry['child']
            # A cast alone has no known-rank obligation. The optional reviewed
            # TC world edge also learns a prefix; AC owns the exact helper only.
            if tc.predecessors(child) != ac.predecessors(child):
                reject('INCOMPATIBLE_TALENT_AURA_SCRIPT',f'{owner}:{child}: helper ranks differ')
            aura_helpers[child][owner] = mask
            if ranked_rule:
                ranked_aura_helpers[child] = {
                    'parent':owner, 'tc_active':0, 'tc_dependent':True,
                    'tc_known_predecessors':list(tc.predecessors(child)),
                    'ac_script':name, 'target_representation':
                        'AC_NATIVE_EXACT_TEMPORARY' if direction == 'tc-to-ac' else 'TC_NATIVE_DEPENDENT_PREFIX_RESTORE',
                    'native_lifetime':'SELECTED_TALENT_ACTIVE_SPEC_HELPER_CAT_FORM',
                }
    # Determine native talent-owned runtime spells before rank compatibility.
    # AC's _addTalentAurasAndSpells uses _addSpell for the exact learned child;
    # it does not reconstruct that child's lower ranks.
    temporary_spells = set()
    native_passive_owners = defaultdict(dict)
    native_passive_catalog = {spell for rule in tc.native_passive_ranks.values()
                              for chain in rule['chains'] for spell in chain}
    for owner,mask in sorted(owners.items()):
        rule = native_passive_rule(owner,tc,ac,cls)
        if rule:
            for child in rule['children'][rule['owners'].index(owner)]:
                native_passive_owners[child][owner] = mask
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
        elif tc.predecessors(child) and child not in native_passive_owners:
            reject('UNSUPPORTED_TEMPORARY_RANK_CHAIN', str(child))
    # Every reached relationship must agree on rank ordering. Comparing the
    # predecessor prefix allows additional *unlearned* higher target ranks.
    def compatible(spell):
        tc.check_spell(spell)
        ac.check_spell(spell)
        source_prefix, target_prefix = tc.predecessors(spell), ac.predecessors(spell)
        # An AC-only rank prefix is harmless for a hidden/passive child that
        # native talents own temporarily, provided TC knows no preceding rank.
        # No persistent row or target predecessor is granted by this exception.
        runtime_exact = (spell in temporary_spells and not source_prefix
                         and bool(tc.spells[spell][4] & (PASSIVE | HIDDEN)))
        if source_prefix != target_prefix and not runtime_exact:
            reject('INCOMPATIBLE_SPELL_CHAIN',
                   f'{spell}: tc_predecessors={source_prefix}; ac_predecessors={target_prefix}; '
                   f'stored_flags={stored.get(spell)}; selected_learn_owners={sorted(authorization_owners.get(spell,{}).items())}')
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
            if any(tc.spells[spell][71+i] == LEARN and tc.spells[spell][116+i] == child
                   and tc.spells[spell][86+i] == 5 for i in range(3)):
                continue
            queue.append((child, new, owner))
    for child,helper_owners in aura_helpers.items():
        for owner,mask in helper_owners.items():
            authorization[child] |= mask
            authorization_owners[child][owner] = mask
    if direction == 'ac-to-tc':
        for child,child_owners in native_passive_owners.items():
            for previous in tc.predecessors(child):
                for owner,mask in child_owners.items():
                    authorization[previous] |= mask
                    authorization_owners[previous][owner] = authorization_owners[previous].get(owner,0) | mask
    source_passive_masks = defaultdict(int)
    passive_higher_masks = defaultdict(int)
    for child,child_owners in native_passive_owners.items():
        for mask in child_owners.values():
            source_passive_masks[child] |= mask
            for previous in tc.predecessors(child):
                source_passive_masks[previous] |= mask
                passive_higher_masks[previous] |= mask
    independent_routes = {}
    def independent_skill_routes(spell):
        """Prove a native ordinary route despite another class's talent learn.

        This authorizes only a reached known spell, never a skill-based grant.
        Existing skill values/caps are still checked by add(). Require matching
        TC/AC skill rewards, explicit class masks and trainable race/class skill
        metadata; an applicable or unknown talent owner keeps its restrictions.
        """
        if spell in independent_routes:
            return independent_routes[spell]
        independent_routes[spell] = []
        candidates = []
        for metadata in (tc,ac):
            if spell in metadata.talents or metadata.first(spell) in metadata.talents:
                return []
            catalog_owners = (metadata.talent_learn_owners.get(spell,set())
                              | metadata.talent_learn_owners.get(metadata.first(spell),set()))
            if not catalog_owners:
                return []
            for owner in catalog_owners:
                tab = metadata.stores['TalentTab'].get(metadata.talent_rows[owner][1])
                if not tab or not tab[20] or tab[20] & class_mask:
                    return []
            routes = {}
            for ability in metadata.abilities[spell]:
                if (ability[9] not in (1,2) or not ability[4] & class_mask
                        or (ability[3] and not ability[3] & race_mask)):
                    continue
                for info in metadata.stores['SkillRaceClassInfo'].values():
                    if (info[1] != ability[1] or not info[3] & class_mask
                            or (info[2] and not info[2] & race_mask) or info[4] & 0x100):
                        continue
                    # Compare all relevant relationships, including acquisition
                    # thresholds and trainability, rather than only table IDs.
                    key = tuple(ability[1:10] + info[1:7])
                    routes[key] = [metadata.core,ability[0],info[0],ability[1],ability[9],ability[7],info[4]]
            candidates.append(routes)
        common = sorted(candidates[0].keys() & candidates[1].keys())
        independent_routes[spell] = [routes[key] for key in common for routes in candidates]
        return independent_routes[spell]

    def talent_restricted(spell, include_requirements=True):
        ordinary_route = independent_skill_routes(spell)
        return any(spell in metadata.talents or metadata.first(spell) in metadata.talents
                   or ((metadata.talent_learn_owners.get(spell)
                        or metadata.talent_learn_owners.get(metadata.first(spell))) and not ordinary_route)
                   or metadata.aura_owners.get(spell)
                   or (include_requirements and (spell in metadata.additional
                                                or metadata.first(spell) in metadata.additional))
                   for metadata in (tc,ac))
    ordinary_training_requirements = {}
    def training_only_requirements(spell):
        """Native loaders preserve known ordinary spells without learning prerequisites.

        AC GetLearnSpellSpecMask returns BOTH before inspecting requirements for
        ordinary spells. Keep every talent-linked relationship on the existing
        strict authorization path, including indirect prerequisite ancestry.
        """
        if spell in ordinary_training_requirements:
            return ordinary_training_requirements[spell]
        requirements = tc.requires[spell] | ac.requires[spell]
        ordinary_training_requirements[spell] = None
        if not requirements or talent_restricted(spell):
            return None
        pending = [(required,False) for required in sorted(requirements)]
        visited, visiting = set(), set()
        while pending:
            required, leaving = pending.pop()
            if leaving:
                visiting.discard(required)
                visited.add(required)
                continue
            if required in visiting:
                reject('CYCLIC_SPELL_RELATIONSHIP',str(required))
            if required in visited:
                continue
            if talent_restricted(required):
                return None
            visiting.add(required)
            pending.append((required,True))
            pending.extend((parent,False) for parent in sorted(tc.requires[required] | ac.requires[required]))
            if len(visiting) > max(len(tc.spells),len(ac.spells)):
                reject('SPELL_TRAVERSAL_BOUND',str(spell))
        proof = {'policy':'NATIVE_ORDINARY_KNOWN_STATE',
                 'tc_required_spells':sorted(tc.requires[spell]),
                 'ac_required_spells':sorted(ac.requires[spell]),
                 'ordinary_ancestry':sorted(visited),
                 'missing_from_known_state':sorted(requirements - known_rank_prefix),
                 'prerequisites_granted':False}
        ordinary_training_requirements[spell] = proof
        return proof

    def eligible(spell):
        if spell in aura_helpers or spell in native_passive_catalog:
            # Native ownership follows the exact selected child, not another
            # rank selected in the other spec. Reverse authorization may also
            # include the TC-only prefix explicitly restored above.
            return authorization.get(spell, 0)
        root = tc.first(spell)
        if spell in tc.talents:
            return owners.get(spell,0)
        mask = authorization.get(root, 0) or authorization.get(spell, 0)
        dependencies = tc.requires[spell] | ac.requires[spell]
        if training_only_requirements(spell):
            return 3
        if dependencies:
            required_mask = 3
            for prerequisite in dependencies:
                if talent_restricted(prerequisite):
                    required_mask &= authorization.get(prerequisite, 0) or authorization.get(tc.first(prerequisite), 0)
                else:
                    # A prerequisite may be a trained spell, but it may not
                    # manufacture authorization for a talent-based ability.
                    # TC may persist only a higher rank of this prerequisite.
                    # Count its verified known prefix, not just stored rows.
                    required_mask &= 3 if prerequisite in known_rank_prefix else 0
            # A talent requirement can itself authorize an otherwise ordinary
            # spell. Ordinary prerequisites cannot authorize an unowned talent
            # or learned child just because they are known.
            fallback = 0 if talent_restricted(spell,include_requirements=False) else 3
            mask = (mask or fallback) & required_mask
        talent_based = talent_restricted(spell)
        return mask if talent_based or dependencies else 3

    known_rank_prefix = set(stored)
    for anchor in stored:
        if anchor not in tc.talents:
            # Do not use a source-only relationship to authorize anything.
            # Direct talent rank lists never establish lower talent ownership.
            compatible(anchor)
            known_rank_prefix.update(tc.predecessors(anchor))

    skill_delegates = defaultdict(list)
    for parent,flags in sorted(stored.items()):
        rule = tc.skill_reward_dependencies.get(str(parent))
        if not rule or eligible(parent) != 3 or cls != 6:
            continue
        if tc.spells[parent][71:74] != rule['parent_effects'] or ac.spells[parent][71:74] != rule['parent_effects']:
            continue
        for child,active,auto in tc.learns[parent]:
            if child not in rule['children'] or not active or auto:
                continue
            pairs = []
            for metadata in (tc,ac):
                if metadata.spells[child][71:74] != rule['child_effects']:
                    break
                abilities = [a for a in metadata.abilities[child]
                             if a[1] == rule['skill'] and a[4] == rule['class_mask']
                             and (not a[3] or a[3] & race_mask) and a[9] == rule['acquire']
                             and a[7] == rule['minimum'] and not a[8]]
                pairs.append({tuple(a[1:12]):a[0] for a in sorted(abilities)})
            if len(pairs) != 2:
                continue
            for relationship in sorted(pairs[0].keys() & pairs[1].keys()):
                skill_delegates[child].append({'parent':parent,'skill':rule['skill'],
                    'value':rule['value'],'max':rule['max'],'tc_ability':pairs[0][relationship],
                    'ac_ability':pairs[1][relationship],'acquire':rule['acquire'],'minimum':rule['minimum']})

    persistent_dependencies = defaultdict(list)
    def persistent_world_dependency(parent, child):
        rule = tc.persistent_world_dependencies.get(str(parent))
        if (not rule or rule != ac.persistent_world_dependencies.get(str(parent))
                or child != rule['child'] or cls != rule['class']
                or talent_restricted(parent) or talent_restricted(child)
                or eligible(parent) != 3 or eligible(child) != 3
                or tc.learns[parent].count((child,1,False)) != 1):
            return False
        ranks = rule['ranks']
        for metadata in (tc,ac):
            if (metadata.spells[parent][71:74] != rule['parent_effects']
                    or metadata.spells[parent][95:98] != rule['parent_auras']
                    or metadata.spells[parent][4] & (PASSIVE|HIDDEN)
                    or metadata.skill_effect(parent) is not None
                    or list(metadata.predecessors(child)) + [child] != ranks
                    or metadata.stores['SkillLine'].get(rule['skill'],[0,0])[1] != rule['skill_category']):
                return False
            for step,rank in enumerate(ranks,1):
                if (metadata.spells[rank][71:74] != rule['child_effects']
                        or metadata.skill_effect(rank) != (rule['skill'],step,step*75,step*75)
                        or rank in metadata.talents
                        or metadata.spells[rank][4] & (PASSIVE|HIDDEN) != rule['child_visibility']
                        or rank in temporary_spells or rank in aura_helpers
                        or talent_restricted(rank) or eligible(rank) != 3):
                    return False
        skill = rule['skill']
        if skill not in skills:
            reject('SPELL_WOULD_ADD_SKILL',f'{parent}:{child}: existing riding skill={skill} required')
        if (list(skills[skill]) not in rule['skill_states']
                or (skills[skill][0] > 225 and rule['higher_anchor'] not in known_rank_prefix)):
            reject('SPELL_WOULD_CHANGE_SKILL',f'{parent}:{child}: skill={skill}; stored={skills[skill]}; '
                   'requires riding 225/225 or 300/300 with a known higher riding anchor')
        proof = {'parent':parent,'child':child,'policy':'TC_WORLD_LOAD_PERSISTENT_RIDING',
                 'skill':skill,'skill_category':rule['skill_category'],
                 'stored_skill':list(skills[skill]),'ranks':ranks}
        if proof not in persistent_dependencies[child]:
            persistent_dependencies[child].append(proof)
        return True

    inactive_skill_proofs = {}
    def inactive_dual_wield(spell, mask):
        """An inactive Shaman talent does not load its child or create a skill.

        This is deliberately limited to the stock 30798 -> 674 relationship.
        Stored child rows, active/shared ownership and other skill effects keep
        the normal preservation checks. Both native talent loaders defer the
        inactive build; switching specs remains the cores' responsibility.
        """
        if (spell != 674 or cls != 7 or groups != 2 or spell in stored or 118 in skills
                or mask != 1 << (1 - active_group) or owners.get(30798) != mask):
            return None
        if spell not in temporary_spells or authorization_owners.get(spell) != {30798:mask}:
            reject('INCOMPATIBLE_INACTIVE_TALENT_SKILL', '30798:674: native child authorization differs')
        for metadata in (tc,ac):
            parent, child = metadata.spells[30798], metadata.spells[674]
            if (metadata.talents.get(30798) != (1690,1)
                    or parent[71:74] != [LEARN,0,0] or parent[116:119] != [674,0,0]
                    or parent[86:92] != [1,0,0,0,0,0]
                    or child[4:13] != [80,0,0,0,0,0,0,0,0]
                    or child[71:74] != [DUAL_WIELD,0,0]
                    or child[86:98] != [1,0,0,0,0,0,0,0,0,0,0,0]
                    or any(child[110:119]) or metadata.skill_effect(674) != (118,1,1,1)
                    or metadata.stores['SkillLine'].get(118,[0,0])[1] != 6
                    or metadata.scripts[30798] or metadata.scripts[674]
                    or metadata.predecessors(30798) or metadata.predecessors(674)
                    or metadata.requires[30798] or metadata.requires[674]
                    or metadata.learns[674] or 674 in metadata.additional
                    or metadata.aura_owners.get(674)
                    or metadata.learns[30798] != [(674,True,True)]):
                reject('INCOMPATIBLE_INACTIVE_TALENT_SKILL', '30798:674: native Dual Wield contract differs')
        proof = {'policy':'NATIVE_INACTIVE_DUAL_WIELD', 'parent':30798, 'child':674,
                 'owner_mask':mask, 'active_spec':active_group, 'skill':118,
                 'skill_present':False, 'skill_granted':False,
                 'target_representation':'NATIVE_ON_SPEC_ACTIVATION'}
        inactive_skill_proofs[spell] = proof
        return proof

    # Validate the selected parent even if a changed pet-target/learn relation
    # would prevent its child from reaching add(). No changed relationship may
    # silently turn a reviewed runtime child into an omitted spell.
    inactive_dual_wield(674,owners.get(30798,0))
    result = {}
    def add(spell, mask, anchor, path, reason):
        compatible(spell)
        if str(spell) in tc.consumed_teachers and spell not in consumed_teachers:
            consumed_teachers[spell] = consumed_teacher_rule(
                spell,character,stored.get(spell,()),skills,tc,ac,direction,level)
        allowed = eligible(spell)
        # All sources of provenance may be unioned, but no source can widen
        # the verified specialization authorization.
        mask &= allowed
        if not mask:
            reject('UNAUTHORIZED_TALENT_SPELL', f'{spell}: anchor={anchor}')
        inactive_skill = inactive_dual_wield(spell,mask)
        for metadata in (tc,ac):
            for script in metadata.scripts[spell]:
                skill = metadata.cast_only_scripts.get(script,{}).get('spell_skills',{}).get(str(spell))
                if skill and (skill not in skills or min(skills[skill]) <= 0):
                    reject('RESEARCH_SKILL_MISSING',f'{spell}: skill={skill}; existing profession required')
        def race_class_rows(metadata, skill):
            return [r for _, r in sorted(metadata.stores['SkillRaceClassInfo'].items())
                    if r[1] == skill and (not r[2] or r[2] & race_mask) and (not r[3] or r[3] & class_mask)]
        target_skill_abilities = [ability for ability in ac.abilities[spell]
                                  if ability[1] in ac.stores['SkillLine']]
        if target_skill_abilities and not any(race_class_rows(ac, ability[1]) for ability in target_skill_abilities):
            reject('AC_WOULD_DELETE_SPELL', f'{spell}: no eligible race/class skill ability')
        if any(ability[1] == 776 for ability in ac.abilities[spell]):
            # Both native skill loaders normalize Runeforging's mono range
            # to 1/1; some addSpell paths also call LearnDefaultSkill. Refuse
            # nonstandard stored state instead of relying on that correction.
            if 776 not in skills:
                reject('SPELL_WOULD_ADD_SKILL',f'{spell}: skill=776')
            layouts = []
            for metadata in (tc,ac):
                infos = race_class_rows(metadata,776)
                line = metadata.stores['SkillLine'].get(776)
                if (not line or line[1] != 7 or not infos
                        or any(info[6] in metadata.stores['SkillTiers'] for info in infos)):
                    reject('INCOMPATIBLE_SKILL_METADATA',f'{spell}: skill=776; expected mono Runeforging metadata')
                layouts.append(sorted(tuple(info[1:7]) for info in infos))
            if layouts[0] != layouts[1]:
                reject('INCOMPATIBLE_SKILL_METADATA',f'{spell}: skill=776; race/class metadata differ')
            if tuple(skills[776]) != (1,1):
                reject('SPELL_WOULD_CHANGE_SKILL',f'{spell}: skill=776; native value=1; cap=1; stored={skills[776]}')
        effect = ac.skill_effect(spell)
        if effect:
            skill, _, minimum, maximum = effect
            if not inactive_skill and (skill not in skills or skills[skill][0] < minimum or skills[skill][1] < maximum):
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
            disposition = ('AURA' if spell in aura_helpers else 'SKILL' if spell in skill_delegates
                           else 'RUNTIME' if runtime else 'PERSISTENT')
        if spell in consumed_teachers:
            disposition = 'TEACHER'
        if disposition == 'PERSISTENT' and LEARN in ac.spells[spell][71:74]:
            reject('UNSUPPORTED_PERSISTENT_LEARN_EFFECT', str(spell))
        if direction == 'ac-to-tc' and spell in source_passive_masks:
            # Store only an active exact child. TC restores its prefix itself;
            # an inactive higher row could disable an active lower rank during
            # AddSpell loading. Other selected specs restore through their
            # unchanged talent rows when natively activated.
            exact_mask = 0
            for owner_mask in native_passive_owners.get(spell,{}).values():
                exact_mask |= owner_mask
            disposition = 'PERSISTENT' if exact_mask & (1 << active_group) else 'RUNTIME'
        elif direction == 'ac-to-tc' and disposition not in ('SKILL','AURA'):
            # TC removes alternate direct talent ranks when AddSpell runs.
            # Only the active selected rank belongs in its stored spellbook;
            # character_talent retains the other specialization's selection.
            if direct and not mask & (1 << active_group):
                disposition = 'TALENT'
            else:
                disposition = 'PERSISTENT'
        if inactive_skill:
            disposition = 'RUNTIME'
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
        source_mask = source_passive_masks.get(spell,mask) if direction == 'tc-to-ac' else mask
        if not source_mask:
            root = tc.first(spell)
            family = tc.talents.get(spell,tc.talents.get(root))
            selected_family = [(s,m) for s,m in sorted(owners.items())
                               if m and family and tc.talents[s][0] == family[0]]
            required = tc.requires[spell] | ac.requires[spell]
            reason = ('UNAUTHORIZED_TALENT_SPELL' if talent_restricted(spell)
                      or any(talent_restricted(parent) for parent in required)
                      else 'MISSING_SPELL_PREREQUISITE')
            reject(reason,
                   f'{spell}: stored_flags={flags}; rank_root={root}; selected_same_talent={selected_family}; '
                   f'eligible_mask=0; required_spells={sorted(required)}; '
                   f'known_prerequisites={sorted(required & known_rank_prefix)}')
        if direction == 'tc-to-ac':
            active, disabled = flags
            if active not in (0, 1) or disabled not in (0, 1):
                reject('INVALID_TC_SPELL_FLAGS', str(spell))
            if disabled:
                if source_mask == 3 or source_mask & (1 << active_group) or not source_mask:
                    reject('UNREPRESENTABLE_DISABLED_SPELL', str(spell))
            elif not source_mask & (1 << active_group):
                reject('TC_SPELL_OWNERSHIP_CONFLICT', str(spell))
            if not active:
                higher = [s for s in stored if spell in tc.predecessors(s) and stored[s][0]
                          and stored[s][1] == disabled and eligible(s) & mask == mask]
                superseded_mask = source_mask if disabled else 1 << active_group
                native_superseded = (spell in source_passive_masks
                                     and passive_higher_masks[spell] & superseded_mask == superseded_mask)
                if tc.stackable(spell) or ac.stackable(spell) or (not higher and not native_superseded):
                    # Direct hidden/passive talent rows are represented by
                    # AC's talent loader, not an inferred active spell.
                    if spell not in owners or not ac.spells[spell][4] & (PASSIVE | HIDDEN):
                        reject('UNREPRESENTABLE_INACTIVE_SPELL', str(spell))
            if not mask and spell in source_passive_masks:
                # Approved TC-only predecessor. Its exact source row and masks
                # are retained on the owning native child's provenance below.
                continue
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
    for child,helper_owners in sorted(aura_helpers.items()):
        for owner,mask in sorted(helper_owners.items()):
            pending.append((child,mask,owner,[owner,child],
                            'TC_WORLD_RANKED_TALENT_AURA' if child in ranked_aura_helpers else
                            'TC_WORLD_TALENT_AURA' if child in world_aura_helpers else 'NATIVE_TALENT_AURA'))
    visited = set()
    while pending:
        spell, mask, anchor, path, reason = pending.popleft()
        key = (spell, mask, anchor)
        if key in visited:
            continue
        visited.add(key)
        add(spell, mask, anchor, path, reason)
        if spell in aura_helpers:
            # Cast-only helpers have no TC known-rank obligation. Reviewed
            # world helpers have verified singleton/exact-rank contracts and
            # no outgoing routes; their TC-only prefixes remain native-owned.
            continue
        # Direct talent rank lists must never be expanded.
        if spell not in tc.talents and not (direction == 'tc-to-ac' and spell in native_passive_owners):
            for previous in tc.predecessors(spell)[-1:]:
                pending.append((previous, mask, anchor, path + [previous], 'LOWER_RANK'))
        for child, child_active, auto in tc.learns[spell]:
            if not auto:
                skill_reward = any(r['parent'] == spell for r in skill_delegates.get(child,[]))
                native = any(row[0] == child for row in ac.effect_learns[spell]) or child in tc.predecessors(spell) or skill_reward
                world_aura = child in world_aura_helpers and world_aura_helpers[child]['parent'] == spell
                ranked_aura = child in ranked_aura_helpers and ranked_aura_helpers[child]['parent'] == spell
                native = native or world_aura or ranked_aura
                persistent = not native and persistent_world_dependency(spell,child)
                if not native and not persistent:
                    reject('UNSUPPORTED_DEPENDENT_LEARN', f'{spell}:{child}: no verified native AC dependency')
                if not child_active and child not in tc.talents and not ac.spells[child][4] & HIDDEN:
                    reject('UNREPRESENTABLE_INACTIVE_DEPENDENCY', f'{spell}:{child}')
                pending.append((child, mask, anchor, path + [child],
                                'TC_WORLD_RANKED_TALENT_AURA' if ranked_aura else
                                'TC_WORLD_TALENT_AURA' if world_aura else
                                'TC_WORLD_PERSISTENT_DEPENDENCY' if persistent else 'TC_DEPENDENT_LEARN'))
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
        for ability in ac.abilities[spell] if spell not in inactive_skill_proofs else ():
            skill = ability[1]
            if (ability[9] == 2 or (skill in (633, 776) and ability[10] == 0)) and skill not in skills:
                reject('SPELL_WOULD_ADD_SKILL', f'{spell}: skill={skill}')
        row['proofs'].sort()
        row['original'] = list(stored.get(spell, ()))
        authorized_by = ({} if spell in aura_helpers else
                         dict(authorization_owners.get(tc.first(spell),{})))
        authorized_by.update(authorization_owners.get(spell,{}))
        if spell in native_passive_owners:
            authorized_by = dict(authorization_owners[spell])
        requirements = sorted(tc.requires[spell] | ac.requires[spell])
        for prerequisite in requirements:
            authorized_by.update(authorization_owners.get(prerequisite,{}))
            authorized_by.update(authorization_owners.get(tc.first(prerequisite),{}))
        row['authorization'] = {
            'policy': 'TALENT_AND_REQUIREMENT_AUTHORIZATION' if authorized_by or requirements else 'ORDINARY_BOTH_SPECS',
            'rank_root': tc.first(spell), 'owner_masks': sorted(authorized_by.items()),
            'required_spells': requirements,
        }
        if spell in inactive_skill_proofs:
            row['authorization']['policy'] = 'NATIVE_INACTIVE_TALENT_SKILL'
            row['authorization']['inactive_talent_skill'] = inactive_skill_proofs[spell]
        training = training_only_requirements(spell)
        if training:
            row['authorization']['policy'] = 'ORDINARY_TRAINING_PREREQUISITES'
            row['authorization']['training_prerequisites'] = training
        routes = independent_skill_routes(spell)
        if routes:
            row['authorization']['policy'] = 'ORDINARY_SKILL_AUTHORIZATION'
            row['authorization']['independent_skill_routes'] = routes
        if spell in skill_delegates:
            row['authorization']['policy'] = 'NATIVE_SKILL_REWARD'
            row['authorization']['native_skill_rewards'] = skill_delegates[spell]
        if spell in aura_helpers:
            row['authorization']['policy'] = 'NATIVE_TALENT_AURA'
            row['authorization']['aura_owners'] = sorted(aura_helpers[spell].items())
        if spell in world_aura_helpers:
            row['authorization']['policy'] = 'TC_WORLD_NATIVE_TALENT_AURA'
            row['authorization']['world_talent_aura'] = world_aura_helpers[spell]
        if spell in ranked_aura_helpers:
            row['authorization']['policy'] = 'TC_WORLD_NATIVE_RANKED_TALENT_AURA'
            row['authorization']['ranked_world_talent_aura'] = ranked_aura_helpers[spell]
        if spell in consumed_teachers:
            row['authorization']['policy'] = 'CONSUMED_DUAL_SPEC_TEACHER'
            row['authorization']['consumed_teacher'] = consumed_teachers[spell]
        teacher_sources = [parent for parent,proof in consumed_teachers.items() if spell in proof['children']]
        if teacher_sources:
            row['authorization']['consumed_teacher_sources'] = teacher_sources
        if spell in persistent_dependencies:
            row['authorization']['persistent_world_dependencies'] = sorted(
                persistent_dependencies[spell],key=lambda item:(item['parent'],item['child']))
        if spell in native_passive_owners:
            row['authorization']['native_passive_rank'] = {
                'policy':'NATIVE_AC_EXACT_PASSIVE_RANK',
                'owner_masks':sorted(native_passive_owners[spell].items()),
                'tc_predecessors':list(tc.predecessors(spell)),
                'tc_known_mask':source_passive_masks[spell],
                'stored_predecessors':[[previous,*stored[previous]] for previous in tc.predecessors(spell)
                                       if previous in stored],
                'target_predecessors_persisted':any(result[p]['disposition']=='PERSISTENT'
                    for p in tc.predecessors(spell) if p in result),
                'target_representation':'AC_NATIVE_EXACT' if direction == 'tc-to-ac' else 'TC_ACTIVE_EXACT_NATIVE_PREFIX',
                'native_lifetime':'SELECTED_TALENT_AND_ACTIVE_SPEC',
            }
        aura_contracts = sorted(
            (metadata.core,name,metadata.aura_talent_scripts[name]['mode'],
             metadata.aura_talent_scripts[name]['parents'][str(spell)]['child'])
            for metadata in (tc,ac) for name in metadata.scripts[spell]
            if name in metadata.aura_talent_scripts)
        if aura_contracts:
            row['authorization']['aura_script_contracts'] = aura_contracts
        load_contracts = sorted(
            (metadata.core,name,'CAST_ONLY_RESEARCH_EXISTING_SKILL',
             metadata.cast_only_scripts[name]['spell_skills'][str(spell)])
            for metadata in (tc,ac) for name in metadata.scripts[spell]
            if str(spell) in metadata.cast_only_scripts.get(name,{}).get('spell_skills',{}))
        if load_contracts:
            row['authorization']['load_script_contracts'] = load_contracts
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
          UNION ALL SELECT guid,4,level,0,0,0 FROM `{schema}`.characters
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
    review_path = output / 'spell-script-review.json'
    review = {'status': 'INCOMPLETE',
              'scope': 'Bindings on stored spell and selected talent IDs of existing source characters; '
                       'excludes derived-only IDs; metadata contract only, not ownership or cleanup approval',
              'bindings': []}
    review_path.write_text(json.dumps(review, indent=2, sort_keys=True) + '\n')
    stored_counts, talent_counts = Counter(), Counter()
    metadata = None
    expected_hasher = hashlib.sha256()
    expected_sql = output / 'spell-expected.sql'
    expected_tsv = output / 'spell-expected.tsv'
    with expected_sql.open('w') as sql, expected_tsv.open('w') as tsv:
        tsv.write('guid\tspell\tspec_mask\tactive\tdisabled\tdisposition\tderived\tprovenance\n')
        for guid, group in itertools.groupby(character_rows(db, args.source_characters, args.direction), lambda row: int(row[0])):
            character, level, stored, talents, skills = None, None, {}, defaultdict(int), {}
            for _, kind, a, b, c, d in group:
                a, b, c, d = map(int, (a, b, c, d))
                if kind == '0':
                    character = (a, b, c, d)
                elif kind == '1':
                    talents[a] |= b
                elif kind == '2':
                    skills[a] = (b, c)
                elif kind == '4':
                    level = a
                else:
                    stored[a] = (b, c)
            if not stored and not talents:
                continue
            if character is None:
                # These rows are already covered by target orphan policy.
                # No unverifiable spell grant is made for a nonexistent player.
                continue
            stored_counts.update(stored.keys())
            talent_counts.update(talents.keys())
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
                rows = reconstruct(character, stored, talents, skills, source, target, args.direction, level=level)
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
    review.update(status='COMPLETE', input_sha256=input_hash,
                  bindings=script_review(metadata or (), stored_counts, talent_counts))
    review_path.write_text(json.dumps(review, indent=2, sort_keys=True) + '\n')
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
    except MetadataQueryError as error:
        detail = error.detail.replace('\t', ' ').replace('\n', ' ')
        (Path(options.output) / 'spell-metadata-errors.tsv').write_text(
            'input\treason_code\tdetail\n'
            f'{error.label}\tSPELL_METADATA_QUERY_FAILED\t{detail}\n')
        print(f'Spell metadata read failed: {error}', file=sys.stderr)
        sys.exit(2)
    except (Unsupported, ValueError, OSError, struct.error) as error:
        print(f'Spell reconstruction failed: {error}', file=sys.stderr)
        sys.exit(1)
