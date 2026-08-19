"""Windows autostart: drop a .lnk shortcut in the per-user Startup folder.
No admin rights needed, no registry edits — easy for the user to remove by
just deleting the shortcut, and it survives a normal (non-admin) install.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

SHORTCUT_NAME = "DatabaseBackupManager.lnk"


def _startup_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise RuntimeError("APPDATA not set — not running on Windows?")
    return Path(appdata) / "Microsoft/Windows/Start Menu/Programs/Startup"


def is_enabled() -> bool:
    return (_startup_dir() / SHORTCUT_NAME).exists()


def enable(target_exe: str | None = None, args: str = "--background") -> None:
    """Creates the Startup shortcut. target_exe defaults to the running
    interpreter/executable (works both for `python main.py` in dev and for
    a PyInstaller-frozen .exe).
    """
    import win32com.client  # pywin32; Windows-only dependency

    target_exe = target_exe or sys.executable
    startup_dir = _startup_dir()
    startup_dir.mkdir(parents=True, exist_ok=True)
    shortcut_path = startup_dir / SHORTCUT_NAME

    shell = win32com.client.Dispatch("WScript.Shell")
    shortcut = shell.CreateShortCut(str(shortcut_path))
    shortcut.Targetpath = target_exe
    shortcut.Arguments = args
    shortcut.WorkingDirectory = str(Path(target_exe).parent)
    shortcut.IconLocation = target_exe
    shortcut.Save()


def disable() -> None:
    path = _startup_dir() / SHORTCUT_NAME
    if path.exists():
        path.unlink()
