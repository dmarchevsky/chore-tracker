# Backup & restore

The household's ledger and every photo live in two Docker volumes, `chorekeeper_db_data` and
`chorekeeper_media_data`. Nothing else on this machine backs them up — the host's nightly
`backup-to-truenas.timer` copies `/home` and `/etc /root /usr/local /opt`, and Docker volumes
live under `/var/lib/docker`, so they are not in it.

Spec §5 requires a backup **and a tested restore**; Phase 6 does not pass until a restore into
a clean environment reproduces every balance exactly (§14). That last part is why
`just restore-verify` exists and why you should actually run it.

## What a backup is

One directory, `backups/chorekeeper-<YYYYmmdd-HHMMSS>/`, containing:

| File | What |
|---|---|
| `db.dump` | `pg_dump -Fc` of the whole database — custom format, compressed |
| `media.tar.gz` | everything under `MEDIA_ROOT` (originals + thumbnails) |
| `manifest.json` | row counts, **every child's balance**, sha256 of both files, alembic head, git commit |

The manifest is what makes the backup checkable rather than merely present. `restore-verify`
reads those numbers back out of a real restore and fails if a single cent differs.

### What a backup does NOT contain

- **`env.production`** — `SESSION_SECRET`, `DB_PASSWORD`, `CLOUDFLARE_TUNNEL_TOKEN`,
  `CF_ACCESS_*`. Excluded on purpose: a dump that carries its own credentials is a worse thing
  to lose or leak. **A restore onto a clean machine needs this file** and will fail
  confusingly without it, so keep it safe separately. It lives under `/home`, so the host's
  existing nightly TrueNAS job already ships it.
- **The backup does not leave this machine.** `just backup` writes to a local directory and
  stops. Until that changes, a dead disk still loses everything — see *Getting backups off the
  box* below.

The break-glass password *is* included: it is a hash in the `users` table, which is dumped.
(The app-level JSON export at Settings → Export is the one that drops it — that is a household
transfer format, not a backup. It carries no photo bytes and no sessions.)

## Taking a backup

```sh
just backup            # the production stack (default)
just backup dev        # the dev stack
just backup-list       # what you have so far
```

The stack's `db` container must be running; the script refuses otherwise rather than writing
an empty dump. Everything runs inside that container, so no host-side `psql`/`pg_dump` is
needed and there is no client/server version skew.

`CK_BACKUP_DIR` overrides the destination (default `backups/`, which is gitignored).

## Verifying a backup — do this, not just the backup

```sh
just restore-verify backups/chorekeeper-20260902-101323
```

Starts a throwaway Postgres with no published port and no volume, restores the dump into it,
recomputes every row count and every child's balance, diffs them against the manifest, prints
PASS/FAIL per line, and removes the container. **It touches no stack and no volume**, so it is
safe to run at any time, against production backups, while production is serving.

Expected output ends with:

```
  PASS  balance kira      expected -9.00, got -9.00
  every row count and every balance matches the manifest
  VERIFIED — this backup restores into a clean environment and reproduces every balance
```

A corrupt or truncated dump fails at the checksum step, before anything is restored anywhere.

## Restoring over a real stack

This destroys data. It asks for it in writing.

```sh
just restore backups/chorekeeper-20260902-101323 prod
```

That command **refuses**, and first prints what it would destroy: the target volumes and the
current row counts and balances. If those numbers are what you mean to replace:

```sh
just restore backups/chorekeeper-20260902-101323 prod overwrite-production
```

It then stops `api` and `worker` (restoring underneath a live worker lands a scheduler tick
mid-schema), drops and recreates the database, restores the dump, unpacks the media archive
over the media volume, starts the services again, and finally re-runs the manifest comparison
against the *restored stack* — so a restore that silently lost rows fails loudly instead of
looking finished.

The database is replaced wholesale; media is *added to*, not wiped first. Media is
content-addressed, so unpacking on top can never produce a wrong file, and there is no window
where a failed extraction has already destroyed the photos. Files deleted since the backup
linger until the retention job clears them.

This is the procedure CLAUDE.md's "Seeding and wiping data — ASK FIRST, EVERY TIME" rule
refers to; the typed confirmation is that rule in executable form.

**The first time you use this, rehearse it on `dev`.** Take a backup of dev, restore it back
over dev, and watch the comparison pass. Learning what the output looks like on a stack you do
not care about is much cheaper than learning it on the one you do — and `restore-verify`
exercises the dump but not the drop-recreate-and-restart sequence that `restore` performs.

## Restoring onto a clean machine

1. Install Docker, `just`, and clone the repo.
2. Put `env.production` back (it is **not** in the backup — see above).
3. `just prod-up` to create the volumes and run migrations.
4. `just restore <backup-dir> prod overwrite-production`.
5. Check `https://<your host>/` signs in, and that Settings → Money shows the balances the
   manifest recorded.

## Upgrading Postgres majors

The pinned image in `docker-compose.prod.yml` cannot be bumped in place — a new major will not
start on an old data directory. The dump/restore path is the upgrade path:

1. `just backup` and `just restore-verify` it.
2. Bump the `postgres:` pin in `docker-compose.prod.yml`.
3. `just prod-down`, `docker volume rm chorekeeper_db_data`, `just prod-up`.
4. `just restore <backup-dir> prod overwrite-production`.

`-Fc` dumps restore into a newer major, which is why the backup uses that format.

## Getting backups off the box — still open

`just backup` is local and manual. Two ways to close that gap, both a small amount of work:

- **Reuse the host's existing job.** `/usr/local/bin/backup-to-truenas.sh` already rsyncs
  `/home` to the ZFS-encrypted TrueNAS dataset nightly, and TrueNAS periodic snapshots give
  versioning for free. Point `CK_BACKUP_DIR` at a directory under `/home` and the copies ride
  along — but run `just backup` *before* 00:00 or the shipped copy is a day stale.
- **A systemd timer** running `just backup` ordered `Before=backup-to-truenas.service`.

Until one of those exists, the honest summary is: there is a tested restore, and the backups
are on the same disk as the thing they protect.
