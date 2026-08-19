"""Restore a chosen Drive snapshot back over a live database.

Safety order:
  1. Snapshot the CURRENT (about-to-be-overwritten) database and upload it
     to Drive first, tagged as a restore safety copy — so restore is always
     itself undoable.
  2. Download the chosen snapshot to staging.
  3. Integrity-check the downloaded file before touching anything real.
  4. Atomically swap it into place (write temp file in the same directory,
     then os.replace — never edits/truncates the live file directly).
  5. Re-verify integrity of the file now sitting at db_path.
"""
from __future__ import annotations

import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from app.config import ConfigStore, staging_dir
from app.core import drive_layout
from app.core.backup_engine import copy_current_db_aside, verify_file_integrity
from app.core.drive_client import DriveClient, DriveFileInfo
from app.core.history_store import HistoryStore
from app.logger import get_logger
from app.models import BackupRecord, BackupStatus, DatabaseConfig

log = get_logger("restore")


class RestoreError(RuntimeError):
    pass


def restore_snapshot(
    db_cfg: DatabaseConfig,
    snapshot: DriveFileInfo,
    *,
    config_store: ConfigStore,
    history: HistoryStore,
    drive: DriveClient,
) -> BackupRecord:
    now = datetime.now(timezone.utc)
    record = BackupRecord(
        db_id=db_cfg.id, app_name=db_cfg.app_name, started_iso=now.isoformat(),
        status=BackupStatus.RUNNING.value, message=f"Restoring {snapshot.name}",
    )
    history.upsert(record)

    work_dir = staging_dir() / db_cfg.id / "restore"
    work_dir.mkdir(parents=True, exist_ok=True)

    try:
        # 1. safety copy of the CURRENT db, uploaded before we touch anything
        if Path(db_cfg.db_path).exists():
            safety_local = work_dir / f"pre-restore-{now.strftime('%H-%M-%S')}.db"
            copy_current_db_aside(db_cfg.db_path, safety_local)
            safety_parts = drive_layout.restore_safety_snapshot_path(db_cfg.app_name, now)
            drive.upload_snapshot(safety_local, safety_parts)
            safety_record = BackupRecord(
                db_id=db_cfg.id, app_name=db_cfg.app_name, started_iso=now.isoformat(),
                finished_iso=datetime.now(timezone.utc).isoformat(), status=BackupStatus.SUCCESS.value,
                drive_path=safety_parts.full_path, size_bytes=safety_local.stat().st_size,
                message="Automatic safety copy before restore", is_restore_safety_copy=True,
            )
            history.upsert(safety_record)
            log.info("[%s] pre-restore safety copy uploaded: %s", db_cfg.app_name, safety_parts.full_path)
        else:
            log.warning("[%s] no existing db at %s to safety-copy before restore", db_cfg.app_name, db_cfg.db_path)

        # 2. download the chosen snapshot
        downloaded = work_dir / snapshot.name
        drive.download_file(snapshot.id, downloaded)

        # 3. verify BEFORE touching the live file
        ok, detail = verify_file_integrity(downloaded)
        if not ok:
            raise RestoreError(f"Downloaded snapshot failed integrity_check: {detail}")

        # 4. atomic swap into place
        target = Path(db_cfg.db_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp_target = target.with_suffix(target.suffix + ".restoring")
        shutil.copyfile(downloaded, tmp_target)
        os.replace(tmp_target, target)  # atomic on POSIX and Windows (same volume)

        # 5. re-verify the file that is now live
        ok2, detail2 = verify_file_integrity(target)
        if not ok2:
            raise RestoreError(f"Post-restore integrity_check failed on live file: {detail2}")

        record.status = BackupStatus.SUCCESS.value
        record.message = f"Restored from {snapshot.name}"
        record.drive_path = drive_layout.snapshot_path(db_cfg.app_name, now).full_path
        log.info("[%s] restore complete from %s", db_cfg.app_name, snapshot.name)

    except Exception as e:  # noqa: BLE001
        log.exception("[%s] restore failed", db_cfg.app_name)
        record.status = BackupStatus.FAILED.value
        record.message = f"{type(e).__name__}: {e}"
        raise
    finally:
        record.finished_iso = datetime.now(timezone.utc).isoformat()
        history.upsert(record)

    return record
