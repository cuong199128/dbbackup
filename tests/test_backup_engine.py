import sqlite3
from pathlib import Path

import pytest

from app.core import backup_engine


def _make_db(path: Path, rows: int = 100):
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    conn.executemany("INSERT INTO t (v) VALUES (?)", [(f"row{i}",) for i in range(rows)])
    conn.commit()
    conn.close()


def test_create_snapshot_copies_data_and_passes_integrity(tmp_path):
    src = tmp_path / "source.db"
    _make_db(src, rows=50)
    dest = tmp_path / "snap" / "snapshot.db"

    result = backup_engine.create_snapshot(str(src), dest)

    assert result.integrity_ok is True
    assert dest.exists()

    conn = sqlite3.connect(str(dest))
    count = conn.execute("SELECT COUNT(*) FROM t").fetchone()[0]
    conn.close()
    assert count == 50


def test_source_file_is_never_modified(tmp_path):
    src = tmp_path / "source.db"
    _make_db(src, rows=10)
    original_bytes = src.read_bytes()
    dest = tmp_path / "snapshot.db"

    backup_engine.create_snapshot(str(src), dest, vacuum=True, analyze=True)

    assert src.read_bytes() == original_bytes


def test_vacuum_and_analyze_do_not_break_integrity(tmp_path):
    src = tmp_path / "source.db"
    _make_db(src, rows=200)
    dest = tmp_path / "snapshot.db"

    result = backup_engine.create_snapshot(str(src), dest, vacuum=True, analyze=True)

    assert result.vacuumed is True
    assert result.analyzed is True
    assert result.integrity_ok is True


def test_verify_file_integrity_detects_corruption(tmp_path):
    src = tmp_path / "source.db"
    _make_db(src, rows=5)
    dest = tmp_path / "snapshot.db"
    backup_engine.create_snapshot(str(src), dest)

    # Corrupt the copy (never the source) by truncating it.
    with open(dest, "r+b") as f:
        f.truncate(50)

    ok, detail = backup_engine.verify_file_integrity(dest)
    assert ok is False
    assert detail
