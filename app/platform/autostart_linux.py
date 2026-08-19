"""Ubuntu/Linux autostart via a systemd user unit — runs at login, restarts
on crash, and shows up in normal service management tooling
(`systemctl --user status dbbackup`), which is friendlier than a raw
autostart .desktop entry for something that needs to keep running.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

UNIT_NAME = "dbbackup.service"


def _unit_dir() -> Path:
    return Path.home() / ".config/systemd/user"


def _unit_path() -> Path:
    return _unit_dir() / UNIT_NAME


def is_enabled() -> bool:
    try:
        out = subprocess.run(
            ["systemctl", "--user", "is-enabled", UNIT_NAME],
            capture_output=True, text=True, check=False,
        )
        return out.returncode == 0 and out.stdout.strip() == "enabled"
    except FileNotFoundError:
        return False


def enable(python_exe: str | None = None, script_path: str | None = None) -> None:
    python_exe = python_exe or sys.executable
    script_path = script_path or str(Path(__file__).resolve().parents[2] / "app" / "main.py")

    _unit_dir().mkdir(parents=True, exist_ok=True)
    unit_content = f"""[Unit]
Description=Database Backup Manager
After=graphical-session.target network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart={python_exe} {script_path} --background
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
"""
    _unit_path().write_text(unit_content, encoding="utf-8")

    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "--now", UNIT_NAME], check=True)


def disable() -> None:
    subprocess.run(["systemctl", "--user", "disable", "--now", UNIT_NAME], check=False)
    if _unit_path().exists():
        _unit_path().unlink()
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
