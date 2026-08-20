from __future__ import annotations

from pathlib import Path

from apscheduler.triggers.cron import CronTrigger
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from app.core.cron_describe import describe_cron
from app.core.drive_client import DriveFileInfo
from app.models import DatabaseConfig, RetentionPolicy

CRON_PRESETS = {
    "Mỗi giờ": "0 * * * *",
    "Mỗi 6 giờ": "0 */6 * * *",
    "Mỗi 12 giờ": "0 */12 * * *",
    "Mỗi ngày (02:00)": "0 2 * * *",
    "Tùy chỉnh...": None,
}


class DatabaseEditDialog(QDialog):
    """Thêm hoặc sửa một DatabaseConfig."""

    def __init__(self, parent: QWidget | None = None, existing: DatabaseConfig | None = None):
        super().__init__(parent)
        self.setWindowTitle("Sửa database" if existing else "Thêm database")
        self._existing = existing
        self._build_ui()
        if existing:
            self._load(existing)

    def _build_ui(self) -> None:
        layout = QFormLayout(self)

        self.app_name_edit = QLineEdit()
        self.app_name_edit.setPlaceholderText("VD: MyInventoryApp")
        layout.addRow("Tên ứng dụng (thư mục trên Drive):", self.app_name_edit)

        path_row = QHBoxLayout()
        self.db_path_edit = QLineEdit()
        browse_btn = QPushButton("Chọn file...")
        browse_btn.clicked.connect(self._browse)
        path_row.addWidget(self.db_path_edit)
        path_row.addWidget(browse_btn)
        path_widget = QWidget()
        path_widget.setLayout(path_row)
        layout.addRow("Đường dẫn file SQLite:", path_widget)

        self.cron_preset = QComboBox()
        self.cron_preset.addItems(list(CRON_PRESETS.keys()))
        self.cron_preset.currentTextChanged.connect(self._on_preset_changed)
        layout.addRow("Lịch backup:", self.cron_preset)

        self.cron_edit = QLineEdit()
        self.cron_edit.setPlaceholderText("cron: phút giờ ngày tháng thứ")
        self.cron_edit.textChanged.connect(self._update_cron_hint)
        layout.addRow("Biểu thức cron:", self.cron_edit)

        self.cron_hint = QLabel()
        self.cron_hint.setWordWrap(True)
        self.cron_hint.setStyleSheet("color: #666; font-style: italic;")
        layout.addRow("", self.cron_hint)

        self.enabled_check = QCheckBox("Bật")
        self.enabled_check.setChecked(True)
        layout.addRow(self.enabled_check)

        self.keep_latest_check = QCheckBox("Giữ bản 'Latest' theo tên file gốc (bật/tắt riêng từng database)")
        self.keep_latest_check.setChecked(True)
        layout.addRow(self.keep_latest_check)

        self.vacuum_check = QCheckBox("VACUUM bản snapshot trước khi tải lên")
        vacuum_tip = (
            "VACUUM sẽ nén lại file SQLite: dọn dẹp các trang trống do dữ liệu bị xóa/sửa "
            "để lại, giúp file backup nhỏ gọn hơn (đôi khi giảm đáng kể dung lượng). Đổi lại, "
            "thao tác này cần đọc/ghi lại toàn bộ database nên có thể mất thêm thời gian với "
            "file lớn. Chỉ áp dụng trên bản snapshot tạm dùng để backup, không đụng đến file "
            "gốc đang chạy."
        )
        self.vacuum_check.setToolTip(vacuum_tip)
        layout.addRow(self.vacuum_check)
        vacuum_hint = QLabel(vacuum_tip)
        vacuum_hint.setWordWrap(True)
        vacuum_hint.setStyleSheet("color: #666; font-style: italic;")
        layout.addRow("", vacuum_hint)

        self.analyze_check = QCheckBox("ANALYZE bản snapshot trước khi tải lên")
        analyze_tip = (
            "ANALYZE sẽ cập nhật lại số liệu thống kê về dữ liệu (số hàng, phân bố giá trị...) "
            "mà SQLite dùng để lên kế hoạch truy vấn. Không làm thay đổi dung lượng file, nhưng "
            "giúp các truy vấn chạy nhanh hơn sau khi khôi phục bản backup này, đặc biệt nếu "
            "database đã lâu chưa được ANALYZE hoặc dữ liệu thay đổi nhiều."
        )
        self.analyze_check.setToolTip(analyze_tip)
        layout.addRow(self.analyze_check)
        analyze_hint = QLabel(analyze_tip)
        analyze_hint.setWordWrap(True)
        analyze_hint.setStyleSheet("color: #666; font-style: italic;")
        layout.addRow("", analyze_hint)

        self.keep_count_spin = QSpinBox()
        self.keep_count_spin.setRange(0, 10000)
        self.keep_count_spin.setValue(14)
        self.keep_count_spin.setSpecialValueText("tắt")
        layout.addRow("Giữ lại N bản gần nhất:", self.keep_count_spin)

        self.keep_days_spin = QSpinBox()
        self.keep_days_spin.setRange(0, 3650)
        self.keep_days_spin.setValue(30)
        self.keep_days_spin.setSpecialValueText("tắt")
        layout.addRow("Giữ lại bản mới hơn (số ngày):", self.keep_days_spin)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Đồng ý")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Hủy")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

        self.cron_preset.setCurrentText("Mỗi 6 giờ")
        self.cron_edit.setText(CRON_PRESETS["Mỗi 6 giờ"])

    def _on_preset_changed(self, text: str) -> None:
        preset = CRON_PRESETS.get(text)
        if preset is not None:
            self.cron_edit.setText(preset)
        self.cron_edit.setEnabled(preset is None)

    def _update_cron_hint(self, text: str) -> None:
        text = text.strip()
        if not text:
            self.cron_hint.setText("")
            return
        self.cron_hint.setText("📅 " + describe_cron(text))

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Chọn file database SQLite", "",
            "SQLite DB (*.db *.sqlite *.sqlite3);;Tất cả file (*)",
        )
        if path:
            self.db_path_edit.setText(path)
            if not self.app_name_edit.text():
                self.app_name_edit.setText(Path(path).parent.name or Path(path).stem)

    def _load(self, cfg: DatabaseConfig) -> None:
        self.app_name_edit.setText(cfg.app_name)
        self.db_path_edit.setText(cfg.db_path)
        self.cron_preset.setCurrentText("Tùy chỉnh...")
        self.cron_edit.setText(cfg.cron)
        self.enabled_check.setChecked(cfg.enabled)
        self.keep_latest_check.setChecked(cfg.keep_latest)
        self.vacuum_check.setChecked(cfg.vacuum_on_backup)
        self.analyze_check.setChecked(cfg.analyze_on_backup)
        self.keep_count_spin.setValue(cfg.retention.keep_count or 0)
        self.keep_days_spin.setValue(cfg.retention.keep_days or 0)

    def _on_accept(self) -> None:
        if not self.app_name_edit.text().strip():
            QMessageBox.warning(self, "Thiếu thông tin", "Vui lòng nhập tên ứng dụng.")
            return
        if not self.db_path_edit.text().strip() or not Path(self.db_path_edit.text()).exists():
            QMessageBox.warning(self, "Thiếu thông tin", "Vui lòng chọn một file .db hợp lệ, đang tồn tại.")
            return
        if not self.cron_edit.text().strip():
            QMessageBox.warning(self, "Thiếu thông tin", "Vui lòng nhập biểu thức cron.")
            return
        try:
            CronTrigger.from_crontab(self.cron_edit.text().strip())
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(
                self, "Biểu thức cron không hợp lệ",
                f"Không thể dùng biểu thức cron này: {e}\n\n"
                "Định dạng đúng: phút giờ ngày tháng thứ (vd. 0 */6 * * * = mỗi 6 giờ).",
            )
            return
        self.accept()

    def result_config(self) -> DatabaseConfig:
        cfg = self._existing or DatabaseConfig()
        cfg.app_name = self.app_name_edit.text().strip()
        cfg.db_path = self.db_path_edit.text().strip()
        cfg.cron = self.cron_edit.text().strip()
        cfg.enabled = self.enabled_check.isChecked()
        cfg.keep_latest = self.keep_latest_check.isChecked()
        cfg.vacuum_on_backup = self.vacuum_check.isChecked()
        cfg.analyze_on_backup = self.analyze_check.isChecked()
        cfg.retention = RetentionPolicy(
            keep_count=self.keep_count_spin.value() or None,
            keep_days=self.keep_days_spin.value() or None,
        )
        return cfg


