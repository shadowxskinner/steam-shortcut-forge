"""What can be checked about the Qt frontend without a display.

PySide6 needs libEGL and a compositor, neither of which exists in CI, so these
are structural: that the Qt shell does not drag in Tk, that the blur shim is
genuinely optional, and that every module is at least syntactically sound.
"""

import ast
from pathlib import Path

import pytest

QT_DIR = Path(__file__).resolve().parents[1] / "kairo" / "qt"
MODULES = sorted(QT_DIR.glob("*.py"))

TK_NAMES = {"tkinter", "customtkinter", "kairo.imaging", "kairo.ui.widgets",
            "kairo.ui.nav", "kairo.ui.app", "kairo.ui.shell"}


def imports_of(path: Path):
    tree = ast.parse(path.read_text())
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def test_there_are_qt_modules():
    assert MODULES, "the Qt frontend is missing"


@pytest.mark.parametrize("path", MODULES, ids=lambda p: p.name)
def test_every_module_parses(path):
    ast.parse(path.read_text())


@pytest.mark.parametrize("path", MODULES, ids=lambda p: p.name)
def test_the_qt_shell_does_not_depend_on_tk(path):
    """Running the Qt shell must not require CustomTkinter to be installed.

    kairo.ui.theme is the one exception: it holds the shared palette and
    spacing tokens and guards its own toolkit import, so both frontends can
    read it and neither can drift from the other.
    """
    offenders = imports_of(path) & TK_NAMES
    assert not offenders, f"{path.name} imports {offenders}"


def test_the_shared_tokens_survive_without_a_toolkit():
    from kairo.ui import theme

    assert theme.C_BG.startswith("#")
    assert theme.PAD_WINDOW > 0


def test_blur_is_optional(fake_home):
    """No shim, no compositor, no crash - just a status worth reading."""
    from kairo.qt import blur

    probe = blur.Blur()
    assert probe.active is False
    assert isinstance(probe.status, str) and probe.status
    assert probe.supported() is False


def test_blur_reports_where_it_looked():
    from kairo.qt import blur

    assert blur.LIBRARY_NAME.endswith(".so")
    assert any("native" in str(path) for path in blur.SEARCH_PATHS)


def test_blur_result_codes_all_explain_themselves():
    from kairo.qt import blur

    assert blur.RESULTS[0] == "blur active"
    for code, message in blur.RESULTS.items():
        assert message, f"result {code} has no explanation"


def test_the_qt_theme_is_built_from_the_shared_tokens():
    from kairo.qt import theme as Q
    from kairo.ui import theme as T

    sheet = Q.stylesheet(0.8)
    assert T.C_ACCENT_BRIGHT in sheet, "the accent must come from one place"
    assert "rgba(" in sheet, "surfaces need an alpha component"
    assert Q.rgba("#FFFFFF", 1.0) == "rgb(255, 255, 255)"


def test_opaque_mode_makes_the_surfaces_solid():
    """--opaque has to be genuinely opaque.

    Only the surfaces are driven by the alpha setting. The soft red outline on
    the destructive button is a deliberate colour blend and stays put at every
    setting, so this checks the surfaces rather than banning rgba() outright.
    """
    from kairo.qt import theme as Q
    from kairo.ui import theme as T

    solid = Q.stylesheet(1.0)
    for surface in (T.C_NAV, T.C_LIST, T.C_PANEL, T.C_CARD):
        assert Q.rgba(surface, 1.0) in solid, f"{surface} is not solid"

    translucent = Q.stylesheet(0.7)
    assert Q.rgba(T.C_PANEL, 0.7) in translucent
    assert Q.rgba(T.C_PANEL, 1.0) not in translucent
