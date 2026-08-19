from __future__ import annotations

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from app.gui.icons import app_icon


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
        quit_action = QAction("Thoát", self._menu)
        quit_action.triggered.connect(self._app.quit)
        self._menu.addAction(quit_action)

    def refresh(self) -> None:
        self._rebuild_menu()

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
