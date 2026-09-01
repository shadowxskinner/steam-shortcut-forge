"""Entry point for Kairo's shipping Qt application."""

from __future__ import annotations

import sys
from pathlib import Path

HELP = """Kairo — automatic launcher artwork for Linux

Usage:
  kairo                             frosted, blur if the compositor offers it
  kairo --glass clear               thinner surfaces, for comparison
  kairo --glass solid               no transparency at all
  kairo --alpha 0.85                nudge every surface toward one value
  kairo --no-blur                   translucent, never ask for blur
  kairo --opaque                    same as --glass solid
  kairo --version

The optional legacy frontend is available as kairo-tk after installing
Kairo's `tk` extra.
"""


def _desktop_file_installed(app_id: str) -> bool:
    """True when ``app_id``.desktop exists where the portal will look.

    Follows the XDG data directory search path rather than guessing at
    ~/.local/share, so a system-wide install counts too.
    """
    import os

    home = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local/share")
    dirs = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    for base in [home, *dirs.split(":")]:
        if base and (Path(base) / "applications" / f"{app_id}.desktop").is_file():
            return True
    return False


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    if {"-h", "--help"} & set(argv):
        print(HELP)
        return 0

    if "--version" in argv:
        from kairo import __version__
        print(__version__)
        return 0

    if not sys.platform.startswith("linux"):
        print("Kairo targets Linux desktops.", file=sys.stderr)
        return 1

    try:
        from PySide6.QtGui import QFont, QGuiApplication
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print("Kairo needs PySide6:\n"
              "    sudo pacman -S pyside6\n"
              "  or:  pip install PySide6\n"
              "The optional legacy frontend is available as kairo-tk.",
              file=sys.stderr)
        return 1

    from kairo import APP_ID
    from kairo.qt import branding
    from kairo.qt import theme as Q
    from kairo.qt.shell import KairoWindow

    glass = Q.PRESETS[Q.DEFAULT_PRESET]
    if "--glass" in argv:
        try:
            name = argv[argv.index("--glass") + 1]
        except IndexError:
            print(f"--glass needs one of: {', '.join(Q.PRESETS)}", file=sys.stderr)
            return 1
        if name not in Q.PRESETS:
            print(f"unknown glass '{name}'. Try: {', '.join(Q.PRESETS)}",
                  file=sys.stderr)
            return 1
        glass = Q.PRESETS[name]
    if "--alpha" in argv:
        try:
            value = float(argv[argv.index("--alpha") + 1])
        except (IndexError, ValueError):
            print("--alpha needs a number between 0.3 and 1.0", file=sys.stderr)
            return 1
        value = max(Q.MIN_ALPHA, min(Q.MAX_ALPHA, value))
        glass = glass.shifted(value - glass.panel)

    opaque = "--opaque" in argv
    if opaque:
        glass = Q.PRESETS["solid"]

    # Claim the application id only if a .desktop file actually backs it.
    # The portal looks the id up and logs a failure when it finds nothing,
    # which is where "App info not found" came from: Kairo was announcing an
    # identity that is only real once the file is installed.
    installed = _desktop_file_installed(APP_ID)
    if installed:
        QGuiApplication.setDesktopFileName(APP_ID)
    application = QApplication(sys.argv)
    application.setApplicationName(APP_ID if installed else "Kairo")
    application.setApplicationDisplayName("Kairo")
    # Without this the window, the task switcher and the taskbar all fall
    # back to a generic placeholder, installed or not.
    application.setWindowIcon(branding.icon())
    application.setOrganizationName("Kairo")
    # A stack rather than one family: "Inter" alone silently fell back to
    # whatever fontconfig chose when Inter was not installed, which on this
    # machine was not close to the intended face at all.
    interface = QFont()
    interface.setFamilies(list(Q.FONT_STACK))
    interface.setPointSize(10)
    interface.setHintingPreference(QFont.PreferFullHinting)
    application.setFont(interface)
    application.setStyleSheet(Q.stylesheet(glass))

    window = KairoWindow(translucent=not opaque,
                         want_blur="--no-blur" not in argv,
                         glass=glass)
    window.show()
    try:
        return application.exec()
    finally:
        # Closing the window drains the pool; ending the loop any other way
        # does not, and Python then tears down around a live worker thread.
        from kairo.qt import work
        work.drain()


if __name__ == "__main__":
    raise SystemExit(main())
