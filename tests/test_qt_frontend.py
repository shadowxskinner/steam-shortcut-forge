"""What can be checked about the Qt frontend without a display.

Widgets need libEGL and a compositor, neither of which exists in CI, so most of
this is structural: that the Qt shell does not drag in Tk, that blur is
genuinely optional, and that every module is at least syntactically sound.

QtCore is the exception. It runs headless, so the worker lifecycle — the thing
that actually crashed the live shell — is exercised for real rather than
grepped for.
"""

import ast
import threading
import time
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


def test_blur_is_optional(fake_home, monkeypatch, tmp_path):
    """No compiled bridge, no compositor, no crash."""
    from kairo.qt import blur

    monkeypatch.setattr(blur, "SEARCH_PATHS", (tmp_path / "missing.so",))
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
    assert Q.PRESETS["frosted"].shifted(5.0).panel == 1.0      # clamped
    # The floor is zero, not a minimum tint: fully transparent is a legitimate
    # setting, and it is what the workspace backdrop used to be.
    assert Q.PRESETS["frosted"].shifted(-5.0).tile == 0.0


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


# -- tuning controls that actually reach the user ---------------------------

def test_tuning_uses_real_shortcuts_not_a_key_handler():
    """Overriding keyPressEvent on the window fails twice over: a focused
    child consumes the event first, and with Control held QKeyEvent.text()
    returns a control character rather than the digit. Neither is obvious
    until nothing happens on a real desktop."""
    source = (QT_DIR / "shell.py").read_text()
    body = source.split('"""', 2)[-1]          # skip the module docstring

    assert "QShortcut" in source
    assert "Qt.ApplicationShortcut" in source
    assert "def keyPressEvent" not in body, "the handler that never fired is back"
    assert "event.text()" not in body


def test_every_preset_gets_a_shortcut_and_nudging_has_alternatives():
    source = (QT_DIR / "shell.py").read_text()
    assert 'f"Ctrl+{index}"' in source
    for sequence in ("Ctrl+]", "Ctrl+[", "Ctrl+=", "Ctrl+-"):
        assert f'"{sequence}"' in source, f"{sequence} is not bound"


def test_applying_glass_updates_the_status_and_the_panel():
    source = (QT_DIR / "shell.py").read_text()
    apply = source.split("def apply_glass")[1].split("\n    def ")[0]
    assert "setStyleSheet" in apply
    assert "set_glass" in apply, "the Appearance panel must follow along"
    assert "self.status.setText" in apply


def test_there_is_a_control_that_needs_no_keyboard():
    """A control reachable only by an unbound shortcut is not a control."""
    source = (QT_DIR / "settings.py").read_text()
    assert "class AppearancePanel" in source
    assert "QSlider" in source
    assert "def set_preset" in source


def test_the_appearance_panel_covers_every_layer():
    from kairo.qt import theme as Q

    source = (QT_DIR / "settings.py").read_text()
    assert "for row, name in enumerate(Q.LAYERS)" in source
    assert set(Q.LAYERS) == {"workspace", "nav", "list", "panel", "card",
                             "tile", "line"}


def test_tuned_values_can_be_reported_back():
    """Six numbers found by eye are useless if they cannot leave the window."""
    from kairo.qt import theme as Q

    described = Q.PRESETS["frosted"].describe()
    assert described.startswith("Glass(") and described.endswith(")")
    for layer in Q.LAYERS:
        assert f"{layer}=" in described

    namespace = {"Glass": Q.Glass}
    assert eval(described, namespace) == Q.PRESETS["frosted"]


def test_replaced_clamps_without_reordering_the_intent():
    from kairo.qt import theme as Q

    tuned = Q.PRESETS["frosted"].replaced(panel=0.99, tile=4.0, card=-1.0)
    assert tuned.panel == 0.99
    assert tuned.tile == 1.0
    assert tuned.card == 0.0
    assert tuned.nav == Q.PRESETS["frosted"].nav


def test_a_denser_preset_exists_to_compare_against():
    """Dense remains an escape hatch for unusually high-contrast wallpaper."""
    from kairo.qt import theme as Q

    dense = Q.PRESETS["dense"]
    frosted = Q.PRESETS["frosted"]
    assert dense.panel > frosted.panel
    assert dense.nav >= dense.list >= dense.panel >= dense.card >= dense.tile
    assert dense.panel < 1.0, "dense is still glass, not a wall"


