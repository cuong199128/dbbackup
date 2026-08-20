from datetime import datetime, timezone

from app.core import drive_layout


def test_snapshot_path_layout():
    # `when` là giờ VN thẳng (naive, không tzinfo) -> to_vn() coi naive là
    # UTC rồi cộng thêm 7 tiếng, nên truyền thẳng datetime VN vào đây sẽ ra
    # sai lệch múi giờ; test dùng datetime UTC-aware để phản ánh đúng cách
    # backup_service.py thực sự gọi hàm này (datetime.now(timezone.utc)).
    when = datetime(2026, 8, 19, 5, 0, 0, tzinfo=timezone.utc)  # 12:00 giờ VN
    parts = drive_layout.snapshot_path("MyApp", when)
    assert parts.folder_segments == ("Python Database Backup", "MyApp", "2026", "08-19")
    assert parts.filename == "12-00-00.db"
    assert parts.full_path == "Python Database Backup/MyApp/2026/08-19/12-00-00.db"


def test_snapshot_path_crosses_midnight_into_vn_next_day():
    # 17:30 UTC ngày 19/08 = 00:30 giờ VN ngày 20/08 -> phải xếp vào thư
    # mục ngày 20, không phải ngày 19 (bug thực tế đã gặp khi dùng UTC
    # thẳng cho tên thư mục trên Drive).
    when = datetime(2026, 8, 19, 17, 30, 0, tzinfo=timezone.utc)
    parts = drive_layout.snapshot_path("MyApp", when)
    assert parts.folder_segments == ("Python Database Backup", "MyApp", "2026", "08-20")
    assert parts.filename == "00-30-00.db"


def test_latest_path_keeps_original_filename():
    parts = drive_layout.latest_path("MyApp", "data.db")
    assert parts.folder_segments == ("Python Database Backup", "MyApp")
    assert parts.filename == "data.db"
    assert parts.full_path == "Python Database Backup/MyApp/data.db"


def test_restore_safety_snapshot_uses_normal_snapshot_layout():
    when = datetime(2026, 1, 1, 8, 30, 5, tzinfo=timezone.utc)
    a = drive_layout.snapshot_path("App", when)
    b = drive_layout.restore_safety_snapshot_path("App", when)
    assert a == b
