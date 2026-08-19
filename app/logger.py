"""Central logging configuration.

Single logger namespace ("dbbackup") used everywhere. Writes to a rotating
file under the app data dir, and exposes an in-memory ring-buffer handler
so the GUI's Log tab can show recent entries without re-reading the file.

Log tự động xoá bớt: dùng RotatingFileHandler nên file log chính không bao
giờ vượt quá maxBytes; khi đầy, nó được đổi tên thành .1, .2... và file cũ
nhất (vượt quá backupCount) bị xoá tự động — không cần dọn tay. Với cấu
hình mặc định (5MB x 5 file) dung lượng log tối đa khoảng 30MB.
"""
from __future__ import annotations

import logging
import logging.handlers
import sys
import threading
from collections import deque
from pathlib import Path
from types import TracebackType
from typing import Deque, List, Type

from app.config import app_data_dir

LOG_NAME = "dbbackup"
LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_BACKUP_COUNT = 5


class RingBufferHandler(logging.Handler):
    """Keeps the last N formatted log lines in memory for the GUI."""

    def __init__(self, capacity: int = 2000):
        super().__init__()
        self.buffer: Deque[str] = deque(maxlen=capacity)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.buffer.append(self.format(record))
        except Exception:
            pass

    def snapshot(self) -> List[str]:
        return list(self.buffer)

    def clear(self) -> None:
        self.buffer.clear()


_ring_handler: RingBufferHandler | None = None


def get_ring_handler() -> RingBufferHandler:
    assert _ring_handler is not None, "call setup_logging() first"
    return _ring_handler


def log_dir() -> Path:
    d = app_data_dir() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _read_tail_lines(path: Path, n: int) -> List[str]:
    """Đọc n dòng cuối của file log (nếu có). File tối đa ~5MB nên đọc
    thẳng toàn bộ rồi cắt là đủ nhanh, không cần seek phức tạp.
    """
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
        return lines[-n:]
    except OSError:
        return []


def clear_log_files() -> None:
    """Manually wipe all log files + the in-memory ring buffer (used by the
    'Xoá log' button in the GUI). Automatic rotation above already keeps
    disk usage bounded — this is only for the user wanting a clean slate.
    """
    for f in log_dir().glob("dbbackup.log*"):
        try:
            f.unlink()
        except OSError:
            pass
    if _ring_handler:
        _ring_handler.clear()


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    global _ring_handler

    logger = logging.getLogger(LOG_NAME)
    if logger.handlers:
        return logger  # already configured (e.g. re-imported)

    logger.setLevel(level)
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    log_path = log_dir() / "dbbackup.log"

    # Nạp trước log của phiên chạy trước vào ring buffer TRƯỚC khi gắn
    # RotatingFileHandler (handler này có thể xoay vòng/tạo file mới ngay
    # khi khởi tạo nếu file hiện tại đã đầy). Nhờ vậy tab "Nhật ký" không
    # còn trống trơn mỗi khi mở lại app — kể cả khi app từng tự thoát bất
    # thường ở phiên trước, log cũ trên đĩa vẫn hiện ra ngay lập tức.
    _ring_handler = RingBufferHandler()
    _ring_handler.setFormatter(fmt)
    for line in _read_tail_lines(log_path, _ring_handler.buffer.maxlen or 2000):
        _ring_handler.buffer.append(line)

    file_handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)
    logger.addHandler(_ring_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(fmt)
    logger.addHandler(console_handler)

    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    return logging.getLogger(f"{LOG_NAME}.{name}" if name else LOG_NAME)


def install_excepthook() -> None:
    """Bắt mọi lỗi KHÔNG nằm trong try/except đã viết (kể cả lỗi ném ra từ
    trong code Qt/slot) và ghi vào log trước khi app thoát.

    Quan trọng cho bản build "windowed" (--windowed/pythonw, không có
    console): bình thường traceback chỉ in ra stderr, mà stderr không tồn
    tại ở dạng build đó nên traceback biến mất hoàn toàn, không để lại dấu
    vết gì để debug. Cài hook này đảm bảo traceback luôn được ghi vào file
    log (và ring buffer) trước khi tiến trình kết thúc, dù chạy kiểu nào.
    """
    log = get_logger("crash")

    def _handle(exc_type: Type[BaseException], exc_value: BaseException, exc_tb: TracebackType | None) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        log.critical("Lỗi chưa được xử lý, app sắp thoát", exc_info=(exc_type, exc_value, exc_tb))
        for handler in logging.getLogger(LOG_NAME).handlers:
            try:
                handler.flush()
            except Exception:
                pass
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = _handle

    # Lỗi ném ra từ thread nền (vd. thread "Backup Now", APScheduler worker)
    # không đi qua sys.excepthook mà qua threading.excepthook riêng — nếu
    # không set, exception trong thread cũng bị nuốt mất không log lại.
    def _handle_thread(args: threading.ExceptHookArgs) -> None:
        log.critical(
            "Lỗi chưa được xử lý trong thread '%s'",
            args.thread.name if args.thread else "?",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    threading.excepthook = _handle_thread
