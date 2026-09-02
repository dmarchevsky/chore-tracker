#!/usr/bin/env bash
#
# Restore a ChoreKeeper backup. Two modes, and the difference between them is the whole point:
#
#   verify <dir>                  restore into a THROWAWAY postgres, compare every row count
#                                 and every child's balance against the manifest, tear it down.
#                                 Touches no stack and no volume. This is the Phase 6
#                                 acceptance test (spec §14) and is safe to run any time.
#
#   apply <dir> <stack> <confirm> DESTROY the stack's database and replace it with the backup.
#                                 Refuses without confirm=overwrite-production. CLAUDE.md
#                                 requires explicit per-run approval for exactly this.
#
# An untested backup is a rumour, so `verify` exists to be run on a schedule you keep, and
# `apply` exists to be run once, badly, at 2am — which is why it prints what it is about to
# destroy before it does anything.

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
source scripts/common.sh

MODE="${1:-}"
DIR="${2:-}"

[[ -n "$MODE" && -n "$DIR" ]] || die "usage: restore.sh verify <dir> | restore.sh apply <dir> <stack> <confirm>"
[[ -d "$DIR" ]] || die "no such backup directory: $DIR"
for f in db.dump media.tar.gz manifest.json; do
    [[ -s "$DIR/$f" ]] || die "$DIR is not a backup — $f is missing or empty"
done

# --- integrity ------------------------------------------------------------------------
# Checked before anything is restored anywhere. A truncated dump that restores "successfully"
# into production is the failure this exists to prevent.
verify_checksums() {
    local want_db want_media
    want_db="$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['sha256']['db.dump'])" "$DIR/manifest.json")"
    want_media="$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['sha256']['media.tar.gz'])" "$DIR/manifest.json")"
    [[ "$(sha256sum "$DIR/db.dump" | cut -d' ' -f1)" == "$want_db" ]] \
        || die "db.dump does not match its checksum in manifest.json — the backup is corrupt"
    [[ "$(sha256sum "$DIR/media.tar.gz" | cut -d' ' -f1)" == "$want_media" ]] \
        || die "media.tar.gz does not match its checksum in manifest.json — the backup is corrupt"
    log "checksums match the manifest"
}

# ======================================================================================
# verify — restore into a throwaway Postgres and check the numbers
# ======================================================================================
if [[ "$MODE" == verify ]]; then
    verify_checksums

    IMAGE="$(grep -oE 'postgres:[0-9.]+' docker-compose.prod.yml | head -1)"
    IMAGE="${IMAGE:-postgres:17}"
    NAME="chorekeeper-verify-$$"
    # No published port and no volume: it exists only inside this script's lifetime, so it
    # cannot collide with a running stack or outlive a failure.
    cleanup() { docker rm -f "$NAME" >/dev/null 2>&1 || true; }
    trap cleanup EXIT

    log "starting a throwaway $IMAGE as $NAME"
    docker run -d --rm --name "$NAME" \
        -e POSTGRES_USER=chore -e POSTGRES_PASSWORD=verify -e POSTGRES_DB=chore \
        "$IMAGE" >/dev/null
    for _ in $(seq 1 60); do
        docker exec "$NAME" pg_isready -U chore -d chore >/dev/null 2>&1 && break
        sleep 1
    done
    docker exec "$NAME" pg_isready -U chore -d chore >/dev/null 2>&1 \
        || die "the throwaway Postgres never became ready"

    log "restoring db.dump into it"
    # --no-owner/--no-acl: the roles from the source cluster do not exist here, and an
    # ownership error is not a reason to call a good backup bad.
    docker exec -i "$NAME" pg_restore -U chore -d chore --no-owner --no-acl < "$DIR/db.dump" \
        || warn "pg_restore reported errors — the comparison below is what decides"

    log "reading the restored numbers back"
    docker exec -i "$NAME" psql -U chore -d chore -At -c "$COUNT_SQL" > "$DIR/.verify-counts.json"
    echo
    # `|| RC=$?` rather than `RC=$?`: under `set -e` a non-zero exit would end the script
    # before the status could be read, and a failed verification must be REPORTED, not silent.
    RC=0
    python3 scripts/manifest.py --compare "$DIR" "$DIR/.verify-counts.json" || RC=$?
    rm -f "$DIR/.verify-counts.json"

    echo
    if [[ $RC -eq 0 ]]; then
        log "VERIFIED — this backup restores into a clean environment and reproduces every balance"
    else
        die "VERIFICATION FAILED — do not rely on this backup"
    fi
    exit 0
