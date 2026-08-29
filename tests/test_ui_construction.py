"""Build the whole window against a stubbed toolkit.

There is no Tk here and no display, so the GUI would otherwise get no
execution at all. Importing a module only runs its class bodies; *constructing*
the widgets runs every _build method, which is where the mistakes actually
live - a misspelled attribute, a theme token that does not exist, a method
called with the wrong arguments, a pane that assumes state set up elsewhere.

It cannot check that anything looks right. It can check that the window can be
assembled at all, which is the difference between a layout problem and a
traceback on first launch.
"""

import sys
import types

import pytest


class _Var:
    """A Tk variable that actually holds a value, because the code reads it."""

    def __init__(self, value="", **kwargs):
        self._value = value

    def get(self):
        return self._value

    def set(self, value):
        self._value = value

    def trace_add(self, *args, **kwargs):
        return "trace0"


class _Widget:
    """Accepts anything, returns something plausible for what the code asks."""

    _LISTS = {"winfo_children"}
    _FALSE = {"winfo_ismapped"}
    _TRUE = {"winfo_exists"}
    _NUMBERS = {"winfo_width", "winfo_reqwidth", "winfo_rootx", "winfo_rooty",
                "winfo_height"}

    def __init__(self, *args, **kwargs):
        self._scrollbar = _Widget.__new__(_Widget)
        self._parent_canvas = _Widget.__new__(_Widget)

    def __getattr__(self, name):
        if name in self._LISTS:
            return lambda *a, **k: []
        if name in self._FALSE:
            return lambda *a, **k: False
        if name in self._TRUE:
            return lambda *a, **k: True
        if name in self._NUMBERS:
            return lambda *a, **k: 200
        if name == "after":
            return lambda *a, **k: "after0"
        return lambda *a, **k: None

    def bind(self, sequence=None, command=None, add=True):
        """Enforce the one CustomTkinter contract we have been bitten by.

        CTk widgets reject any `add` other than "+" or True, to protect their
        internal bindings. The stub accepts everything else a widget is asked
        to do, which is the point - but a permissive stub gave false
        confidence here, so this specific rule is encoded rather than
        rediscovered on somebody's desktop.
        """
        if not (add == "+" or add is True):
            raise ValueError("'add' argument can only be '+' or True to "
                             "preserve internal callbacks")
        return "bind0"

    def __call__(self, *args, **kwargs):
        return None


class _StubModule(types.ModuleType):
    """Attributes are subclassable classes; exception-ish names are exceptions."""

    _SPECIAL = {"StringVar": _Var, "BooleanVar": _Var, "IntVar": _Var,
                "DoubleVar": _Var}

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        if name in self._SPECIAL:
            created = self._SPECIAL[name]
        elif name.endswith("Error"):
            created = type(name, (Exception,), {})
        else:
            created = type(name, (_Widget,), {})
        setattr(self, name, created)
        return created


class _DialogModule(types.ModuleType):
    """Dialogs decline by default.

    A construction test must not have confirmations answering "yes" and
    quietly running the very code paths it is not trying to exercise.
    """

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        if name.startswith("ask"):
            if "filename" in name or "directory" in name:
                return lambda *a, **k: ""
            return lambda *a, **k: False
        return lambda *a, **k: None


@pytest.fixture
def toolkit(monkeypatch):
    if "tkinter" in sys.modules and not isinstance(sys.modules["tkinter"], _StubModule):
        pytest.skip("real Tk is available; this stub would shadow it")

    modules = {}
    for name in ("tkinter", "tkinter.ttk", "customtkinter",
                 "customtkinter.windows", "customtkinter.windows.widgets",
                 "customtkinter.windows.widgets.core_rendering"):
        modules[name] = _StubModule(name)
    for name in ("tkinter.filedialog", "tkinter.messagebox"):
        modules[name] = _DialogModule(name)

    # `from tkinter import messagebox` resolves the attribute on the parent
    # package before falling back to sys.modules, so the parent has to carry
    # its submodules explicitly.
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
        if "." in name:
            parent, _, leaf = name.rpartition(".")
            setattr(modules[parent], leaf, module)

    for name in list(sys.modules):
        if name.startswith("kairo.ui") or name in {"kairo.imaging"}:
            monkeypatch.delitem(sys.modules, name, raising=False)
    yield


