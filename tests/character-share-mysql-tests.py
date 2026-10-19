#!/usr/bin/env python3
"""Exercise private snapshot redaction only on owned disposable MySQL schemas."""
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
    cleanup = (ROOT / 'tools/redact-character-share.sql').read_text()
    catalog = [{'table': t, 'columns': [list(x) for x in re.findall(
        r'^\s*`([^`]+)`\s+(\w+)', b, re.M)]}
        for t, b in re.findall(r'CREATE TABLE `([^`]+)` \((.*?)\) ENGINE=', native, re.S)]
    # Independent expected change set: broader SQL updates cannot silently
    # redefine the preservation assertions.
    clear = {
        'channels': ['password'], 'mail': ['subject', 'body'], 'item_instance': ['text'],
        'character_social': ['note'], 'character_banned': ['bannedby', 'banreason'],
        'guild': ['info', 'motd'], 'guild_member': ['pnote', 'offnote'],
        'guild_bank_tab': ['TabName', 'TabIcon', 'TabText'], 'guild_rank': ['rname'],
        'calendar_events': ['title', 'description'], 'calendar_invites': ['text'],
        'gm_ticket': ['description', 'comment', 'response'], 'gm_survey': ['comment'],
        'gm_subsurvey': ['answerComment'], 'bugreport': ['type', 'content'],
        'account_data': ['data'], 'character_account_data': ['data'],
        'character_equipmentsets': ['name', 'iconname'], 'worldstates': ['comment'],
    }
    rules = [(t, c, 'EMPTY') for t, cols in clear.items() for c in cols] + [
        ('account_data', 'time', 'ZERO'), ('character_account_data', 'time', 'ZERO')]
    assert len(rules) == 32
    sensitive = {(t, c): a for t, c, a in rules}
    prefix = 'share_' + uuid.uuid4().hex[:10]
    schema, untouched = prefix + '_chars', prefix + '_world'
    user = prefix + '_writer'
    owned = []
    checks = []

    def passed(name):
        checks.append(name)
        print('PASS ' + name, flush=True)

    def apply(*, good=True, who=None):
        return run(f'USE `{schema}`;\n' + cleanup, good=good, user=who)

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
        for db in (schema, untouched):
            run(f'CREATE DATABASE `{db}`;')
            owned.append(db)
        run(f'USE `{untouched}`; CREATE TABLE sentinel(id INT,private_text TEXT);'
            "INSERT INTO sentinel VALUES(1,'WORLD MUST NOT CHANGE');")
        run(f'USE `{schema}`;\n' + native)
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
            f"INSERT INTO `{schema}`.channels(name,team,password,lastUsed) VALUES('NULL',1,NULL,1);"
            f"INSERT INTO `{schema}`.mail(id,subject,body) VALUES(2,NULL,NULL);"
            f"INSERT INTO `{schema}`.guild_bank_tab(guildid,TabId,TabText) VALUES(2,1,NULL);"
            f"INSERT INTO `{schema}`.worldstates(entry,value,comment) VALUES(2,1,NULL);"
            f"UPDATE `{schema}`.account_data SET data=X'';")
        # Unrelated custom objects are left alone rather than becoming blockers.
        run(f"ALTER TABLE `{schema}`.characters ADD transmog_test INT DEFAULT 42;"
            f"CREATE TABLE `{schema}`.custom_feature(id INT PRIMARY KEY,value VARCHAR(20));"
            f"INSERT INTO `{schema}`.custom_feature VALUES(1,'KEEP CUSTOM');")
        before = snapshot()
        # Deny the final UPDATE after earlier writes, including cache payload/time.
        # Batch mysql must disconnect before COMMIT and roll all of them back.
        run(f"CREATE USER '{user}'@'%'; GRANT SELECT ON `{schema}`.* TO '{user}'@'%';")
        for t in sorted({t for t, _, _ in rules}):
            cols = ','.join(f'`{c}`' for rt, c, _ in rules
                            if rt == t and (t, c) != ('worldstates', 'comment'))
            if cols:
                run(f"GRANT UPDATE ({cols}) ON `{schema}`.`{t}` TO '{user}'@'%';")
        failed = apply(good=False, who=user)
        assert ('denied' in failed.stderr and 'worldstates' in failed.stderr
                and 'Character sharing copy redacted' not in failed.stdout), failed.stderr
        assert snapshot() == before
        passed('late UPDATE denial rolls back all prior redactions')

        report = apply().stdout
        assert 'Character sharing copy redacted' in report and 'SECRET' not in report
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
        assert run(f'SELECT transmog_test FROM `{schema}`.characters').stdout.strip() == '42'
        assert run(f'SELECT value FROM `{schema}`.custom_feature').stdout.strip() == 'KEEP CUSTOM'
        passed('custom columns/tables preserved without requiring a special schema name or routines')
        assert 'Character sharing copy redacted' in apply().stdout and snapshot() == after
        passed('rerun is idempotent')

        # Exercise the operator's actual export/restore workflow and check every
        # retained/redacted stock field again on the exported representation.
        args = [x for x in options if x not in (
            '--skip-column-names', '--skip-force', '--batch', '--binary-as-hex')]
        dump = subprocess.run(['mysqldump', *args, '--single-transaction', '--quick',
            '--hex-blob', '--skip-routines', '--skip-events', '--skip-triggers',
            '--no-tablespaces', '--set-gtid-purged=OFF', schema], capture_output=True, text=True)
        assert dump.returncode == 0, dump.stderr
        assert 'SECRET' not in dump.stdout and 'migrator_redact_character_share' not in dump.stdout
        restore = prefix + '_restore'
        run(f'CREATE DATABASE `{restore}`;')
        owned.append(restore)
        run(f'USE `{restore}`;\n' + dump.stdout)
        original_schema = schema
        schema = restore
        assert snapshot() == after
        assert run(f'SELECT value FROM `{schema}`.custom_feature').stdout.strip() == 'KEEP CUSTOM'
        schema = original_schema
        passed('real dump/restore contains no secret sentinels and preserves expected state')
        print(f'Character share MySQL tests passed ({len(checks)} groups).', flush=True)
    finally:
        run(f"DROP USER IF EXISTS '{user}'@'%';")
        for db in reversed(owned):
            run(f'DROP DATABASE `{db}`;')


if __name__ == '__main__':
    main()
