"""The set of providers this build knows about."""

from __future__ import annotations

from kairo.models import AppEntry
from kairo.providers.base import AppProvider
from kairo.providers.desktop_entry import DesktopEntryProvider
from kairo.providers.emulator import providers_from_config
from kairo.providers.steam import SteamProvider


class ProviderRegistry:
    def __init__(self, providers: list[AppProvider] | None = None):
        self._providers: list[AppProvider] = list(providers or [])

    def register(self, provider: AppProvider) -> None:
        self._providers.append(provider)

    def all(self) -> list[AppProvider]:
        return list(self._providers)

    def available(self) -> list[AppProvider]:
        """Providers with something to offer on this machine.

        A machine with no Steam install simply does not show a Steam section,
        rather than showing an empty one.
        """
        return [p for p in self._providers if p.available()]

    def get(self, provider_id: str) -> AppProvider | None:
        for provider in self._providers:
            if provider.id == provider_id:
                return provider
        return None

    def for_entry(self, entry: AppEntry) -> AppProvider | None:
        return self.get(entry.provider_id)


def default_registry(config: dict | None = None) -> ProviderRegistry:
    """Adding a provider is one import and one line here.

    Emulators are the exception: there is no EmulatorProvider class to add,
    because each configured emulator becomes its own provider. They come last
    so Steam and Applications keep their positions, and the sidebar groups
    them under Emulators without this file saying so.
    """
    return ProviderRegistry([SteamProvider(), DesktopEntryProvider(),
                             *providers_from_config(config)])