def test_live_default_keeps_reading_content_quiet():
    """The shell-6 desktop capture left terminal text competing with Kairo."""
    from kairo.qt import theme as Q

    frosted = Q.PRESETS[Q.DEFAULT_PRESET]
    assert frosted.workspace >= 0.75
    assert frosted.panel >= 0.94


# -- the backdrop behind the cards ------------------------------------------

def test_the_workspace_has_a_backdrop_at_all():
    """It used to be fully transparent, which is why content behind the window
    stayed legible however hard the compositor blurred. Blur smears what is
    behind a surface; it does not dim it, and a region with no surface has
    nothing to dim with."""
    from kairo.qt import theme as Q
    from kairo.ui import theme as T

    sheet = Q.stylesheet("frosted")
    line = next(l for l in sheet.splitlines() if "QWidget#workspace" in l)
    assert "transparent" not in line
    assert Q.rgba(T.C_BG, Q.PRESETS["frosted"].workspace) in line


def test_the_window_itself_still_has_no_rectangle():
    """The root stays fully transparent so Kairo never draws a slab the
    compositor has to blur around."""
    from kairo.qt import theme as Q

    line = next(l for l in Q.stylesheet("dense").splitlines()
                if "QWidget#root" in l)
    assert "transparent" in line


def test_the_backdrop_sits_under_the_cards_in_every_preset():
    from kairo.qt import theme as Q

    for name, glass in Q.PRESETS.items():
        assert glass.workspace <= glass.panel, name


def test_dense_raises_the_backdrop_most():
    """It is the lever that actually stops text reading through."""
    from kairo.qt import theme as Q

    frosted, dense = Q.PRESETS["frosted"], Q.PRESETS["dense"]
    assert dense.workspace - frosted.workspace > dense.panel - frosted.panel


# -- the UI must not imply Kairo can set blur strength ----------------------

def test_appearance_says_who_controls_what():
    """ext-background-effect-v1 carries a region and nothing else - no radius,
    no strength. A slider here would be claiming a setting that does not
    exist."""
    source = (QT_DIR / "settings.py").read_text()
    note = source.split("Kairo controls opacity")[1].split('"""')[0]

    assert "compositor controls blur" in note.lower()
    assert "Desktop Effects" in note
    assert "no radius or strength" in note


def test_no_blur_strength_control_is_offered():
    from kairo.qt import theme as Q

    assert not any("blur" in layer for layer in Q.LAYERS)
    for path in MODULES:
        source = path.read_text().lower()
        assert "blurstrength" not in source
        assert "blur_radius" not in source


def test_blur_never_forces_qt_onto_xwayland():
    source = (QT_DIR / "__main__.py").read_text()
    assert "QT_QPA_PLATFORM" not in source
    assert "xcb" not in source


def test_native_blur_uses_a_real_exact_region_not_null():
    """The protocol says NULL removes blur; shell 6 did exactly that."""
    source = (QT_DIR / "native" / "blur.c").read_text()
    assert "wl_compositor_create_region" in source
    assert "wl_region_add(region, 0, 0, width, height)" in source
    assert "set_blur_region(effect, region)" in source
    assert "set_blur_region(effect, NULL)" not in source
    assert "INT32_MAX" not in source


def test_native_blur_uses_a_private_wayland_queue():
    """A default-queue roundtrip can dispatch Qt callbacks re-entrantly."""
    source = (QT_DIR / "native" / "blur.c").read_text()
    assert "wl_display_create_queue" in source
    assert "wl_proxy_set_queue" in source
    assert source.count("wl_display_roundtrip_queue") >= 2
    assert "wl_display_roundtrip(display)" not in source


def test_blur_bridge_keeps_the_gil_and_tracks_resizes():
    bridge = (QT_DIR / "blur.py").read_text()
    shell = (QT_DIR / "shell.py").read_text()
    assert "ctypes.PyDLL" in bridge
    assert "ctypes.CDLL" not in bridge
    assert "kairo_blur_resize" in bridge
    assert "def resizeEvent" in shell
    assert "_blur_resize_timer" in shell
    assert "self.blur.update(self)" in shell


