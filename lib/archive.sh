#!/usr/bin/env bash

archive_source_only_table() {
    local kind=$1 schema=$2 table=$3 schema_hash=$4 archive_root=$5 approval=$6
    local rows
    rows=$(source_snapshot_count "$kind" "$table")
    [[ $rows != 0 ]] || return 0

    [[ $ALLOW_SOURCE_ARCHIVE == 1 ]] ||
        die "$schema.$table has $rows unsupported row(s); set ALLOW_SOURCE_ARCHIVE=1 after review"
    [[ $approval != REVIEW_REQUIRED || $ALLOW_GAMEPLAY_ARCHIVE == 1 ]] ||
        die "$schema.$table contains gameplay-bearing unsupported data; review it and set ALLOW_GAMEPLAY_ARCHIVE=1"

    local relative="${kind}-${table}.sql.gz"
    local destination="$archive_root/$relative"
    local recorded_hash
    recorded_hash=$(mysql_query -e "
        SELECT COALESCE(MAX(dump_sha256),'')
        FROM \`$CONTROL_SCHEMA\`.archive_manifest
        WHERE run_id='$(sql_escape "$RUN_ID")'
          AND database_kind='$(sql_escape "$kind")'
          AND source_table='$(sql_escape "$table")';")
    if [[ -n $recorded_hash && -f $destination &&
          $(sha256sum "$destination" | awk '{print $1}') == "$recorded_hash" ]]; then
        log "Skipping verified archive: $schema.$table"
        return 0
    fi

    local temporary="$destination.tmp"
    umask 077
    mysqldump "${MYSQLDUMP_ARGS[@]}" \
        --single-transaction --quick --hex-blob --skip-comments \
        --set-gtid-purged=OFF "$schema" "$table" |
        gzip -9 > "$temporary"
    chmod 0600 "$temporary"
    local hash
    hash=$(sha256sum "$temporary" | awk '{print $1}')
    mv "$temporary" "$destination"

    mysql_query -e "
        INSERT INTO \`$CONTROL_SCHEMA\`.archive_manifest
            (run_id,database_kind,source_table,row_count,dump_path,
             dump_sha256,schema_fingerprint)
        VALUES
            ('$(sql_escape "$RUN_ID")','$(sql_escape "$kind")',
             '$(sql_escape "$table")',$rows,'$(sql_escape "$destination")',
             '$hash','$schema_hash') AS new
        ON DUPLICATE KEY UPDATE
            row_count=new.row_count,dump_path=new.dump_path,
            dump_sha256=new.dump_sha256,
            schema_fingerprint=new.schema_fingerprint,
            archived_at=UTC_TIMESTAMP();"
    log "Archived $rows unsupported row(s) from $schema.$table"
}

perform_archive_unsupported() {
    require_phase preflight
    require_command gzip
    check_quiescence

    local archive_root=
    local has_rows=0
    local kind schema mapping source_table _target _sc _tc _expr _defaults
    local _group disposition _validation _approval rows
    for kind in auth characters; do
        schemas_for_kind "$kind"
        schema=$SOURCE_SCHEMA
        mapping=$(mapping_file_for "$kind")
        while IFS=, read -r source_table _target _sc _tc _expr _defaults \
            _group disposition _validation _approval; do
            [[ $source_table == source_table || $disposition != SOURCE_ARCHIVE ]] && continue
            rows=$(source_snapshot_count "$kind" "$source_table")
            (( rows == 0 )) || has_rows=1
        done < "$mapping"
    done

    if (( has_rows == 0 )); then
        log "No nonempty unsupported source tables require archival"
        return 0
    fi

    [[ -n $ARCHIVE_DIR ]] ||
        die "ARCHIVE_DIR is required because unsupported source tables contain data"
    archive_root=$(absolute_path "$ARCHIVE_DIR")/"$RUN_ID"
    [[ $archive_root != "$MIGRATION_ROOT"/* ]] ||
        die "ARCHIVE_DIR must be outside the migration repository"
    mkdir -p "$archive_root"
    chmod 0700 "$archive_root"

    for kind in auth characters; do
        schemas_for_kind "$kind"
        schema=$SOURCE_SCHEMA
        mapping=$(mapping_file_for "$kind")
        local schema_hash
        schema_hash=$(schema_fingerprint "$schema")
        while IFS=, read -r source_table _target _sc _tc _expr _defaults \
            _group disposition _validation _approval; do
            [[ $source_table == source_table || $disposition != SOURCE_ARCHIVE ]] && continue
            archive_source_only_table "$kind" "$schema" "$source_table" \
                "$schema_hash" "$archive_root" "$_approval"
        done < "$mapping"
    done

    mysql "${MYSQL_ARGS[@]}" --batch --raw -e "
        SELECT database_kind,source_table,row_count,dump_path,dump_sha256,
               schema_fingerprint,archived_at
        FROM \`$CONTROL_SCHEMA\`.archive_manifest
        WHERE run_id='$(sql_escape "$RUN_ID")'
        ORDER BY database_kind,source_table;" \
        > "$archive_root/manifest.tsv"
    chmod 0600 "$archive_root/manifest.tsv"
    sha256sum "$archive_root/manifest.tsv" > "$archive_root/manifest.tsv.sha256"
    chmod 0600 "$archive_root/manifest.tsv.sha256"
    log "Unsupported-data archive complete: $archive_root"
}
