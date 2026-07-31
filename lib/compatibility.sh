#!/usr/bin/env bash
# shellcheck disable=SC2034 # State is consumed by other sourced runner modules.

COMPATIBILITY_SEMANTIC_PATTERN='SRP6|verifier|session_key_auth|session_key|character_talent|specMask|character_spell_cooldown|pet_spell_cooldown|item_loot_(storage|items|money)|channels_bans|joinAnnouncement|character_battleground_data|entryPointX|extendState|petition_id|petitionguid|creature_respawn|gameobject_respawn'

manifest_digest() {
    sha256sum "$1" | awk '{print $1}'
}

write_path_manifest() {
    local repository=$1 destination=$2 mode=$3
    shift 3
    local inventory
    inventory=$(mktemp)
    : > "$inventory"

    local relative absolute found
    for relative in "$@"; do
        absolute="$repository/$relative"
        [[ -e $absolute ]] || die "Compatibility input is absent: $absolute"
        if [[ -L $absolute ]]; then
            die "Compatibility inputs must not be symbolic links: $absolute"
        elif [[ -d $absolute ]]; then
            find "$absolute" -type l -print -quit | grep -q . &&
                die "Compatibility input tree contains a symbolic link: $absolute"
            if [[ $mode == sql ]]; then
                while IFS= read -r -d '' found; do
                    printf '%s\n' "${found#"$repository"/}" >> "$inventory"
                done < <(find "$absolute" -type f -name '*.sql' -print0)
            else
                while IFS= read -r -d '' found; do
                    printf '%s\n' "${found#"$repository"/}" >> "$inventory"
                done < <(find "$absolute" -type f \
                    \( -name '*.cpp' -o -name '*.h' \) -print0)
            fi
        else
            printf '%s\n' "$relative" >> "$inventory"
        fi
    done

    if [[ $mode == semantic ]]; then
        while IFS= read -r -d '' found; do
            printf '%s\n' "${found#"$repository"/}" >> "$inventory"
        done < <(rg -l -0 --glob '*.{cpp,h}' "$COMPATIBILITY_SEMANTIC_PATTERN" \
            "$repository/src/server" || true)
    fi

    LC_ALL=C sort -u "$inventory" -o "$inventory"
    : > "$destination"
    while IFS= read -r relative; do
        [[ -n $relative ]] || continue
        absolute="$repository/$relative"
        [[ -f $absolute && ! -L $absolute && -r $absolute ]] ||
            die "Compatibility input is not a readable regular file: $absolute"
        printf '%s  %s\n' "$(sha256sum "$absolute" | awk '{print $1}')" "$relative" \
            >> "$destination"
    done < "$inventory"
    rm -f "$inventory"
}

write_trinitycore_semantic_manifest() {
    local destination=$1
    write_path_manifest "$TRINITYCORE_DIR" "$destination" semantic \
        src/server/database/Database/Implementation/CharacterDatabase.cpp \
        src/server/database/Database/Implementation/CharacterDatabase.h \
        src/server/database/Database/Implementation/LoginDatabase.cpp \
        src/server/database/Database/Implementation/LoginDatabase.h \
        src/server/authserver/Server/AuthSession.cpp \
        src/server/authserver/Server/AuthSession.h \
        src/server/game/Accounts/AccountMgr.cpp \
        src/server/game/Accounts/AccountMgr.h \
        src/server/game/Battlegrounds/Battleground.cpp \
        src/server/game/Chat/Channels/Channel.cpp \
        src/server/game/Chat/Channels/Channel.h \
        src/server/game/Chat/Channels/ChannelMgr.cpp \
        src/server/game/Chat/Channels/ChannelMgr.h \
        src/server/game/Entities/Player/Player.cpp \
        src/server/game/Entities/Player/Player.h \
        src/server/game/Handlers/PetitionsHandler.cpp \
        src/server/game/Instances/InstanceSaveMgr.cpp \
        src/server/game/Maps/Map.cpp \
        src/server/game/Petitions/PetitionMgr.cpp \
        src/server/game/Spells/SpellHistory.cpp \
        src/server/game/Spells/SpellHistory.h
}

