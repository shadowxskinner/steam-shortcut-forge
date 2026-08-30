"""What the navigation column contains, independent of any toolkit.

Which providers appear, how they are grouped and which icon each one gets are
questions about the application, not about Tk or Qt. Keeping the answers here
means both frontends build the same navigation from the same registry, and a
future provider reaches both of them by declaring ``group`` - without either
shell knowing anything about it.
"""

from __future__ import annotations

from dataclasses import dataclass

VIEW_CHANGES = "view:changes"
VIEW_SETTINGS = "view:settings"

GROUP_MANAGEMENT = "Management"

#: Icons for the destinations that are not providers.
VIEW_ICONS = {VIEW_CHANGES: "history", VIEW_SETTINGS: "sliders"}

#: Icons for providers that shipped before ``nav_icon`` existed. A provider may
#: name its own; anything unrecognised falls back by group, so an emulator
#: provider gets the neutral chip without supplying artwork.
PROVIDER_ICONS = {"steam": "steam", "desktop": "grid"}
GROUP_ICONS = {"Emulators": "chip"}


@dataclass(frozen=True)
class NavItem:
    key: str
    label: str
    group: str
    provider: object | None = None
    subtitle: str = ""


def icon_for(item: NavItem) -> str:
    if item.provider is not None:
        named = getattr(item.provider, "nav_icon", None)
        if named:
            return named
        return PROVIDER_ICONS.get(item.provider.id,
                                  GROUP_ICONS.get(item.group, "chip"))
    return VIEW_ICONS.get(item.key, "chip")


def build_items(registry) -> list[NavItem]:
    """Providers first, grouped as they declare, then the fixed destinations."""
    providers = registry.available() or registry.all()

    groups: dict[str, list] = {}
    for provider in providers:
        groups.setdefault(provider.group, []).append(provider)

    items: list[NavItem] = []
    for group, members in groups.items():
        for provider in sorted(members, key=lambda p: (p.order, p.label)):
            items.append(NavItem(key=f"provider:{provider.id}",
                                 label=provider.label, group=group,
                                 provider=provider))

    items.append(NavItem(key=VIEW_CHANGES, label="Changes",
                         group=GROUP_MANAGEMENT))
    items.append(NavItem(key=VIEW_SETTINGS, label="Settings",
                         group=GROUP_MANAGEMENT))
    return items
