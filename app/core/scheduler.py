"""Background scheduling. One APScheduler cron job per enabled database.

Runs in a background thread inside the same process as the tray/GUI (there
is no separate daemon process — the tray app itself IS the background
process; autostart just makes sure it's launched at login, see
app/platform/).
"""
from __future__ import annotations

import threading
from typing import Callable, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import ConfigStore
from app.core.backup_service import run_backup
from app.core.drive_client import DriveClient
from app.core.history_store import HistoryStore
from app.logger import get_logger
from app.models import BackupRecord, DatabaseConfig

log = get_logger("scheduler")

OnRunCallback = Callable[[BackupRecord], None]


class BackupScheduler:
    def __init__(self, config_store: ConfigStore, history: HistoryStore, drive: DriveClient):
        self._config = config_store
        self._history = history
        self._drive = drive
        self._sched = BackgroundScheduler()
        self._lock = threading.RLock()
        self._on_run: Optional[OnRunCallback] = None

    def set_on_run_callback(self, cb: OnRunCallback) -> None:
        """GUI hooks in here to refresh Status/History tabs after each run."""
        self._on_run = cb

    def start(self) -> None:
        with self._lock:
            for db_cfg in self._config.list_databases():
                if db_cfg.enabled:
                    self._add_job(db_cfg)
            self._sched.start()
            log.info("Scheduler started with %d job(s)", len(self._sched.get_jobs()))

    def stop(self) -> None:
        self._sched.shutdown(wait=False)

    def reload(self) -> None:
        """Call after any add/edit/remove/enable-toggle of a database."""
        with self._lock:
            for job in self._sched.get_jobs():
                self._sched.remove_job(job.id)
            for db_cfg in self._config.list_databases():
                if db_cfg.enabled:
                    self._add_job(db_cfg)
            log.info("Scheduler reloaded with %d job(s)", len(self._sched.get_jobs()))

    def _add_job(self, db_cfg: DatabaseConfig) -> None:
        trigger = CronTrigger.from_crontab(db_cfg.cron)
        self._sched.add_job(
            self._run_for, trigger=trigger, id=db_cfg.id,
            args=[db_cfg.id], replace_existing=True, misfire_grace_time=3600,
            coalesce=True, max_instances=1,
        )

    def _run_for(self, db_id: str, force: bool = False) -> Optional[BackupRecord]:
        db_cfg = self._config.get_database(db_id)
        if db_cfg is None:
            log.warning("Scheduled job fired for unknown db_id=%s (removed?)", db_id)
            return None
        record = run_backup(db_cfg, config_store=self._config, history=self._history, drive=self._drive, force=force)
        if self._on_run:
            try:
                self._on_run(record)
            except Exception:
                log.exception("on_run callback raised")
        return record

    def run_now(self, db_id: str) -> None:
        """Manual 'Backup Now' from GUI/tray — runs in a worker thread so the
        UI never blocks on network I/O.
        """
        threading.Thread(target=self._run_for, args=(db_id, True), daemon=True).start()
