"""Orchestrates a single backup run for one DatabaseConfig, tying together
change detection, snapshotting, upload, retention and history logging.

Order of operations matters for the "never lose a recoverable backup"
guarantee:
  1. check for change (skip early if nothing changed)
  2. create local snapshot (online backup API, integrity_check)
  3. upload snapshot to Drive -> only on confirmed success do we proceed
  4. update the Latest mirror (if enabled) — best-effort, does not block
     the run being considered a success, but is logged if it fails
  5. run retention (delete old snapshots) — ONLY after step 3 succeeded
  6. persist last_backup_hash / status to config, write history record
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.config import ConfigStore, staging_dir
from app.core import change_detector, drive_layout, retention
from app.core.backup_engine import BackupIntegrityError, create_snapshot
from app.core.drive_client import DriveClient
from app.core.history_store import HistoryStore
from app.logger import get_logger
from app.models import BackupRecord, BackupStatus, DatabaseConfig

log = get_logger("backup_service")


class BackupRunError(RuntimeError):
    pass


def run_backup(
    db_cfg: DatabaseConfig,
    *,
    config_store: ConfigStore,
    history: HistoryStore,
    drive: DriveClient,
    force: bool = False,
) -> BackupRecord:
    """Runs (or skips) one backup for db_cfg. Always returns a BackupRecord
    (also already persisted to history) describing what happened.
    """
    now = datetime.now(timezone.utc)
    record = BackupRecord(
        db_id=db_cfg.id, app_name=db_cfg.app_name,
        started_iso=now.isoformat(), status=BackupStatus.RUNNING.value,
    )
    history.upsert(record)

    try:
        if not force and not change_detector.has_changed(db_cfg.db_path, db_cfg.last_backup_hash):
            record.status = BackupStatus.SKIPPED_NO_CHANGE.value
            record.message = "No change detected since last backup."
            record.finished_iso = datetime.now(timezone.utc).isoformat()
            history.upsert(record)
            log.info("[%s] skipped — no change", db_cfg.app_name)
            return record

        parts = drive_layout.snapshot_path(db_cfg.app_name, now)
        local_snapshot = staging_dir() / db_cfg.id / parts.filename
        snap = create_snapshot(
            db_cfg.db_path, local_snapshot,
            vacuum=db_cfg.vacuum_on_backup, analyze=db_cfg.analyze_on_backup,
        )

        file_id = drive.upload_snapshot(snap.path, parts)
        record.drive_path = parts.full_path
        record.size_bytes = snap.size_bytes
        log.info("[%s] uploaded snapshot id=%s path=%s", db_cfg.app_name, file_id, parts.full_path)

        if db_cfg.keep_latest:
            try:
                original_name = Path(db_cfg.db_path).name
                latest_parts = drive_layout.latest_path(db_cfg.app_name, original_name)
                drive.upload_or_replace(snap.path, latest_parts)
            except Exception:
                log.exception("[%s] Latest mirror update failed (non-fatal)", db_cfg.app_name)

        deleted = retention.apply_retention(drive, db_cfg.app_name, db_cfg.retention)
        if deleted:
            log.info("[%s] retention removed %d old snapshot(s)", db_cfg.app_name, deleted)

        db_cfg.last_backup_hash = change_detector.fingerprint(db_cfg.db_path).as_key()
        db_cfg.last_backup_iso = now.isoformat()
        db_cfg.last_backup_status = BackupStatus.SUCCESS.value
        config_store.update_database(db_cfg)

        record.status = BackupStatus.SUCCESS.value
        record.message = f"OK ({snap.size_bytes} bytes, retention removed {deleted})"

    except BackupIntegrityError as e:
        log.error("[%s] integrity check failed: %s", db_cfg.app_name, e)
        record.status = BackupStatus.FAILED.value
        record.message = str(e)
        db_cfg.last_backup_status = BackupStatus.FAILED.value
        config_store.update_database(db_cfg)
    except Exception as e:  # noqa: BLE001 - top-level run boundary, must not crash the scheduler
        log.exception("[%s] backup failed", db_cfg.app_name)
        record.status = BackupStatus.FAILED.value
        record.message = f"{type(e).__name__}: {e}"
        db_cfg.last_backup_status = BackupStatus.FAILED.value
        config_store.update_database(db_cfg)
    finally:
        record.finished_iso = datetime.now(timezone.utc).isoformat()
        history.upsert(record)

    return record