@pytest.fixture
def furnished(fake_home, steam_library, system_apps):
    """A home with a couple of Steam games and a couple of applications."""
    return fake_home


# -- navigation is built from providers, not hard-coded ---------------------

def test_nav_groups_providers_and_management(toolkit, furnished):
    from kairo.providers.registry import default_registry
    from kairo.ui import nav

    items = nav.build_items(default_registry())
    groups = [i.group for i in items]
    assert "Library" in groups
    assert nav.GROUP_MANAGEMENT in groups
    assert {i.key for i in items} >= {"provider:steam", "provider:desktop",
                                      nav.VIEW_CHANGES, nav.VIEW_SETTINGS}


def test_a_new_provider_group_appears_without_touching_the_ui(toolkit, furnished):
    """The whole point of putting `group` on the provider: a future
    PCSX2Provider must reach the navigation without a UI change."""
    from kairo.providers.base import AppProvider
    from kairo.providers.registry import default_registry
    from kairo.ui import nav

    class PretendEmulator(AppProvider):
        id = "pretend"
        label = "PCSX2"
        noun = "games"
        group = "Emulators"
        order = 0

        def scan(self):
            return []

        def artwork_query(self, entry):
            raise NotImplementedError

        def writer(self):
            raise NotImplementedError

    registry = default_registry()
    registry.register(PretendEmulator())

    items = nav.build_items(registry)
    emulators = [i for i in items if i.group == "Emulators"]
    assert [i.label for i in emulators] == ["PCSX2"]
    # and it lands before the management section
    assert items.index(emulators[0]) < items.index(
        next(i for i in items if i.key == nav.VIEW_CHANGES))


def test_management_comes_last(toolkit, furnished):
    from kairo.providers.registry import default_registry
    from kairo.ui import nav

    items = nav.build_items(default_registry())
    assert items[-2].key == nav.VIEW_CHANGES
    assert items[-1].key == nav.VIEW_SETTINGS


# -- every pane can actually be built ---------------------------------------

def test_library_pane_builds_for_each_provider(toolkit, furnished):
    from kairo.ledger import Ledger
    from kairo.providers.registry import default_registry
    from kairo.artwork.registry import default_registry as artwork_registry
    from kairo.tasks import ActivityTokens
    from kairo.ui.context import UIContext
    from kairo.ui.library import LibraryPane

    registry = default_registry()
    ctx = UIContext(providers=registry, sources=artwork_registry({}), config={},
                    ledger=Ledger().load(), tokens=ActivityTokens())

    for provider in registry.all():
        pane = LibraryPane(None, provider, ctx)
        assert pane.provider is provider
        assert isinstance(pane.entries, list)


def test_library_pane_lists_and_filters_entries(toolkit, furnished):
    from kairo.ledger import Ledger
    from kairo.providers.registry import default_registry
    from kairo.artwork.registry import default_registry as artwork_registry
    from kairo.tasks import ActivityTokens
    from kairo.ui.context import UIContext
    from kairo.ui.library import LibraryPane

    registry = default_registry()
    ctx = UIContext(providers=registry, sources=artwork_registry({}), config={},
                    ledger=Ledger().load(), tokens=ActivityTokens())
    pane = LibraryPane(None, registry.get("steam"), ctx)

    assert len(pane.entries) == 2                     # from the fixture
    pane.search_var.set("portal")
    assert [e.name for e in pane.visible_entries()] == ["Portal 2"]
    pane.search_var.set("")
    pane._set_filter("with")
    assert pane.visible_entries() == []


