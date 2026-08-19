"""Pure path-building logic for the Drive folder layout. No network calls —
kept separate from drive_client.py so it's trivially unit-testable.

Layout:
  Python Database Backup/
    <app_name>/
      <original_filename>          <- optional "Latest" mirror, toggled per DB
      2026/08-19/
        08-00-00.db
        12-00-00.db
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath

from app.config import DRIVE_ROOT_FOLDER


@dataclass(frozen=True)
class DrivePathParts:
    """Folder path components (each a single path segment, in order) plus
    the final filename — drive_client walks/creates folders segment by
    segment using these.
    """
    folder_segments: tuple[str, ...]
    filename: str

    @property
    def full_path(self) -> str:
        return str(PurePosixPath(*self.folder_segments, self.filename))


def app_root_segments(app_name: str) -> tuple[str, ...]:
    return (DRIVE_ROOT_FOLDER, app_name)


def snapshot_path(app_name: str, when: datetime) -> DrivePathParts:
    """.../<app_name>/2026/08-19/12-00-00.db"""
    year = when.strftime("%Y")
    month_day = when.strftime("%m-%d")
    filename = when.strftime("%H-%M-%S") + ".db"
    segments = app_root_segments(app_name) + (year, month_day)
    return DrivePathParts(folder_segments=segments, filename=filename)


def latest_path(app_name: str, original_filename: str) -> DrivePathParts:
    """.../<app_name>/data.db  (kept at original name so it opens directly,
    e.g. from a SQLite viewer on Android)
    """
    return DrivePathParts(folder_segments=app_root_segments(app_name), filename=original_filename)


def restore_safety_snapshot_path(app_name: str, when: datetime) -> DrivePathParts:
    """Same layout as a normal snapshot — pre-restore safety copies live
    alongside regular backups so retention/history treats them uniformly;
    they're distinguished in local history by `is_restore_safety_copy`.
    """
    return snapshot_path(app_name, when)
