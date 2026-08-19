"""Background scheduling. One APScheduler cron job per enabled database.

Runs in a background thread inside the same process as the tray/GUI (there
is no separate daemon process — the tray app itself IS the background
process; autostart just makes sure it's launched at login, see
app/platform/).
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
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

# APScheduler chỉ "bắt kịp" một lượt chạy bị lỡ nếu app được mở lại trong
# vòng misfire_grace_time (bên dưới) sau giờ lẽ ra phải chạy — quá thời gian
# này nó tự huỷ bỏ lượt đó, không backup bù. Với máy cá nhân hay tắt qua
# đêm/nhiều ngày, khoảng lỡ thực tế thường dài hơn nhiều so với một giờ, nên
# cần cơ chế catch-up riêng ở dưới (catch_up_missed_backups) chạy một lần
# khi khởi động app để bù cho khoảng thời gian máy tắt.
MISFIRE_GRACE_SECONDS = 3600


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
            args=[db_cfg.id], replace_existing=True, misfire_grace_time=MISFIRE_GRACE_SECONDS,
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

    # -------------------------------------------------- catch-up khi mở máy
    def catch_up_missed_backups(self, lookback_days: int = 14) -> None:
        """Gọi một lần ngay sau start(), lúc app vừa mở lên. Với mỗi database
        đang bật, tính xem lần gần nhất đáng lẽ backup theo lịch cron là khi
        nào; nếu thời điểm đó muộn hơn lần backup thành công gần nhất đã ghi
        nhận (hoặc chưa từng backup) thì coi là bị lỡ lịch — chạy bù ngay.

        Chạy bù vẫn tuân thủ "chỉ backup khi có thay đổi" (force=False):
        nếu database không đổi gì trong lúc máy tắt thì chỉ ghi nhận
        SKIPPED, không tải file thừa lên Drive.

        Chạy trong thread nền để không chặn lúc khởi động app.
        """
        threading.Thread(target=self._catch_up_worker, args=(lookback_days,), daemon=True).start()

    def _catch_up_worker(self, lookback_days: int) -> None:
        now = datetime.now(timezone.utc)
        for db_cfg in self._config.list_databases():
            if not db_cfg.enabled:
                continue
            try:
                missed_at = self._last_missed_fire_time(db_cfg, now, lookback_days)
            except Exception:
                log.exception("[%s] không tính được lịch bị lỡ, bỏ qua catch-up", db_cfg.app_name)
                continue
            if missed_at is None:
                continue
            log.info(
                "[%s] phát hiện lỡ lịch backup lúc %s (máy có thể đã tắt/ngủ) — chạy bù ngay",
                db_cfg.app_name, missed_at.isoformat(),
            )
            self._run_for(db_cfg.id, force=False)

    def _last_missed_fire_time(self, db_cfg: DatabaseConfig, now: datetime, lookback_days: int) -> Optional[datetime]:
        """Trả về thời điểm cron gần nhất (trong vòng lookback_days) đáng lẽ
        đã chạy nhưng chưa có bản backup nào sau đó — tức là bị lỡ. Trả về
        None nếu không lỡ lịch nào (backup gần nhất đã sau lần cron gần nhất
        rồi, hoặc job chưa từng tới lượt chạy nào trong khoảng lookback).
        """
        trigger = CronTrigger.from_crontab(db_cfg.cron)
        window_start = now - timedelta(days=lookback_days)

        last_fire: Optional[datetime] = None
        fire = trigger.get_next_fire_time(None, window_start)
        iterations = 0
        while fire is not None and fire <= now and iterations < 100_000:
            last_fire = fire
            next_fire = trigger.get_next_fire_time(fire, fire)
            iterations += 1
            if next_fire is None or next_fire <= fire:
                break
            fire = next_fire

        if last_fire is None:
            return None

        last_backup_dt = _parse_iso(db_cfg.last_backup_iso)
        if last_backup_dt is None or last_backup_dt < last_fire:
            return last_fire
        return None


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
