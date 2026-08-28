"""Entry point."""

from __future__ import annotations

import sys


def main() -> int:
    if not sys.platform.startswith("linux"):
        print("Kairo targets Linux desktops.", file=sys.stderr)
        return 1

    try:
        import customtkinter  # noqa: F401
    except ImportError:
        print("Kairo needs customtkinter:  pip install customtkinter",
              file=sys.stderr)
        return 1

    from kairo.ui import theme
    from kairo.ui.app import KairoApp

    theme.apply()
    KairoApp().mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
