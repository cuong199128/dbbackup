"""Shared data models. Pure dataclasses, no I/O, no Qt, no Google — safe to
import from anywhere (core, gui, tests) without pulling in heavy deps.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional


class BackupStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED_NO_CHANGE = "skipped_no_change"
    RUNNING = "running"


@dataclass
class RetentionPolicy:
    """Retention is evaluated with AND semantics: a snapshot is kept if it is
    within `keep_count` most-recent OR within `keep_days` days — whichever
    keeps more, i.e. union, since the point of retention is "don't delete
    something a user might still want". Both are optional; 0/None disables
    that rule.
    """
    keep_count: Optional[int] = 14      # keep at least the last N snapshots
    keep_days: Optional[int] = 30       # keep everything newer than N days

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "RetentionPolicy":
        return RetentionPolicy(
            keep_count=d.get("keep_count", 14),
            keep_days=d.get("keep_days", 30),
        )


@dataclass
class DatabaseConfig:
    """One managed SQLite database."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    app_name: str = ""          # -> Drive folder name under "Python Database Backup/"
    db_path: str = ""           # absolute path to the source .db file
    enabled: bool = True
    cron: str = "0 */6 * * *"   # every 6 hours, standard 5-field cron
    retention: RetentionPolicy = field(default_factory=RetentionPolicy)
    keep_latest: bool = True    # mirror newest snapshot as <original filename> at app root
    vacuum_on_backup: bool = False
    analyze_on_backup: bool = False
    last_backup_hash: Optional[str] = None   # content hash at last successful backup
    last_backup_iso: Optional[str] = None
    last_backup_status: Optional[str] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["retention"] = self.retention.to_dict()
        return d

    @staticmethod
    def from_dict(d: dict) -> "DatabaseConfig":
        d = dict(d)
        retention = RetentionPolicy.from_dict(d.pop("retention", {}) or {})
        return DatabaseConfig(retention=retention, **d)


@dataclass
class BackupRecord:
    """One row in local backup history (also mirrors what happened on Drive)."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    db_id: str = ""
    app_name: str = ""
    started_iso: str = ""
    finished_iso: Optional[str] = None
    status: str = BackupStatus.RUNNING.value
    drive_path: Optional[str] = None
    size_bytes: Optional[int] = None
    message: str = ""
    is_restore_safety_copy: bool = False
