"""Build a standalone executable with PyInstaller, đóng gói kèm assets/
(icon .ico/.png/.svg) để icon hiển thị đúng cả khi chạy từ file .exe/binary
đã build (không chỉ khi chạy `python -m app.main` từ source).

Chạy:
    pip install pyinstaller
    python packaging/build.py

Kết quả nằm trong dist/DatabaseBackupManager/ (hoặc dist/DatabaseBackupManager.exe
nếu dùng --onefile, xem biến ONEFILE bên dưới).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import PyInstaller.__main__

ROOT = Path(__file__).resolve().parents[1]
ONEFILE = "--onedir"  # đổi thành "--onefile" nếu muốn 1 file .exe duy nhất (khởi động chậm hơn)

# PyInstaller --add-data cần dấu phân cách khác nhau: ';' trên Windows, ':' trên Linux/macOS
DATA_SEP = ";" if sys.platform.startswith("win") else ":"


def main() -> None:
    icon_path = ROOT / "assets" / ("icon.ico" if sys.platform.startswith("win") else "icon.png")

    args = [
        str(ROOT / "app" / "main.py"),
        "--name", "DatabaseBackupManager",
        "--windowed",  # không mở console đen phía sau app
        ONEFILE,
        "--icon", str(icon_path),
        "--add-data", f"{ROOT / 'assets'}{DATA_SEP}assets",
        "--noconfirm",
    ]
    print("PyInstaller args:", args)
    PyInstaller.__main__.run(args)


if __name__ == "__main__":
    main()
