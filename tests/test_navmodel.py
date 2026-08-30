"""Navigation is a property of the registry, not of a toolkit.

These run with no GUI library present at all, which is the point: both shells
build the same navigation from the same providers, so this can be asserted once
rather than once per frontend.
"""

import pytest

from kairo import navmodel
from kairo.providers.base import AppProvider
from kairo.providers.registry import default_registry


class PretendEmulator(AppProvider):
    id = "pcsx2"
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


def test_providers_are_grouped_as_they_declare(fake_home):
    items = navmodel.build_items(default_registry())
    assert {item.group for item in items} >= {"Library", navmodel.GROUP_MANAGEMENT}


def test_management_destinations_come_last(fake_home):
    items = navmodel.build_items(default_registry())
    assert items[-2].key == navmodel.VIEW_CHANGES
    assert items[-1].key == navmodel.VIEW_SETTINGS


def test_a_future_provider_reaches_the_navigation_unaided(fake_home):
    """No UI file knows what an emulator is; declaring a group is enough."""
    registry = default_registry()
    registry.register(PretendEmulator())
    items = navmodel.build_items(registry)

    emulators = [item for item in items if item.group == "Emulators"]
    assert [item.label for item in emulators] == ["PCSX2"]
    assert items.index(emulators[0]) < items.index(
        next(i for i in items if i.key == navmodel.VIEW_CHANGES))


def test_known_providers_keep_their_icons(fake_home):
    items = {item.key: item for item in navmodel.build_items(default_registry())}
    assert navmodel.icon_for(items["provider:desktop"]) == "grid"
    assert navmodel.icon_for(items[navmodel.VIEW_CHANGES]) == "history"
    assert navmodel.icon_for(items[navmodel.VIEW_SETTINGS]) == "sliders"


def test_a_provider_may_name_its_own_icon():
    class Named(PretendEmulator):
        nav_icon = "chip"

    item = navmodel.NavItem("provider:pcsx2", "PCSX2", "Emulators", Named())
    assert navmodel.icon_for(item) == "chip"


def test_an_unknown_provider_falls_back_by_group():
    item = navmodel.NavItem("provider:x", "X", "Emulators", PretendEmulator())
    assert navmodel.icon_for(item) == "chip"


def test_the_tk_shell_re_exports_the_same_model():
    """Both frontends must agree, so one of them cannot quietly diverge."""
    pytest.importorskip("customtkinter")
    from kairo.ui import nav

    assert nav.build_items is navmodel.build_items
    assert nav.icon_for is navmodel.icon_for
    assert nav.VIEW_CHANGES == navmodel.VIEW_CHANGES
