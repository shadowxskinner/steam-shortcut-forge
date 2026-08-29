"""Shared state handed to each pane, so panes need no reference to the shell."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from kairo.ledger import Ledger
from kairo.tasks import ActivityTokens


@dataclass
class UIContext:
    providers: Any
    sources: Any
    config: dict
    ledger: Ledger
    tokens: ActivityTokens
    #: Called when a pane changes something the rest of the window shows.
    on_changed: Callable[[], None] = lambda: None
    #: Called to put a line in the shell's status bar.
    set_status: Callable[[str], None] = lambda _text: None
