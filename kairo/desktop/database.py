"""Telling the desktop that the launcher directory changed."""

from __future__ import annotations

import shutil
import subprocess

from kairo import paths


def refresh() -> None:
    """Re-index ~/.local/share/applications so changes appear immediately.

    Best effort: the desktop picks the change up on its own eventually, and
    the binary is absent on some minimal installs. Never fail an apply over it.
    """
    binary = shutil.which("update-desktop-database")
    if not binary:
        return
    try:
        subprocess.run([binary, str(paths.applications_dir())],
                       capture_output=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        pass
