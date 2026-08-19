from datetime import datetime

from app.core import drive_layout


def test_snapshot_path_layout():
    when = datetime(2026, 8, 19, 12, 0, 0)
    parts = drive_layout.snapshot_path("MyApp", when)
    assert parts.folder_segments == ("Python Database Backup", "MyApp", "2026", "08-19")
    assert parts.filename == "12-00-00.db"
    assert parts.full_path == "Python Database Backup/MyApp/2026/08-19/12-00-00.db"


def test_latest_path_keeps_original_filename():
    parts = drive_layout.latest_path("MyApp", "data.db")
    assert parts.folder_segments == ("Python Database Backup", "MyApp")
    assert parts.filename == "data.db"
    assert parts.full_path == "Python Database Backup/MyApp/data.db"


def test_restore_safety_snapshot_uses_normal_snapshot_layout():
    when = datetime(2026, 1, 1, 8, 30, 5)
    a = drive_layout.snapshot_path("App", when)
    b = drive_layout.restore_safety_snapshot_path("App", when)
    assert a == b