def test_the_resize_bridge_is_debounced():
    """Wayland gets one region per gesture, not one per resize event."""
    shell = (QT_DIR / "shell.py").read_text()
    setup = shell.split("_blur_resize_timer = QTimer")[1].split("want_blur")[0]
    assert "setSingleShot(True)" in setup
    assert "setInterval(" in setup


def test_every_native_return_code_has_a_message():
    """The C and the Python status table are one contract in two files."""
    import re

    from kairo.qt import blur

    source = (QT_DIR / "native" / "blur.c").read_text()
    codes = {int(code) for code in re.findall(r"return\s+(-\d+);", source)}
    assert codes, "no failure codes found in the bridge"
    missing = sorted(codes - set(blur.RESULTS))
    assert not missing, f"native codes with no explanation: {missing}"


def test_a_bridge_from_an_older_tree_degrades_instead_of_crashing(
        monkeypatch, tmp_path):
    """A stale .so loads, then has no kairo_blur_resize.

    That raises AttributeError rather than OSError, so catching only OSError
    turned a leftover library on disk into a hard startup failure.
    """
    import types

    from kairo.qt import blur

    stale = tmp_path / blur.LIBRARY_NAME
    stale.write_bytes(b"")

    class OlderBridge:
        def __init__(self, path):
            pass

        def __getattr__(self, name):
            if name in ("kairo_blur_available", "kairo_blur_enable"):
                return types.SimpleNamespace()
            raise AttributeError(name)

    monkeypatch.setattr(blur, "SEARCH_PATHS", (stale,))
    monkeypatch.setattr(blur.ctypes, "PyDLL", OlderBridge)

    probe = blur.Blur()
    assert probe._library is None
    assert probe.active is False
    assert "would not load" in probe.status
    assert probe.supported() is False


def test_blur_is_released_before_qt_destroys_the_surface():
    native = (QT_DIR / "native" / "blur.c").read_text()
    bridge = (QT_DIR / "blur.py").read_text()
    close = (QT_DIR / "shell.py").read_text().split("def closeEvent")[1]
    remove = bridge.split("def remove")[1]
    assert "kairo_blur_disable" in native
    assert "ext_background_effect_surface_v1_destroy" in native
    assert "kairo_blur_disable.argtypes" in bridge
    assert "_surface(" not in remove, "teardown must use the cached handle"
    assert close.index("self.blur.remove(self)") < close.index("super().closeEvent")


def test_qt_jobs_are_destroyed_on_the_gui_thread():
    """Auto-delete caused the live Shiboken/Python reference race."""
    source = (QT_DIR / "work.py").read_text()
    assert "setAutoDelete(False)" in source
    assert "Qt.QueuedConnection" in source
    assert "QThreadPool.globalInstance()" not in source
    assert "finally:" in source and "signals.finished.emit()" in source


# -- the worker lifecycle, for real -----------------------------------------
#
# The shell-7 segfault was a QRunnable with autoDelete letting Qt destroy a
# Python-owned QObject on a pool thread. Grepping for setAutoDelete(False)
# proves the line exists; these prove the behaviour it was meant to buy.

@pytest.fixture
def qt_core():
    """A QCoreApplication. No display, no widgets, no libEGL."""
    from PySide6.QtCore import QCoreApplication

    yield QCoreApplication.instance() or QCoreApplication([])


def settle(app, timeout=10.0):
    """Pump the loop until every job has been released on this thread."""
    from kairo.qt import work

    deadline = time.monotonic() + timeout
    while not work.is_idle() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()
    return work.is_idle()


def test_a_finished_job_is_released_on_the_calling_thread(qt_core):
    from kairo.qt import work

    seen = {}

    def record(value):
        seen["value"] = value
        seen["thread"] = threading.get_ident()

    job = work.submit(lambda: 21 * 2, on_done=record)
    # Qt must never delete this: it owns a QObject created on this thread.
    assert job.autoDelete() is False
    assert job in work._LIVE_JOBS

    assert settle(qt_core), "the job never drained"
    assert seen["value"] == 42
    assert seen["thread"] == threading.get_ident(), "result crossed threads"
    assert job not in work._LIVE_JOBS, "the job outlived its release"


