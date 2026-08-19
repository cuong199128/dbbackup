"""Loads the app icon from assets/, working both when run from source and
when frozen into a standalone .exe/binary by PyInstaller (which unpacks
bundled data files into a temp dir exposed as sys._MEIPASS).
"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QIcon


def _project_root() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parents[2]


def assets_dir() -> Path:
    return _project_root() / "assets"


def app_icon() -> QIcon:
    """Prefers the Windows .ico (multi-resolution) when present, falls back
    to the PNG (used on Linux where .ico isn't the native format), and
    finally to a drawn placeholder so the app never crashes over a missing
    asset file.
    """
    ico = assets_dir() / "icon.ico"
    png = assets_dir() / "icon.png"
    if ico.exists():
        return QIcon(str(ico))
    if png.exists():
        return QIcon(str(png))
    return _drawn_fallback_icon()


def _drawn_fallback_icon() -> QIcon:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPixmap, QPainter, QColor

    pix = QPixmap(64, 64)
    pix.fill(QColor(0, 0, 0, 0))
    p = QPainter(pix)
    p.setBrush(QColor(56, 132, 255))
    p.setPen(QColor(20, 60, 140))
    p.drawEllipse(4, 4, 56, 56)
    p.setPen(QColor(255, 255, 255))
    font = p.font()
    font.setBold(True)
    font.setPointSize(28)
    p.setFont(font)
    p.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, "B")
    p.end()
    return QIcon(pix)