def test_changes_pane_builds_empty_and_populated(toolkit, furnished):
    from kairo.ledger import ChangeRecord, Ledger
    from kairo.providers.registry import default_registry
    from kairo.artwork.registry import default_registry as artwork_registry
    from kairo.tasks import ActivityTokens
    from kairo.ui.changes_pane import ChangesPane
    from kairo.ui.context import UIContext

    ledger = Ledger().load()
    ctx = UIContext(providers=default_registry(),
                    sources=artwork_registry({}), config={}, ledger=ledger,
                    tokens=ActivityTokens())
    ChangesPane(None, ctx)                            # empty state

    from kairo import paths
    target = paths.applications_dir() / "kairo-440.desktop"
    target.write_text("[Desktop Entry]\nType=Application\nName=TF2\n"
                      "Icon=/x.png\nX-Kairo-Managed=true\n")
    ledger.record(ChangeRecord(key="steam:440", provider_id="steam", name="TF2",
                               action="created", target=str(target)))
    ChangesPane(None, ctx)                            # populated state


def test_settings_pane_builds(toolkit, furnished):
    from kairo.ledger import Ledger
    from kairo.providers.registry import default_registry
    from kairo.artwork.registry import default_registry as artwork_registry
    from kairo.tasks import ActivityTokens
    from kairo.ui.context import UIContext
    from kairo.ui.settings_pane import SettingsPane

    ctx = UIContext(providers=default_registry(), sources=artwork_registry({}),
                    config={"steamgriddb_api_key": "abc"},
                    ledger=Ledger().load(), tokens=ActivityTokens())
    SettingsPane(None, ctx)


# -- and the whole window -----------------------------------------------------

def test_the_shell_assembles(toolkit, furnished):
    from kairo.ui.shell import KairoShell

    shell = KairoShell()
    assert shell.items
    assert shell.current_key is not None
    assert shell.current_key in shell.panes


def test_switching_panes_builds_each_destination(toolkit, furnished):
    from kairo.ui import nav
    from kairo.ui.shell import KairoShell

    shell = KairoShell()
    for item in shell.items:
        shell._select(item)
        assert shell.current_key == item.key
        assert item.key in shell.panes
    assert nav.VIEW_CHANGES in shell.panes
    assert nav.VIEW_SETTINGS in shell.panes


def test_shell_survives_rescan(toolkit, furnished):
    from kairo.ui.shell import KairoShell

    shell = KairoShell()
    shell.rescan()
    shell._on_changed()


def test_shell_collects_entries_across_providers(toolkit, furnished):
    from kairo.ui.shell import KairoShell

    shell = KairoShell()
    entries = shell._all_entries()
    keys = {e.key for e in entries}
    assert any(k.startswith("steam:") for k in keys)
    assert any(k.startswith("desktop:") for k in keys)


def test_classic_window_still_assembles(toolkit, furnished):
    """Kept reachable via `kairo --classic` while the new shell is proven."""
    from kairo.ui.app import KairoApp

    app = KairoApp()
    assert app.entries is not None


# -- the shared pill control has real behaviour worth pinning ---------------

def test_pills_select_the_first_value_by_default(toolkit, furnished):
    from kairo.ui.widgets import SegmentedPills

    pills = SegmentedPills(None, values=["A", "B", "C"])
    assert pills.values() == ["A", "B", "C"]
    assert pills.get() == "A"


def test_pills_report_and_change_selection(toolkit, furnished):
    from kairo.ui.widgets import SegmentedPills

    chosen = []
    pills = SegmentedPills(None, values=["A", "B"], command=chosen.append)
    pills._pick("B")
    assert pills.get() == "B"
    assert chosen == ["B"]


def test_pills_drive_a_shared_variable(toolkit, furnished):
    """The source picker and the rest of the pane read the same variable."""
    import customtkinter as ctk
    from kairo.ui.widgets import SegmentedPills

    var = ctk.StringVar(value="")
    pills = SegmentedPills(None, values=["Icon themes", "Iconify"], variable=var)
    assert var.get() == "Icon themes"
    pills.set("Iconify")
    assert var.get() == "Iconify"


def test_pills_reselect_when_the_current_value_disappears(toolkit, furnished):
    """Sources are pruned per application, so the selected one can vanish."""
    import customtkinter as ctk
    from kairo.ui.widgets import SegmentedPills

    var = ctk.StringVar(value="")
    pills = SegmentedPills(None, values=["SteamGridDB", "Icon themes"], variable=var)
    pills.set("Icon themes")
    pills.set_values(["SteamGridDB"])
    assert pills.values() == ["SteamGridDB"]
    assert var.get() == "SteamGridDB"


