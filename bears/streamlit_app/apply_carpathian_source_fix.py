"""Correct doubled Carpathian GPS records caused by concatenating two overlapping CSVs.

Run in bears/streamlit_app:
    python apply_carpathian_source_fix.py
    python apply_carpathian_source_fix.py --verify
    python apply_carpathian_source_fix.py --audit-db   # optional; SELECT only

This installer modifies exactly carpathian_bears.py and wildlife_db_mariadb.py.
Existing MariaDB tables are NEVER changed. Backups are saved next to each file.
"""
from __future__ import annotations

import argparse
import ast
import shutil
import sys
from pathlib import Path

ROOT = Path.cwd()
CSV_MODULE = ROOT / "carpathian_bears.py"
DB_MODULE = ROOT / "wildlife_db_mariadb.py"
BACKUP_SUFFIX = ".before_carpathian_source_fix.bak"


def replace_one(src: str, old: str, new: str, purpose: str) -> str:
    matches = src.count(old)
    if matches != 1:
        raise ValueError(f"{purpose}: expected 1 matching block, found {matches}. Nothing written.")
    return src.replace(old, new, 1)


def replace_in_method(src: str, method: str, next_method: str, old: str, new: str, purpose: str) -> str:
    begin = src.find(method)
    finish = src.find(next_method, begin + len(method)) if begin >= 0 else -1
    if begin < 0 or finish < 0:
        raise ValueError(f"{purpose}: method boundaries were not found. Nothing written.")
    current = src[begin:finish]
    replacement = replace_one(current, old, new, purpose)
    return src[:begin] + replacement + src[finish:]


def patch_csv_module(src: str) -> str:
    old = '''    if not os.path.exists(f1):
        return pd.DataFrame()

    df1 = _normalize_tracking_columns(pd.read_csv(f1))

    df2 = pd.DataFrame()
    if os.path.exists(f2):
        try:
            df2 = _normalize_tracking_columns(pd.read_csv(f2))
        except Exception:
            df2 = pd.DataFrame()

    df = pd.concat([df1, df2], ignore_index=True) if not df2.empty else df1.copy()
'''
    new = '''    # 2_bears_RO_seasons.csv is a SUBSET of 1_bears_RO.csv, not a
    # complementary set of GPS measurements. Both files already carry
    # Season / Season2. Concatenating them doubles overlapping fixes.
    # Prefer the full dataset, and only use the smaller file as fallback.
    source_file = f1 if os.path.isfile(f1) else f2
    if not os.path.isfile(source_file):
        return pd.DataFrame()

    df = _normalize_tracking_columns(pd.read_csv(source_file))
'''
    return replace_one(src, old, new, "CSV source selection")


def patch_db_module(src: str) -> str:
    # Two independent import entry points must both select just one file.
    for indent, tag in [("        ", "single-table importer"), ("    ", "all-data migration")]:
        old = (
            indent + 'tracking_files = [\n'
            + indent + '    "data/animal_data/carpathian_bears/1_bears_RO.csv",\n'
            + indent + '    "data/animal_data/carpathian_bears/2_bears_RO_seasons.csv"\n'
            + indent + ']\n'
        )
        new = old + (
            indent + '# The second CSV is already contained in the first; not additive.\n'
            + indent + 'tracking_files = [p for p in tracking_files if os.path.isfile(p)][:1]\n'
        )
        src = replace_one(src, old, new, tag + " source selection")

    # Read-time protection while MariaDB still contains previously imported
    # duplicate rows. Ignore the DB's auto-increment id in the GPS identity.
    old = '''            results = self.execute_query(query, params)
            df = pd.DataFrame(results) if results else pd.DataFrame()
            
            if not df.empty and 'timestamp' in df.columns:
                df['timestamp'] = pd.to_datetime(df['timestamp'])
                
            return df
'''
    new = '''            results = self.execute_query(query, params)
            df = pd.DataFrame(results) if results else pd.DataFrame()

            # Preexisting DB rows can still contain duplicate GPS fixes
            # from the older CSV concatenation. Deduplicate only identical
            # bear + timestamp + projected coordinate measurements.
            fix_key = ['bear_id', 'timestamp', 'x', 'y']
            if not df.empty and all(k in df.columns for k in fix_key):
                df = df.drop_duplicates(subset=fix_key, keep='first').reset_index(drop=True)

            if not df.empty and 'timestamp' in df.columns:
                df['timestamp'] = pd.to_datetime(df['timestamp'])

            return df
'''
    src = replace_in_method(src, "    def get_bear_data(", "    def get_date_range(", old, new, "DB tracking reads")

    # The bear overview counts the number of recorded fixes, not inserted rows.
    src = replace_in_method(
        src, "    def get_bears_list(", "    def get_bear_data(",
        "                COUNT(*) as point_count\n",
        "                COUNT(DISTINCT timestamp, x, y) as point_count\n",
        "DB bear fix counts",
    )

    # The seasonal query contains averages and counts. Deduplicating before
    # aggregation avoids weighting fixes twice in mixed/imported datasets.
    src = replace_in_method(
        src, "    def get_seasonal_data(", "    def get_home_range_data(",
        "            FROM bears_tracking\n",
        """            FROM (
                SELECT DISTINCT bear_id, season, sex, age,
                                timestamp, x, y, lat, lng
                FROM bears_tracking
            ) AS bears_tracking
""",
        "DB seasonal aggregation input",
    )
    return src


