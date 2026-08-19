"""Creates a consistent snapshot of a live SQLite database.

Uses sqlite3.Connection.backup() (wraps SQLite's Online Backup API), which
is safe to run against a database that is being written to concurrently —
it takes a read lock, copies pages, and never touches the source file for
writing. The *source* connection is always opened read-only so this module
cannot modify the original database under any code path.
"""
from __future__ import annotations

import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from app.logger import get_logger

log = get_logger("backup_engine")


class BackupIntegrityError(RuntimeError):
    pass


@dataclass
class SnapshotResult:
    path: Path
    size_bytes: int
    integrity_ok: bool
    integrity_detail: str
    vacuumed: bool
    analyzed: bool


def _open_source_readonly(db_path: str) -> sqlite3.Connection:
    # uri=True + mode=ro guarantees SQLite will refuse to write, even if our
    # own code has a bug — belt and suspenders on top of "we never call
    # execute() for writes on this connection".
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=30)


def create_snapshot(
    db_path: str,
    dest_path: Path,
    *,
    vacuum: bool = False,
    analyze: bool = False,
    run_integrity_check: bool = True,
) -> SnapshotResult:
    """Copy db_path -> dest_path using the SQLite Online Backup API, then
    optionally VACUUM/ANALYZE and integrity-check the *copy only*.
    Raises BackupIntegrityError if the copy fails integrity_check.
    """
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    if dest_path.exists():
        dest_path.unlink()

    log.info("Starting online backup: %s -> %s", db_path, dest_path)
    src = _open_source_readonly(db_path)
    dst = sqlite3.connect(str(dest_path))
    try:
        with dst:
            src.backup(dst, pages=0, progress=None)  # pages=0 = copy in one go
    finally:
        src.close()
        # dst stays open for the post-processing steps below

    try:
        integrity_ok, detail = _check_integrity(dst) if run_integrity_check else (True, "skipped")
        if not integrity_ok:
            raise BackupIntegrityError(f"Snapshot failed integrity_check: {detail}")

        if analyze:
            log.info("Running ANALYZE on snapshot %s", dest_path)
            dst.execute("ANALYZE;")
            dst.commit()

        if vacuum:
            log.info("Running VACUUM on snapshot %s", dest_path)
            dst.execute("VACUUM;")
            dst.commit()
    finally:
        dst.close()

    size = dest_path.stat().st_size
    log.info("Snapshot ready: %s (%d bytes, integrity=%s)", dest_path, size, integrity_ok)
    return SnapshotResult(
        path=dest_path,
        size_bytes=size,
        integrity_ok=integrity_ok,
        integrity_detail=detail,
        vacuumed=vacuum,
        analyzed=analyze,
    )


def _check_integrity(conn: sqlite3.Connection) -> tuple[bool, str]:
    try:
        rows = conn.execute("PRAGMA integrity_check;").fetchall()
    except sqlite3.DatabaseError as e:
        # File isn't a valid SQLite database at all (e.g. truncated/corrupt
        # beyond what integrity_check can even parse) — still a failure,
        # just reported before PRAGMA had anything to say.
        return False, f"not a valid SQLite database: {e}"
    texts = [r[0] for r in rows]
    ok = len(texts) == 1 and texts[0].lower() == "ok"
    return ok, "; ".join(texts)


def verify_file_integrity(path: Path) -> tuple[bool, str]:
    """Standalone integrity check against an arbitrary .db file (used before
    restoring a downloaded snapshot, or to spot-check an existing backup).
    """
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return _check_integrity(conn)
    finally:
        conn.close()


def copy_current_db_aside(db_path: str, dest_path: Path) -> Path:
    """Used by the restore flow to save today's live db before overwriting
    it. Goes through the same online-backup path (never a raw file copy of
    a possibly-open database).
    """
    result = create_snapshot(db_path, dest_path, vacuum=False, analyze=False)
    return result.path
