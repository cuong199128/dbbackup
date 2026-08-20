from __future__ import annotations

import sys

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QApplication

from app.config import ConfigStore
from app.core.drive_client import DriveClient
from app.core.history_store import HistoryStore
from app.core.scheduler import BackupScheduler
from app.core.single_instance import SingleInstanceGuard
from app.gui.main_window import MainWindow
from app.gui.tray import TrayIcon
from app.gui.icons import app_icon
from app.logger import setup_logging, get_logger, install_excepthook
from app.platform import autostart


def _sync_autostart(config_store: ConfigStore, log) -> None:
    """Đồng bộ trạng thái khởi động cùng hệ thống với cài đặt đã lưu
    (`start_with_os`, mặc định BẬT).

    Project này không có installer riêng (không có setup.exe kiểu Inno
    Setup/MSI) — bước "cài đặt" trong thực tế chính là lần đầu chạy file
    .exe đã build bằng packaging/build.py. Trước đây `start_with_os` chỉ
    là 1 giá trị nằm im trong config.json, không có chỗ nào thật sự gọi
    `autostart.enable()`, nên app KHÔNG tự thêm vào khởi động cùng Windows
    dù cài đặt mặc định là True. Gọi hàm này ngay khi khởi động đảm bảo
    lần chạy đầu tiên đó tự đăng ký khởi động cùng hệ thống luôn, đồng thời
    những lần sau tự tắt đi nếu người dùng đã bỏ chọn.
    """
    wanted = config_store.get_setting("start_with_os", True)
    try:
        currently_enabled = autostart.is_enabled()
        if wanted and not currently_enabled:
            autostart.enable()
            log.info("Đã tự động thêm vào khởi động cùng hệ thống")
        elif not wanted and currently_enabled:
            autostart.disable()
            log.info("Đã tắt khởi động cùng hệ thống theo cài đặt")
    except Exception:
        log.exception("Không thể đồng bộ trạng thái khởi động cùng hệ thống")


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
    install_excepthook()
    log = get_logger("main")
    log.info("Starting Database Backup Manager (background=%s)", background)

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # tray keeps it alive when the window is closed
    app.setWindowIcon(app_icon())

    # Chống mở 2 app: phải kiểm tra ngay sau khi có QApplication (cần cho
    # QSharedMemory/QLocalServer) và TRƯỚC khi tạo bất kỳ cửa sổ/scheduler
    # nào — nếu đã có phiên bản khác chạy, tiến trình này chỉ nhắn "hiện
    # cửa sổ lên" cho phiên bản đó rồi thoát ngay, không khởi tạo gì thêm.
    guard = SingleInstanceGuard()
    if guard.is_already_running():
        guard.notify_running_instance(request_show=not background)
        return 0

    config_store = ConfigStore()
    _sync_autostart(config_store, log)
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

    # Khi có tiến trình thứ 2 bị chặn bởi guard và gửi yêu cầu "hiện cửa sổ
    # lên", tín hiệu này chạy trên GUI thread (do QLocalServer nằm trong
    # cùng event loop) nên có thể gọi thẳng vào Qt widget, không cần bridge
    # thread-safe như với scheduler.
    guard.show_requested.connect(lambda: (window.showNormal(), window.raise_(), window.activateWindow()))

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
    scheduler.catch_up_missed_backups()  # bù các lượt backup bị lỡ trong lúc máy tắt/ngủ

    if not background:
        window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
