"""Entry point for Kairo's optional legacy Tk frontend."""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    if "--help" in argv or "-h" in argv:
        print("Kairo legacy Tk frontend\n"
              "\n  kairo-tk             the three-column Tk window"
              "\n  kairo-tk --classic   the previous single-provider window"
              "\n  kairo-tk --version"
              "\n\nThe shipping Qt application is: kairo")
        return 0

    if "--version" in argv:
        from kairo import __version__
        print(__version__)
        return 0

    if not sys.platform.startswith("linux"):
        print("Kairo targets Linux desktops.", file=sys.stderr)
        return 1

    try:
        import customtkinter  # noqa: F401
    except ImportError:
        print("kairo-tk needs the optional Tk dependencies:"
              "  pip install 'kairo[tk]'",
              file=sys.stderr)
        return 1

    from kairo.ui import theme
    theme.apply()

    # The previous window is kept reachable while the new shell is proven on
    # real desktops. It will go once it has stopped being useful.
    if "--classic" in argv:
        from kairo.ui.app import KairoApp
        KairoApp().mainloop()
        return 0

    from kairo.ui.shell import KairoShell
    KairoShell().mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
