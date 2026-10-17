"""One-time, cautious cleanup of duplicated Carpathian bear GPS fixes in MariaDB.

Run from bears/streamlit_app (VPN connected; stop Streamlit/import jobs):

    python cleanup_carpathian_db.py              # read-only preview
    python cleanup_carpathian_db.py --apply      # backup, check, ask confirmation, delete
    python cleanup_carpathian_db.py              # verify final counts

Identity: bear_id, timestamp, x, y (matching the prior audited GPS definition).
Only bears_tracking is read/written. A full compressed JSONL backup is written
locally, and verified, BEFORE any DELETE. SQL changes are a single transaction;
any mismatch/exception rolls back. On metadata conflicts, nothing is deleted.
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import json
import os
import shutil
import sys
from collections import defaultdict
from pathlib import Path

BASE = Path(__file__).resolve().parent
KEY_FIELDS = ("bear_id", "timestamp", "x", "y")
METADATA_FIELDS = ("lat", "lng", "season_code", "season", "sex", "age", "is_daytime")
BACKUP_DIR = BASE / "backups" / "carpathian_tracking"
CHUNK_SIZE = 500
# Guard against connecting to an unexpected/changed database. These values
# come from the read-only audit that the user just ran on 2026-10-17.
EXPECTED_STORED = 116_014
EXPECTED_UNIQUE = 59_997


def _has_value(value):
    return value is not None and (not isinstance(value, str) or value.strip() != "")


def analyze(rows):
    """Return ids to remove; refuse contradictory nonempty metadata."""
    by_fix = defaultdict(list)
    null_key_ids = []
    ids = set()
    for r in rows:
        record_id = int(r["id"])
        if record_id in ids:
            raise ValueError(f"Duplicate database primary key id={record_id}")
        ids.add(record_id)
        key = tuple(r.get(k) for k in KEY_FIELDS)
        if any(v is None for v in key):
            null_key_ids.append(record_id)
        else:
            by_fix[key].append(r)
    if null_key_ids:
        raise ValueError(f"{len(null_key_ids)} rows have NULL in GPS identity fields; aborting. Example IDs: {null_key_ids[:5]}")

    duplicates = []
    conflicts = []
    groups = 0
    for key, group in by_fix.items():
        if len(group) <= 1:
            continue
        groups += 1
        for field in METADATA_FIELDS:
            values = {str(r[field]).strip() for r in group if _has_value(r.get(field))}
            if len(values) > 1:
                conflicts.append((key, field, sorted(values)[:4]))
        # Prefer the row with the most populated attributes, then the smallest
        # original ID for stable choice. Never lose complementary nonempty data.
        def quality(r):
            return (sum(_has_value(r.get(f)) for f in METADATA_FIELDS), -int(r["id"]))
        keep = max(group, key=quality)
        for r in group:
            if int(r["id"]) != int(keep["id"]):
                # If one row has a nonempty value not contained in the row we
                # would keep, do not delete it without merging metadata.
                lost = [f for f in METADATA_FIELDS
                        if _has_value(r.get(f)) and not _has_value(keep.get(f))]
                if lost:
                    conflicts.append((key, "missing metadata", lost))
                duplicates.append(int(r["id"]))

    return {
        "total": len(rows),
        "unique": len(by_fix),
        "groups": groups,
        "duplicate_ids": sorted(duplicates),
        "conflicts": conflicts,
    }


def summary(a):
    print(f"  Physically stored rows: {a['total']:,}")
    print(f"  Unique GPS fixes:       {a['unique']:,}")
    print(f"  Extra duplicate rows:  {len(a['duplicate_ids']):,}")
    print(f"  Duplicate groups:      {a['groups']:,}")
    print(f"  Metadata conflicts:    {len(a['conflicts']):,}")
    for fix, field, values in a["conflicts"][:5]:
        print(f"    Conflict example {fix}: {field}: {values}")


def connect():
    sys.path.insert(0, str(BASE))
    from wildlife_db_mariadb import WildlifeDatabase
    db = WildlifeDatabase()
    # Access exactly the same configured MariaDB as the existing application.
    return db._get_connection()


def fetch_all(cursor):
    cursor.execute("SELECT * FROM bears_tracking ORDER BY id")
    return cursor.fetchall()


def backup_rows(rows, schema):
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    output = BACKUP_DIR / f"bears_tracking_before_dedup_{stamp}_{os.getpid()}.jsonl.gz"
    header = {"format": "bears_tracking_backup_v1", "created_at": dt.datetime.now().isoformat(),
              "table": "bears_tracking", "rows": len(rows), "schema_sql": schema,
              "columns": list(rows[0]) if rows else []}
    try:
        with gzip.open(output, "wt", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps({"__backup_header__": header}, ensure_ascii=False, default=str) + "\n")
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False, default=str, separators=(",", ":")) + "\n")
        actual = 0
        with gzip.open(output, "rt", encoding="utf-8") as f:
            first = json.loads(next(f))["__backup_header__"]
            if first["format"] != "bears_tracking_backup_v1" or first["rows"] != len(rows):
                raise ValueError("Backup header verification failed")
            for line in f:
                if line.strip():
                    json.loads(line)
                    actual += 1
        if actual != len(rows):
            raise ValueError(f"Backup incomplete: expected {len(rows)} rows, found {actual}")
        sha = hashlib.sha256()
        with output.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                sha.update(chunk)
        print(f"  Verified backup: {output}")
        print(f"  Rows in backup:  {actual:,}")
        print(f"  Compressed size: {output.stat().st_size / 1048576:.2f} MiB")
        print(f"  SHA-256:         {sha.hexdigest()}")
        return output
    except Exception:
        output.unlink(missing_ok=True)
        raise


def run(apply):
    if not (BASE / "wildlife_db_mariadb.py").exists():
        raise RuntimeError("Place this script in bears/streamlit_app next to wildlife_db_mariadb.py")
    conn = connect()
    try:
        conn.autocommit = False
        # REPEATABLE READ transaction ensures consistent reads during the
        # backup/deletion; stop other writers before running the cleanup.
        conn.start_transaction(isolation_level="REPEATABLE READ")
        cursor = conn.cursor(dictionary=True)
        rows = fetch_all(cursor)
        review = analyze(rows)
        print("MariaDB bears_tracking GPS audit:")
        summary(review)
        if review["conflicts"]:
            print("\nSTOP: Metadata conflicts exist. No rows will be deleted.")
            print("The duplicated GPS rows have different additional information;")
            print("send the conflict examples for review before cleanup.")
            conn.rollback()
            return 2
        if not apply:
            print("\nPreview only. No backup created and NO rows changed.")
            conn.rollback()
            return 0
        if not review["duplicate_ids"]:
            print("Nothing to delete. Database already has unique GPS fixes.")
            conn.rollback()
            return 0
        if (review["total"], review["unique"]) != (EXPECTED_STORED, EXPECTED_UNIQUE):
            print("STOP: Database contents differ from the audited snapshot.")
            print(f"Expected {EXPECTED_STORED:,} rows / {EXPECTED_UNIQUE:,} unique fixes.")
            print("No rows deleted. Re-check data before using this one-time script.")
            conn.rollback()
            return 2
        cursor.execute("SHOW CREATE TABLE bears_tracking")
        schema_row = cursor.fetchone()
        schema = schema_row.get("Create Table") or next(reversed(schema_row.values()))
        free = shutil.disk_usage(BACKUP_DIR.parent if BACKUP_DIR.parent.is_dir() else BASE).free
        if free < 30 * 1024 * 1024:
            raise RuntimeError("Less than 30 MiB free for a backup. Aborting.")
        print("\nCreating full local backup BEFORE any deletion...")
        backup = backup_rows(rows, schema)
        print("\nOnly this table will change: bears_tracking")
        print(f"Planned deletion: {len(review['duplicate_ids']):,} rows")
        print(f"Rows to retain:   {review['unique']:,}")
        print(f"Backup path:      {backup}")
        confirmation = input("Type DELETE to continue (anything else cancels): ").strip()
        if confirmation != "DELETE":
            print("Cancelled. Backup is retained; MariaDB unchanged.")
            conn.rollback()
            return 0

        print("\nDeleting duplicate IDs within ONE database transaction...")
        ids = review["duplicate_ids"]
        for offset in range(0, len(ids), CHUNK_SIZE):
            chunk = ids[offset:offset + CHUNK_SIZE]
            placeholders = ",".join(["%s"] * len(chunk))
            cursor.execute(f"DELETE FROM bears_tracking WHERE id IN ({placeholders})", chunk)
            if cursor.rowcount != len(chunk):
                raise RuntimeError(f"Expected to delete {len(chunk)} rows, deleted {cursor.rowcount}. ROLLBACK.")
            if (offset // CHUNK_SIZE + 1) % 20 == 0:
                print(f"  Deleted {offset + len(chunk):,} / {len(ids):,} duplicate rows (not committed yet)")

        # Re-audit actual rows from the same transaction to verify that no GPS
        # measurement is lost and no duplicates remain.
        final_rows = fetch_all(cursor)
        after = analyze(final_rows)
        print("\nVerification before commit:")
        summary(after)
        if after["total"] != review["unique"] or after["unique"] != review["unique"] or after["duplicate_ids"]:
            raise RuntimeError("Post-deletion verification failed. ROLLBACK.")
        conn.commit()
        print("\nSUCCESS: Transaction committed. Backed-up original table is preserved locally.")
        print(f"Kept GPS fixes: {after['unique']:,}. Removed duplicate rows: {len(ids):,}.")
        print("Run: python cleanup_carpathian_db.py   to independently re-audit.")
        return 0
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="create verified backup and delete duplicates after explicit confirmation")
    args = parser.parse_args()
    try:
        return run(args.apply)
    except Exception as e:
        print(f"ERROR: {e}")
        print("Database changes have been rolled back (or deletion never started).")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
