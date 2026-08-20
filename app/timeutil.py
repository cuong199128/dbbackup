"""Tiện ích xử lý múi giờ dùng chung.

Nơi lưu trữ dữ liệu (history, config) vẫn dùng UTC nội bộ để nhất quán và
dễ so sánh/sắp xếp — KHÔNG đổi phần đó. Module này chỉ lo việc CHUYỂN ĐỔI
sang giờ Việt Nam (Asia/Ho_Chi_Minh, UTC+7) và định dạng kiểu VN
(dd/mm/yyyy) khi hiển thị cho người dùng hoặc khi đặt tên thư mục/file
theo ngày trên Drive — tránh lệch giờ khi máy chạy múi giờ khác UTC/VN
(vd. server đặt UTC, hoặc IT policy đổi timezone Windows).
"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
VN_DATETIME_FMT = "%d/%m/%Y %H:%M:%S"
VN_DATE_FMT = "%d/%m/%Y"


def to_vn(dt: datetime) -> datetime:
    """Chuyển 1 datetime (có tzinfo hoặc naive — coi là UTC) sang giờ VN."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(VN_TZ)


def now_vn() -> datetime:
    return datetime.now(VN_TZ)


def format_vn(dt: datetime, fmt: str = VN_DATETIME_FMT) -> str:
    return to_vn(dt).strftime(fmt)


def format_vn_iso(iso_str: str | None, fmt: str = VN_DATETIME_FMT) -> str:
    """Dùng cho các chuỗi ISO đã lưu (UTC, vd. BackupRecord.started_iso) để
    hiển thị lên GUI theo giờ VN, định dạng dd/mm/yyyy thay vì ISO 8601 mặc
    định (vốn khó đọc và hiển thị đúng giờ UTC chứ không phải giờ VN).
    """
    if not iso_str:
        return "-"
    try:
        dt = datetime.fromisoformat(iso_str)
    except ValueError:
        return iso_str
    return format_vn(dt, fmt)
