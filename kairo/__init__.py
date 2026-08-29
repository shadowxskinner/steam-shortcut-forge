"""Kairo — automatic launcher artwork for Linux.

Kairo finds the applications installed on a machine, finds artwork for them,
and applies it to the desktop launcher. Steam is the most complete integration,
not the identity: anything that ships a freedesktop ``.desktop`` entry is in
scope, which already covers native packages, Flatpaks and AppImages.
"""

from __future__ import annotations

#: The single source of truth for the version. pyproject reads it from here,
#: and release.sh checks it rather than maintaining a copy.
__version__ = "2.3.2"

#: Public product name. No suffix, no qualifier.
APP_NAME = "Kairo"

TAGLINE = "Automatic launcher artwork for Linux"

#: Reverse-DNS application id. Matches the GitHub owner so it is verifiable on
#: Flathub without owning a domain. Fixed now rather than later because it is
#: baked into the .desktop filename, the icon name and the D-Bus name, and
#: changing it after publication is painful.
APP_ID = "io.github.shadowxskinner.Kairo"