write_azerothcore_semantic_manifest() {
    local destination=$1
    write_path_manifest "$AZEROTHCORE_DIR" "$destination" semantic \
        src/server/database/Database/Implementation/CharacterDatabase.cpp \
        src/server/database/Database/Implementation/CharacterDatabase.h \
        src/server/database/Database/Implementation/LoginDatabase.cpp \
        src/server/database/Database/Implementation/LoginDatabase.h \
        src/server/apps/authserver/Server/AuthSession.cpp \
        src/server/apps/authserver/Server/AuthSession.h \
        src/server/game/Accounts/AccountMgr.cpp \
        src/server/game/Accounts/AccountMgr.h \
        src/server/game/Battlegrounds/Battleground.cpp \
        src/server/game/Chat/Channels/Channel.cpp \
        src/server/game/Chat/Channels/Channel.h \
        src/server/game/Chat/Channels/ChannelMgr.cpp \
        src/server/game/Chat/Channels/ChannelMgr.h \
        src/server/game/Entities/Pet/Pet.cpp \
        src/server/game/Entities/Player/Player.cpp \
        src/server/game/Entities/Player/Player.h \
        src/server/game/Entities/Player/PlayerStorage.cpp \
        src/server/game/Handlers/PetitionsHandler.cpp \
        src/server/game/Instances/InstanceSaveMgr.cpp \
        src/server/game/Petitions/PetitionMgr.cpp \
        src/server/game/Spells/SpellMgr.cpp \
        src/server/game/World/World.cpp
}

