#!/usr/bin/env bash
# Backup of the database and the result pages to a second S3 server, see "Backups" in README.md.
#   scripts/backup.sh                  dump the database, mirror the results bucket, drop old backups (run nightly)
#   scripts/backup.sh restore DATE     put the dump of DATE (YYYY-MM-DD) and the stored pages back
# Reads .env of the deployment: BACKUP_S3_ENDPOINT, BACKUP_S3_BUCKET, BACKUP_S3_ACCESS_KEY, BACKUP_S3_SECRET_KEY
# (BACKUP_S3_REGION optional), and the POSTGRES_* and RESULTS_S3_* the compose services use.
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -f .env ]; then set -a; . ./.env; set +a; fi
: "${BACKUP_S3_ENDPOINT:?}" "${BACKUP_S3_BUCKET:?}" "${BACKUP_S3_ACCESS_KEY:?}" "${BACKUP_S3_SECRET_KEY:?}"

POSTGRES_CONTAINER=${POSTGRES_CONTAINER:-yaptide_postgresql}
GARAGE_CONTAINER=${GARAGE_CONTAINER:-yaptide_garage}
DB_USER=${POSTGRES_USER:-yaptide_user}
DB_NAME=${POSTGRES_DB:-yaptide_db}
RESULTS=results:${RESULTS_S3_BUCKET:-yaptide-results}
BACKUP=backup:$BACKUP_S3_BUCKET
DAILY_DAYS=14
WEEKLY_DAYS=56
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

# the results bucket is reached from inside the garage container's network, no port of it is published
NETWORK=bridge
if [ -n "${RESULTS_S3_ACCESS_KEY:-}" ]; then
    NETWORK=container:$GARAGE_CONTAINER
else
    echo "RESULTS_S3_ACCESS_KEY not set: the result pages are not backed up" >&2
fi

# passed to the container by name only, so the keys do not show in the process list
export RCLONE_CONFIG=/dev/null RCLONE_S3_NO_CHECK_BUCKET=true \
    RCLONE_CONFIG_BACKUP_TYPE=s3 RCLONE_CONFIG_BACKUP_PROVIDER=Other \
    RCLONE_CONFIG_BACKUP_ENDPOINT="$BACKUP_S3_ENDPOINT" RCLONE_CONFIG_BACKUP_REGION="${BACKUP_S3_REGION:-}" \
    RCLONE_CONFIG_BACKUP_ACCESS_KEY_ID="$BACKUP_S3_ACCESS_KEY" RCLONE_CONFIG_BACKUP_SECRET_ACCESS_KEY="$BACKUP_S3_SECRET_KEY" \
    RCLONE_CONFIG_RESULTS_TYPE=s3 RCLONE_CONFIG_RESULTS_PROVIDER=Other \
    RCLONE_CONFIG_RESULTS_ENDPOINT=http://localhost:3900 RCLONE_CONFIG_RESULTS_REGION=garage \
    RCLONE_CONFIG_RESULTS_ACCESS_KEY_ID="${RESULTS_S3_ACCESS_KEY:-}" \
    RCLONE_CONFIG_RESULTS_SECRET_ACCESS_KEY="${RESULTS_S3_SECRET_KEY:-}"

rclone() {
    # shellcheck disable=SC2046 # names of variables, no spaces
    docker run --rm --network "$NETWORK" -v "$WORK:/work" $(compgen -e | grep '^RCLONE_' | sed 's/^/-e /') \
        rclone/rclone:1.71.1 "$@"
}

days_ago() {
    date -d "-$1 days" +%F 2>/dev/null || date -v-"$1"d +%F
}

# removes what is under the directory and named after a date (a file or a directory) older than the given days
prune() {
    local before
    before=$(days_ago "$2")
    for name in $(rclone lsf "$BACKUP/$1/" 2>/dev/null); do
        if [[ "${name:0:10}" < "$before" ]]; then
            echo "removing $1/$name"
            if [[ "$name" == */ ]]; then rclone purge "$BACKUP/$1/$name"; else rclone deletefile "$BACKUP/$1/$name"; fi
        fi
    done
}

