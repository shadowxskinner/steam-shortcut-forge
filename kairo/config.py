"""User configuration — a single JSON file."""

from __future__ import annotations

import json
from typing import Any

from kairo import paths
from kairo.desktop.entry import atomic_write_text


def load() -> dict[str, Any]:
    path = paths.config_file()
    if path.is_file():
        try:
            data = json.loads(path.read_text())
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save(cfg: dict[str, Any]) -> None:
    atomic_write_text(paths.config_file(), json.dumps(cfg, indent=2) + "\n")