def test_a_failing_job_is_released_too(qt_core):
    """The release runs from ``finally``; an exception must not leak a job."""
    from kairo.qt import work

    failures = []

    def boom():
        raise RuntimeError("nope")

    job = work.submit(boom, on_failed=failures.append)
    assert settle(qt_core), "a failed job never drained"
    assert failures == ["nope"]
    assert job not in work._LIVE_JOBS


def test_many_jobs_all_drain(qt_core):
    """is_idle is what closeEvent waits on, so it has to mean what it says."""
    from kairo.qt import work

    results = []
    jobs = [work.submit(lambda n=n: n * n, on_done=results.append)
            for n in range(24)]
    assert settle(qt_core), "a batch of jobs never drained"
    assert sorted(results) == sorted(n * n for n in range(24))
    assert not any(job in work._LIVE_JOBS for job in jobs)
    assert work.is_idle()


def test_is_idle_is_false_while_a_job_is_outstanding(qt_core):
    """A close that does not wait is the bug; this is the signal it waits on."""
    from kairo.qt import work

    release = threading.Event()
    job = work.submit(release.wait)
    try:
        assert work.is_idle() is False
    finally:
        release.set()
    assert settle(qt_core)
    assert job not in work._LIVE_JOBS


def test_close_drains_artwork_jobs_before_qt_teardown():
    source = (QT_DIR / "shell.py").read_text()
    close = source.split("def closeEvent")[1].split("\n    def ")[0]
    assert "work.is_idle()" in close
    assert "event.ignore()" in close
    assert "self.hide()" in close
    assert "def _finish_close" in source


def test_a_clicked_signal_is_never_wired_straight_to_a_bare_signal():
    """QPushButton.clicked carries a checked flag.

    Connecting it to the emit of a zero-argument Signal type-checks fine and
    fails at the first press — exactly what a read-only milestone with no
    display cannot catch by itself.
    """
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent / "kairo" / "qt"
    pattern = re.compile(r"clicked\.connect\(\s*self\.\w+\.emit\s*\)")
    offenders = [path.name for path in sorted(root.glob("*.py"))
                 if pattern.search(path.read_text())]
    assert not offenders, offenders


def test_a_disabled_button_never_keeps_its_accent():
    """ID selectors outrank bare pseudo-classes in QSS.

    QPushButton:disabled alone loses to QPushButton#primary, so a disabled
    Apply rendered in full accent and read as live. Caught by rendering it.
    """
    from kairo.qt import theme as Q
    for preset in ("frosted", "dense", "clear", "solid"):
        assert "QPushButton#primary:disabled" in Q.stylesheet(preset), preset


def test_only_one_primary_action_is_offered_at_a_time():
    """Apply is the primary action; nothing else competes with it."""
    from pathlib import Path
    source = (Path(__file__).resolve().parent.parent
              / "kairo" / "qt" / "library.py").read_text()
    primaries = [line.strip() for line in source.splitlines()
                 if 'setObjectName("primary")' in line]
    assert len(primaries) == 1, primaries
    assert "apply_btn" in primaries[0]


def test_a_cleared_widget_is_unparented_before_it_is_deleted():
    """deleteLater only runs on the next event-loop turn.

    Until then the old tiles keep painting over the new grid, so a source
    switch flickers the previous results on top of the incoming ones.
    """
    from pathlib import Path
    source = (Path(__file__).resolve().parent.parent
              / "kairo" / "qt" / "library.py").read_text()
    index = source.index("widget.deleteLater()")
    assert "widget.setParent(None)" in source[index - 200:index]


def test_a_pane_subclass_asks_for_its_own_background():
    """QSS backgrounds are opt-in for QWidget subclasses.

    A plain QWidget instance painted #workspace fine, so the library looked
    right while Settings and Changes silently fell back to the default
    palette and read as light grey panels.
    """
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent / "kairo" / "qt"
    offenders = []
    for path in sorted(root.glob("*.py")):
        body = path.read_text()
        for match in re.finditer(r"class (\w+)\(QWidget\):", body):
            block = body[match.start():match.start() + 2600]
            names = re.search(r'self\.setObjectName\("(\w+)"\)', block)
            if names and "WA_StyledBackground" not in block:
                offenders.append(f"{path.name}: {match.group(1)} -> {names.group(1)}")
    assert not offenders, offenders