class RestoreDialog(QDialog):
    """Danh sách các bản backup của một database (do nơi gọi lấy từ Drive)
    để người dùng chọn bản cần khôi phục.
    """

    def __init__(self, parent: QWidget | None, app_name: str, snapshots: list[DriveFileInfo]):
        super().__init__(parent)
        self.setWindowTitle(f"Khôi phục — {app_name}")
        self.resize(480, 420)
        self._snapshots = snapshots

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Chọn một bản backup để khôi phục. Database hiện tại sẽ được tự "
            "động sao lưu trước khi bị ghi đè."
        ))

        self.list_widget = QListWidget()
        for f in sorted(snapshots, key=lambda x: x.modified_time, reverse=True):
            item = QListWidgetItem(f"{f.modified_time}   ({f.size} bytes)   {f.name}")
            item.setData(1, f.id)
            self.list_widget.addItem(item)
        layout.addWidget(self.list_widget)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Khôi phục")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Hủy")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._selected: DriveFileInfo | None = None

    def _on_accept(self) -> None:
        row = self.list_widget.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Chưa chọn", "Vui lòng chọn một bản backup để khôi phục.")
            return
        self._selected = self._snapshots_sorted()[row]
        confirm = QMessageBox.question(
            self, "Xác nhận khôi phục",
            f"Thao tác này sẽ ghi đè database hiện tại bằng:\n{self._selected.name}\n\n"
            "Một bản sao lưu an toàn của database hiện tại sẽ được tạo trước. Tiếp tục?",
        )
        if confirm == QMessageBox.StandardButton.Yes:
            self.accept()

    def _snapshots_sorted(self) -> list[DriveFileInfo]:
        return sorted(self._snapshots, key=lambda x: x.modified_time, reverse=True)

    def selected_snapshot(self) -> DriveFileInfo | None:
        return self._selected


