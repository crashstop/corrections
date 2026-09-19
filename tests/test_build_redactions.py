"""Tests for scripts/build_redactions.py: YAML entry expansion, CSV output,
and id validation against a serving db."""

import csv
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from build_redactions import (  # noqa: E402
    FIELDS,
    build_rows,
    check_ids_exist,
    rows_from_entry,
    write_csv,
)

CRASH_A = "a" * 128
CRASH_B = "b" * 128


def test_crash_level_entry_is_one_crash_row():
    entry = {
        "crash_record_id": CRASH_A,
        "ignore_crash_completely": True,
        "notes": "  shooting\nhttps://x.test  ",
    }
    assert rows_from_entry(entry) == [
        (CRASH_A, CRASH_A, "crash", "shooting\nhttps://x.test")
    ]


def test_crash_level_entry_ignores_person_and_vehicle_ids():
    entry = {
        "crash_record_id": CRASH_A,
        "ignore_crash_completely": True,
        "ignore_person_ids": ["O1"],
        "ignore_vehicle_ids": [1],
    }
    assert [r[2] for r in rows_from_entry(entry)] == ["crash"]


def test_partial_entry_expands_person_and_vehicle_ids_as_strings():
    entry = {
        "crash_record_id": CRASH_A,
        "ignore_crash_completely": False,
        "notes": "",
        "ignore_person_ids": ["O1", "P2"],
        "ignore_vehicle_ids": [10, 11],
    }
    assert rows_from_entry(entry) == [
        (CRASH_A, "O1", "person", ""),
        (CRASH_A, "P2", "person", ""),
        (CRASH_A, "10", "vehicle", ""),
        (CRASH_A, "11", "vehicle", ""),
    ]


def test_missing_crash_record_id_is_an_error():
    with pytest.raises(ValueError, match="crash_record_id"):
        rows_from_entry({"ignore_crash_completely": True})


def test_entry_that_redacts_nothing_is_an_error():
    with pytest.raises(ValueError, match="redacts nothing"):
        rows_from_entry({"crash_record_id": CRASH_A, "ignore_crash_completely": False})


def test_build_rows_sorts_and_rejects_duplicates():
    entries = [
        {"crash_record_id": CRASH_B, "ignore_crash_completely": True},
        {
            "crash_record_id": CRASH_A,
            "ignore_vehicle_ids": [2, 1],
            "ignore_person_ids": ["O9"],
        },
    ]
    rows = build_rows(entries)
    assert [(r[0][0], r[2], r[1]) for r in rows] == [
        ("a", "person", "O9"),
        ("a", "vehicle", "1"),
        ("a", "vehicle", "2"),
        ("b", "crash", CRASH_B),
    ]

    with pytest.raises(ValueError, match="duplicate"):
        build_rows(
            entries + [{"crash_record_id": CRASH_B, "ignore_crash_completely": True}]
        )


def test_write_csv_round_trips_multiline_notes(tmp_path):
    out = tmp_path / "redactions.csv"
    rows = [
        (CRASH_A, CRASH_A, "crash", "line one\nline two"),
        (CRASH_A, "5", "vehicle", ""),
    ]
    write_csv(rows, out)

    with open(out, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        assert tuple(reader.fieldnames) == FIELDS
        back = [tuple(r[k] for k in FIELDS) for r in reader]
    assert back == rows


def _serving_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE raw_crashes (crash_record_id TEXT);
        CREATE TABLE raw_people (person_id TEXT);
        CREATE TABLE raw_vehicles (vehicle_id INTEGER);
        """)
    conn.execute("INSERT INTO raw_crashes VALUES (?)", (CRASH_A,))
    conn.execute("INSERT INTO raw_people VALUES ('O1')")
    conn.execute("INSERT INTO raw_vehicles VALUES (10)")
    return conn


def test_check_ids_exist_passes_when_every_id_is_present():
    conn = _serving_db()
    rows = [
        (CRASH_A, CRASH_A, "crash", ""),
        (CRASH_A, "O1", "person", ""),
        (CRASH_A, "10", "vehicle", ""),
    ]
    assert check_ids_exist(conn, rows) == []


def test_check_ids_exist_reports_each_missing_id():
    conn = _serving_db()
    rows = [
        (CRASH_B, CRASH_B, "crash", ""),
        (CRASH_A, "O2", "person", ""),
        (CRASH_A, "11", "vehicle", ""),
        (CRASH_A, "10", "vehicle", ""),
    ]
    missing = check_ids_exist(conn, rows)
    assert missing == [
        f"crash {CRASH_B} not in raw_crashes",
        "person O2 not in raw_people",
        "vehicle 11 not in raw_vehicles",
    ]
