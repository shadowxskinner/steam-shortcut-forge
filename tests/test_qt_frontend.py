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


def test_artwork_sources_stay_available_after_empty_or_failed_searches():
    """One poor query must not make its source tab disappear."""
    source = (QT_DIR / "library.py").read_text()
    assert "_probe_cache" not in source
    assert "_probe_sources" not in source
    empty = source.split("if not results:")[1].split("return", 1)[0]
    assert "Try a different search" in empty
    assert "_refresh_sources" not in empty


def test_choosing_artwork_only_proposes_it():
    """Nothing writes until Apply, which is the rule the review screen has
    always followed and the single-item path now follows too."""
    source = (QT_DIR / "library.py").read_text()
    propose = source.split("def _propose(self, art)")[1]
    for writing in ("fetch_and_apply", "apply_icon", "restore_entry",
                    "remove_entry"):
        assert writing not in propose


# -- how the shell is allowed to write --------------------------------------
#
# The read-only guard has served its purpose and is replaced, not deleted:
# writing is now permitted, but only through the one door that owns the
# marker checks, the ledger and the atomic write.

def test_the_shell_never_writes_a_launcher_file_itself():
    """Every write goes through kairo.actions, never a writer or a path."""
    for path in MODULES:
        source = path.read_text()
        for backdoor in ("writer.apply", "writer.restore(", "writer.remove(",
                         "os.replace", "shutil.copyfile", "write_text(",
                         "write_bytes(", "unlink("):
            assert backdoor not in source, f"{path.name} uses {backdoor}"


def test_every_write_records_itself_in_the_ledger():
    """An unrecorded change cannot be undone from the Changes view."""
    source = (QT_DIR / "library.py").read_text()
    for call in ("actions.fetch_and_apply(", "actions.restore_entry(",
                 "actions.remove_entry("):
        assert call in source, f"{call} is not wired"
        tail = source.split(call)[1].split(")")[0]
        assert "ledger=self.ctx.ledger" in tail, f"{call} skips the ledger"


def test_applying_runs_off_the_ui_thread_and_can_be_cancelled():
    source = (QT_DIR / "library.py").read_text()
    apply_body = source.split("def _apply")[1].split("def _restore")[0]
    assert "work.submit(" in apply_body, "a network fetch must not block the UI"
    assert "self.tokens.start(" in apply_body
    assert "token=token" in apply_body


def test_only_the_destructive_action_asks_first():
    """Apply and restore are recoverable from Changes; deleting is not."""
    source = (QT_DIR / "library.py").read_text()
    remove = source.split("def _remove")[1].split("def _browse")[0]
    assert "QMessageBox" in remove
    assert "QMessageBox.Cancel" in remove, "cancel must be the default"
    for safe in ("def _apply", "def _restore"):
        body = source.split(safe)[1].split("\n    def ")[0]
        assert "QMessageBox" not in body, f"{safe} should not interrupt"


def test_apply_is_offered_only_once_there_is_something_to_apply():
    source = (QT_DIR / "library.py").read_text()
    assert "self.apply_btn.setEnabled(False)" in source
    propose = source.split("def _propose")[1].split("\n    def ")[0]
    assert "self.apply_btn.setEnabled(True)" in propose


# -- tuning controls that actually reach the user ---------------------------






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
    # The finished signal must fire from finally, whatever run() did, or the
    # job is never released. It goes through _emit now so a dead receiver
    # cannot strand it either.
    assert "finally:" in source
    assert "self._emit(self.signals.finished)" in source


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

# -- what the window deliberately no longer has -----------------------------

def test_there_is_no_status_strip():
    """The window is the three columns and nothing else.

    A footer that reports blur state and a read-only banner is scaffolding
    from the milestone, not part of the product.
    """
    shell = (QT_DIR / "shell.py").read_text()
    assert "objectName(\"footer\")" not in shell
    assert "read-only shell" not in shell
    assert "_refresh_status" not in shell


