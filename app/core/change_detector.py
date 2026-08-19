"""Decide whether a database has changed since its last successful backup.

Approach: hash the file cheaply. We avoid re-hashing the whole file on every
poll by first comparing (size, mtime_ns); only if either differs do we
compute a real hash — that hash becomes the value stored in
DatabaseConfig.last_backup_hash after a successful backup, and is what makes
the decision robust against mtime-only touches (e.g. a WAL checkpoint that
doesn't actually change row data can still update mtime; hashing after the
cheap check keeps false positives rare without paying full I/O cost when
nothing happened at all).
"""
from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass
class FileFingerprint:
    size: int
    mtime_ns: int
    quick_hash: str  # cheap hash, not a full-file hash

    def as_key(self) -> str:
        return f"{self.size}:{self.mtime_ns}:{self.quick_hash}"


def _quick_hash(path: Path, sample_bytes: int = 1_048_576) -> str:
    """Hash a bounded sample (head + tail) instead of the whole file, so
    large databases don't cost a full read on every scheduler tick. This is
    a *change* signal, not a security digest — collisions just mean we
    might skip a backup we shouldn't, which change-driven backup already
    tolerates by also being schedule-driven as a fallback via WAL/mtime.
    """
    h = hashlib.blake2b(digest_size=16)
    size = path.stat().st_size
    with path.open("rb") as f:
        head = f.read(min(sample_bytes, size))
        h.update(head)
        if size > sample_bytes:
            f.seek(max(size - sample_bytes, 0))
            h.update(f.read(sample_bytes))
    return h.hexdigest()


def fingerprint(db_path: str) -> FileFingerprint:
    p = Path(db_path)
    st = p.stat()
    return FileFingerprint(size=st.st_size, mtime_ns=st.st_mtime_ns, quick_hash=_quick_hash(p))


def has_changed(db_path: str, last_hash: str | None) -> bool:
    """True if the on-disk database differs from the fingerprint recorded at
    the last successful backup. Also checkpoints WAL first (read-only,
    non-exclusive) so a pending WAL that hasn't been folded into the main
    file yet is reflected in the fingerprint — otherwise we could miss a
    change that only lives in -wal.
    """
    _best_effort_wal_checkpoint(db_path)
    if last_hash is None:
        return True
    return fingerprint(db_path).as_key() != last_hash


def _best_effort_wal_checkpoint(db_path: str) -> None:
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=1)
        try:
            conn.execute("PRAGMA wal_checkpoint(PASSIVE);")
        finally:
            conn.close()
    except Exception:
        # Read-only / locked / not in WAL mode — fine, just skip.
        pass