def patch_files() -> None:
    if not CSV_MODULE.is_file() or not DB_MODULE.is_file():
        raise FileNotFoundError("Run from bears/streamlit_app; expected carpathian_bears.py and wildlife_db_mariadb.py")

    files = [
        (CSV_MODULE, patch_csv_module),
        (DB_MODULE, patch_db_module),
    ]
    proposals = []
    already_patched = True
    for path, transform in files:
        current = path.read_text(encoding="utf-8")
        if path == CSV_MODULE:
            marker = "source_file = f1 if os.path.isfile(f1) else f2"
        else:
            marker = "fix_key = ['bear_id', 'timestamp', 'x', 'y']"
        if marker not in current:
            already_patched = False
        proposals.append((path, current, transform))

    if already_patched:
        print("These two files already contain this fix. Nothing changed.")
        return

    edits = []
    for path, current, transform in proposals:
        if path == CSV_MODULE and "source_file = f1 if os.path.isfile(f1) else f2" in current:
            raise ValueError("Partial installation detected: CSV is patched, DB is not. Please restore backups before retrying.")
        if path == DB_MODULE and "fix_key = ['bear_id', 'timestamp', 'x', 'y']" in current:
            raise ValueError("Partial installation detected: DB is patched, CSV is not. Please restore backups before retrying.")
        updated = transform(current)
        ast.parse(updated, filename=str(path))
        if updated == current:
            raise ValueError(f"{path.name}: unchanged unexpectedly; aborted.")
        edits.append((path, updated))

    for path, _ in edits:
        backup = path.with_name(path.name + BACKUP_SUFFIX)
        if backup.exists():
            raise FileExistsError(f"Backup already exists: {backup}; no files were changed.")
    for path, _ in edits:
        shutil.copy2(path, path.with_name(path.name + BACKUP_SUFFIX))
    for path, updated in edits:
        path.write_text(updated, encoding="utf-8")
    print("Carpathian source fix installed successfully.")
    for path, _ in edits:
        print(f"  Updated: {path.name}")
        print(f"  Backup:  {path.name}{BACKUP_SUFFIX}")
    print("MariaDB data was NOT changed.")


def verify_csv() -> None:
    import pandas as pd
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from carpathian_bears import _load_carpathian_csv_tracking_cached

    folder = ROOT / "data" / "animal_data" / "carpathian_bears"
    main_file = folder / "1_bears_RO.csv"
    other_file = folder / "2_bears_RO_seasons.csv"
    if not main_file.exists():
        raise FileNotFoundError(f"Expected primary dataset: {main_file}")
    primary = pd.read_csv(main_file)
    df = _load_carpathian_csv_tracking_cached()
    unique = df.drop_duplicates(subset=["bear_id", "timestamp", "x", "y"])
    print(f"Original 1_bears_RO.csv rows: {len(primary):,}")
    print(f"App CSV loader rows:          {len(df):,}")
    print(f"Distinct GPS fixes in app:    {len(unique):,}")
    if len(primary) != len(df):
        raise AssertionError("CSV loader did not return the primary file's row count")
    if len(unique) != len(df):
        raise AssertionError("CSV loader still returns duplicate GPS fixes")
    if other_file.exists():
        secondary = pd.read_csv(other_file)
        keys = ["Name", "timestamp", "X", "Y"]
        overlap = primary[keys].drop_duplicates().merge(secondary[keys].drop_duplicates(), on=keys)
        print(f"Secondary CSV rows:           {len(secondary):,}")
        print(f"Shared fixes across sources:  {len(overlap):,}")
        if len(overlap) != len(secondary):
            print("NOTE: Secondary file contains some independent fixes; review before discarding it.")
        else:
            print("The secondary file adds no new GPS fixes.")
    print("CSV check passed. Restart Streamlit to clear caches.")


def audit_db() -> None:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from wildlife_db_mariadb import WildlifeDatabase
    db = WildlifeDatabase()
    # This branch only performs SELECT statements; the physical table
    # remains untouched and can be inspected before any future migration.
    query = """SELECT COUNT(*) AS stored_rows,
                COUNT(DISTINCT bear_id, timestamp, x, y) AS distinct_fixes
               FROM bears_tracking"""
    res = db.execute_query(query)
    if not res:
        print("No tracking records returned.")
        return
    n = res[0]
    print("MariaDB read-only audit:")
    print(f"  Physically stored rows: {n['stored_rows']:,}")
    print(f"  Unique GPS fixes:       {n['distinct_fixes']:,}")
    print(f"  Duplicate rows:         {n['stored_rows']-n['distinct_fixes']:,}")
    print("No database rows have been changed or deleted.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--verify", action="store_true", help="check real CSVs and loader (no changes)")
    actions.add_argument("--audit-db", action="store_true", help="count existing MariaDB duplicates via SELECT only")
    args = parser.parse_args()
    if args.verify:
        verify_csv()
    elif args.audit_db:
        audit_db()
    else:
        patch_files()
