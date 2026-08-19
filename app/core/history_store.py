"""Local history of backup/restore runs, used by the GUI's History tab.
This is the tool's own bookkeeping database (separate from any db it
manages) — stored under the app data dir.
"""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from app.config import history_db_path
from app.models import BackupRecord

_SCHEMA = """
CREATE TABLE IF NOT EXISTS backup_history (
    id TEXT PRIMARY KEY,
    db_id TEXT NOT NULL,
    app_name TEXT NOT NULL,
    started_iso TEXT NOT NULL,
    finished_iso TEXT,
    status TEXT NOT NULL,
    drive_path TEXT,
    size_bytes INTEGER,
    message TEXT,
    is_restore_safety_copy INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_history_db_id ON backup_history(db_id);
CREATE INDEX IF NOT EXISTS idx_history_started ON backup_history(started_iso);
"""


class HistoryStore:
    def __init__(self, path: Path | None = None):
        self._path = path or history_db_path()
        self._lock = threading.RLock()
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._path))
        conn.row_factory = sqlite3.Row
        return conn

    def upsert(self, record: BackupRecord) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO backup_history
                    (id, db_id, app_name, started_iso, finished_iso, status,
                     drive_path, size_bytes, message, is_restore_safety_copy)
                VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    finished_iso=excluded.finished_iso,
                    status=excluded.status,
                    drive_path=excluded.drive_path,
                    size_bytes=excluded.size_bytes,
                    message=excluded.message
                """,
                (
                    record.id, record.db_id, record.app_name, record.started_iso,
                    record.finished_iso, record.status, record.drive_path,
                    record.size_bytes, record.message, int(record.is_restore_safety_copy),
                ),
            )

    def list_for_db(self, db_id: str, limit: int = 200) -> list[BackupRecord]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM backup_history WHERE db_id=? ORDER BY started_iso DESC LIMIT ?",
                (db_id, limit),
            ).fetchall()
            return [self._row_to_record(r) for r in rows]

    def list_all(self, limit: int = 500) -> list[BackupRecord]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM backup_history ORDER BY started_iso DESC LIMIT ?", (limit,)
            ).fetchall()
            return [self._row_to_record(r) for r in rows]

    def trim_old(self, keep_days: int = 180, keep_min_records: int = 500) -> int:
        """Lịch sử backup/restore không tự xoá theo dung lượng như file log
        (RotatingFileHandler) vì đây là dữ liệu có ý nghĩa lâu dài — nhưng
        vẫn cần chặn phình to vô hạn. Xoá các bản ghi cũ hơn keep_days ngày,
        trừ khi làm vậy sẽ còn lại ít hơn keep_min_records bản ghi gần nhất
        (khi đó vẫn giữ đủ keep_min_records bản ghi mới nhất). Trả về số
        bản ghi đã xoá. Gọi định kỳ (ví dụ lúc khởi động app).
        """
        from datetime import datetime, timedelta, timezone

        cutoff = (datetime.now(timezone.utc) - timedelta(days=keep_days)).isoformat()
        with self._lock, self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM backup_history").fetchone()[0]
            eligible = conn.execute(
                "SELECT COUNT(*) FROM backup_history WHERE started_iso < ?", (cutoff,)
            ).fetchone()[0]
            # Don't drop below keep_min_records total rows.
            max_deletable = max(0, total - keep_min_records)
            to_delete = min(eligible, max_deletable)
            if to_delete <= 0:
                return 0
            ids = [
                r[0]
                for r in conn.execute(
                    "SELECT id FROM backup_history WHERE started_iso < ? ORDER BY started_iso ASC LIMIT ?",
                    (cutoff, to_delete),
                ).fetchall()
            ]
            conn.executemany("DELETE FROM backup_history WHERE id=?", [(i,) for i in ids])
            return len(ids)

    @staticmethod
    def _row_to_record(r: sqlite3.Row) -> BackupRecord:
        return BackupRecord(
            id=r["id"], db_id=r["db_id"], app_name=r["app_name"],
            started_iso=r["started_iso"], finished_iso=r["finished_iso"],
            status=r["status"], drive_path=r["drive_path"], size_bytes=r["size_bytes"],
            message=r["message"] or "", is_restore_safety_copy=bool(r["is_restore_safety_copy"]),
        )