def test_blur_state_never_reaches_the_window():
    """It still prints once for a terminal launch, and stops there."""
    shell = (QT_DIR / "shell.py").read_text()
    settings = (QT_DIR / "settings.py").read_text()
    assert "set_blur_status" not in shell and "set_blur_status" not in settings
    # It may be assigned and printed; it may never be put into a widget.
    for line in shell.splitlines():
        if "blur.status" in line:
            assert "setText" not in line, line.strip()
            assert "addWidget" not in line, line.strip()


def test_appearance_is_fixed_not_edited():
    """The glass values are the design now, not a runtime control."""
    settings = (QT_DIR / "settings.py").read_text()
    shell = (QT_DIR / "shell.py").read_text()
    assert "AppearancePanel" not in settings
    assert "QSlider" not in settings
    assert "on_glass_change" not in settings and "on_glass_change" not in shell
    assert "QShortcut" not in shell, "no live retuning keys"


def test_the_fixed_appearance_is_still_applied():
    """Removing the controls must not remove the look they were setting."""
    from kairo.qt import theme as Q

    shell = (QT_DIR / "shell.py").read_text()
    assert "def apply_glass" in shell
    assert "setStyleSheet(Q.stylesheet(self.glass))" in shell
    frosted = Q.PRESETS[Q.DEFAULT_PRESET]
    assert (frosted.workspace, frosted.nav, frosted.panel) == (0.78, 0.97, 0.95)


def test_a_dead_receiver_never_strands_a_job(qt_core, monkeypatch):
    """Emitting from a deleted sender raises rather than being dropped.

    When the application tears down mid-lookup, that RuntimeError used to
    escape run() and take the finished signal with it, so the job was never
    released and is_idle() stayed false — a close that waits on it would then
    wait forever.
    """
    from kairo.qt import work

    class DeadSignal:
        def emit(self, *args):
            raise RuntimeError("Signal source has been deleted")

    job = work.submit(lambda: "value")
    monkeypatch.setattr(job.signals, "done", DeadSignal(), raising=False)
    monkeypatch.setattr(job.signals, "finished", DeadSignal(), raising=False)
    job.run()                      # as the pool thread would call it

    assert job not in work._LIVE_JOBS, "a stranded job blocks every close"


def test_closing_waits_for_work_but_not_forever():
    """A window must always be closable."""
    source = (QT_DIR / "shell.py").read_text()
    assert "CLOSE_DRAIN_SECONDS" in source
    finish = source.split("def _finish_close")[1]
    assert "_close_deadline" in finish, "the drain has no deadline"


# -- one asset, several resolutions -----------------------------------------

def _ico(sizes):
    """A .ico holding several frames, smallest first, as SteamGridDB serves.

    Built with QImage alone: QPainter and QFont need a QGuiApplication, and
    this must stay runnable on a machine with no display.
    """
    import struct

    from PySide6.QtCore import QBuffer, QByteArray
    from PySide6.QtGui import QColor, QImage

    frames = []
    for index, size in enumerate(sizes):
        img = QImage(size, size, QImage.Format_ARGB32)
        img.fill(QColor(40 * (index + 1) % 256, 90, 160))
        blob = QByteArray()
        buffer = QBuffer(blob)
        buffer.open(QBuffer.WriteOnly)
        img.save(buffer, "PNG")
        frames.append((size, bytes(blob.data())))

    out = struct.pack("<HHH", 0, 1, len(frames))
    offset = 6 + 16 * len(frames)
    entries = body = b""
    for size, blob in frames:
        entries += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0,
                               1, 32, len(blob), offset)
        body += blob
        offset += len(blob)
    return out + entries + body


def test_the_biggest_frame_is_the_one_that_gets_decoded():
    """QPixmap.loadFromData returns the *first* frame, which is the smallest.

    SteamGridDB serves one asset at several resolutions in a single .ico -
    a 256px icon ships alongside 128, 64, 48, 32 and 16 - so the browser was
    rendering a 16px thumbnail enlarged into a 116px tile. The reported
    dimensions were never wrong; nobody was decoding the frame they named.
    """
    from kairo.qt import images

    assert images._largest_frame(_ico([16, 32, 64, 128, 256])).width() == 256


def test_a_single_frame_image_is_unaffected():
    from kairo.qt import images

    assert images._largest_frame(_ico([256])).width() == 256


