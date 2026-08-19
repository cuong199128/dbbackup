import sqlite3
import time

import pytest

from app.core import change_detector


def _make_db(path, value: str):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE IF NOT EXISTS t (v TEXT)")
    conn.execute("INSERT INTO t (v) VALUES (?)", (value,))
    conn.commit()
    conn.close()


def test_first_backup_always_considered_changed(tmp_path):
    db_path = tmp_path / "data.db"
    _make_db(str(db_path), "a")
    assert change_detector.has_changed(str(db_path), last_hash=None) is True


def test_unchanged_db_is_detected(tmp_path):
    db_path = tmp_path / "data.db"
    _make_db(str(db_path), "a")
    fp = change_detector.fingerprint(str(db_path)).as_key()
    assert change_detector.has_changed(str(db_path), last_hash=fp) is False


def test_changed_db_is_detected(tmp_path):
    db_path = tmp_path / "data.db"
    _make_db(str(db_path), "a")
    fp = change_detector.fingerprint(str(db_path)).as_key()

    time.sleep(0.01)
    _make_db(str(db_path), "b" * 2000)  # force size change so quick hash differs

    assert change_detector.has_changed(str(db_path), last_hash=fp) is True
