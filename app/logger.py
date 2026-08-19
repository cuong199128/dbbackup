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
from collections import deque
from pathlib import Path
from typing import Deque, List

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

    file_handler = logging.handlers.RotatingFileHandler(
        log_dir() / "dbbackup.log", maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    _ring_handler = RingBufferHandler()
    _ring_handler.setFormatter(fmt)
    logger.addHandler(_ring_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(fmt)
    logger.addHandler(console_handler)

    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    return logging.getLogger(f"{LOG_NAME}.{name}" if name else LOG_NAME)
