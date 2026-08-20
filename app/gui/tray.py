from __future__ import annotations

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from app.gui.icons import app_icon
from app.logger import get_logger
from app.platform import autostart

log = get_logger("tray")


class TrayIcon(QSystemTrayIcon):
    def __init__(self, app: QApplication, main_window, scheduler, config_store):
        super().__init__(app_icon(), app)
        self._app = app
        self._main_window = main_window
        self._scheduler = scheduler
        self._config = config_store
        self.setToolTip("Trình quản lý Backup Database")

        self._menu = QMenu()
        self._backup_now_menu = QMenu("Backup ngay")
        self._rebuild_menu()
        self.setContextMenu(self._menu)

        self.activated.connect(self._on_activated)

    def _rebuild_menu(self) -> None:
        self._menu.clear()
        show_action = QAction("Mở Trình quản lý Backup Database", self._menu)
        show_action.triggered.connect(self._show_window)
        self._menu.addAction(show_action)

        self._backup_now_menu = QMenu("Backup ngay", self._menu)
        for db in self._config.list_databases():
            act = QAction(db.app_name or db.db_path, self._backup_now_menu)
            act.triggered.connect(lambda checked=False, db_id=db.id: self._scheduler.run_now(db_id))
            self._backup_now_menu.addAction(act)
        if not self._config.list_databases():
            empty = QAction("(chưa có database nào)", self._backup_now_menu)
            empty.setEnabled(False)
            self._backup_now_menu.addAction(empty)
        self._menu.addMenu(self._backup_now_menu)

        self._menu.addSeparator()
        autostart_action = QAction("Khởi động cùng Windows", self._menu)
        autostart_action.setCheckable(True)
        try:
            autostart_action.setChecked(autostart.is_enabled())
        except Exception:
            autostart_action.setChecked(self._config.get_setting("start_with_os", True))
        autostart_action.toggled.connect(self._on_toggle_autostart)
        self._menu.addAction(autostart_action)

        self._menu.addSeparator()
        quit_action = QAction("Thoát", self._menu)
        quit_action.triggered.connect(self._app.quit)
        self._menu.addAction(quit_action)

    def refresh(self) -> None:
        self._rebuild_menu()

    def _on_toggle_autostart(self, checked: bool) -> None:
        self._config.set_setting("start_with_os", checked)
        try:
            if checked:
                autostart.enable()
            else:
                autostart.disable()
        except Exception:
            log.exception("Không thể %s khởi động cùng hệ thống", "bật" if checked else "tắt")
            self.notify(
                "Khởi động cùng Windows",
                f"Không thể {'bật' if checked else 'tắt'} khởi động cùng hệ thống. Xem tab Nhật ký để biết chi tiết.",
                is_error=True,
            )

    def _on_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._show_window()

    def _show_window(self) -> None:
        self._main_window.showNormal()
        self._main_window.raise_()
        self._main_window.activateWindow()

    def notify(self, title: str, message: str, is_error: bool = False) -> None:
        icon = QSystemTrayIcon.MessageIcon.Critical if is_error else QSystemTrayIcon.MessageIcon.Information
        self.showMessage(title, message, icon, 5000)