def test_undecodable_bytes_yield_nothing():
    from kairo.qt import images

    assert images._largest_frame(b"not an image at all") is None


def test_the_floor_is_applied_to_the_frame_that_decoded():
    """The API's dimensions describe the asset; the frame describes the pixels.

    An .ico can advertise 256 and contain nothing above 64. Filtering on the
    reported size alone let those through, so the same floor is applied again
    to what actually arrived - the one measurement that cannot be wrong.
    """
    from kairo.qt import images
    from kairo.qt.library import MIN_USABLE_EDGE

    assert images.native_edge(_ico([16, 32, 64])) < MIN_USABLE_EDGE
    assert images.native_edge(_ico([16, 32, 256])) >= MIN_USABLE_EDGE
    assert images.native_edge(b"not an image") == 0


def test_valid_svg_is_not_rejected_by_its_nominal_canvas_size():
    """Theme icons are scalable even when their SVG says 48 by 48."""
    from kairo.qt import images
    from kairo.qt.library import MIN_USABLE_EDGE

    svg = (b'<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" '
           b'viewBox="0 0 48 48"><rect width="48" height="48"/></svg>')
    assert images.native_edge(svg) < MIN_USABLE_EDGE
    assert images.is_usable_preview(svg, MIN_USABLE_EDGE)
    assert not images.is_usable_preview(_ico([16, 32, 64]), MIN_USABLE_EDGE)
    assert images.is_usable_preview(_ico([16, 32, 256]), MIN_USABLE_EDGE)
    assert not images.is_usable_preview(b"not an image", MIN_USABLE_EDGE)


def test_a_dropped_tile_does_not_leave_a_hole():
    """Removing a widget from a QGridLayout leaves its cell empty."""
    source = (QT_DIR / "library.py").read_text()
    drop = source.split("def _drop_tile")[1].split("\n    def ")[0]
    assert "_reflow_tiles" in drop
    reflow = source.split("def _reflow_tiles")[1].split("\n    def ")[0]
    assert "self.grid.addWidget(tile" in reflow
    assert "_grid_note" in reflow, "an emptied grid must say so"


def test_dropping_the_chosen_tile_clears_the_proposal():
    """Applying artwork that was just removed from the grid is not a thing."""
    source = (QT_DIR / "library.py").read_text()
    drop = source.split("def _drop_tile")[1].split("\n    def ")[0]
    assert "self._clear_proposal()" in drop


def test_clearing_the_proposal_also_withdraws_apply():
    source = (QT_DIR / "library.py").read_text()
    clear = source.split("def _clear_proposal")[1].split("\n    def ")[0]
    assert "self.apply_btn.setEnabled(False)" in clear


def test_previews_are_delivered_by_identity_not_by_position():
    """Dropping one tile must not misdirect every preview after it.

    Previews arrive keyed by their index in the result list while tiles are
    being removed as they land, so position in self.tiles stops matching the
    moment anything is dropped: later images went to the wrong tile and the
    tail was never filled at all, which is what showed up as blank squares.
    """
    source = (QT_DIR / "library.py").read_text()
    fill = source.split("def _fill_tile")[1].split("\n    def ")[0]
    assert "self._tile_at.get(index)" in fill
    assert "self.tiles[index]" not in fill, "positional lookup is the bug"

    drop = source.split("def _drop_tile")[1].split("\n    def ")[0]
    assert "del self._tile_at[index]" in drop, "a dropped tile must be unkeyed"


def test_a_preview_that_cannot_be_fetched_drops_its_tile():
    """An empty square is worse than one fewer choice."""
    source = (QT_DIR / "library.py").read_text()
    pump = source.split("def _stream_previews")[1].split("\n    def ")[0]
    assert "data = None" in pump, "a failure must be reported, not skipped"
    assert "continue" not in pump, "skipping leaves the tile blank forever"

    fill = source.split("def _fill_tile")[1].split("\n    def ")[0]
    assert "data is None" in fill


