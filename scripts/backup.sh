#!/usr/bin/env bash
#
# Take a backup of one ChoreKeeper stack (spec §5, §14). Run it via `just backup [stack]`.
#
# One backup is one directory holding three files:
#   db.dump        pg_dump -Fc  — custom format, so pg_restore can go selective or cross-major
#   media.tar.gz   MEDIA_ROOT   — content-addressed and immutable, so a full copy is cheap
#   manifest.json  row counts, per-child balances, checksums, alembic head, git commit
#
# The manifest is the point. A dump you cannot check is a rumour: `just restore-verify` reads
# these numbers back out of a throwaway Postgres and refuses to call the restore good until
# every child's balance matches to the cent.
#
# Everything runs inside the db container, so no host-side postgres client is needed and there
# is no client/server version skew to think about.
#
# NOT included, deliberately: env.production (SESSION_SECRET, DB_PASSWORD, tunnel token). A
# dump that carries its own credentials is a worse thing to lose. See docs/restore.md.

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
source scripts/common.sh

STACK="${1:-prod}"
BACKUP_DIR="${CK_BACKUP_DIR:-backups}"

CMP="$(compose_for "$STACK")"
DB_USER="$(db_user_for "$STACK")"
DB_NAME="$(db_name_for "$STACK")"

require_db_running "$STACK"

STAMP="$(date +%Y%m%d-%H%M%S)"
DEST="${BACKUP_DIR}/chorekeeper-${STAMP}"
[[ -e "$DEST" ]] && die "$DEST already exists"
mkdir -p "$DEST"
# The dump holds the household's real ledger and every Google address in it.
chmod 700 "$DEST"

log "backing up the '$STACK' stack (db=$DB_NAME user=$DB_USER) -> $DEST"

# --- database ------------------------------------------------------------------------
# -Fc is the custom format: compressed, and pg_restore can read it selectively and into a
# newer Postgres major, which is the documented path for a version bump.
log "dumping the database"
$CMP exec -T db pg_dump -U "$DB_USER" -d "$DB_NAME" -Fc > "$DEST/db.dump"
[[ -s "$DEST/db.dump" ]] || die "pg_dump produced an empty file"

# --- media ---------------------------------------------------------------------------
# Media is mounted into api/worker, not db, so read it straight off the volume with a
# throwaway container. That way a backup still works when api is stopped.
if [[ "$STACK" == prod ]]; then VOLUME=chorekeeper_media_data; else VOLUME=chorekeeper_dev_media_data; fi
log "archiving media from volume $VOLUME"
docker run --rm -v "${VOLUME}:/m:ro" alpine tar -czf - -C /m . > "$DEST/media.tar.gz"
[[ -s "$DEST/media.tar.gz" ]] || die "media archive is empty"

# --- manifest ------------------------------------------------------------------------
log "recording the manifest"
# Straight to a file rather than a shell variable: these values contain usernames, and
# interpolating them into a script is how a quote in a display name becomes a broken backup.
$CMP exec -T db psql -U "$DB_USER" -d "$DB_NAME" -At -c "$COUNT_SQL" > "$DEST/.counts.json"
[[ -s "$DEST/.counts.json" ]] || die "could not read row counts"

ALEMBIC="$($CMP exec -T db psql -U "$DB_USER" -d "$DB_NAME" -At \
    -c 'select version_num from alembic_version' 2>/dev/null | tr -d '\r' || true)"
PGVER="$($CMP exec -T db pg_dump --version | tr -d '\r')"
GITREV="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
SHA_DB="$(sha256sum "$DEST/db.dump" | cut -d' ' -f1)"
SHA_MEDIA="$(sha256sum "$DEST/media.tar.gz" | cut -d' ' -f1)"

# jq is not a dependency of this repo; python3 is. Every value arrives as argv or a file,
# never interpolated into the program text.
python3 scripts/manifest.py "$DEST" "$STACK" "$(date -Is)" "$DB_NAME" "$DB_USER" \
        "$ALEMBIC" "$PGVER" "$GITREV" "$VOLUME" "$SHA_DB" "$SHA_MEDIA"
rm -f "$DEST/.counts.json"

chmod 600 "$DEST"/*
log "done — $(du -sh "$DEST" | cut -f1) in $DEST"
python3 scripts/manifest.py --print "$DEST"
echo
log "verify it with:  just restore-verify $DEST"
