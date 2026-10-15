#!/usr/bin/env python3
"""Focused wide-metadata regression on a dedicated disposable MySQL 8.4 server."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'lib'))
from spells import Database, MetadataQueryError


def main():
    port = os.environ.get('REHEARSAL_MYSQL_PORT', '33317')
    if (os.environ.get('MIGRATOR_DISPOSABLE_MYSQL') != '1' or not port.isascii()
            or not port.isdigit() or not 1 <= int(port) <= 65535 or int(port) == 3306):
        raise SystemExit('Requires MIGRATOR_DISPOSABLE_MYSQL=1 and a non-production localhost port')
    option_file = os.environ.get('REHEARSAL_MYSQL_DEFAULTS_FILE', '')
    admin_args = ([f'--defaults-extra-file={option_file}'] if option_file else ['--no-defaults']) + [
        '--host=127.0.0.1', f'--port={int(port)}', '--protocol=TCP', '--user=root',
        '--batch', '--skip-column-names', '--default-character-set=utf8mb4']

    def sql(query):
        result = subprocess.run(['mysql', *admin_args], input=query, text=True, capture_output=True)
        if result.returncode:
            raise AssertionError(result.stderr)
        return result.stdout.strip()

    version = sql('SELECT @@version;')
    assert version.startswith('8.4.'), f'Requires MySQL 8.4.x; got {version}'
    schema = 'migrator_metadata_' + uuid.uuid4().hex[:12]
    user = schema
    owned_schema = owned_user = False
    try:
        # Never reuse a database or account; cleanup owns only successful creates.
        sql(f'CREATE DATABASE `{schema}`;')
        owned_schema = True
        sql(f"CREATE USER '{user}'@'%' IDENTIFIED BY '';")
        owned_user = True
        sql(f"GRANT SELECT ON `{schema}`.* TO '{user}'@'%';")
        ac = Path(os.environ.get('AZEROTHCORE_DIR', ROOT.parent/'azerothcore-wotlk'))
        profile = json.loads((ROOT/'compatibility'/os.environ.get('COMPATIBILITY_PROFILE', 'tc335-acwotlk-v2')/'spell-metadata.json').read_text())
        layout = profile['stores']['Spell']
        ddl = re.search(r'CREATE TABLE `spell_dbc` \(.*?\) ENGINE=[^;]+;',
                        (ac/'data/sql/base/db_world/spell_dbc.sql').read_text(), re.S)[0]
        sql(f'USE `{schema}`;{ddl}')
        columns = layout['columns']
        strings = re.findall(r'`([^`]+)` text\b', ddl)
        assert strings, 'Fixture needs the native wide localized text fields'
        insert_columns = ','.join(f'`{name}`' for name in [columns[0], *strings])
        values = ','.join('(' + ','.join([str(i), *("REPEAT('x',2048)" for _ in strings)]) + ')'
                          for i in range(1, 65))
        sql(f'INSERT INTO `{schema}`.spell_dbc ({insert_columns}) VALUES {values};')
        read_args = ['--no-defaults', '--host=127.0.0.1', f'--port={int(port)}', '--protocol=TCP',
                     f'--user={user}', '--default-character-set=utf8mb4',
                     '--init-command=SET SESSION sort_buffer_size=32768']
        db = Database(read_args)
        selected = ','.join(f'`{name}`' for name in columns)
        # This is the old query. Wide sort keys must exceed the deliberately
        # small per-session buffer, establishing the failure before the fix.
        try:
            list(db.rows('old-reader', f'SELECT {selected} FROM `{schema}`.spell_dbc ORDER BY {selected};'))
        except MetadataQueryError as error:
            assert '1038' in str(error), str(error)
        else:
            raise AssertionError('Old wide ORDER BY unexpectedly succeeded')
        rows = db.table(schema, 'spell_dbc', columns)
        assert len(rows) == 64
        fingerprint = db.fingerprints[f'{schema}.spell_dbc']
        assert rows == db.table(schema, 'spell_dbc', columns)
        assert fingerprint == db.fingerprints[f'{schema}.spell_dbc']
        # Fingerprints still cover ignored/localized text and same-count edits.
        sql(f"UPDATE `{schema}`.spell_dbc SET `{strings[0]}`=CONCAT(`{strings[0]}`,'y') WHERE `{columns[0]}`=1;")
        assert len(db.table(schema, 'spell_dbc', columns)) == 64
        assert fingerprint != db.fingerprints[f'{schema}.spell_dbc']
        try:
            list(db.rows('write-guard', f'DELETE FROM `{schema}`.spell_dbc;'))
        except MetadataQueryError as error:
            assert '1142' in str(error), str(error)
        else:
            raise AssertionError('Metadata account could write world rows')
        assert sql(f'SELECT COUNT(*) FROM `{schema}`.spell_dbc;') == '64'
        print(f'MySQL {version}: old reader fails with 1038; canonical metadata read, drift and read-only checks passed.')
    finally:
        if owned_schema:
            sql(f'DROP DATABASE `{schema}`;')
        if owned_user:
            sql(f"DROP USER '{user}'@'%';")


if __name__ == '__main__':
    main()
