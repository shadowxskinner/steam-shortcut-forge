"""The set of providers this build knows about."""

from __future__ import annotations

from kairo.models import AppEntry
from kairo.providers.base import AppProvider
from kairo.providers.desktop_entry import DesktopEntryProvider
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


def default_registry() -> ProviderRegistry:
    """Adding a provider is one import and one line here."""
    return ProviderRegistry([SteamProvider(), DesktopEntryProvider()])
