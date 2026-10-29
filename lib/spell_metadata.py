"""Read-only MySQL and DBC metadata with deterministic fingerprints."""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Iterator, Sequence
import hashlib
import itertools
from pathlib import Path
import struct
import subprocess
from typing import Any

from cleanup_types import DbcStores, Evidence, MetadataReader
from spell_common import (
    DUAL_WIELD,
    HIDDEN,
    LEARN,
    MetadataQueryError,
    PASSIVE,
    SKILL,
    SKILL_STEP,
    canonical,
    digest,
    read_dbc,
    reject,
    signed,
)


class Database:
    """Stream read-only MySQL rows and fingerprint complete query results."""

    arguments: Sequence[str]
    fingerprints: dict[str, str]

    def __init__(self, arguments: Sequence[str]) -> None:
        self.arguments = arguments
        self.fingerprints = {}

    def rows(self, label: str, query: str) -> Iterator[list[str]]:
        hasher = hashlib.sha256()
        # Do not print arguments: option files may contain authentication data.
        # Escaped batch output keeps tabs/newlines in ignored localized DBC
        # strings from corrupting record boundaries. Script identifiers use
        # the protected ASCII names; numeric source rows need no decoding.
        with subprocess.Popen(['mysql', *self.arguments, '--batch',
            '--skip-raw',
            '--skip-column-names', '--quick'],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE) as process:
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

    def table(
        self,
        schema: str,
        table: str,
        columns: list[str],
        optional: bool = False,
    ) -> list[list[Any]]:
        present = list(self.rows(f'{schema}.{table}.present',
            'SELECT COUNT(*) FROM information_schema.TABLES WHERE '
            f"TABLE_SCHEMA='{schema}' AND TABLE_NAME='{table}' AND "
            "TABLE_TYPE='BASE TABLE';"))
        if present != [['1']]:
            if optional:
                return []
            reject('MISSING_SPELL_METADATA_TABLE', f'{schema}.{table}')
        layout = list(self.rows(f'{schema}.{table}.layout',
            'SELECT COLUMN_NAME,COLUMN_TYPE,IS_NULLABLE,ORDINAL_POSITION '
            "FROM information_schema.COLUMNS WHERE TABLE_SCHEMA='"
            f"{schema}' AND TABLE_NAME='{table}' ORDER BY "
            'ORDINAL_POSITION;'))
        if table.endswith('_dbc') and [row[0] for row in layout] != columns:
            reject('INCOMPATIBLE_DBC_OVERLAY',
                f'{schema}.{table}: ordered columns differ from pinned '
                'AC reader')
        # Names come exclusively from the protected profile layout.
        selected = ','.join('`' + name + '`' for name in columns)
        label = f'{schema}.{table}'
        # Metadata is already materialized for relationship checks. Sort it
        # here rather than asking MySQL to filesort every column, including
        # the wide localized text fields in spell_dbc. Fingerprint the full
        # canonical rows so physical order and database collation do not affect
        # checkpoints, while same-count changes (including text) still do.
        rows = sorted(self.rows(label,
            f'SELECT {selected} FROM `{schema}`.`{table}`;'))
        self.fingerprints[label] = digest(canonical(rows))
        return rows