class CredentialsMissingDialog(QDialog):
    """Hiện ra khi chưa tìm thấy credentials.json — cho phép người dùng
    chọn file OAuth client tải từ Google Cloud Console. Dùng QFileDialog
    của Qt nên hoạt động giống nhau trên cả Windows và Linux.
    """

    def __init__(self, parent: QWidget | None, expected_path: str):
        super().__init__(parent)
        self.setWindowTitle("Thiếu file credentials.json")
        self.resize(480, 220)
        self._chosen_path: str | None = None

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Chưa tìm thấy file credentials.json (OAuth client, loại "
            "'Desktop app') tại:\n"
            f"{expected_path}\n\n"
            "Bạn có thể tải file này từ Google Cloud Console rồi chọn ở "
            "đây — ứng dụng sẽ tự sao chép vào đúng vị trí cần thiết."
        ))
        self.path_label = QLabel("(chưa chọn file)")
        self.path_label.setWordWrap(True)
        layout.addWidget(self.path_label)

        browse_btn = QPushButton("Chọn file credentials.json...")
        browse_btn.clicked.connect(self._browse)
        layout.addWidget(browse_btn)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Đồng ý")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Hủy")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Chọn file credentials.json", "", "JSON (*.json)")
        if path:
            self._chosen_path = path
            self.path_label.setText(path)

    def _on_accept(self) -> None:
        if not self._chosen_path:
            QMessageBox.warning(self, "Chưa chọn file", "Vui lòng chọn file credentials.json trước.")
            return
        self.accept()

    def chosen_path(self) -> str | None:
        return self._chosen_path
