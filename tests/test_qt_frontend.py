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


def test_a_numeric_setting_nudges_rather_than_flattens():
    """--alpha moves every layer together and keeps their relationship.

    Flattening them to one value would lose the depth the layering exists for;
    "solid" is a preset for when none is wanted at all.
    """
    from kairo.qt import theme as Q
    from kairo.ui import theme as T

    nudged = Q.stylesheet(0.70)
    assert Q.rgba(T.C_PANEL, 0.70) in nudged
    assert Q.rgba(T.C_PANEL, 1.0) not in nudged

    glass = Q.resolve(0.70)
    assert glass.nav > glass.panel > glass.tile


# -- glass is per surface, not per window -----------------------------------

def test_reading_surfaces_are_nearly_solid():
    """Content behind a panel should be shape and colour, never legible text.

    A single window-wide opacity - the only thing Tk offered - cannot express
    this: it fades text along with the background and makes every surface
    equally see-through whether it holds content or not.
    """
    from kairo.qt import theme as Q

    frosted = Q.PRESETS["frosted"]
    for name in ("nav", "list", "panel"):
        assert getattr(frosted, name) >= 0.88, f"{name} is too see-through"


def test_depth_runs_from_columns_down_to_tiles():
    from kairo.qt import theme as Q

    g = Q.PRESETS["frosted"]
    assert g.nav >= g.list >= g.panel >= g.card >= g.tile
    assert g.nav - g.tile >= 0.05, "the layers are too close to read as depth"


def test_every_preset_keeps_that_ordering():
    from kairo.qt import theme as Q

    for name, g in Q.PRESETS.items():
        assert g.nav >= g.list >= g.panel >= g.card >= g.tile, name


def test_text_never_takes_the_surface_alpha():
    """The whole reason for leaving Tk."""
    from kairo.qt import theme as Q
    from kairo.ui import theme as T

    sheet = Q.stylesheet("frosted")
    for label in ("QLabel#title", "QLabel#rowName", "QLabel#meta"):
        line = next(l for l in sheet.splitlines() if label in l)
        assert "rgba(" not in line, f"{label} is translucent"
    assert T.C_TEXT in sheet


def test_glass_can_be_nudged_without_inverting_the_layers():
    from kairo.qt import theme as Q

    nudged = Q.PRESETS["frosted"].shifted(-0.10)
    assert nudged.nav >= nudged.panel >= nudged.tile
    assert Q.PRESETS["frosted"].shifted(5.0).panel == 1.0     # clamped
    assert Q.PRESETS["frosted"].shifted(-5.0).tile >= 0.30


def test_resolve_accepts_a_name_a_number_or_a_glass():
    from kairo.qt import theme as Q

    assert Q.resolve("solid").panel == 1.0
    assert Q.resolve(None) == Q.PRESETS[Q.DEFAULT_PRESET]
    assert Q.resolve(Q.PRESETS["clear"]) == Q.PRESETS["clear"]
    assert abs(Q.resolve(0.80).panel - 0.80) < 1e-9
    assert Q.resolve("nonsense") == Q.PRESETS[Q.DEFAULT_PRESET]


def test_solid_really_is_solid():
    from kairo.qt import theme as Q
    from kairo.ui import theme as T

    sheet = Q.stylesheet("solid")
    for surface in (T.C_NAV, T.C_LIST, T.C_PANEL, T.C_CARD):
        assert Q.rgba(surface, 1.0) in sheet


# -- behaviour parity with the validated Tk build ---------------------------

def test_the_action_verbs_come_from_the_writer(): 
    """A generated entry's ordinary undo is Reset artwork; an override's is
    Restore original. Hard-coding either in the frontend is how the Tk build
    came to describe a deletion as a restore."""
    source = (QT_DIR / "library.py").read_text()
    build = source.split("def _update_actions")[0]

    assert '"Restore original"' not in build
    assert '"Remove shortcut"' not in build
    assert "writer.restore_label" in source
    assert "writer.remove_label" in source
    assert "supports_remove" in source


def test_remove_is_only_offered_where_the_writer_supports_it():
    source = (QT_DIR / "library.py").read_text()
    assert "self.remove_btn.setVisible(supports_remove)" in source


def test_the_backend_still_disagrees_about_the_two_verbs(fake_home):
    """The parity the frontend is deferring to."""
    from kairo.providers.steam import SteamProvider
    from kairo.providers.writers import OverrideWriter

    generated = SteamProvider().writer()
    override = OverrideWriter()
    assert generated.restore_label == "Reset artwork"
    assert generated.remove_label == "Remove shortcut"
    assert generated.supports_remove is True
    assert override.restore_label == "Restore original"
    assert override.supports_remove is False


def test_a_failed_lookup_does_not_hide_a_source():
    """Being briefly unreachable is not evidence of having nothing."""
    source = (QT_DIR / "library.py").read_text()
    failed = source.split("def failed(message):")[1].split("def ")[0]
    assert "_probe_cache" not in failed, "a failure must not mark a source empty"


def test_a_probe_error_leaves_the_source_visible():
    source = (QT_DIR / "library.py").read_text()
    ask = source.split("def ask():")[1].split("def arrived")[0]
    assert "except Exception:" in ask
    assert "True" in ask, "an unreachable source must stay visible"


def test_an_empty_result_does_hide_the_source():
    source = (QT_DIR / "library.py").read_text()
    assert "self._probe_cache[(key, source.id)] = False" in source


def test_choosing_artwork_only_proposes_it():
    """Nothing writes until Apply, which is the rule the review screen has
    always followed and the single-item path now follows too."""
    source = (QT_DIR / "library.py").read_text()
    propose = source.split("def _propose(self, art)")[1]
    for writing in ("fetch_and_apply", "apply_icon", "restore_entry",
                    "remove_entry"):
        assert writing not in propose


def test_the_milestone_writes_nothing_at_all():
    """No Qt module may call an action that touches a launcher entry."""
    for path in MODULES:
        source = path.read_text()
        for writing in ("actions.apply_icon", "actions.fetch_and_apply",
                        "actions.restore_entry", "actions.remove_entry",
                        "actions.restore_all", "actions.apply_many",
                        "config_store.save", "housekeeping.sweep"):
            assert writing not in source, f"{path.name} calls {writing}"