class Metadata:
    """Effective DBC and world metadata for one reviewed core."""

    abilities: dict[int, list[list[int]]]
    additional: set[int]
    aura_owners: dict[int, set[int]]
    aura_talent_scripts: Evidence
    cast_only_scripts: Evidence
    chains: dict[int, tuple[int, ...]]
    consumed_teachers: Evidence
    core: str
    correction_guards: dict[int, list[Evidence]]
    effect_learns: dict[int, list[tuple[int, int, int]]]
    hashes: dict[str, str]
    invalid_talents: set[int]
    learn_parents: dict[int, set[int]]
    learns: dict[int, list[tuple[int, int]]]
    native_passive_ranks: Evidence
    ordinary_teachers: Evidence
    persistent_world_dependencies: Evidence
    position: dict[int, tuple[int, int]]
    prerequisite_users: dict[int, set[int]]
    requires: dict[int, set[int]]
    script_policy: dict[str, str]
    scripts: dict[int, set[str]]
    skill_reward_dependencies: Evidence
    spells: dict[int, list[int]]
    stores: DbcStores
    talent_learn_owners: dict[int, set[int]]
    talent_rows: dict[int, list[int]]
    talents: dict[int, tuple[int, int]]
    trainer_taught: set[int]
    world: str
    world_aura_owners: dict[int, int]
    world_ranked_talent_auras: Evidence
    world_talent_auras: Evidence

    def __init__(
        self,
        core: str,
        dbc_dir: str | Path,
        world: str,
        profile: Evidence,
        db: MetadataReader,
    ) -> None:
        self.core, self.world = core, world
        self._load_stores(dbc_dir, profile, db)
        self._load_talents(profile)
        self._load_chains(db)
        self._load_requirements(db)
        self._load_learning_routes(db)
        self._load_skill_abilities()
        self._load_scripts(profile, db)
        self._load_native_consumers(db)
        self._load_custom_attributes(db)

    def _load_stores(
        self,
        dbc_dir: str | Path,
        profile: Evidence,
        db: MetadataReader,
    ) -> None:
        self.stores, self.hashes = {}, {}
        for name, layout in profile['stores'].items():
            path = Path(dbc_dir) / (name + '.dbc')
            try:
                records, sha = read_dbc(path, layout['formats'][self.core])
            except OSError:
                reject('MISSING_DBC', f'{self.core}: {name}.dbc')
            self.hashes[f'{self.core}.{name}.dbc'] = sha
            if self.core == 'ac':
                rows = db.table(self.world, layout['table'], layout['columns'])
                for row in rows:
                    # Only numeric fields affect this transform. Float bits are
                    # kept for layout fidelity; strings are deliberately
                    # ignored.
                    record = [0] * len(row)
                    for i, (value, fmt) in enumerate(zip(row, layout[
                        'formats'][self.core])):
                        if fmt == 'f':
                            record[i] = (struct.unpack('<I', struct.pack('<f',
                                float(value)))[0])
                        elif fmt not in 'sxX':
                            record[i] = int(value) & 0xffffffff
                    records[record[0]] = record
            elif name == 'Spell':
                # TC custom entries are additions, never replacements (its
                # DBCDatabaseLoader aborts on duplicate DBC IDs).
                sql_fmt = profile['tc_spell_sql_format']
                positions = ([i for i, value in enumerate(sql_fmt) if value
                    == 'p'])
                # SELECT * matches the pinned TC reader; validate its width.
                list(db.rows('tc.spell_dbc.layout',
                    'SELECT '
                    'COLUMN_NAME,COLUMN_TYPE,IS_NULLABLE,ORDINAL_POSITION '
                    "FROM information_schema.COLUMNS WHERE TABLE_SCHEMA='"
                    f"{self.world}' AND TABLE_NAME='spell_dbc' ORDER BY "
                    'ORDINAL_POSITION;'))
                rows = list(db.rows(f'{self.core}.spell_dbc',
                    f'SELECT * FROM `{self.world}`.spell_dbc ORDER BY Id;'))
                for row in rows:
                    if len(row) != len(positions):
                        reject('INCOMPATIBLE_DBC_OVERLAY',
                            'TC spell_dbc column count')
                    record = [0] * len(sql_fmt)
                    for i, value in zip(positions, row):
                        if layout['formats'][self.core][i] == 'f':
                            record[i] = (struct.unpack('<I', struct.pack('<f',
                                float(value)))[0])
                        elif layout['formats'][self.core][i] != 's':
                            record[i] = int(value) & 0xffffffff
                    if record[0] in records:
                        reject('TC_DBC_OVERLAY_COLLISION', str(record[0]))
                    records[record[0]] = record
            self.stores[name] = records

    def _load_talents(self, profile: Evidence) -> None:
        self.spells = self.stores['Spell']
        self.talents, self.talent_rows, self.invalid_talents = {}, {}, set()
        for _, talent in sorted(self.stores['Talent'].items()):
            ranks = talent[4:9]
            nonzero = [x for x in ranks if x]
            malformed = (ranks[:len(nonzero)] != nonzero or any(spell not
                in self.spells for spell in nonzero))
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
        for rule in profile['corrections'][self.core]['guards']:
            for spell in rule['ids']:
                self.correction_guards[spell].extend(rule['fields'])
        for rule in profile['corrections'][self.core]['operations']:
            for spell in rule['ids']:
                if spell in self.spells:
                    record = self.spells[spell]
                    for field, op, value in rule['changes']:
                        operand = (record[value['field']] if isinstance(value,
                            dict) else value)
                        record[field] = {'=': lambda: operand,
                            '|=': lambda: record[field] | operand,
                            '&=': lambda: record[field]
                            & operand} [op]() & 0xffffffff
        # Reviewed global correction in both pinned cores.
        for record in self.spells.values():
            if record[134] == 2158:
                record[4] |= PASSIVE

    def _load_chains(self, db: MetadataReader) -> None:
        self.chains, self.position = {}, {}
        for talent in self.stores['Talent'].values():
            ranks = tuple(x for x in talent[4:9] if x)
            if (len(ranks) > 1 and not any(spell in self.invalid_talents
                for spell in ranks)):
                self.add_chain(ranks)
        rank_rows = db.table(self.world, 'spell_ranks', ['first_spell_id',
            'spell_id', 'rank'])
        for first, rows in itertools.groupby(rank_rows, key=lambda r: int(r[
            0])):
            ranks = sorted((int(rank), int(spell)) for _, spell, rank in rows)
            if (not ranks or len(ranks) > 255 or [r for r, _ in ranks] != list(
                range(1, len(ranks) + 1)) or ranks[0][1] != first):
                reject('MALFORMED_SPELL_CHAIN', f'{self.core}: first={first}')
            chain = tuple(spell for _, spell in ranks)
            if len(chain) > 1:
                self.add_chain(chain)
            elif chain[0] not in self.spells:
                reject('MISSING_CHAIN_SPELL', f'{self.core}: {chain[0]}')

    def _load_requirements(self, db: MetadataReader) -> None:
        self.requires = defaultdict(set)
        for spell, required in db.table(self.world, 'spell_required', [
            'spell_id',
            'req_spell']):
            spell, required = int(spell), int(required)
            if (spell not in self.spells or required not in self.spells
                or self.first(spell) == self.first(required)):
                reject('INVALID_SPELL_REQUIREMENT',
                    f'{self.core}: {spell}:{required}')
            self.requires[spell].add(required)

    def _load_learning_routes(self, db: MetadataReader) -> None:
        self.learns, self.effect_learns = defaultdict(list), defaultdict(list)
        world_learns = []
        if self.core == 'tc':
            world_learns = db.table(self.world, 'spell_learn_spell', ['entry',
                'SpellID', 'Active'])
            for parent, child, active in world_learns:
                parent, child, active = int(parent), int(child), int(active)
                if (parent not in self.spells or child not in self.spells
                    or child in self.talents or active not in (0, 1)):
                    reject('INVALID_LEARNED_SPELL', f'{parent}:{child}')
                self.learns[parent].append((child, active, False))
        for spell, record in self.spells.items():
            for i in range(3):
                child = record[116 + i]
                if record[71 + i] == LEARN and child in self.spells:
                    auto = (record[86 + i] == 5 or spell in self.talents
                        or bool(record[4] & PASSIVE) or SKILL_STEP in record[
                            71:74])
                    self.effect_learns[spell].append((child, 1, auto))
                    # TC returns early, before scanning DBC learn effects,
                    # when spell_learn_spell is empty. Cast learn effects
                    # still exist independently of that loader map.
                    if ((self.core == 'ac' or world_learns) and not any(row[0]
                        == child for row in self.learns[spell])):
                        self.learns[spell].append((child, 1, auto))
        self.additional = set()
        for talent in self.talents:
            for child, _, _ in self.effect_learns[talent]:
                if (child in self.position and not self.spells[child][4] & (
                    PASSIVE | HIDDEN)):
                    self.additional.add(child)
        # Classify ownership from the complete catalog, independently of the
        # character's selections. Otherwise an unselected hidden talent child
        # can incorrectly fall through to the ordinary mask-3 policy.
        self.talent_learn_owners = defaultdict(set)
        for owner in self.talents:
            pending, visited = deque([owner]), set()
            while pending:
                parent = pending.popleft()
                if parent in visited:
                    continue
                visited.add(parent)
                pet_children = {self.spells[parent][116 + i] for i in range(3)
                    if self.spells[parent][71 + i] == LEARN
                    and self.spells[parent][86 + i] == 5}
                children = ({row[0] for row in self.effect_learns[parent]
                    + self.learns[parent]} - pet_children)
                for child in children:
                    self.talent_learn_owners[child].add(owner)
                    pending.append(child)
        for spell, prerequisites in self.requires.items():
            if any(parent in self.talents for parent in prerequisites):
                self.additional.add(spell)

    def _load_skill_abilities(self) -> None:
        self.abilities = defaultdict(list)
        for ability in self.stores['SkillLineAbility'].values():
            self.abilities[ability[2]].append(ability)

    def _load_scripts(self, profile: Evidence, db: MetadataReader) -> None:
        self.scripts = defaultdict(set)
        for spell, name in db.table(self.world, 'spell_script_names', [
            'spell_id',
            'ScriptName']):
            spell = int(spell)
            if spell < 0:
                for member in self.chain(abs(spell)):
                    self.scripts[member].add(name)
            else:
                self.scripts[spell].add(name)
        self.script_policy = profile.get('scripts', {}).get(self.core, {})
        self.cast_only_scripts = profile.get('cast_only_scripts', {}).get(
            self.core,
            {})
        self.aura_talent_scripts = profile.get('aura_talent_scripts', {}).get(
            self.core, {})
        self.skill_reward_dependencies = profile.get(
            'skill_reward_dependencies', {})
        self.persistent_world_dependencies = profile.get(
            'persistent_world_dependencies', {})
        self.native_passive_ranks = profile.get('native_passive_ranks', {})
        self.world_talent_auras = profile.get('world_talent_auras', {})
        self.world_ranked_talent_auras = profile.get(
            'world_ranked_talent_auras', {})
        self.consumed_teachers = profile.get('consumed_teachers', {})
        self.ordinary_teachers = profile.get('ordinary_teachers', {})
        self.world_aura_owners = {child: owner for rule in (
            *self.world_talent_auras.values(),
            *self.world_ranked_talent_auras.values())
            for owner, child in zip(rule['owners'], rule[
                'children'])}

    def _load_native_consumers(self, db: MetadataReader) -> None:
        self.trainer_taught = set()
        if self.core == 'ac':
            pending_trainers = deque()
            for row in db.table(self.world, 'trainer_spell', ['SpellId']):
                try:
                    spell = int(row[0])
                except (ValueError, TypeError, IndexError):
                    reject('INVALID_TRAINER_SPELL_METADATA',
                        f'{self.world}.trainer_spell: invalid SpellId')
                if not 0 <= spell <= 0xffffffff:
                    reject('INVALID_TRAINER_SPELL_METADATA',
                        f'{self.world}.trainer_spell: SpellId outside '
                        'unsigned domain')
                pending_trainers.append(spell)
            while pending_trainers:
                spell = pending_trainers.popleft()
                if spell not in self.spells or spell in self.trainer_taught:
                    continue
                self.trainer_taught.add(spell)
                pending_trainers.extend(child for child, _, _
                    in self.effect_learns.get(spell, ()))
        self.learn_parents, self.prerequisite_users = defaultdict(
            set), defaultdict(set)
        for parent in self.learns.keys() | self.effect_learns.keys():
            for child, _, _ in self.learns[parent] + self.effect_learns[
                parent]:
                self.learn_parents[child].add(parent)
        for dependent, requirements in self.requires.items():
            for required in requirements:
                self.prerequisite_users[required].add(dependent)
        self.aura_owners = defaultdict(set)
        for name, rule in self.aura_talent_scripts.items():
            for parent, entry in rule['parents'].items():
                if name in self.scripts[int(parent)]:
                    self.aura_owners[entry['child']].add(int(parent))

    def _load_custom_attributes(self, db: MetadataReader) -> None:
        custom_columns = (['entry', 'attributes'] if self.core == 'tc' else[
            'spell_id', 'attributes'])
        for spell, attributes in db.table(self.world, 'spell_custom_attr',
            custom_columns):
            if (self.core == 'tc' and int(attributes) & 0x00800000 and int(
                spell) not in self.talents):
                reject('CUSTOM_TALENT_CLASSIFICATION', spell)

    def add_chain(self, chain: Sequence[int]) -> None:
        for index, spell in enumerate(chain):
            if spell not in self.spells:
                reject('MISSING_CHAIN_SPELL', f'{self.core}: {spell}')
            if spell in self.position and self.chain(spell) != chain:
                reject('CONFLICTING_SPELL_CHAINS', f'{self.core}: {spell}')
            self.position[spell] = (chain[0], index)
        self.chains[chain[0]] = chain

    def chain(self, spell: int) -> tuple[int, ...]:
        return self.chains.get(self.first(spell), (spell,))

    def first(self, spell: int) -> int:
        return self.position.get(spell, (spell, 0))[0]

    def predecessors(self, spell: int) -> tuple[int, ...]:
        return self.chain(spell)[:self.position.get(spell, (spell, 0))[1]]

    def stackable(self, spell: int) -> bool:
        record = self.spells[spell]
        effects = record[71:74]
        profession = any(self.stores['SkillLine'].get(row[1], [0, 0])[1] in (9,
            11) or row[1] == 762
            for row in self.abilities[spell])
        if (record[4] & PASSIVE or signed(record[41]) not in (0, -2)
            or profession):
            return False
        if (record[208] == 10 and (65 in effects or (self.core == 'tc'
            and record[210] & 0x20000000))):
            return False
        if (record[208] == 7 and any(effects[i] == 6 and record[95 + i] == 36
            for i in range(3))):
            return False
        return True

    def check_spell(self, spell: int) -> None:
        if spell not in self.spells:
            reject('UNKNOWN_SPELL_ID', f'{self.core}: {spell}')
        if spell in self.invalid_talents:
            reject('MALFORMED_TALENT_CHAIN', f'{self.core}: {spell}')
        record = self.spells[spell]
        for field in self.correction_guards[spell]:
            if field == 'visibility':
                reject('UNSUPPORTED_CORE_CORRECTION',
                    f'{self.core}: {spell}: {field}')
            index, name = field.split(':')
            effect = record[71 + int(index)]
            if (name == 'Effect' or effect in (LEARN, SKILL, SKILL_STEP,
                DUAL_WIELD, 65) or (effect == 6 and name == 'ApplyAuraName')):
                reject('UNSUPPORTED_CORE_CORRECTION',
                    f'{self.core}: {spell}: {field}')
        for name in sorted(self.scripts[spell]):
            self.check_script(spell, name)

    def check_script(self, spell: int, name: str) -> None:
        """One binding's metadata contract, independent of character
        ownership.
        """
        if spell not in self.spells:
            reject('UNKNOWN_SPELL_ID', f'{self.core}: {spell}')
        record = self.spells[spell]
        if name in self.aura_talent_scripts:
            rule = self.aura_talent_scripts[name]
            entry = rule['parents'].get(str(spell), {})
            helper = self.spells.get(entry.get('child'), [])
            if (not entry or spell not in self.talents or self.talents[spell][
                1] != entry['rank']
                or record[71:74] != rule['effects'] or record[95] != rule[
                    'aura']
                or not record[4] & PASSIVE or record[12] or record[20]
                or not helper or entry['child'] in self.talents
                or helper[71:74] != rule['helper_effects'] or helper[95]
                != rule['helper_aura']
                or helper[12] != rule['helper_stances'] or helper[20]
                or helper[4] & (PASSIVE | HIDDEN) != HIDDEN):
                reject('UNSUPPORTED_TALENT_AURA_SCRIPT',
                    f'{self.core}: {spell}: {name}')
        elif self.script_policy.get(name) != 'NO_SPELLBOOK_MUTATION':
            rule = self.cast_only_scripts.get(name, {})
            skill = rule.get('spell_skills', {}).get(str(spell))
            # Both native loaders leave this exact non-passive research
            # spell uncast. Passive/stance, talent and teaching variants
            # require a separate review even if they use the same script.
            if (not skill or spell in self.talents or record[4] & PASSIVE
                or (record[4] & HIDDEN and record[12])
                or record[71:74] != rule.get('effects')
                or self.stores['SkillLine'].get(skill, [0, 0])[1] != 11
                or not any(row[1] == skill for row in self.abilities[
                    spell])):
                reject('UNSUPPORTED_LEARNING_SCRIPT',
                    f'{self.core}: {spell}: {name}')

    def skill_effect(self, spell: int) -> tuple[int, int, int, int] | None:
        record = self.spells[spell]
        for i in range(3):
            if record[71 + i] == SKILL:
                if record[74 + i] not in (0, 1):
                    reject('NONDETERMINISTIC_SKILL_EFFECT', str(spell))
                step = signed(record[80 + i]) + (1 if record[74 + i] else 0)
                return record[110 + i], step, step * 75 if record[110
                    + i] == 762 else 1, step * 75
            if record[71 + i] == DUAL_WIELD:
                return 118, 1, 1, 1
        return None
