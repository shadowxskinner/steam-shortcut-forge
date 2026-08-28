"""SteamGridDB — community artwork, keyed on Steam appid.

Genuinely Steam-only: the API is indexed by Steam appid, so it cannot serve an
application that has no Steam presence.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.parse
from pathlib import Path
from typing import Any

from kairo import net, paths
from kairo.artwork.base import ArtworkSource
from kairo.models import Artwork, ArtQuery

SOURCE_ID = "steamgriddb"
API_BASE = "https://www.steamgriddb.com/api/v2"
CONFIG_KEY = "steamgriddb_api_key"

LIST_CACHE_SECONDS = 86400

# A launcher slot is square. Anything wider than this letterboxes into an
# unreadable sliver once scaled down, so it is not offered as an icon.
LOGO_MAX_ASPECT = 2.0


def _fits_as_icon(width: int, height: int) -> bool:
    if not width or not height:
        return True                     # unknown - let the user judge the tile
    return max(width, height) / min(width, height) <= LOGO_MAX_ASPECT


class SteamGridDBSource(ArtworkSource):
    id = SOURCE_ID
    label = "SteamGridDB"

    def __init__(self, api_key: str = ""):
        self.api_key = api_key

    # -- availability ----------------------------------------------------

    def supports(self, provider_id: str) -> bool:
        return provider_id == "steam"

    def available(self, config: dict[str, Any] | None = None) -> bool:
        return bool(self._key(config))

    def unavailable_reason(self, config: dict[str, Any] | None = None) -> str:
        return "Add a free SteamGridDB API key in Settings to browse game artwork."

    def _key(self, config: dict[str, Any] | None = None) -> str:
        if self.api_key:
            return self.api_key
        return (config or {}).get(CONFIG_KEY, "")

    # -- HTTP ------------------------------------------------------------

    def _api_get(self, path: str) -> dict:
        try:
            raw = net.get(f"{API_BASE}{path}",
                          headers={"Authorization": f"Bearer {self.api_key}"})
            return json.loads(raw)
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                raise net.NetworkError("Invalid API key - check Settings.") from exc
            if exc.code == 404:
                return {"data": None}
            if exc.code == 429:
                raise net.NetworkError("Rate-limited. Wait a moment.") from exc
            raise net.NetworkError(f"SteamGridDB HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise net.NetworkError(f"Network error: {exc.reason}") from exc

    # -- lookups ---------------------------------------------------------

    def game_id(self, steam_appid: str) -> int | None:
        """Steam appid to SteamGridDB game id. Cached permanently; it is stable."""
        cache = paths.cache_dir() / f"gameid_{steam_appid}.json"
        if cache.is_file():
            try:
                return json.loads(cache.read_text()).get("game_id")
            except (json.JSONDecodeError, OSError):
                pass
        data = self._api_get(f"/games/steam/{steam_appid}")
        record = data.get("data")
        game_id = record["id"] if record else None
        try:
            paths.cache_dir().mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps({"game_id": game_id}))
        except OSError:
            pass
        return game_id

    def _assets(self, endpoint: str, game_id: int, kind: str) -> list[Artwork]:
        cache = paths.cache_dir() / f"{kind}s_{game_id}.json"
        if cache.is_file():
            try:
                if time.time() - cache.stat().st_mtime < LIST_CACHE_SECONDS:
                    return [Artwork(**d) for d in json.loads(cache.read_text())]
            except (json.JSONDecodeError, OSError, TypeError):
                pass

        raw: list[dict] = []
        page = 0
        while True:
            response = self._api_get(
                f"/{endpoint}/game/{game_id}?types=static&nsfw=false&page={page}")
            batch = response.get("data") or []
            if not batch:
                break
            raw.extend(batch)
            if len(raw) >= response.get("total", 0):
                break
            page += 1

        out: list[Artwork] = []
        for item in raw:
            try:
                width = item.get("width", 0) or 0
                height = item.get("height", 0) or 0
                votes = (item.get("upvotes", 0) or 0) - (item.get("downvotes", 0) or 0)
                style = item.get("style", "") or ""
                out.append(Artwork(
                    id=str(item["id"]),
                    source_id=self.id,
                    label=style,
                    width=width,
                    height=height,
                    score=float(votes),
                    locator=item["url"],
                    mime=item.get("mime", "") or "",
                    kind=kind,
                    official=style.lower() == "official",
                ))
            except (KeyError, TypeError):
                continue

        try:
            paths.cache_dir().mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps([a.__dict__ for a in out]))
        except (OSError, TypeError):
            pass
        return out

    def find(self, query: ArtQuery) -> list[Artwork]:
        """Icons first, then logos square enough to pass as launcher icons.

        Icons alone are often only a handful per game, so logos supply the
        rest - but icons always outrank them, so auto-assign never picks a
        wordmark while a real icon exists.
        """
        if not query.steam_appid:
            return []
        game_id = self.game_id(query.steam_appid)
        if game_id is None:
            return []

        assets = self._assets("icons", game_id, "icon")
        try:
            logos = self._assets("logos", game_id, "logo")
            assets += [lg for lg in logos if _fits_as_icon(lg.width, lg.height)]
        except net.NetworkError:
            pass            # logos are a bonus; never fail the lookup over them

        assets.sort(key=lambda a: (a.kind == "icon", a.score, a.width * a.height),
                    reverse=True)
        return assets

    # -- transfer --------------------------------------------------------

    def preview(self, art: Artwork) -> bytes:
        digest = hashlib.md5(art.locator.encode()).hexdigest()
        cache = paths.cache_dir() / f"preview_{digest}"
        if cache.is_file():
            return cache.read_bytes()
        data = net.get(art.locator, timeout=20)
        try:
            paths.cache_dir().mkdir(parents=True, exist_ok=True)
            cache.write_bytes(data)
        except OSError:
            pass
        return data

    def fetch(self, art: Artwork, dest_dir: Path, stem: str) -> Path:
        ext = Path(urllib.parse.urlparse(art.locator).path).suffix.lower()
        if ext not in {".ico", ".png", ".svg", ".xpm"}:
            ext = ".png"
        dest = dest_dir / f"{stem}{ext}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(net.get(art.locator, timeout=30))
        return dest
