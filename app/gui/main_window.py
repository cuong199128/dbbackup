from __future__ import annotations

from datetime import date, datetime, timedelta

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor, QBrush
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QMainWindow,
    QMessageBox, QPushButton,
    QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from app.config import ConfigStore, credentials_path, install_credentials_file
from app.core.drive_client import DriveAuthError, DriveClient
from app.core.history_store import HistoryStore
from app.core.restore import restore_snapshot
from app.core.scheduler import BackupScheduler
from app.gui.dialogs import CredentialsMissingDialog, DatabaseEditDialog, RestoreDialog
from app.gui.icons import app_icon
from app.logger import clear_log_files, get_logger, get_ring_handler
from app.models import DatabaseConfig
from app.timeutil import format_vn_iso, now_vn, to_vn

log = get_logger("main_window")

DB_ID_ROLE = Qt.ItemDataRole.UserRole

COLOR_SUCCESS = QColor(30, 140, 60)
COLOR_FAILED = QColor(190, 40, 40)
COLOR_NEUTRAL = QColor(120, 120, 120)


class MainWindow(QMainWindow):
    def __init__(self, config_store: ConfigStore, history: HistoryStore, drive: DriveClient, scheduler: BackupScheduler):
        super().__init__()
        self.setWindowTitle("Trình quản lý Backup Database")
        self.setWindowIcon(app_icon())
        self.resize(980, 640)

        self._config = config_store
        self._history = history
        self._drive = drive
        self._scheduler = scheduler
        self._tray = None  # gán bởi main.py sau khi tạo tray
        self._log_grouped_cache: dict[str, list[str]] | None = None

        self._tabs = QTabWidget()
        self.setCentralWidget(self._tabs)

        self._build_databases_tab()
        self._build_history_tab()
        self._build_logs_tab()

        self._log_timer = QTimer(self)
        self._log_timer.timeout.connect(self._refresh_logs)
        self._log_timer.start(2000)

        self._refresh_databases_tree()
        self._refresh_history_table()
        self._refresh_logs()

    def set_tray(self, tray) -> None:
        self._tray = tray

    # ------------------------------------------------------- Tab Database
    def _build_databases_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        login_row = QHBoxLayout()
        self.login_status_label = QLabel()
        self.login_status_label.setTextFormat(Qt.TextFormat.RichText)
        self.login_btn = QPushButton("Đăng nhập Google Drive")
        self.login_btn.clicked.connect(self._on_login_clicked)
        login_row.addWidget(self.login_status_label)
        login_row.addStretch(1)
        login_row.addWidget(self.login_btn)
        layout.addLayout(login_row)

        self.db_tree = QTreeWidget()
        self.db_tree.setColumnCount(2)
        self.db_tree.setHeaderLabels(["Database", "Thông tin"])
        self.db_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.db_tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.db_tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.db_tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.db_tree.itemSelectionChanged.connect(self._on_tree_selection_changed)

        btn_row = QHBoxLayout()
        self.add_btn = QPushButton("Thêm database")
        self.edit_btn = QPushButton("Sửa")
        self.remove_btn = QPushButton("Xóa")
        self.backup_now_btn = QPushButton("Backup ngay")
        self.restore_btn = QPushButton("Khôi phục...")
        self.expand_btn = QPushButton("Mở rộng tất cả")
        self.collapse_btn = QPushButton("Thu gọn tất cả")

        self.add_btn.clicked.connect(self._on_add)
        self.edit_btn.clicked.connect(self._on_edit)
        self.remove_btn.clicked.connect(self._on_remove)
        self.backup_now_btn.clicked.connect(self._on_backup_now)
        self.restore_btn.clicked.connect(self._on_restore)
        self.expand_btn.clicked.connect(self.db_tree.expandAll)
        self.collapse_btn.clicked.connect(self.db_tree.collapseAll)

        for b in (self.add_btn, self.edit_btn, self.remove_btn, self.backup_now_btn,
                  self.restore_btn, self.expand_btn, self.collapse_btn):
            btn_row.addWidget(b)
        layout.addLayout(btn_row)

        layout.addWidget(self.db_tree)

        self._tabs.addTab(tab, "Database")
        self._update_login_status()
        self._update_selection_buttons(selected=False)

    def _update_login_status(self) -> None:
        if self._drive.is_logged_in():
            email = ""
            try:
                email = self._drive.get_account_email()
            except Exception:
                log.exception("Không lấy được email tài khoản Drive")
            suffix = f" — {email}" if email else ""
            self.login_status_label.setText(
                f'<span style="color:#1e8c3c; font-weight:bold;">● Đã kết nối Google Drive{suffix}</span>'
            )
            self.login_btn.setText("Đăng xuất")
        else:
            self.login_status_label.setText(
                '<span style="color:#be2828; font-weight:bold;">● Chưa kết nối Google Drive</span>'
            )
            self.login_btn.setText("Đăng nhập Google Drive")

    def _on_login_clicked(self) -> None:
        try:
            if self._drive.is_logged_in():
                self._drive.logout()
            else:
                self._login_with_credentials_fallback()
        except Exception as e:  # noqa: BLE001
            log.exception("Đăng nhập/đăng xuất thất bại")
            QMessageBox.critical(self, "Google Drive", f"Thao tác thất bại: {e}")
        self._update_login_status()

    def _login_with_credentials_fallback(self) -> None:
        """Thử đăng nhập; nếu chưa có credentials.json, hiện dialog cho
        người dùng chọn file (chạy giống nhau trên Windows và Linux) rồi
        tự sao chép vào đúng vị trí và thử đăng nhập lại.
        """
        try:
            self._drive.login_interactive()
            return
        except DriveAuthError:
            pass  # rơi xuống dưới để hỏi chọn file

        dlg = CredentialsMissingDialog(self, str(credentials_path()))
        if dlg.exec() and dlg.chosen_path():
            try:
                install_credentials_file(dlg.chosen_path())
            except Exception as e:  # noqa: BLE001
                QMessageBox.critical(self, "Lỗi", f"Không thể sao chép file: {e}")
                return
            try:
                self._drive.login_interactive()
            except Exception as e:  # noqa: BLE001
                log.exception("Đăng nhập thất bại sau khi chọn credentials.json")
                QMessageBox.critical(self, "Google Drive", f"Đăng nhập thất bại: {e}")

    # --------------------------------------------------- tree selection --
    def _selected_db_id(self) -> str | None:
        items = self.db_tree.selectedItems()
        if not items:
            return None
        item = items[0]
        while item.parent() is not None:
            item = item.parent()
        return item.data(0, DB_ID_ROLE)

    def _selected_db(self) -> DatabaseConfig | None:
        db_id = self._selected_db_id()
        return self._config.get_database(db_id) if db_id else None

    def _on_tree_selection_changed(self) -> None:
        self._update_selection_buttons(selected=self._selected_db() is not None)

    def _update_selection_buttons(self, selected: bool) -> None:
        # Các nút chỉ có ý nghĩa khi đã chọn một database cụ thể sẽ ẩn đi
        # khi chưa chọn gì, thay vì chỉ mờ đi.
        self.edit_btn.setVisible(selected)
        self.remove_btn.setVisible(selected)
        self.backup_now_btn.setVisible(selected)
        self.restore_btn.setVisible(selected)

    # ------------------------------------------------------------ CRUD ---
    def _on_add(self) -> None:
        dlg = DatabaseEditDialog(self)
        if dlg.exec():
            self._config.add_database(dlg.result_config())
            self._scheduler.reload()
            self._refresh_databases_tree()
            if self._tray:
                self._tray.refresh()

    def _on_edit(self) -> None:
        db = self._selected_db()
        if not db:
            return
        dlg = DatabaseEditDialog(self, existing=db)
        if dlg.exec():
            self._config.update_database(dlg.result_config())
            self._scheduler.reload()
            self._refresh_databases_tree()
            if self._tray:
                self._tray.refresh()

    def _on_remove(self) -> None:
        db = self._selected_db()
        if not db:
            return
        confirm = QMessageBox.question(
            self, "Xóa database",
            f"Ngừng quản lý '{db.app_name}'? Các bản backup đã có trên Drive sẽ KHÔNG bị xóa.",
        )
        if confirm == QMessageBox.StandardButton.Yes:
            self._config.remove_database(db.id)
            self._scheduler.reload()
            self._refresh_databases_tree()
            if self._tray:
                self._tray.refresh()

    def _on_backup_now(self) -> None:
        db = self._selected_db()
        if not db:
            return
        self._scheduler.run_now(db.id)
        QMessageBox.information(self, "Đã bắt đầu backup", f"Đang backup '{db.app_name}' ở chế độ nền.")

    def _on_restore(self) -> None:
        db = self._selected_db()
        if not db:
            return
        if not self._drive.is_logged_in():
            QMessageBox.warning(self, "Chưa kết nối", "Vui lòng đăng nhập Google Drive trước.")
            return
        try:
            snapshots = self._drive.list_snapshots(db.app_name)
        except Exception as e:  # noqa: BLE001
            log.exception("Không thể lấy danh sách bản backup")
            QMessageBox.critical(self, "Khôi phục", f"Không thể lấy danh sách backup: {e}")
            return
        if not snapshots:
            QMessageBox.information(self, "Khôi phục", "Chưa có bản backup nào cho database này.")
            return
        dlg = RestoreDialog(self, db.app_name, snapshots)
        if dlg.exec() and dlg.selected_snapshot():
            try:
                restore_snapshot(db, dlg.selected_snapshot(), config_store=self._config, history=self._history, drive=self._drive)
                QMessageBox.information(self, "Khôi phục", "Khôi phục thành công.")
            except Exception as e:  # noqa: BLE001
                QMessageBox.critical(self, "Khôi phục thất bại", str(e))
            self._refresh_history_table()

    # ------------------------------------------------------- tree render
    def _status_color(self, status: str | None) -> QColor:
        if status == "success":
            return COLOR_SUCCESS
        if status == "failed":
            return COLOR_FAILED
        return COLOR_NEUTRAL

    def _status_text(self, status: str | None) -> str:
        return {
            "success": "Thành công",
            "failed": "Thất bại",
            "skipped_no_change": "Bỏ qua (không đổi)",
            "running": "Đang chạy",
        }.get(status or "", "Chưa backup lần nào")

    def _refresh_databases_tree(self) -> None:
        previously_selected = self._selected_db_id()
        self.db_tree.clear()
        for db in self._config.list_databases():
            top = QTreeWidgetItem([db.app_name, self._status_text(db.last_backup_status)])
            top.setData(0, DB_ID_ROLE, db.id)
            color = self._status_color(db.last_backup_status)
            top.setForeground(1, QBrush(color))
            if not db.enabled:
                top.setForeground(0, QBrush(COLOR_NEUTRAL))
                top.setText(1, top.text(1) + " (đang tắt)")

            rows = [
                ("Đường dẫn", db.db_path),
                ("Lịch backup (cron)", db.cron),
                ("Giữ bản Latest", "Bật" if db.keep_latest else "Tắt"),
                ("VACUUM / ANALYZE", f"{'Bật' if db.vacuum_on_backup else 'Tắt'} / {'Bật' if db.analyze_on_backup else 'Tắt'}"),
                ("Retention", f"{db.retention.keep_count or 'tắt'} bản gần nhất, "
                              f"{db.retention.keep_days or 'tắt'} ngày"),
                ("Backup gần nhất", format_vn_iso(db.last_backup_iso)),
            ]
            for label, value in rows:
                child = QTreeWidgetItem([label, str(value)])
                top.addChild(child)

            self.db_tree.addTopLevelItem(top)
            if previously_selected == db.id:
                top.setSelected(True)

        self.db_tree.collapseAll()
        self._update_selection_buttons(selected=self._selected_db() is not None)

    # --------------------------------------------------------- Tab Lịch sử
    def _build_history_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        btn_row = QHBoxLayout()
        refresh_btn = QPushButton("Làm mới")
        refresh_btn.clicked.connect(self._refresh_history_table)
        hist_expand_btn = QPushButton("Mở rộng tất cả")
        hist_collapse_btn = QPushButton("Thu gọn tất cả")
        btn_row.addWidget(refresh_btn)
        btn_row.addWidget(hist_expand_btn)
        btn_row.addWidget(hist_collapse_btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        self.history_tree = QTreeWidget()
        self.history_tree.setColumnCount(5)
        self.history_tree.setHeaderLabels(
            ["Giờ / Ứng dụng", "Trạng thái", "Kích thước", "Đường dẫn trên Drive", "Ghi chú"]
        )
        self.history_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.history_tree.header().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.history_tree.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        layout.addWidget(self.history_tree)

        hist_expand_btn.clicked.connect(self.history_tree.expandAll)
        hist_collapse_btn.clicked.connect(self.history_tree.collapseAll)

        self._tabs.addTab(tab, "Lịch sử")

    def _parse_history_local_dt(self, iso_str: str):
        """started_iso được lưu dạng ISO UTC (xem backup_service.py); quy
        đổi sang giờ VN để nhóm theo đúng ngày lịch VN, nhất quán với cách
        hiển thị dùng ở nơi khác (format_vn_iso, tên thư mục Drive...).
        """
        if not iso_str:
            return None
        try:
            dt = datetime.fromisoformat(iso_str)
        except ValueError:
            return None
        return to_vn(dt)

    def _add_history_group(self, tree_parent_data: str, label: str, rows: list, expanded_keys: set) -> None:
        group_item = QTreeWidgetItem([label])
        group_item.setData(0, Qt.ItemDataRole.UserRole, tree_parent_data)
        group_item.setFirstColumnSpanned(True)
        for row_label, r in rows:
            text = row_label
            if r.is_restore_safety_copy:
                text += " (bản an toàn trước khi khôi phục)"
            child = QTreeWidgetItem([
                text,
                self._status_text(r.status),
                str(r.size_bytes or "-"),
                r.drive_path or "-",
                r.message,
            ])
            child.setForeground(1, QBrush(self._status_color(r.status)))
            group_item.addChild(child)
        self.history_tree.addTopLevelItem(group_item)
        if tree_parent_data in expanded_keys:
            group_item.setExpanded(True)

    def _refresh_history_table(self) -> None:
        records = self._history.list_all()

        grouped: dict[str, list] = {}
        undated: list = []
        for r in records:
            local_dt = self._parse_history_local_dt(r.started_iso)
            if local_dt is None:
                undated.append(r)
                continue
            grouped.setdefault(local_dt.date().isoformat(), []).append((local_dt, r))

        # Giữ trạng thái mở rộng/thu gọn hiện có qua mỗi lần làm mới. Mặc
        # định LUÔN thu gọn (kể cả ngày mới nhất) — người dùng tự bấm để
        # xem chi tiết khi cần, thay vì cả danh sách hiện phẳng ra hết.
        expanded_keys = {
            self.history_tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole)
            for i in range(self.history_tree.topLevelItemCount())
            if self.history_tree.topLevelItem(i).isExpanded()
        }

        self.history_tree.clear()
        for date_key in sorted(grouped.keys(), reverse=True):
            entries = grouped[date_key]
            day = date.fromisoformat(date_key)
            label = f"{self._vn_date_label(day)} ({len(entries)} bản ghi)"
            rows = [(local_dt.strftime("%H:%M:%S") + "  " + r.app_name, r) for local_dt, r in entries]
            self._add_history_group(date_key, label, rows, expanded_keys)

        if undated:
            rows = [(r.app_name, r) for r in undated]
            self._add_history_group("?", f"Không rõ ngày ({len(undated)} bản ghi)", rows, expanded_keys)



    # ------------------------------------------------------------ Tab Nhật ký
    def _build_logs_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        btn_row = QHBoxLayout()
        clear_btn = QPushButton("Xóa log")
        clear_btn.clicked.connect(self._on_clear_logs)
        log_expand_btn = QPushButton("Mở rộng tất cả")
        log_collapse_btn = QPushButton("Thu gọn tất cả")
        btn_row.addWidget(clear_btn)
        btn_row.addWidget(log_expand_btn)
        btn_row.addWidget(log_collapse_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(QLabel("Log tự động xoá bớt khi vượt quá 5MB x 5 file (giữ khoảng 30MB gần nhất)."))
        layout.addLayout(btn_row)

        self.log_tree = QTreeWidget()
        self.log_tree.setColumnCount(1)
        self.log_tree.setHeaderHidden(True)
        self.log_tree.setUniformRowHeights(True)
        layout.addWidget(self.log_tree)

        log_expand_btn.clicked.connect(self.log_tree.expandAll)
        log_collapse_btn.clicked.connect(self.log_tree.collapseAll)

        self._tabs.addTab(tab, "Nhật ký")

    def _on_clear_logs(self) -> None:
        confirm = QMessageBox.question(
            self, "Xóa log",
            "Xóa toàn bộ file log trên đĩa và nhật ký đang hiển thị? Thao tác này không thể hoàn tác.",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        clear_log_files()
        self._log_grouped_cache = None  # ép rebuild kể cả khi rỗng == rỗng
        self._refresh_logs()

    def _vn_date_label(self, day: date) -> str:
        today = now_vn().date()
        if day == today:
            return f"Hôm nay — {day.strftime('%d/%m/%Y')}"
        if day == today - timedelta(days=1):
            return f"Hôm qua — {day.strftime('%d/%m/%Y')}"
        return day.strftime("%d/%m/%Y")

    def _log_entry_color(self, first_line: str) -> QColor | None:
        if "[CRITICAL]" in first_line or "[ERROR]" in first_line:
            return COLOR_FAILED
        if "[WARNING]" in first_line:
            return QColor(200, 140, 0)
        return None

    def _refresh_logs(self) -> None:
        # Mỗi phần tử trong ring buffer là 1 dòng log đã format sẵn
        # "YYYY-MM-DD HH:MM:SS [LEVEL] logger: message" (giờ VN, xem
        # VNFormatter trong logger.py) — có thể kèm nhiều dòng traceback
        # nối phía sau nếu log kèm exc_info.
        lines = get_ring_handler().snapshot()[-2000:]
        grouped: dict[str, list[str]] = {}
        for entry in lines:
            date_key = entry[:10] if len(entry) >= 10 and entry[4] == "-" and entry[7] == "-" else "?"
            grouped.setdefault(date_key, []).append(entry)

        if grouped == self._log_grouped_cache:
            return
        self._log_grouped_cache = grouped

        # Giữ lại trạng thái mở rộng/thu gọn của người dùng qua mỗi lần
        # làm mới (log tự refresh mỗi 2 giây). Mặc định LUÔN thu gọn — kể
        # cả nhóm ngày mới nhất — người dùng tự bấm để xem khi cần.
        expanded_dates = {
            self.log_tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole)
            for i in range(self.log_tree.topLevelItemCount())
            if self.log_tree.topLevelItem(i).isExpanded()
        }

        self.log_tree.clear()
        for date_key in sorted(grouped.keys(), reverse=True):
            entries = grouped[date_key]
            try:
                day = date.fromisoformat(date_key)
                label = f"{self._vn_date_label(day)} ({len(entries)} dòng)"
            except ValueError:
                label = f"{date_key} ({len(entries)} dòng)"

            day_item = QTreeWidgetItem([label])
            day_item.setData(0, Qt.ItemDataRole.UserRole, date_key)
            for entry in entries:
                entry_lines = entry.split("\n")
                child = QTreeWidgetItem([entry_lines[0]])
                color = self._log_entry_color(entry_lines[0])
                if color is not None:
                    child.setForeground(0, QBrush(color))
                for extra in entry_lines[1:]:
                    child.addChild(QTreeWidgetItem([extra]))
                day_item.addChild(child)
            self.log_tree.addTopLevelItem(day_item)

            if date_key in expanded_dates:
                day_item.setExpanded(True)



    # ---------------------------------------------------------- lifecycle
    def on_backup_finished(self) -> None:
        """Gọi (qua Qt signal) sau mỗi lần backup thủ công hoặc theo lịch,
        từ thread của scheduler.
        """
        self._refresh_databases_tree()
        self._refresh_history_table()

    def closeEvent(self, event) -> None:
        # Thu nhỏ vào tray thay vì thoát hẳn, để lịch backup vẫn chạy nền.
        if self._config.get_setting("minimize_to_tray", True):
            event.ignore()
            self.hide()
            if self._tray:
                self._tray.notify("Trình quản lý Backup Database", "Ứng dụng vẫn đang chạy nền.")
        else:
            event.accept()
