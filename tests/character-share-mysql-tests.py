#!/usr/bin/env python3
"""Exercise private snapshot redaction only on owned disposable MySQL schemas."""
import json
import os
from pathlib import Path
import re
import subprocess
import uuid

ROOT = Path(__file__).resolve().parents[1]


def main():
    port = os.environ.get('REHEARSAL_MYSQL_PORT', '33317')
    if (os.environ.get('MIGRATOR_DISPOSABLE_MYSQL') != '1'
            or not port.isascii() or not port.isdigit()
            or not 1 <= int(port) <= 65535 or int(port) == 3306):
        raise SystemExit('Requires dedicated disposable localhost MySQL on a non-production port')
    defaults = os.environ.get('REHEARSAL_MYSQL_DEFAULTS_FILE', '')
    options = ([f'--defaults-extra-file={defaults}'] if defaults else ['--no-defaults']) + [
        '--host=127.0.0.1', f'--port={int(port)}', '--protocol=TCP', '--user=root',
        '--batch', '--skip-column-names', '--skip-force', '--binary-as-hex']

    def run(query, *, good=True, user=None):
        args = [x for x in options if not (user and x.startswith('--user='))]
        if user:
            args.append('--user=' + user)
        p = subprocess.run(['mysql', *args], input=query, text=True, capture_output=True)
        assert (p.returncode == 0) == good, p.stdout + p.stderr
        return p

    assert run('SELECT @@version').stdout.startswith('8.4.')
    tc = Path(os.environ.get('TRINITYCORE_DIR', ROOT.parent / 'TrinityCore'))
    native = (tc / 'sql/base/characters_database.sql').read_text()
    ddl = (ROOT / 'tools/redact-character-share.sql').read_text()
    catalog = json.loads(re.search(r"SET v_catalog='(.*?)';", ddl, re.S)[1])
    actual = [{'table': t, 'columns': [list(x) for x in re.findall(
        r'^\s*`([^`]+)`\s+(\w+)', b, re.M)]}
        for t, b in re.findall(r'CREATE TABLE `([^`]+)` \((.*?)\) ENGINE=', native, re.S)]
    assert catalog == actual, 'Reviewed share inventory differs from TC schema'
    rule_text = ddl.split('INSERT INTO tmp_migrator_share_rules(table_name,column_name,action) VALUES', 1)[1]
    rules = re.findall(r"\('([^']+)','([^']+)','(EMPTY|ZERO)'\)", rule_text.split(';', 1)[0])
    assert len(rules) == 32
    sensitive = {(t, c): a for t, c, a in rules}
    prefix = 'share_' + uuid.uuid4().hex[:10]
    schema, untouched, ordinary = prefix + '_share', prefix + '_world', prefix + '_chars'
    user = prefix + '_writer'
    owned = []
    checks = []

    def passed(name):
        checks.append(name)
        print('PASS ' + name, flush=True)

    def call(mode, ack='', *, good=True, who=None, target=None):
        return run(f"USE `{target or schema}`; CALL migrator_redact_character_share('{mode}','{ack}');",
                   good=good, user=who)

    def snapshot():
        # Stable, binary-exact snapshots per column prove preservation of every
        # row/key and every nonredacted field, including structured text blobs.
        result = {}
        for table in catalog:
            t = table['table']
            exprs = ','.join(f"IF(`{c}` IS NULL,'NULL',HEX(CAST(`{c}` AS BINARY)))"
                             for c, _ in table['columns'])
            result[t] = run(f'SELECT {exprs} FROM `{schema}`.`{t}`').stdout
        return result

    try:
        for db in (schema, untouched, ordinary):
            run(f'CREATE DATABASE `{db}`;')
            owned.append(db)
        run(f'USE `{untouched}`; CREATE TABLE sentinel(id INT,private_text TEXT);'
            "INSERT INTO sentinel VALUES(1,'WORLD MUST NOT CHANGE');")
        run(f'USE `{schema}`;\n' + native + '\n' + ddl)
        # One complete row in every native table, using independent secret and
        # structured-text sentinels. Full column comparison below catches broad
        # text wiping and accidental deletion, including account cache records.
        for table in catalog:
            cols, values = [], []
            run(f"DELETE FROM `{schema}`.`{table['table']}`;")
            for col, typ in table['columns']:
                cols.append(f'`{col}`')
                if typ in ('varchar', 'char', 'tinytext', 'text', 'longtext', 'blob'):
                    values.append("'SECRET'" if (table['table'], col) in sensitive else "'KEEP'")
                elif typ in ('timestamp', 'datetime', 'date'):
                    values.append("'2020-01-02 03:04:05'")
                else:
                    values.append('1')
            run(f"INSERT INTO `{schema}`.`{table['table']}`({','.join(cols)}) VALUES({','.join(values)});")
        # A letter and its item link must survive together; nullable originals
        # remain NULL. Empty text plus nonzero cache timestamps are also covered.
        run(f"UPDATE `{schema}`.item_instance SET text=NULL;"
            f"INSERT INTO `{schema}`.item_instance(guid,itemEntry,owner_guid,enchantments,text)"
            " VALUES(2,6948,1,'123 456','SECRET LETTER');"
            f"INSERT INTO `{schema}`.character_spell VALUES(2,48942,1,0);"
            f"INSERT INTO `{schema}`.character_talent VALUES(2,12296,0);"
            f"INSERT INTO `{schema}`.character_skills VALUES(2,762,225,225);"
            f"UPDATE `{schema}`.account_data SET data=X'';")
        before = snapshot()
        assert 'PREVIEW_ONLY' in call('PREVIEW').stdout
        assert snapshot() == before
        assert 'SHARE_REDACTION_INCOMPLETE' in call('VERIFY', good=False).stderr
        assert snapshot() == before
        assert 'SHARE_ACK_REQUIRED' in call('APPLY', good=False).stderr
        assert snapshot() == before
        passed('preview and verify are read-only; apply requires explicit copy acknowledgement')

        # Guard the selected schema even if the procedure is installed elsewhere.
        run(f'USE `{ordinary}`;\n' + ddl)
        assert 'SHARE_SCHEMA_REQUIRED' in call('APPLY', 'DISPOSABLE_SHARE_COPY_WRITERS_STOPPED',
                                               target=ordinary, good=False).stderr
        passed('ordinary character database rejected')

        def rejects(add, remove, reason):
            run(f'USE `{schema}`;' + add)
            preview = call('PREVIEW').stdout
            assert 'REVIEW_REQUIRED' in preview and reason in preview, preview
            assert 'SHARE_SCHEMA_REVIEW_REQUIRED' in call(
                'APPLY', 'DISPOSABLE_SHARE_COPY_WRITERS_STOPPED', good=False).stderr
            run(f'USE `{schema}`;' + remove)
            assert snapshot() == before

        rejects('CREATE TABLE private_custom(id INT,password TEXT);', 'DROP TABLE private_custom;',
                'UNREVIEWED_TABLE_OR_VIEW')
        rejects('ALTER TABLE characters ADD legacy_secret TEXT;',
                'ALTER TABLE characters DROP COLUMN legacy_secret;', 'UNREVIEWED_COLUMN')
        rejects('ALTER TABLE characters ADD legacy_numeric_secret BIGINT;',
                'ALTER TABLE characters DROP COLUMN legacy_numeric_secret;', 'UNREVIEWED_COLUMN')
        rejects('CREATE VIEW private_view AS SELECT * FROM characters;', 'DROP VIEW private_view;',
                'UNREVIEWED_TABLE_OR_VIEW')
        rejects('CREATE TRIGGER no_redaction BEFORE UPDATE ON channels FOR EACH ROW SET NEW.password=OLD.password;',
                'DROP TRIGGER no_redaction;', 'UNREVIEWED_TRIGGER')
        rejects("CREATE EVENT private_event ON SCHEDULE AT CURRENT_TIMESTAMP + INTERVAL 1 DAY DO SELECT 1;",
                'DROP EVENT private_event;', 'UNREVIEWED_EVENT')
        rejects('CREATE PROCEDURE private_routine() SELECT 1;', 'DROP PROCEDURE private_routine;',
                'UNREVIEWED_ROUTINE')
        rejects('ALTER TABLE channels ENGINE=MyISAM;', 'ALTER TABLE channels ENGINE=InnoDB;',
                'NONTRANSACTIONAL_TABLE')
        rejects('ALTER TABLE channels MODIFY password TEXT;',
                'ALTER TABLE channels MODIFY password VARCHAR(32);', 'MISSING_OR_CHANGED_STOCK_COLUMN')
        passed('custom fields/tables, views, triggers, routines, events, changed types and MyISAM refuse writes')

        # A late permission failure follows real earlier writes. Everything must
        # roll back, including cache payload/time, and no REDACTED status appears.
        run(f"CREATE USER '{user}'@'%'; GRANT SELECT,TRIGGER ON *.* TO '{user}'@'%';"
            f"GRANT CREATE TEMPORARY TABLES ON `{schema}`.* TO '{user}'@'%';"
            f"GRANT EXECUTE ON PROCEDURE `{schema}`.migrator_redact_character_share TO '{user}'@'%';")
        for t in sorted({t for t, _, _ in rules}):
            cols = ','.join(f'`{c}`' for rt, c, _ in rules if rt == t and (t, c) != ('mail', 'body'))
            run(f"GRANT UPDATE ({cols}) ON `{schema}`.`{t}` TO '{user}'@'%';")
        failed = call('APPLY', 'DISPOSABLE_SHARE_COPY_WRITERS_STOPPED', good=False, who=user)
        assert ('denied' in failed.stderr and 'mail' in failed.stderr
                and 'body' in failed.stderr and 'REDACTED' not in failed.stdout), failed.stderr
        assert snapshot() == before
        passed('late UPDATE denial rolls back all prior redactions')

        report = call('APPLY', 'DISPOSABLE_SHARE_COPY_WRITERS_STOPPED').stdout
        assert 'REDACTED' in report and 'SECRET' not in report
        assert 'VERIFIED' in call('VERIFY').stdout
        after = snapshot()
        for table in catalog:
            t = table['table']
            old_rows = [line.split('\t') for line in before[t].splitlines()]
            new_rows = [line.split('\t') for line in after[t].splitlines()]
            assert len(old_rows) == len(new_rows), t
            for old, new in zip(old_rows, new_rows):
                for i, (c, _) in enumerate(table['columns']):
                    action = sensitive.get((t, c))
                    expected = ('NULL' if old[i] == 'NULL' else
                                ('30' if action == 'ZERO' else '')) if action else old[i]
                    assert new[i] == expected, (t, c, old[i], new[i], expected)
        assert run(f'SELECT private_text FROM `{untouched}`.sentinel').stdout.strip() == 'WORLD MUST NOT CHANGE'
        passed('all 32 field rules applied; NULLs, all 91 row sets, names/keys and unrelated fields preserved')
        again = call('APPLY', 'DISPOSABLE_SHARE_COPY_WRITERS_STOPPED').stdout
        assert 'REDACTED' in again and snapshot() == after
        assert all(line.split('\t')[4] == '0' for line in again.splitlines()
                   if len(line.split('\t')) == 6)
        passed('apply is idempotent with zero changed rows on rerun')

        # The dump contains no helper routines/triggers/events; restore it and
        # independently reinstall/verify the checker on the actual exported data.
        args = [x for x in options if x not in (
            '--skip-column-names', '--skip-force', '--batch', '--binary-as-hex')]
        dump = subprocess.run(['mysqldump', *args, '--single-transaction', '--quick',
            '--hex-blob', '--skip-routines', '--skip-events', '--skip-triggers',
            '--no-tablespaces', '--set-gtid-purged=OFF', schema], capture_output=True, text=True)
        assert dump.returncode == 0, dump.stderr
        assert 'SECRET' not in dump.stdout and 'migrator_redact_character_share' not in dump.stdout
        restore = prefix + '_restore_share'
        run(f'CREATE DATABASE `{restore}`;')
        owned.append(restore)
        run(f'USE `{restore}`;\n' + dump.stdout + '\n' + ddl)
        assert 'VERIFIED' in call('VERIFY', target=restore).stdout
        passed('real dump/restore contains no secret sentinels or helper routines and verifies clean')
        print(f'Character share MySQL tests passed ({len(checks)} groups).', flush=True)
    finally:
        run(f"DROP USER IF EXISTS '{user}'@'%';")
        for db in reversed(owned):
            run(f'DROP DATABASE `{db}`;')


if __name__ == '__main__':
    main()
