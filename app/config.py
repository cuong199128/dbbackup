"""Cross-platform app config & storage locations.

Everything the app persists (config.json, oauth token, local history db,
logs) lives under one per-user app data directory so install/uninstall and
backup-of-the-tool-itself is trivial.

Windows: %APPDATA%\\DatabaseBackupManager
Linux:   ~/.local/share/DatabaseBackupManager   (XDG_DATA_HOME if set)
"""
from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path
from typing import List

from app.models import DatabaseConfig

APP_DIR_NAME = "DatabaseBackupManager"
DRIVE_ROOT_FOLDER = "Python Database Backup"  # top-level folder name on Google Drive


def app_data_dir() -> Path:
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    path = base / APP_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def credentials_path() -> Path:
    """OAuth client secret (installed-app type) the user drops in once.
    Downloaded from Google Cloud Console -> APIs & Services -> Credentials.
    """
    return app_data_dir() / "credentials.json"


def install_credentials_file(source_path: "Path | str") -> Path:
    """Copies a user-picked OAuth client JSON (chosen via a file dialog on
    Windows or Linux) into the app data dir as credentials.json. Works the
    same on both platforms since app_data_dir() already resolves per-OS.
    """
    import shutil

    src = Path(source_path)
    if not src.exists():
        raise FileNotFoundError(f"Không tìm thấy file: {src}")
    dest = credentials_path()
    shutil.copyfile(src, dest)
    return dest


def token_path() -> Path:
    return app_data_dir() / "token.json"


def config_path() -> Path:
    return app_data_dir() / "config.json"


def history_db_path() -> Path:
    return app_data_dir() / "history.sqlite3"


def staging_dir() -> Path:
    """Scratch space for snapshots before/while uploading. Never touches the
    real source database directories.
    """
    p = app_data_dir() / "staging"
    p.mkdir(parents=True, exist_ok=True)
    return p


class ConfigStore:
    """Thread-safe load/save of the list of managed databases + app settings."""

    def __init__(self, path: Path | None = None):
        self._path = path or config_path()
        self._lock = threading.RLock()
        self._settings: dict = {}
        self._databases: List[DatabaseConfig] = []
        self.load()

    # -- persistence -----------------------------------------------------
    def load(self) -> None:
        with self._lock:
            if not self._path.exists():
                self._settings = {"start_with_os": True, "minimize_to_tray": True}
                self._databases = []
                return
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            self._settings = raw.get("settings", {})
            self._databases = [DatabaseConfig.from_dict(d) for d in raw.get("databases", [])]

    def save(self) -> None:
        with self._lock:
            payload = {
                "settings": self._settings,
                "databases": [d.to_dict() for d in self._databases],
            }
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self._path)  # atomic on both platforms

    # -- database CRUD ----------------------------------------------------
    def list_databases(self) -> List[DatabaseConfig]:
        with self._lock:
            return list(self._databases)

    def get_database(self, db_id: str) -> DatabaseConfig | None:
        with self._lock:
            return next((d for d in self._databases if d.id == db_id), None)

    def add_database(self, cfg: DatabaseConfig) -> None:
        with self._lock:
            self._databases.append(cfg)
            self.save()

    def update_database(self, cfg: DatabaseConfig) -> None:
        with self._lock:
            for i, d in enumerate(self._databases):
                if d.id == cfg.id:
                    self._databases[i] = cfg
                    break
            self.save()

    def remove_database(self, db_id: str) -> None:
        with self._lock:
            self._databases = [d for d in self._databases if d.id != db_id]
            self.save()

    # -- settings -----------------------------------------------------
    def get_setting(self, key: str, default=None):
        with self._lock:
            return self._settings.get(key, default)

    def set_setting(self, key: str, value) -> None:
        with self._lock:
            self._settings[key] = value
            self.save()
