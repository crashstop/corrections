"""
Build redactions.csv from seeds/redactions.yaml.

The CSV is a denormalized blocklist of crash/person/vehicle record ids that
the serving side (server-chicagocrashes, `make db-update-redactions`) loads
into its `redactions` table so those records are excluded from the clean
views and everything downstream. Each YAML entry expands to one or more rows:

  - ignore_crash_completely: true
      -> one row (crash_record_id, crash_record_id, 'crash', notes)
  - ignore_crash_completely: false
      -> one row per id in ignore_person_ids  (crash_record_id, id, 'person', notes)
      -> one row per id in ignore_vehicle_ids (crash_record_id, id, 'vehicle', notes)

Columns: crash_record_id, record_id, record_type, notes. For crash rows
record_id == crash_record_id; the crash_record_id column exists so person and
vehicle rows stay traceable to their crash. Rows are sorted so a rebuild with
no YAML change is a no-op diff.

When a serving database is available (the db.sqlite symlink, or --db), every
id is checked against raw_crashes / raw_people / raw_vehicles and the build
fails on any miss — a typo in a blocklist would otherwise silently redact
nothing. Without a db the check is skipped with a warning.

Usage:
    python scripts/build_redactions.py [--seed PATH] [--out PATH] [--db PATH]
"""

import argparse
import csv
import sqlite3
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SEED = REPO_ROOT / "seeds" / "redactions.yaml"
DEFAULT_OUT = REPO_ROOT / "redactions.csv"
DEFAULT_DB = REPO_ROOT / "db.sqlite"

FIELDS = ("crash_record_id", "record_id", "record_type", "notes")
RECORD_TYPES = ("crash", "person", "vehicle")

# record_type -> (table, id column). vehicle_id is INTEGER in raw_vehicles;
# the YAML ids are bare ints too, but everything is compared as text so a
# future zero-padded or lettered id can't slip past the check.
ID_SOURCES = {
    "crash": ("raw_crashes", "crash_record_id"),
    "person": ("raw_people", "person_id"),
    "vehicle": ("raw_vehicles", "vehicle_id"),
}

Row = tuple[str, str, str, str]


def load_entries(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or []
    if not isinstance(data, list):
        raise ValueError(
            f"{path}: expected a top-level list, got {type(data).__name__}"
        )
    return data


def rows_from_entry(entry: dict) -> list[Row]:
    crash_id = entry.get("crash_record_id")
    if not crash_id:
        raise ValueError(f"redaction entry missing crash_record_id: {entry!r}")
    crash_id = str(crash_id)
    notes = (entry.get("notes") or "").strip()

    if entry.get("ignore_crash_completely"):
        return [(crash_id, crash_id, "crash", notes)]

    rows: list[Row] = []
    for pid in entry.get("ignore_person_ids") or []:
        rows.append((crash_id, str(pid), "person", notes))
    for vid in entry.get("ignore_vehicle_ids") or []:
        rows.append((crash_id, str(vid), "vehicle", notes))
    if not rows:
        raise ValueError(
            f"redaction entry for {crash_id[:12]}… redacts nothing: "
            "set ignore_crash_completely or list person/vehicle ids"
        )
    return rows


def build_rows(entries: list[dict]) -> list[Row]:
    rows: list[Row] = []
    for entry in entries:
        rows.extend(rows_from_entry(entry))
    seen: set[tuple[str, str]] = set()
    for _, record_id, record_type, _ in rows:
        key = (record_id, record_type)
        if key in seen:
            raise ValueError(f"duplicate redaction: {record_type} {record_id}")
        seen.add(key)
    return sorted(rows, key=lambda r: (r[0], r[2], r[1]))


def check_ids_exist(conn: sqlite3.Connection, rows: list[Row]) -> list[str]:
    """Return one message per id not found in the serving db's raw tables."""
    missing: list[str] = []
    for record_type, (table, col) in ID_SOURCES.items():
        ids = sorted({r[1] for r in rows if r[2] == record_type})
        if not ids:
            continue
        found: set[str] = set()
        for i in range(0, len(ids), 500):
            chunk = ids[i : i + 500]
            marks = ",".join("?" * len(chunk))
            found.update(
                str(v)
                for (v,) in conn.execute(
                    f"SELECT {col} FROM {table} WHERE CAST({col} AS TEXT) IN ({marks})",
                    chunk,
                )
            )
        missing.extend(
            f"{record_type} {i} not in {table}" for i in ids if i not in found
        )
    return missing


def write_csv(rows: list[Row], out: Path) -> None:
    with open(out, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(FIELDS)
        writer.writerows(rows)


def summarize(rows: list[Row]) -> str:
    by_type: dict[str, int] = {}
    for _, _, t, _ in rows:
        by_type[t] = by_type.get(t, 0) + 1
    return ", ".join(f"{n} {t}" for t, n in sorted(by_type.items()))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=Path, default=DEFAULT_SEED)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB,
        help="serving db to validate ids against (skipped, with a warning, if absent)",
    )
    args = parser.parse_args()

    rows = build_rows(load_entries(args.seed))

    if args.db.exists():
        conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
        try:
            missing = check_ids_exist(conn, rows)
        finally:
            conn.close()
        if missing:
            print(f"ERROR: {len(missing)} redaction id(s) not found in {args.db}:")
            for m in missing:
                print(f"  {m}")
            return 1
    else:
        print(f"WARNING: {args.db} not found; skipping id validation", file=sys.stderr)

    write_csv(rows, args.out)
    print(f"Wrote {len(rows)} redactions to {args.out.name} ({summarize(rows)}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
