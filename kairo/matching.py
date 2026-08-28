"""Working out what artwork each application should get, without applying it.

Matching is deliberately separate from applying. Scanning and matching read
the machine and the network; they never write a ``.desktop`` file. The user
sees what Kairo proposes and decides.

    Scan  ->  Match  ->  Review  ->  Apply

**Confidence, not enthusiasm.** Every source that participates in automatic
matching has to say how sure it is, and anything below
``AUTO_APPLY_THRESHOLD`` leaves the application unmatched. Applying
questionable artwork automatically is worse than applying none: a wrong icon
that arrives silently has to be noticed before it can be undone, and a tool
that occasionally puts the Dolphin emulator's logo on the file manager is one
the user stops trusting with the bulk button. "No match" is a perfectly good
answer, and the review screen shows those applications as unmatched so the
user can search manually.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from kairo.models import AUTO_APPLY_THRESHOLD, AppEntry, Artwork, Suggestion
from kairo.tasks import BulkSummary, CancelToken, Skip, run_bulk


@dataclass(frozen=True)
class Match:
    """One application and the artwork Kairo proposes for it."""

    entry: AppEntry
    suggestion: Suggestion
    source_id: str
    source_label: str = ""

    @property
    def artwork(self) -> Artwork:
        return self.suggestion.artwork

    @property
    def confidence(self) -> float:
        return self.suggestion.confidence

    @property
    def reason(self) -> str:
        return self.suggestion.reason

    @property
    def confident(self) -> bool:
        return self.suggestion.confident


@dataclass
class MatchReport:
    scanned: int = 0
    matches: list[Match] = field(default_factory=list)
    unmatched: list[AppEntry] = field(default_factory=list)
    cancelled: bool = False
    failures: list[str] = field(default_factory=list)

    @property
    def matched(self) -> int:
        return len(self.matches)

    def headline(self) -> str:
        """The line that should tell a user why Kairo is worth having open."""
        apps = "application" if self.scanned == 1 else "applications"
        return (f"{self.scanned} {apps} discovered  ·  "
                f"{self.matched} artwork matches found")

    def by_key(self) -> dict[str, Match]:
        return {m.entry.key: m for m in self.matches}


class Matcher:
    """Finds the best confident artwork for an application.

    Consults the sources in the order the *provider* declares, stopping at the
    first confident answer. For Steam that is SteamGridDB first, because it
    matches on the actual Steam app ID and so cannot have found the wrong
    game; installed themes and Iconify follow as fallbacks for titles it does
    not index and for users with no API key.
    """

    def __init__(self, providers, sources, config: dict[str, Any] | None = None,
                 threshold: float = AUTO_APPLY_THRESHOLD):
        self.providers = providers
        self.sources = sources
        self.config = config or {}
        self.threshold = threshold

    def chain_for(self, entry: AppEntry):
        provider = self.providers.for_entry(entry)
        if provider is None:
            return []
        return self.sources.auto_match_chain(provider, self.config)

    def match_entry(self, entry: AppEntry,
                    token: CancelToken | None = None) -> Match | None:
        """The first confident suggestion, or None. Writes nothing."""
        provider = self.providers.for_entry(entry)
        if provider is None:
            return None
        query = provider.artwork_query(entry)

        for source in self.sources.auto_match_chain(provider, self.config):
            if token is not None:
                token.check()
            try:
                suggestion = source.best_match(query)
            except Exception:
                # A source being down must not cost the application its
                # chance at a match from the next one in the chain.
                continue
            if suggestion is None:
                continue
            if suggestion.confidence >= self.threshold:
                return Match(entry=entry, suggestion=suggestion,
                             source_id=source.id, source_label=source.label)
        return None

    def match_all(
        self,
        entries: Iterable[AppEntry],
        *,
        token: CancelToken | None = None,
        include_customized: bool = False,
        on_progress: Callable[[int, int, AppEntry], None] | None = None,
    ) -> MatchReport:
        """Match a whole library. Reads only."""
        entries = [e for e in entries if include_customized or not e.customized]
        report = MatchReport(scanned=len(entries))

        def work(entry: AppEntry) -> None:
            match = self.match_entry(entry, token=token)
            if match is None:
                report.unmatched.append(entry)
                raise Skip("no confident artwork match")
            report.matches.append(match)

        summary: BulkSummary = run_bulk(
            entries, work, token=token,
            label=lambda e: e.name, on_progress=on_progress)

        report.cancelled = summary.cancelled
        report.failures = summary.failures
        return report
