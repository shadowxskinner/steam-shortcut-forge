"""Minimal HTTP helpers shared by the online artwork sources."""

from __future__ import annotations

import urllib.error
import urllib.request

from kairo import __version__

USER_AGENT = f"Kairo/{__version__}"


class NetworkError(RuntimeError):
    """A user-facing network failure."""


def get(url: str, *, headers: dict[str, str] | None = None, timeout: int = 15) -> bytes:
    request = urllib.request.Request(url)
    request.add_header("User-Agent", USER_AGENT)
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()