backup() {
    local today
    today=$(date +%F)
    echo "$(date) dumping $DB_NAME"
    docker exec "$POSTGRES_CONTAINER" pg_dump --format=custom -U "$DB_USER" "$DB_NAME" > "$WORK/$today.dump"
    # a dump that pg_restore cannot read is not a backup
    docker exec -i "$POSTGRES_CONTAINER" pg_restore --list > /dev/null < "$WORK/$today.dump"
    rclone copyto "/work/$today.dump" "$BACKUP/postgres/daily/$today.dump"
    if [ "$(date +%u)" = 7 ]; then rclone copyto "/work/$today.dump" "$BACKUP/postgres/weekly/$today.dump"; fi
    if [ "$NETWORK" != bridge ]; then
        echo "$(date) mirroring the result pages"
        # a bucket lost or emptied would empty the mirror, and its pages kept aside expire: stop instead
        local pages mirrored
        pages=$(rclone lsf -R --files-only --include "simulations/**" "$RESULTS" | wc -l)
        mirrored=$(rclone lsf -R --files-only "$BACKUP/results" | wc -l)
        if [ "$pages" -lt $((mirrored / 2)) ]; then
            echo "only $pages pages in the bucket, $mirrored in the backup: not mirrored, check the storage" >&2
            exit 1
        fi
        # objects removed or replaced in the bucket since the last run are kept aside, named after the day;
        # -M keeps Content-Encoding: gzip, without which the browser cannot read a page put back
        rclone sync -M "$RESULTS" "$BACKUP/results" --include "simulations/**" --backup-dir "$BACKUP/replaced/$today"
    fi
    prune postgres/daily "$DAILY_DAYS"
    prune postgres/weekly "$WEEKLY_DAYS"
    prune replaced "$DAILY_DAYS"
    echo "$(date) done"
}

restore() {
    local day=$1 dump
    for dump in "postgres/daily/$day.dump" "postgres/weekly/$day.dump" ""; do
        if [ -z "$dump" ]; then echo "no dump of $day" >&2; exit 1; fi
        if rclone copyto "$BACKUP/$dump" /work/restore.dump 2>/dev/null; then break; fi
    done
    read -r -p "Replace database $DB_NAME in $POSTGRES_CONTAINER with $dump? Type its name to go on: " answer
    if [ "$answer" != "$DB_NAME" ]; then echo "nothing changed" >&2; exit 1; fi
    # what is replaced is kept, so the restore can be undone
    local before
    before=postgres/before-restore/$(date +%F-%H%M%S).dump
    docker exec "$POSTGRES_CONTAINER" pg_dump --format=custom -U "$DB_USER" "$DB_NAME" > "$WORK/before.dump"
    rclone copyto /work/before.dump "$BACKUP/$before"
    echo "restoring $dump into $DB_NAME (the database before is in $before)"
    docker exec -i "$POSTGRES_CONTAINER" pg_restore --clean --if-exists --single-transaction \
        -U "$DB_USER" -d "$DB_NAME" < "$WORK/restore.dump"
    if [ "$NETWORK" != bridge ]; then
        echo "copying the result pages back"
        # only the missing ones: a page in the bucket is never replaced
        rclone copy -M --ignore-existing "$BACKUP/results" "$RESULTS"
        # pages removed since the dump: the earliest copy kept aside after that day, where none is in the bucket
        for kept in $(rclone lsf --dirs-only "$BACKUP/replaced/" 2>/dev/null); do
            if [[ ! "${kept:0:10}" < "$day" ]]; then rclone copy -M --ignore-existing "$BACKUP/replaced/$kept" "$RESULTS"; fi
        done
    fi
    echo "done"
}

case "${1:-backup}" in
    backup) backup ;;
    restore) restore "${2:?restore needs the date of a dump, YYYY-MM-DD}" ;;
    *) echo "usage: $0 [backup | restore YYYY-MM-DD]" >&2; exit 2 ;;
esac
