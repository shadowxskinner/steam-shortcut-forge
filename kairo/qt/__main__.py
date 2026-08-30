"""Entry point for the Qt shell:  python -m kairo.qt

The Tk shell is untouched and still runs as ``python -m kairo``. Both drive the
same backend; only the frontend differs.
"""

from __future__ import annotations

import sys

HELP = """Kairo — automatic launcher artwork for Linux (Qt shell milestone)

  python -m kairo.qt              translucent, blur if the compositor offers it
  python -m kairo.qt --no-blur    translucent, never ask for blur
  python -m kairo.qt --opaque     no transparency at all
  python -m kairo.qt --alpha 0.7  surface opacity, 0.4 to 1.0

  python -m kairo                 the CustomTkinter shell, unchanged
"""


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    if {"-h", "--help"} & set(argv):
        print(HELP)
        return 0

    if not sys.platform.startswith("linux"):
        print("Kairo targets Linux desktops.", file=sys.stderr)
        return 1

    try:
        from PySide6.QtGui import QFont, QGuiApplication
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print("The Qt shell needs PySide6:\n"
              "    sudo pacman -S pyside6\n"
              "  or:  pip install PySide6\n"
              "The CustomTkinter shell still works: python -m kairo",
              file=sys.stderr)
        return 1

    from kairo import APP_ID
    from kairo.qt import theme as Q
    from kairo.qt.shell import KairoWindow

    alpha = Q.DEFAULT_ALPHA
    if "--alpha" in argv:
        try:
            alpha = float(argv[argv.index("--alpha") + 1])
        except (IndexError, ValueError):
            print("--alpha needs a number between 0.4 and 1.0", file=sys.stderr)
            return 1
        alpha = max(Q.MIN_ALPHA, min(Q.MAX_ALPHA, alpha))

    opaque = "--opaque" in argv
    if opaque:
        alpha = 1.0

    # Set before the QApplication exists: this is what the portal reads, and
    # matching it to the installed .desktop is what stops it complaining.
    QGuiApplication.setDesktopFileName(APP_ID)
    application = QApplication(sys.argv)
    application.setApplicationName(APP_ID)
    application.setApplicationDisplayName("Kairo")
    application.setOrganizationName("Kairo")
    application.setFont(QFont("Inter", 10))
    application.setStyleSheet(Q.stylesheet(alpha))

    window = KairoWindow(translucent=not opaque,
                         want_blur="--no-blur" not in argv)
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