def test_the_app_id_is_only_claimed_when_a_desktop_file_backs_it(
        monkeypatch, tmp_path):
    """The portal logs a failure for an id it cannot look up.

    Announcing io.github.shadowxskinner.Kairo without the .desktop file
    installed is what produced "App info not found" on every launch.
    """
    from kairo import APP_ID
    from kairo.qt.__main__ import _desktop_file_installed

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_DIRS", str(tmp_path / "none"))
    assert _desktop_file_installed(APP_ID) is False

    applications = tmp_path / "applications"
    applications.mkdir()
    (applications / f"{APP_ID}.desktop").write_text("[Desktop Entry]\n")
    assert _desktop_file_installed(APP_ID) is True


def test_a_system_wide_install_counts_too():
    """XDG_DATA_DIRS, not a guess at ~/.local/share."""
    source = (QT_DIR / "__main__.py").read_text()
    assert "XDG_DATA_DIRS" in source
    assert "XDG_DATA_HOME" in source



def test_scanning_a_library_does_not_block_the_window():
    """A ROM folder can be thousands of files on a spinning disk."""
    source = (QT_DIR / "library.py").read_text()
    rescan = source.split("def rescan")[1].split("\n    def ")[0]
    assert "work.submit(" in rescan
    assert 'self.tokens.start(f"{ACTIVITY_SCAN}:{provider.id}")' in rescan
    assert "self.tokens.start(ACTIVITY_SCAN)" not in rescan
    assert "provider.scan()" in rescan
    assert "token.cancelled" in rescan, "a stale scan must not overwrite a new one"


def test_unchanged_pills_are_not_destroyed_and_recreated():
    """Refreshing stable tabs must not make them flash or lose selection."""
    source = (QT_DIR / "widgets.py").read_text()
    body = source.split("def set_values(self, values)")[1].split("\n    def ")[0]
    assert "values == list(self._buttons)" in body
    assert "self._layout.removeWidget(button)" in body
    assert "button.setParent(None)" in body


def test_rows_are_built_in_pages_not_all_at_once():
    """A row is five widgets; a library is not necessarily small.

    Building one per entry cost 1.8 seconds and 225MB on a 2000-game
    library — and paid it again every time the search box was cleared.
    """
    from kairo.qt.library import ROW_PAGE

    source = (QT_DIR / "library.py").read_text()
    assert 0 < ROW_PAGE < 500
    refilter = source.split("def refilter")[1].split("\n    def ")[0]
    assert "self._shown = min(" in refilter
    assert "self._bind_rows(entries[:self._shown])" in refilter


def test_reaching_the_bottom_brings_the_next_page():
    """Paging must not put entries out of reach."""
    source = (QT_DIR / "library.py").read_text()
    grow = source.split("def _grow_if_near_bottom")[1].split("\n    def ")[0]
    assert "self._shown + ROW_PAGE" in grow
    assert "verticalScrollBar" in grow
    assert "valueChanged.connect" in source


def test_the_count_reports_the_library_not_the_page():
    """Showing 120 of 2000 must still say 2000."""
    source = (QT_DIR / "library.py").read_text()
    refilter = source.split("def refilter")[1].split("\n    def ")[0]
    assert "self.visible = len(entries)" in refilter
    assert "self.count.setText(str(len(entries)))" in refilter


def test_growing_the_page_keeps_the_selection():
    source = (QT_DIR / "library.py").read_text()
    grow = source.split("def _grow_if_near_bottom")[1].split("\n    def ")[0]
    assert "self.selected" in grow, "scrolling must not drop the selection"


def test_the_application_has_an_icon_at_all():
    """It had none: window, task switcher and taskbar all fell back."""
    from kairo.qt import branding

    source = (QT_DIR / "__main__.py").read_text()
    assert "setWindowIcon(branding.icon())" in source
    built = branding.icon()
    assert not built.isNull()
    assert max(s.width() for s in built.availableSizes()) >= 256


def test_the_icon_is_found_from_a_checkout_too():
    """Installed it comes from the theme; run from source there is no theme."""
    source = (QT_DIR / "branding.py").read_text()
    assert "QIcon.fromTheme(APP_ID)" in source
    assert "_repository_icons" in source
