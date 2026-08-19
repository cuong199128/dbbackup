"""Retention policy.

Selection logic is pure (no network) so it's unit-testable. The apply step
is called ONLY after a new backup's upload has been confirmed successful —
callers must not invoke apply_retention() until the new snapshot's file id
came back from Drive, so a failed/partial upload never leaves a database
with zero recoverable backups.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from app.models import RetentionPolicy

if TYPE_CHECKING:
    from app.core.drive_client import DriveClient, DriveFileInfo


def select_files_to_delete(
    files: list["DriveFileInfo"], policy: RetentionPolicy, now: datetime | None = None
) -> list["DriveFileInfo"]:
    """files must be sorted oldest-first (as list_snapshots() returns them).
    A file is KEPT if it satisfies keep_count OR keep_days (union — whichever
    rule would keep it, it stays); everything else is returned for deletion.
    """
    if not files:
        return []
    now = now or datetime.now(timezone.utc)

    newest_first = list(reversed(files))
    kept_ids: set[str] = set()

    if policy.keep_count and policy.keep_count > 0:
        for f in newest_first[: policy.keep_count]:
            kept_ids.add(f.id)

    if policy.keep_days and policy.keep_days > 0:
        cutoff = now - timedelta(days=policy.keep_days)
        for f in files:
            modified = _parse_rfc3339(f.modified_time)
            if modified >= cutoff:
                kept_ids.add(f.id)

    return [f for f in files if f.id not in kept_ids]


def _parse_rfc3339(s: str) -> datetime:
    # Drive returns e.g. "2026-08-19T12:00:00.123Z"
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def apply_retention(client: "DriveClient", app_name: str, policy: RetentionPolicy) -> int:
    """Call only after a new snapshot upload is confirmed successful.
    Returns the number of old snapshots deleted.
    """
    files = client.list_snapshots(app_name)
    to_delete = select_files_to_delete(files, policy)
    for f in to_delete:
        client.delete_file(f.id)
    return len(to_delete)