def test_pills_tolerate_an_empty_set(toolkit, furnished):
    from kairo.ui.widgets import SegmentedPills

    pills = SegmentedPills(None, values=["A"])
    pills.set_values([])
    assert pills.values() == []


def test_filter_pills_drive_the_library_filter(toolkit, furnished):
    from kairo.ledger import Ledger
    from kairo.providers.registry import default_registry
    from kairo.artwork.registry import default_registry as artwork_registry
    from kairo.tasks import ActivityTokens
    from kairo.ui.context import UIContext
    from kairo.ui.library import LibraryPane

    registry = default_registry()
    ctx = UIContext(providers=registry, sources=artwork_registry({}), config={},
                    ledger=Ledger().load(), tokens=ActivityTokens())
    pane = LibraryPane(None, registry.get("steam"), ctx)

    assert len(pane.visible_entries()) == 2
    pane.filter_pills._pick("Customized")
    assert pane._filter_mode == "with"
    assert pane.visible_entries() == []
    pane.filter_pills._pick("All")
    assert len(pane.visible_entries()) == 2


def test_search_field_binds_without_breaking_internal_callbacks(toolkit, furnished):
    """Regression: bind_entry defaulted `add` to None and forwarded it, which
    CTkEntry rejects - so the workspace crashed the moment a source needing a
    query was selected."""
    import customtkinter as ctk
    from kairo.ui.widgets import SearchField

    field = SearchField(None, textvariable=ctk.StringVar(value=""))
    field.bind_entry("<KeyRelease>", lambda _event: None)
    field.bind_entry("<Return>", lambda _event: None, add=True)

    with pytest.raises(ValueError):
        field.bind_entry("<Key>", lambda _event: None, add=None)


# -- image lifetime ---------------------------------------------------------
#
# The stub cannot model Tk's image lifetimes, so it could not have caught the
# original failure. What it can pin is the contract derived from it: the
# widget must stop referencing an image before Python releases it.

def test_apply_image_configures_before_releasing_the_previous_one(toolkit,
                                                                  furnished):
    """Rebinding first frees the old image while the widget still points at
    it, and every later configure() on that widget then raises - including one
    that only changes text."""
    from kairo.ui.widgets import apply_image

    class Owner:
        pass

    owner = Owner()
    owner._photo = "OLD"
    seen = []

    class RecordingLabel:
        def configure(self, **kwargs):
            # The owner must still hold the previous image at this moment.
            seen.append(owner._photo)

    apply_image(RecordingLabel(), owner, "_photo", "NEW", text="")

    assert seen == ["OLD"], "configure must run before the reference is replaced"
    assert owner._photo == "NEW"


def test_apply_image_recovers_from_a_stale_handle(toolkit, furnished):
    """If a widget is already holding a freed image, clear it and retry."""
    import tkinter as tk
    from kairo.ui.widgets import apply_image

    class Owner:
        pass

    owner = Owner()
    owner._photo = None
    calls = []

    class StaleLabel:
        def configure(self, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise tk.TclError('image "pyimage5" doesn\'t exist')

    apply_image(StaleLabel(), owner, "_photo", "NEW", text="")

    assert len(calls) == 3            # failed, cleared, succeeded
    assert calls[1] == {"image": None}
    assert owner._photo == "NEW"


def test_apply_image_never_raises_into_the_caller(toolkit, furnished):
    import tkinter as tk
    from kairo.ui.widgets import apply_image

    class Owner:
        pass

    class BrokenLabel:
        def configure(self, **kwargs):
            raise tk.TclError("hopeless")

    owner = Owner()
    apply_image(BrokenLabel(), owner, "_photo", "NEW", text="")
    assert owner._photo == "NEW"


def test_icon_well_degrades_instead_of_aborting_a_selection(toolkit, furnished,
                                                            tmp_path):
    """show() runs from click handlers, so a decode failure must not abort
    the selection."""
    from kairo.ui.widgets import IconWell

    well = IconWell(None, size=48)
    well.show(None)                                   # nothing to show
    well.show(tmp_path / "missing.png")               # path does not exist
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"not an image at all")
    well.show(broken)                                 # undecodable
    well.show_data(b"also not an image")


