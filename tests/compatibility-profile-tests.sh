#!/usr/bin/env bash

set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROFILE="$ROOT/compatibility/tc335-acwotlk-v1"
TC_SOURCE=${TRINITYCORE_DIR:-"$ROOT/../TrinityCore"}
AC_SOURCE=${AZEROTHCORE_DIR:-"$ROOT/../azerothcore-wotlk"}
TEST_ROOT=$(mktemp -d)
trap 'rm -rf "$TEST_ROOT"' EXIT

copy_manifest_files() {
    local manifest=$1 source=$2 destination=$3 relative
    while read -r _ relative; do
        [[ -n ${relative:-} ]] || continue
        mkdir -p "$destination/$(dirname "$relative")"
        cp "$source/$relative" "$destination/$relative"
    done < "$manifest"
}

prepare_repository() {
    local repository=$1
    git -C "$repository" init -q
    git -C "$repository" add .
    git -C "$repository" -c user.name=compatibility-test \
        -c user.email=compatibility@example.invalid -c commit.gpgsign=false \
        commit -qm baseline
}

tc="$TEST_ROOT/TrinityCore"
ac="$TEST_ROOT/azerothcore-wotlk"
mkdir -p "$tc" "$ac"
copy_manifest_files "$PROFILE/trinitycore-sql.sha256" "$TC_SOURCE" "$tc"
copy_manifest_files "$PROFILE/trinitycore-semantic.sha256" "$TC_SOURCE" "$tc"
copy_manifest_files "$PROFILE/azerothcore-sql.sha256" "$AC_SOURCE" "$ac"
copy_manifest_files "$PROFILE/azerothcore-semantic.sha256" "$AC_SOURCE" "$ac"
prepare_repository "$tc"
prepare_repository "$ac"

config="$TEST_ROOT/migration.env"
sed -e "s#^TRINITYCORE_DIR=.*#TRINITYCORE_DIR=$tc#" \
    -e "s#^AZEROTHCORE_DIR=.*#AZEROTHCORE_DIR=$ac#" \
    "$ROOT/tests/rehearsal.env" > "$config"

expect_pass() {
    "$ROOT/bin/migrate.sh" --config "$config" compatibility >/dev/null 2>&1 || {
        printf 'Expected compatibility success: %s\n' "$1" >&2
        exit 1
    }
}

expect_fail() {
    local output report
    if output=$("$ROOT/bin/migrate.sh" --config "$config" compatibility 2>&1); then
        printf 'Expected compatibility failure: %s\n' "$1" >&2
        exit 1
    fi
    report=${output##*see }
    report=${report%%$'\n'*}
    [[ -f $report && -f ${report%.tsv}-diff.txt ]] || {
        printf 'Compatibility failure did not produce reports: %s\n' "$1" >&2
        exit 1
    }
    rg -q $'\tFAIL$' "$report"
}

expect_pass baseline

mkdir -p "$ac/data/sql/updates/db_world" "$ac/src/server/game"
printf '%s\n' '-- world-only compatibility fixture' > "$ac/data/sql/updates/db_world/test.sql"
printf '%s\n' '// unrelated compatibility fixture' > "$ac/src/server/game/Unrelated.cpp"
expect_pass world-and-unrelated-content

printf '%s\n' '-- protected change' >> "$ac/data/sql/base/db_auth/account.sql"
expect_fail modified-auth-sql
git -C "$ac" checkout -q -- data/sql/base/db_auth/account.sql

printf '%s\n' '// protected change' >> \
    "$tc/src/server/database/Database/Implementation/LoginDatabase.cpp"
expect_fail modified-semantic-reader
git -C "$tc" checkout -q -- src/server/database/Database/Implementation/LoginDatabase.cpp

printf '%s\n' '-- untracked protected update' > "$tc/sql/updates/auth/3.3.5/test.sql"
expect_fail untracked-auth-sql
rm -f "$tc/sql/updates/auth/3.3.5/test.sql"

printf '%s\n' '// item_loot_storage semantic addition' > \
    "$ac/src/server/game/NewMigrationSemantic.cpp"
expect_fail added-semantic-reader
rm -f "$ac/src/server/game/NewMigrationSemantic.cpp"

git -C "$ac" add data/sql/updates/db_world/test.sql src/server/game/Unrelated.cpp
git -C "$ac" -c user.name=compatibility-test \
    -c user.email=compatibility@example.invalid -c commit.gpgsign=false \
    commit -qm unrelated
new_revision=$(git -C "$ac" rev-parse HEAD)
command_output=$("$ROOT/bin/migrate.sh" --config "$config" compatibility 2>&1)
report=${command_output##*Wrote }
rg -q "azerothcore-revision.*$new_revision.*INFO" "$report"

if bash -c '
    set -Eeuo pipefail
    source "$1/lib/common.sh"
    source "$1/lib/compatibility.sh"
    load_configuration "$2"
    printf "%s\n" "// second unrelated commit" > "$3/src/server/game/AnotherUnrelated.cpp"
    git -C "$3" add src/server/game/AnotherUnrelated.cpp
    git -C "$3" -c user.name=compatibility-test \
        -c user.email=compatibility@example.invalid -c commit.gpgsign=false \
        commit -qm moved
    verify_repository_revisions
' _ "$ROOT" "$config" "$ac" >/dev/null 2>&1; then
    printf 'Expected checkout movement to invalidate loaded state\n' >&2
    exit 1
fi

printf 'Compatibility profile behavior tests passed.\n'
