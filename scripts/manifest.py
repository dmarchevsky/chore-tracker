"""Write and read a backup's manifest.json — the record that makes a restore checkable.

Kept in Python rather than jq (not a dependency here) or inline shell, so that usernames and
display names arrive as argv and never as interpolated script text: a quote in a child's name
should not be able to produce a malformed backup.

    manifest.py <dest> <stack> <taken_at> <db> <user> <alembic> <pgver> <git> <vol> <sha_db> <sha_media>
    manifest.py --print <dest>
    manifest.py --compare <dest> <counts.json>     exit 1 if the numbers differ
"""

from __future__ import annotations

import json
import pathlib
import sys

FIELDS = ("users", "chores", "chore_occurrences", "ledger_entries", "submissions")


def _load(dest: str) -> dict:
    return json.loads((pathlib.Path(dest) / "manifest.json").read_text())


def write(argv: list[str]) -> None:
    (dest, stack, taken, dbname, dbuser, alembic, pgver, gitrev, volume, sha_db, sha_media) = argv
    d = pathlib.Path(dest)
    payload = {
        "version": 1,
        "stack": stack,
        "taken_at": taken,
        "database": {"name": dbname, "user": dbuser},
        "alembic_head": alembic or None,
        "pg_dump_version": pgver,
        "git_commit": gitrev,
        "media_volume": volume,
        "sha256": {"db.dump": sha_db, "media.tar.gz": sha_media},
        "counts": json.loads((d / ".counts.json").read_text()),
    }
    (d / "manifest.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def show(dest: str) -> None:
    m = _load(dest)
    c = m["counts"]
    print("  alembic head     :", m["alembic_head"])
    for k in FIELDS:
        print(f"  {k:<17}:", c[k])
    for name, cents in sorted(c["balances"].items()):
        print(f"  balance {name:<9}: {cents / 100:.2f}")


def compare(dest: str, actual_path: str) -> int:
    """Diff what came back out of the restore against what went in. Balances are the ones
    that matter (spec §14: 'reproduces all balances exactly'), so they are reported per child
    and any mismatch fails the whole run."""
    want = _load(dest)["counts"]
    got = json.loads(pathlib.Path(actual_path).read_text())
    bad = []

    for k in FIELDS:
        ok = want[k] == got[k]
        print(f"  {'PASS' if ok else 'FAIL'}  {k:<17} expected {want[k]}, got {got[k]}")
        if not ok:
            bad.append(k)

    for name in sorted(set(want["balances"]) | set(got["balances"])):
        w, g = want["balances"].get(name), got["balances"].get(name)
        ok = w == g
        shown = "missing" if g is None else f"{g / 100:.2f}"
        expect = "missing" if w is None else f"{w / 100:.2f}"
        print(f"  {'PASS' if ok else 'FAIL'}  balance {name:<9} expected {expect}, got {shown}")
        if not ok:
            bad.append(f"balance:{name}")

    if bad:
        print("\n  RESTORE DOES NOT MATCH THE BACKUP:", ", ".join(bad))
        return 1
    print("\n  every row count and every balance matches the manifest")
    return 0


if __name__ == "__main__":
    if sys.argv[1] == "--print":
        show(sys.argv[2])
    elif sys.argv[1] == "--compare":
        sys.exit(compare(sys.argv[2], sys.argv[3]))
    else:
        write(sys.argv[1:])
