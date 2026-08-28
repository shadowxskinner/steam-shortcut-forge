"""Iconify — ~275,000 open source icons, no account and no API key.

Searchable by name, which is what makes it usable for arbitrary applications.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.parse
from pathlib import Path

from kairo import net, paths
from kairo.artwork.base import ArtworkSource
from kairo.models import CONFIDENCE_EXACT_SEARCH, Artwork, ArtQuery, Suggestion

SOURCE_ID = "iconify"

#: Mirrors, tried in order on timeout.
HOSTS = (
    "https://api.iconify.design",
    "https://api.simplesvg.com",
    "https://api.unisvg.com",
)

CACHE_SECONDS = 86400
RENDER_HEIGHT = 256


class IconifySource(ArtworkSource):
    id = SOURCE_ID
    label = "Iconify"
    needs_query = True
    query_label = "Iconify search"
    query_placeholder = "gamepad, browser, terminal..."

    def supports(self, provider_id: str) -> bool:
        # Every provider, including Steam: Iconify covers games SteamGridDB
        # does not index, and is the only keyless source for them.
        return True

    # -- HTTP ------------------------------------------------------------

    def _get(self, path: str, timeout: int = 15) -> bytes:
        last: Exception | None = None
        for host in HOSTS:
            try:
                return net.get(f"{host}{path}", timeout=timeout)
            except urllib.error.HTTPError as exc:
                raise net.NetworkError(f"Iconify HTTP {exc.code}") from exc
            except (TimeoutError, urllib.error.URLError) as exc:
                last = exc
                continue
        raise net.NetworkError(f"Iconify network error: {last}")

    @staticmethod
    def _svg_path(prefix: str, name: str) -> str:
        return (f"/{urllib.parse.quote(prefix, safe='')}"
                f"/{urllib.parse.quote(name, safe='')}.svg"
                f"?height={RENDER_HEIGHT}&color=%23ffffff")

    # -- search ----------------------------------------------------------

    def find(self, query: ArtQuery) -> list[Artwork]:
        term = (query.text or "").strip()
        if not term:
            return []
        results = self._search(term)
        if not results and query.fallback_text:
            results = self._search(query.fallback_text)
        return results

    def _search(self, term: str, limit: int = 64) -> list[Artwork]:
        limit = max(32, min(int(limit), 999))
        params = urllib.parse.urlencode({"query": term, "limit": limit})
        data = json.loads(self._get(f"/search?{params}"))
        collections = data.get("collections") or {}

        out: list[Artwork] = []
        for full_name in data.get("icons") or []:
            if ":" not in full_name:
                continue
            prefix, name = full_name.split(":", 1)
            collection = collections.get(prefix) or {}
            path = self._svg_path(prefix, name)
            out.append(Artwork(
                id=f"iconify_{hashlib.md5(full_name.encode()).hexdigest()[:12]}",
                source_id=self.id,
                name=name,
                label=collection.get("name") or prefix,
                width=RENDER_HEIGHT,
                height=RENDER_HEIGHT,
                locator=f"{HOSTS[0]}{path}",
                mime="image/svg+xml",
                kind="icon",
            ))
        return out

    def best_match(self, query: ArtQuery) -> Suggestion | None:
        """Only when an icon set contains this exact name.

        Iconify search is a relevance ranking over 275,000 icons, so its top
        result is often merely thematically related - searching "steam" returns
        locomotives. Requiring the icon's own name to equal the search term
        turns a fuzzy source into one that can say "yes, this set has an icon
        called firefox" and nothing weaker.
        """
        for term in (query.text, query.fallback_text):
            term = (term or "").strip().lower()
            if not term:
                continue
            try:
                results = self._search(term)
            except Exception:
                return None
            for art in results:
                if art.name.lower() == term:
                    return Suggestion(art, CONFIDENCE_EXACT_SEARCH,
                                      f"'{term}' in {art.label}")
        return None

    # -- transfer --------------------------------------------------------

    def _svg(self, url: str) -> bytes:
        digest = hashlib.md5(url.encode()).hexdigest()
        cache = paths.cache_dir() / f"iconify_{digest}.svg"
        if cache.is_file():
            try:
                if time.time() - cache.stat().st_mtime < CACHE_SECONDS:
                    return cache.read_bytes()
            except OSError:
                pass
        parsed = urllib.parse.urlparse(url)
        path = f"{parsed.path}?{parsed.query}" if parsed.query else parsed.path
        data = self._get(path)
        try:
            paths.cache_dir().mkdir(parents=True, exist_ok=True)
            cache.write_bytes(data)
        except OSError:
            pass
        return data

    def preview(self, art: Artwork) -> bytes:
        return self._svg(art.locator)

    def fetch(self, art: Artwork, dest_dir: Path, stem: str) -> Path:
        dest = dest_dir / f"{stem}.svg"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(self._svg(art.locator))
        return dest
