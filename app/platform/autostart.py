"""Picks the right autostart backend for the current OS."""
from __future__ import annotations

import sys


def is_enabled() -> bool:
    if sys.platform.startswith("win"):
        from app.platform import autostart_windows as impl
    else:
        from app.platform import autostart_linux as impl
    return impl.is_enabled()


def enable() -> None:
    if sys.platform.startswith("win"):
        from app.platform import autostart_windows as impl
    else:
        from app.platform import autostart_linux as impl
    impl.enable()


def disable() -> None:
    if sys.platform.startswith("win"):
        from app.platform import autostart_windows as impl
    else:
        from app.platform import autostart_linux as impl
    impl.disable()