# -- switching between artwork and placeholder ------------------------------
#
# CustomTkinter cannot empty a label: CTkLabel._update_image() ignores a None
# image, so the Tk label keeps the previous one. Everything below pins the way
# IconWell works around that.

@pytest.fixture
def png(tmp_path):
    from PIL import Image

    path = tmp_path / "icon.png"
    Image.new("RGBA", (32, 32), (90, 60, 245, 255)).save(path)
    return path


def test_placeholder_hides_the_image_rather_than_clearing_it(toolkit, furnished, png):
    from kairo.ui.widgets import IconWell

    well = IconWell(None, size=64)
    well.show(png)
    assert well._showing_image is True
    shown = well._photo
    assert shown is not None

    well.show_placeholder("—")
    assert well._showing_image is False
    # The reference is deliberately retained: the hidden image label still
    # points at it, and freeing it would leave a dangling Tk handle.
    assert well._photo is shown


def test_artwork_survives_alternating_with_a_placeholder(toolkit, furnished, png):
    """The reported failure: select an entry with no icon, then one that has
    one, and the second refuses to render."""
    from kairo.ui.widgets import IconWell

    well = IconWell(None, size=64)
    for _ in range(5):
        well.show(png)
        assert well._showing_image is True
        well.show(None, placeholder="—")
        assert well._showing_image is False
    well.show(png)
    assert well._showing_image is True
    assert well._photo is not None


def test_a_missing_icon_does_not_poison_the_next_one(toolkit, furnished, png,
                                                     tmp_path):
    from kairo.ui.widgets import IconWell

    well = IconWell(None, size=64)
    well.show(tmp_path / "gone.png", placeholder="—")
    assert well._showing_image is False
    well.show(png)
    assert well._showing_image is True


def test_an_undecodable_icon_does_not_poison_the_next_one(toolkit, furnished,
                                                          png, tmp_path):
    from kairo.ui.widgets import IconWell

    broken = tmp_path / "broken.png"
    broken.write_bytes(b"not an image")
    well = IconWell(None, size=64)
    well.show(broken)
    assert well._showing_image is False
    well.show(png)
    assert well._showing_image is True


def test_show_data_and_show_path_interchange_freely(toolkit, furnished, png):
    from kairo.ui.widgets import IconWell

    well = IconWell(None, size=64)
    well.show_data(png.read_bytes())
    assert well._showing_image is True
    well.show_placeholder("—")
    well.show_data(png.read_bytes())
    assert well._showing_image is True


def test_icon_well_does_not_shadow_the_widget_size_method(toolkit, furnished):
    """tkinter.Grid defines size() as an alias for grid_size(); assigning an
    int over it is the same trap as assigning to self.config."""
    from kairo.ui.widgets import IconWell

    well = IconWell(None, size=48)
    assert well.size == 48
    assert "size" not in vars(well)


def test_rows_and_tiles_share_the_well(toolkit, furnished, png):
    """One implementation of 'show artwork or a placeholder', not three."""
    from kairo.models import AppEntry
    from kairo.ui.widgets import AppRow, ArtworkTile, IconWell
    from kairo.models import Artwork

    with_icon = AppEntry(key="steam:1", provider_id="steam", name="With",
                         current_icon=png)
    without = AppEntry(key="steam:2", provider_id="steam", name="Without")

    row_a = AppRow(None, with_icon, on_click=lambda _r: None)
    row_b = AppRow(None, without, on_click=lambda _r: None)
    assert isinstance(row_a.well, IconWell)
    assert row_a.well._showing_image is True
    assert row_b.well._showing_image is False

    tile = ArtworkTile(None, Artwork(id="a", source_id="s"), on_pick=lambda _a: None)
    assert isinstance(tile.well, IconWell)
    tile.set_image(png.read_bytes())
    assert tile.well._showing_image is True
    tile.set_image(b"not an image")
    assert tile.well._showing_image is False