load_compatibility_profile() {
    [[ $COMPATIBILITY_PROFILE =~ ^[A-Za-z0-9._-]+$ ]] ||
        die "COMPATIBILITY_PROFILE contains unsafe characters"
    COMPATIBILITY_PROFILE_DIR="$MIGRATION_ROOT/compatibility/$COMPATIBILITY_PROFILE"
    local profile_file="$COMPATIBILITY_PROFILE_DIR/profile.env"
    [[ -r $profile_file ]] || die "Unknown compatibility profile: $COMPATIBILITY_PROFILE"

    # shellcheck disable=SC1090
    source "$profile_file"
    [[ ${PROFILE_FORMAT:-} == 1 ]] || die "Unsupported compatibility profile format"
    [[ ${PROFILE_ID:-} == "$COMPATIBILITY_PROFILE" ]] ||
        die "Compatibility profile ID does not match its directory"
    [[ ${PROFILE_APPROVAL:-} == APPROVED ]] ||
        die "Compatibility profile is not approved: $COMPATIBILITY_PROFILE"

    local required=(
        TRINITYCORE_SQL_MANIFEST TRINITYCORE_SEMANTIC_MANIFEST
        AZEROTHCORE_SQL_MANIFEST AZEROTHCORE_SEMANTIC_MANIFEST
        TRINITYCORE_AUTH_TABLES TRINITYCORE_CHARACTERS_TABLES
        AZEROTHCORE_AUTH_TABLES AZEROTHCORE_CHARACTERS_TABLES
    ) name
    for name in "${required[@]}"; do
        [[ -n ${!name:-} ]] || die "Compatibility profile is missing $name"
        [[ ${!name} =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] ||
            die "Compatibility profile artifact name is unsafe: ${!name}"
        [[ -r "$COMPATIBILITY_PROFILE_DIR/${!name}" ]] ||
            die "Compatibility profile artifact is unreadable: ${!name}"
    done
    [[ ${REVIEWED_TRINITYCORE_REVISION:-} =~ ^[0-9a-f]{40}$ ]] ||
        die "Compatibility profile has an invalid reviewed TrinityCore revision"
    [[ ${REVIEWED_AZEROTHCORE_REVISION:-} =~ ^[0-9a-f]{40}$ ]] ||
        die "Compatibility profile has an invalid reviewed AzerothCore revision"
}

capture_repository_compatibility_state() {
    require_command git
    require_command rg
    require_command sha256sum

    TRINITYCORE_REVISION=$(git -C "$TRINITYCORE_DIR" rev-parse HEAD 2>/dev/null) ||
        die "TRINITYCORE_DIR is not a Git checkout"
    AZEROTHCORE_REVISION=$(git -C "$AZEROTHCORE_DIR" rev-parse HEAD 2>/dev/null) ||
        die "AZEROTHCORE_DIR is not a Git checkout"
    [[ $TRINITYCORE_REVISION =~ ^[0-9a-f]{40}$ ]] || die "Invalid TrinityCore revision"
    [[ $AZEROTHCORE_REVISION =~ ^[0-9a-f]{40}$ ]] || die "Invalid AzerothCore revision"

    COMPATIBILITY_WORK_DIR=$(mktemp -d)
    write_path_manifest "$TRINITYCORE_DIR" "$COMPATIBILITY_WORK_DIR/trinitycore-sql.sha256" sql \
        sql/base/auth_database.sql sql/base/characters_database.sql \
        sql/updates/auth/3.3.5 sql/updates/characters/3.3.5
    write_path_manifest "$AZEROTHCORE_DIR" "$COMPATIBILITY_WORK_DIR/azerothcore-sql.sha256" sql \
        data/sql/base/db_auth data/sql/base/db_characters \
        data/sql/updates/db_auth data/sql/updates/db_characters
    write_trinitycore_semantic_manifest \
        "$COMPATIBILITY_WORK_DIR/trinitycore-semantic.sha256"
    write_azerothcore_semantic_manifest \
        "$COMPATIBILITY_WORK_DIR/azerothcore-semantic.sha256"

    TRINITYCORE_SQL_DIGEST=$(manifest_digest "$COMPATIBILITY_WORK_DIR/trinitycore-sql.sha256")
    TRINITYCORE_SEMANTIC_DIGEST=$(manifest_digest "$COMPATIBILITY_WORK_DIR/trinitycore-semantic.sha256")
    AZEROTHCORE_SQL_DIGEST=$(manifest_digest "$COMPATIBILITY_WORK_DIR/azerothcore-sql.sha256")
    AZEROTHCORE_SEMANTIC_DIGEST=$(manifest_digest "$COMPATIBILITY_WORK_DIR/azerothcore-semantic.sha256")
}

verify_compatibility_component() {
    local label=$1 expected=$2 actual=$3 report=$4
    local expected_digest actual_digest status
    expected_digest=$(manifest_digest "$expected")
    actual_digest=$(manifest_digest "$actual")
    status=PASS
    if ! cmp -s "$expected" "$actual"; then
        status=FAIL
        {
            printf '\n## %s differences\n' "$label"
            diff -u "$expected" "$actual" || true
        } >> "${report%.tsv}-diff.txt"
    fi
    printf '%s\t%s\t%s\t%s\n' "$label" "$expected_digest" "$actual_digest" "$status" \
        >> "$report"
    [[ $status == PASS ]]
}

verify_repository_compatibility() {
    local report=$1 failed=0
    mkdir -p "$(dirname "$report")"
    printf 'component\texpected_digest\tactual_digest\tstatus\n' > "$report"
    printf 'trinitycore-revision\t%s\t%s\tINFO\n' \
        "$REVIEWED_TRINITYCORE_REVISION" "$TRINITYCORE_REVISION" >> "$report"
    printf 'azerothcore-revision\t%s\t%s\tINFO\n' \
        "$REVIEWED_AZEROTHCORE_REVISION" "$AZEROTHCORE_REVISION" >> "$report"
    rm -f "${report%.tsv}-diff.txt"

    verify_compatibility_component trinitycore-sql \
        "$COMPATIBILITY_PROFILE_DIR/$TRINITYCORE_SQL_MANIFEST" \
        "$COMPATIBILITY_WORK_DIR/trinitycore-sql.sha256" "$report" || failed=1
    verify_compatibility_component trinitycore-semantic \
        "$COMPATIBILITY_PROFILE_DIR/$TRINITYCORE_SEMANTIC_MANIFEST" \
        "$COMPATIBILITY_WORK_DIR/trinitycore-semantic.sha256" "$report" || failed=1
    verify_compatibility_component azerothcore-sql \
        "$COMPATIBILITY_PROFILE_DIR/$AZEROTHCORE_SQL_MANIFEST" \
        "$COMPATIBILITY_WORK_DIR/azerothcore-sql.sha256" "$report" || failed=1
    verify_compatibility_component azerothcore-semantic \
        "$COMPATIBILITY_PROFILE_DIR/$AZEROTHCORE_SEMANTIC_MANIFEST" \
        "$COMPATIBILITY_WORK_DIR/azerothcore-semantic.sha256" "$report" || failed=1

    [[ $failed == 0 ]] ||
        die "Repository content is not approved by profile $COMPATIBILITY_PROFILE; see $report"
    log "Repository content matches compatibility profile $COMPATIBILITY_PROFILE"
}

profile_table_inventory() {
    local core=$1 kind=$2
    local variable
    variable="${core^^}_${kind^^}_TABLES"
    printf '%s/%s\n' "$COMPATIBILITY_PROFILE_DIR" "${!variable}"
}

cleanup_compatibility_state() {
    if [[ -n ${COMPATIBILITY_WORK_DIR:-} && -d $COMPATIBILITY_WORK_DIR ]]; then
        rm -rf "$COMPATIBILITY_WORK_DIR"
    fi
}
