#!/usr/bin/env python3
"""Compatibility facade and streaming CLI for spell-state reconstruction."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from collections.abc import Iterator
import hashlib
import itertools
import json
from pathlib import Path
import struct
import sys

from cleanup_types import Direction
from spell_common import (
    DUAL_WIELD,
    HIDDEN,
    LEARN,
    MetadataQueryError,
    PASSIVE,
    POLICY,
    SKILL,
    SKILL_STEP,
    Unsupported,
    canonical,
    digest,
    read_dbc,
    reject,
    signed,
    sql_text,
)
from spell_metadata import Database, Metadata
from spell_reconstruction import reconstruct
from spell_rules import (
    assert_acyclic,
    consumed_teacher_rule,
    known_ranked_language_without_skill,
    known_runeforging_without_skill,
    native_passive_rule,
    ordinary_teacher_rule,
    ranked_world_talent_aura_rule,
    script_review,
    seal_rank_split_rule,
    world_talent_aura_rule,
)


def character_rows(
    db: Database,
    schema: str,
    direction: Direction,
) -> Iterator[list[str]]:
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


def main(args: argparse.Namespace) -> int:
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
        'scope': 'Bindings on stored spell and selected talent IDs of existing '
        'source characters; excludes derived-only IDs; metadata contract '
        'only, not ownership or cleanup approval',
        'bindings': []}
    review_path.write_text(json.dumps(review, indent=2, sort_keys=True) + '\n')
    stored_counts, talent_counts = Counter(), Counter()
    metadata = None
    expected_hasher = hashlib.sha256()
    expected_sql = output / 'spell-expected.sql'
    expected_tsv = output / 'spell-expected.tsv'
    with expected_sql.open('w') as sql, expected_tsv.open('w') as tsv:
        tsv.write(
            'guid\tspell\tspec_mask\tactive\tdisabled\tdisposition\tderived\t'
            'provenance\n')
        for guid, group in itertools.groupby(character_rows(db,
            args.source_characters, args.direction), lambda row: int(row[0])):
            character, level, stored, talents, skills = None, None, {
            }, defaultdict(int), {}
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
                    if (not args.source_world or not args.target_world
                        or not args.tc_dbc or not args.ac_dbc):
                        reject('MISSING_SPELL_METADATA_INPUT',
                            'both worlds and both DBC directories are '
                            'required')
                    tc_world, ac_world = ((args.source_world,
                        args.target_world) if args.direction == 'tc-to-ac'
                        else(args.target_world,
                            args.source_world))
                    tc = Metadata('tc', args.tc_dbc, tc_world, profile, db)
                    ac = Metadata('ac', args.ac_dbc, ac_world, profile, db)
                    metadata = (tc, ac)
                source, target = (metadata if args.direction == 'tc-to-ac'
                    else metadata[::-1])
                rows = reconstruct(character, stored, talents, skills, source,
                    target, args.direction, level=level)
                for spell, row in sorted(rows.items()):
                    proof = json.dumps({'original': row['original'],
                        'derivations': row['proofs'],
                        'authorization': row['authorization']},
                        sort_keys=True, separators= (',', ':'))
                    line = '\t'.join(map(str, [guid, spell, row['mask'], row[
                        'active'], row['disabled'],
                        row['disposition'], int(row[
                            'derived']), proof])) + '\n'
                    expected_hasher.update(line.encode())
                    tsv.write(line)
                    sql.write(f'INSERT INTO `{args.control}`.spell_expected '
                        '(run_id,guid,spell,spec_mask,active,disabled,disposition,derived,provenance) '
                        f"VALUES ('{args.run_id}',{guid},{spell},"
                        f"{row['mask']},{row['active']},{row['disabled']},'"
                        f"{row['disposition']}',{int(row['derived'])},"
                        f'{sql_text(proof)});\n')
            except Unsupported as error:
                with blockers.open('a') as report:
                    report.write(f'{guid}\t*\t{error.reason}\t'
                        f"{str(error).replace(chr(9), ' ').replace(chr(10), ' ')}"
                        '\n')
                # Metadata failures affect every character; repeating the
                # expensive read cannot recover and would obscure the cause.
                if metadata is None:
                    for _ in group:
                        pass
                    # Drain to finish the source digest / terminate client.
                    # The entire run is rejected; no expected SQL is imported.
                    raise
    fingerprints = {'policy': digest(POLICY.encode()), 'profile': digest(
        profile_bytes), **db.fingerprints}
    if metadata:
        for core in metadata:
            fingerprints.update(core.hashes)
    input_hash = digest(canonical(fingerprints))
    expected_hash = expected_hasher.hexdigest()
    review.update(status='COMPLETE', input_sha256=input_hash,
        bindings=script_review(metadata or (), stored_counts,
            talent_counts))
    review_path.write_text(json.dumps(review, indent=2, sort_keys=True) + '\n')
    (output / 'spell-fingerprints.tsv').write_text('input\tsha256\n' + ''.join(
        f'{key}\t{value}\n' for key, value in sorted(fingerprints.items())))
    (output / 'spell-digests.tsv').write_text(
        f'{input_hash}\t{expected_hash}\n')
    if len(blockers.read_text().splitlines()) > 1:
        return 1
    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for name in ['profile', 'output', 'source-characters', 'control', 'run-id',
        'direction']:
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
            f'input\treason_code\tdetail\n{error.label}\t'
            f'SPELL_METADATA_QUERY_FAILED\t{detail}\n')
        print(f'Spell metadata read failed: {error}', file=sys.stderr)
        sys.exit(2)
    except (Unsupported, ValueError, OSError, struct.error) as error:
        print(f'Spell reconstruction failed: {error}', file=sys.stderr)
        sys.exit(1)
