#!/usr/bin/env bash

set -Eeuo pipefail
export LC_ALL=C

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPATIBILITY_PROFILE=${COMPATIBILITY_PROFILE:-tc335-acwotlk-v2}
PROFILE="$ROOT/compatibility/$COMPATIBILITY_PROFILE"
TC_SOURCE=${TRINITYCORE_DIR:-"$ROOT/../TrinityCore"}
AC_SOURCE=${AZEROTHCORE_DIR:-"$ROOT/../azerothcore-wotlk"}
TEST_ROOT=$(mktemp -d)
trap 'rm -rf "$TEST_ROOT"' EXIT
# shellcheck source=tests/test-support.sh
source "$ROOT/tests/test-support.sh"
prepare_test_toolkit "$TEST_ROOT/toolkit"
TEST_TOOLKIT="$TEST_ROOT/toolkit"

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
write_test_config "$config" "$tc" "$ac"

expect_pass() {
    "$TEST_TOOLKIT/bin/migrate.sh" --config "$config" compatibility >/dev/null 2>&1 || {
        printf 'Expected compatibility success: %s\n' "$1" >&2
        exit 1
    }
}

expect_fail() {
    local output report
    if output=$("$TEST_TOOLKIT/bin/migrate.sh" --config "$config" compatibility 2>&1); then
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

for relative in src/server/game/Entities/Item/Item.h \
    src/server/game/Entities/Item/ItemDefines.h src/server/game/Entities/Item/Container/Bag.cpp \
    src/server/game/Entities/Corpse/Corpse.cpp src/server/game/Mails/Mail.h \
    src/server/game/Loot/LootItemStorage.cpp src/server/game/Battlegrounds/ArenaTeam.cpp \
    src/server/game/Guilds/GuildMgr.cpp src/server/game/Spells/SpellMgr.cpp \
    src/server/game/Spells/SpellInfo.cpp src/server/shared/DataStores/DBCfmt.h \
    src/server/game/Entities/Creature/Trainer.cpp \
    src/server/game/Spells/SpellDefines.h src/server/game/Spells/Auras/SpellAuraDefines.h \
    src/server/scripts/Outland/Auchindoun/ShadowLabyrinth/boss_murmur.cpp; do
    printf '%s\n' '// protected format-2 change' >> "$tc/$relative"
    expect_fail "expanded-reader:$relative"
    git -C "$tc" checkout -q -- "$relative"
done

approval_file="$TEST_TOOLKIT/compatibility/$COMPATIBILITY_PROFILE/profile.env"
sed -i 's/^PROFILE_APPROVAL=APPROVED$/PROFILE_APPROVAL=UNREVIEWED/' "$approval_file"
if output=$("$TEST_TOOLKIT/bin/migrate.sh" --config "$config" compatibility 2>&1); then
    printf 'Unreviewed profile was accepted\n' >&2
    exit 1
fi
[[ $output == *'not approved'* ]]
sed -i 's/^PROFILE_APPROVAL=UNREVIEWED$/PROFILE_APPROVAL=APPROVED/' "$approval_file"
cp "$config" "$TEST_ROOT/retired.env"
printf 'COMPATIBILITY_PROFILE=tc335-acwotlk-v1\n' >> "$TEST_ROOT/retired.env"
if output=$("$TEST_TOOLKIT/bin/migrate.sh" --config "$TEST_ROOT/retired.env" compatibility 2>&1); then
    printf 'Retired profile was accepted\n' >&2
    exit 1
fi
[[ $output == *'retired'* && $output == *'older toolkit'* ]]

"$TEST_TOOLKIT/bin/generate-compatibility-profile.sh" "$tc" "$ac" \
    "$COMPATIBILITY_PROFILE" "$TEST_ROOT/generated" >/dev/null
rg -q '^PROFILE_FORMAT=2$' "$TEST_ROOT/generated/$COMPATIBILITY_PROFILE/profile.env"
rg -q '^PROFILE_APPROVAL=UNREVIEWED$' "$TEST_ROOT/generated/$COMPATIBILITY_PROFILE/profile.env"
for manifest in "$PROFILE"/*.sha256 "$PROFILE"/*.tables; do
    cmp "$manifest" "$TEST_ROOT/generated/$COMPATIBILITY_PROFILE/$(basename "$manifest")"
done
cmp "$PROFILE/spell-metadata.json" "$TEST_ROOT/generated/$COMPATIBILITY_PROFILE/spell-metadata.json"

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
command_output=$("$TEST_TOOLKIT/bin/migrate.sh" --config "$config" compatibility 2>&1)
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
' _ "$TEST_TOOLKIT" "$config" "$ac" >/dev/null 2>&1; then
    printf 'Expected checkout movement to invalidate loaded state\n' >&2
    exit 1
fi

printf 'Compatibility profile behavior tests passed.\n'
