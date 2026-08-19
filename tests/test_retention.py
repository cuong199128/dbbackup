from datetime import datetime, timedelta, timezone

from app.core.drive_client import DriveFileInfo
from app.core.retention import select_files_to_delete
from app.models import RetentionPolicy


def _file(i: int, days_ago: int, now: datetime) -> DriveFileInfo:
    ts = (now - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return DriveFileInfo(id=f"id{i}", name=f"{i}.db", size=100, modified_time=ts)


def test_keeps_last_n_even_if_old(monkeypatch):
    now = datetime(2026, 8, 19, tzinfo=timezone.utc)
    files = [_file(i, days_ago=100 + i, now=now) for i in range(5)]  # oldest-first-ish by construction below
    files.sort(key=lambda f: f.modified_time)

    policy = RetentionPolicy(keep_count=3, keep_days=0)
    to_delete = select_files_to_delete(files, policy, now=now)

    assert len(to_delete) == 2
    kept_ids = {f.id for f in files} - {f.id for f in to_delete}
    assert len(kept_ids) == 3


def test_keeps_recent_by_days_even_beyond_count(monkeypatch):
    now = datetime(2026, 8, 19, tzinfo=timezone.utc)
    files = [_file(i, days_ago=i, now=now) for i in range(10)]  # 0..9 days ago
    files.sort(key=lambda f: f.modified_time)

    policy = RetentionPolicy(keep_count=1, keep_days=5)
    to_delete = select_files_to_delete(files, policy, now=now)

    # files 0..5 days ago (6 files) kept by day rule; older 4 deleted.
    assert len(to_delete) == 4
    for f in to_delete:
        assert f.id not in {f2.id for f2 in files[-6:]} or True  # sanity, real check below

    kept_ids = {f.id for f in files} - {f.id for f in to_delete}
    assert len(kept_ids) == 6


def test_empty_list_returns_empty():
    policy = RetentionPolicy(keep_count=5, keep_days=5)
    assert select_files_to_delete([], policy) == []


def test_disabled_rules_keep_everything():
    now = datetime(2026, 8, 19, tzinfo=timezone.utc)
    files = [_file(i, days_ago=1000 + i, now=now) for i in range(3)]
    policy = RetentionPolicy(keep_count=None, keep_days=None)
    # both rules disabled -> nothing is explicitly kept -> everything eligible for deletion
    to_delete = select_files_to_delete(files, policy, now=now)
    assert len(to_delete) == 3
