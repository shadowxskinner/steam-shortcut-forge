"""Request KWin blur through the standard Wayland background-effect protocol.

The small C bridge isolates its registry work on a private Wayland event queue,
sets the exact logical window region, and releases the effect before Qt destroys
the surface. Calls use ``PyDLL`` so Python's GIL remains held. Without the
optional library or protocol, Kairo stays translucent and never raises.
"""

from __future__ import annotations

import ctypes
from pathlib import Path

LIBRARY_NAME = "libkairoblur.so"
SEARCH_PATHS = (
    Path(__file__).parent / "native" / LIBRARY_NAME,
    Path(__file__).parent / LIBRARY_NAME,
)

RESULTS = {
    0: "blur active",
    -1: "no display or surface pointer",
    -2: "the window handle was not a wl_surface",
    -3: "could not read the Wayland registry",
    -4: "this compositor does not offer background blur",
    -5: "the compositor refused the effect object",
    -6: "the compositor refused the blur region",
    -7: "could not retain the blur effect",
}


def library_path():
    for candidate in SEARCH_PATHS:
        if candidate.is_file():
            return candidate
    return None


class Blur:
    def __init__(self) -> None:
        self._library = None
        self._display_ptr = None
        self._surface_ptr = None
        self.status = "not attempted"
        self.active = False

        path = library_path()
        if path is None:
            self.status = "blur unavailable — optional bridge not built"
            return
        try:
            library = ctypes.PyDLL(str(path))
            library.kairo_blur_available.argtypes = [ctypes.c_void_p]
            library.kairo_blur_available.restype = ctypes.c_int
            library.kairo_blur_enable.argtypes = [
                ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
            library.kairo_blur_enable.restype = ctypes.c_int
            library.kairo_blur_resize.argtypes = [
                ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
            library.kairo_blur_resize.restype = ctypes.c_int
            library.kairo_blur_disable.argtypes = [ctypes.c_void_p,
                                                   ctypes.c_void_p]
            library.kairo_blur_disable.restype = ctypes.c_int
        except (OSError, AttributeError) as exc:
            # A bridge built from an older tree loads fine and then has no
            # kairo_blur_resize, which raises AttributeError rather than
            # OSError. Catching only OSError turned a stale .so on disk into
            # a hard startup failure instead of a translucent window.
            self.status = f"blur unavailable — bridge would not load ({exc})"
            return
        self._library = library

    @staticmethod
    def _display():
        from PySide6.QtGui import QGuiApplication

        application = QGuiApplication.instance()
        native = application.nativeInterface() if application else None
        getter = getattr(native, "display", None) if native else None
        try:
            return getter() if callable(getter) else None
        except Exception:
            return None

    @staticmethod
    def _surface(window):
        handle = window.windowHandle()
        if handle is None:
            return None
        try:
            return int(handle.winId())
        except Exception:
            return None

    def supported(self) -> bool:
        if self._library is None:
            return False
        display = self._display()
        if not display:
            self.status = "blur unavailable — not a Wayland session"
            return False
        try:
            return bool(self._library.kairo_blur_available(
                ctypes.c_void_p(display)))
        except Exception as exc:
            self.status = f"blur unavailable — {exc}"
            return False

    def apply(self, window) -> bool:
        if self._library is None or not self.supported():
            if self.status in ("not attempted", ""):
                self.status = "blur unavailable — compositor declined it"
            return False
        display, surface = self._display(), self._surface(window)
        if not display or not surface:
            self.status = "blur unavailable — Qt withheld a surface handle"
            return False
        try:
            result = self._library.kairo_blur_enable(
                ctypes.c_void_p(display), ctypes.c_void_p(surface),
                max(1, window.width()), max(1, window.height()))
        except Exception as exc:
            self.status = f"blur unavailable — {exc}"
            return False
        self.active = result == 0
        self.status = RESULTS.get(result, f"blur unavailable — code {result}")
        if self.active:
            self._display_ptr = display
            self._surface_ptr = surface
        return self.active

    def update(self, window) -> None:
        if not self.active or not self._display_ptr or not self._surface_ptr:
            return
        try:
            self._library.kairo_blur_resize(
                ctypes.c_void_p(self._display_ptr),
                ctypes.c_void_p(self._surface_ptr),
                max(1, window.width()), max(1, window.height()))
        except Exception:
            return

    def remove(self, _window) -> None:
        if self._library is None or not self.active:
            return
        try:
            self._library.kairo_blur_disable(
                ctypes.c_void_p(self._display_ptr),
                ctypes.c_void_p(self._surface_ptr))
        except Exception:
            pass
        finally:
            self.active = False
            self._display_ptr = None
            self._surface_ptr = None
