#!/usr/bin/env bash

# Only test entrypoints source this file. The production runner has no approval
# override: candidates are enabled solely in a disposable copy under /tmp.
prepare_test_toolkit() {
    local destination=$1
    [[ $destination == /tmp/* && ! -e $destination ]] || {
        printf 'Test toolkit must be a fresh directory under /tmp\n' >&2
        return 1
    }
    mkdir -p "$destination"
    cp -R "$ROOT"/{bin,lib,sql,mappings,compatibility,config,tests,tools} "$destination/"
    chmod -R u+rwX "$destination"
    local profile="$destination/compatibility/$COMPATIBILITY_PROFILE/profile.env"
    [[ -f $profile ]] || return 1
    sed -i 's/^PROFILE_APPROVAL=UNREVIEWED$/PROFILE_APPROVAL=APPROVED/' "$profile"
}

write_test_config() {
    local destination=$1 tc=$2 ac=$3
    # %q keeps paths with whitespace and shell metacharacters literal.
    cat "$ROOT/tests/rehearsal.env" > "$destination"
    {
        printf 'TRINITYCORE_DIR=%q\n' "$tc"
        printf 'AZEROTHCORE_DIR=%q\n' "$ac"
        printf 'COMPATIBILITY_PROFILE=%q\n' "$COMPATIBILITY_PROFILE"
    } >> "$destination"
}
