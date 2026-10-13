#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEST_ROOT=$(mktemp -d)
trap 'rm -rf "$TEST_ROOT"' EXIT
cat > "$TEST_ROOT/mysqldump" <<'EOF'
#!/usr/bin/env bash
printf 'partial untrusted DDL\n'
exit 1
EOF
chmod +x "$TEST_ROOT/mysqldump"

if output=$(PATH="$TEST_ROOT:$PATH" bash -c '
    set -Eeuo pipefail
    source "$1/lib/common.sh"
    mysql_query() { printf "events\t0\nroutines\t0\n"; }
    MYSQLDUMP_ARGS=()
    # Exercise the substitution context which suppresses implicit errexit.
    result=$(schema_fingerprint fixture)
    printf "%s\n" "$result"
' _ "$ROOT" 2>&1); then
    printf 'A failed schema dump produced a trusted fingerprint\n' >&2
    exit 1
fi
[[ $output == *'Could not capture complete DDL'* ]]

if output=$(bash -c '
    set -Eeuo pipefail
    source "$1/lib/common.sh"
    mysql_query() { return 1; }
    result=$(schema_dump_object_arguments fixture)
    printf "%s\n" "$result"
' _ "$ROOT" 2>&1); then
    printf 'A failed object inventory was accepted\n' >&2
    exit 1
fi
[[ $output == *'Could not inventory schema objects'* ]]
printf 'Schema dump failure checks passed.\n'