fi

# ======================================================================================
# apply — overwrite a real stack
# ======================================================================================
[[ "$MODE" == apply ]] || die "unknown mode '$MODE' — expected 'verify' or 'apply'"

STACK="${3:-}"
CONFIRM="${4:-}"
[[ -n "$STACK" ]] || die "apply needs a stack: prod or dev"

CMP="$(compose_for "$STACK")"
DB_USER="$(db_user_for "$STACK")"
DB_NAME="$(db_name_for "$STACK")"
if [[ "$STACK" == prod ]]; then VOLUME=chorekeeper_media_data; else VOLUME=chorekeeper_dev_media_data; fi

require_db_running "$STACK"
verify_checksums

echo
warn "about to REPLACE the '$STACK' stack's data. This cannot be undone."
echo "    database volume : $([[ $STACK == prod ]] && echo chorekeeper_db_data || echo chorekeeper_dev_db_data)"
echo "    media volume    : $VOLUME"
echo "    restoring from  : $DIR"
echo
echo "  what is in that stack RIGHT NOW:"
CURRENT="$(mktemp)"
trap 'rm -f "$CURRENT"' EXIT
$CMP exec -T db psql -U "$DB_USER" -d "$DB_NAME" -At -c "$COUNT_SQL" > "$CURRENT" 2>/dev/null || true
python3 - "$CURRENT" <<'PY' || true
import json, sys
c = json.load(open(sys.argv[1]))
for k in ("users", "chores", "chore_occurrences", "ledger_entries", "submissions"):
    print(f"    {k:<17}: {c[k]}")
for name, cents in sorted(c["balances"].items()):
    print(f"    balance {name:<9}: {cents / 100:.2f}")
PY
echo

if [[ "$CONFIRM" != "overwrite-production" ]]; then
    die "refusing without explicit confirmation. If those numbers are what you mean to destroy, re-run:
         just restore $DIR $STACK overwrite-production"
fi

# The worker ticks every minute against this database. Restoring underneath a live worker is
# how a scheduler pass lands mid-schema and throws NoResultFound; stop them first.
log "stopping api and worker"
$CMP stop api worker >/dev/null

log "dropping and recreating the database"
$CMP exec -T db psql -U "$DB_USER" -d postgres -c "drop database if exists \"$DB_NAME\" with (force)" >/dev/null
$CMP exec -T db psql -U "$DB_USER" -d postgres -c "create database \"$DB_NAME\" owner \"$DB_USER\"" >/dev/null

log "restoring the database"
$CMP exec -T db pg_restore -U "$DB_USER" -d "$DB_NAME" --no-owner --no-acl < "$DIR/db.dump" \
    || warn "pg_restore reported errors — check the comparison below"

# Extract OVER the existing files rather than wiping first. Media is content-addressed — a
# given sha256 is always the same bytes — so unpacking on top is idempotent and can never
# produce a wrong file, while "wipe, then extract" has a window where a failed extraction has
# already destroyed the photos. Anything deleted since the backup simply lingers, and the
# retention job (services/retention.py) is what removes those anyway.
log "restoring media into $VOLUME"
docker run --rm -i -v "${VOLUME}:/m" alpine tar -xzf - -C /m < "$DIR/media.tar.gz"

log "starting api and worker"
$CMP start api worker >/dev/null

log "checking the restored data against the manifest"
sleep 3
$CMP exec -T db psql -U "$DB_USER" -d "$DB_NAME" -At -c "$COUNT_SQL" > "$DIR/.applied-counts.json"
echo
RC=0
python3 scripts/manifest.py --compare "$DIR" "$DIR/.applied-counts.json" || RC=$?
rm -f "$DIR/.applied-counts.json"
echo
[[ $RC -eq 0 ]] || die "the restored stack does NOT match the backup"
log "restore complete and verified"
