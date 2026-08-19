from __future__ import annotations

import sys

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QApplication

from app.config import ConfigStore
from app.core.drive_client import DriveClient
from app.core.history_store import HistoryStore
from app.core.scheduler import BackupScheduler
from app.gui.main_window import MainWindow
from app.gui.tray import TrayIcon
from app.gui.icons import app_icon
from app.logger import setup_logging, get_logger


class _SchedulerBridge(QObject):
    """The scheduler fires its callback from a background thread (APScheduler
    worker or the manual 'Backup Now' thread). Qt widgets may only be
    touched from the GUI thread, so we hop over via a queued signal instead
    of calling into MainWindow directly.
    """
    backup_finished = Signal()


def main() -> int:
    background = "--background" in sys.argv  # start minimized to tray (used by autostart)

    setup_logging()
    log = get_logger("main")
    log.info("Starting Database Backup Manager (background=%s)", background)

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # tray keeps it alive when the window is closed
    app.setWindowIcon(app_icon())

    config_store = ConfigStore()
    history = HistoryStore()
    history_deleted = history.trim_old()  # dọn bớt lịch sử quá cũ, không giới hạn cứng như log file
    if history_deleted:
        log.info("Đã dọn %d bản ghi lịch sử cũ", history_deleted)
    drive = DriveClient()
    scheduler = BackupScheduler(config_store, history, drive)

    window = MainWindow(config_store, history, drive, scheduler)
    tray = TrayIcon(app, window, scheduler, config_store)
    window.set_tray(tray)
    tray.show()

    bridge = _SchedulerBridge()
    bridge.backup_finished.connect(window.on_backup_finished, Qt.ConnectionType.QueuedConnection)
    bridge.backup_finished.connect(tray.refresh, Qt.ConnectionType.QueuedConnection)

    def _on_run(record):
        # runs on a worker thread — only emit a signal here, no widget access.
        bridge.backup_finished.emit()
        if record.status == "failed":
            tray.notify("Backup thất bại", f"{record.app_name}: {record.message}", is_error=True)

    scheduler.set_on_run_callback(_on_run)
    scheduler.start()

    if not background:
        window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
