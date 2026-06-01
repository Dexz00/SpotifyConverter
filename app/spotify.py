"""
Fetch Spotify metadata WITHOUT requiring API credentials.

Strategy (the same one used by sites like spotidownloader): the Spotify
"embed" page (open.spotify.com/embed/...) ships a JSON blob (`__NEXT_DATA__`)
with all the metadata for a track / album / playlist: name, artist, duration,
cover art and — for collections — the track list.

No DRM is touched here: we only read public information. The audio itself is
later obtained from YouTube (see downloader.py).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Optional

import requests

# ---------------------------------------------------------------------------

_URL_RE = re.compile(
    r"(?:open\.spotify\.com/(?:intl-[a-z]{2}/)?|spotify:)"
    r"(track|album|playlist)[/:]([A-Za-z0-9]+)",
    re.IGNORECASE,
)
_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
    re.DOTALL,
)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
    ),
    "Accept-Language": "en",
}


class SpotifyError(Exception):
    """Raised when reading Spotify metadata fails."""


@dataclass
class Track:
    """A single track to download."""

    title: str
    artist: str
    album: str = ""
    cover_url: str = ""
    duration_ms: int = 0
    spotify_id: str = ""

    @property
    def search_query(self) -> str:
        """Query used to find the track on YouTube."""
        return f"{self.artist} - {self.title}".strip(" -")

    @property
    def duration_str(self) -> str:
        if not self.duration_ms:
            return ""
        s = self.duration_ms // 1000
        return f"{s // 60}:{s % 60:02d}"


@dataclass
class Collection:
    """Result of reading a link: one or more tracks with a context title."""

    kind: str  # track | album | playlist
    name: str
    cover_url: str
    tracks: list[Track] = field(default_factory=list)


# ---------------------------------------------------------------------------


def parse_url(url: str) -> tuple[str, str]:
    """Extract (kind, id) from a Spotify URL/URI."""
    m = _URL_RE.search(url.strip())
    if not m:
        raise SpotifyError("Invalid Spotify link. Paste a track, album or playlist link.")
    return m.group(1).lower(), m.group(2)


def _fetch_embed_json(kind: str, sid: str) -> dict:
    """Download the embed page and return the __NEXT_DATA__ JSON."""
    url = f"https://open.spotify.com/embed/{kind}/{sid}"
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as exc:  # network / 404
        raise SpotifyError(f"Could not reach Spotify: {exc}") from exc

    m = _NEXT_DATA_RE.search(resp.text)
    if not m:
        raise SpotifyError("Could not find metadata on the Spotify page (content may be private).")
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as exc:
        raise SpotifyError("Unreadable Spotify metadata.") from exc


def _entity(next_data: dict) -> dict:
    try:
        return next_data["props"]["pageProps"]["state"]["data"]["entity"]
    except (KeyError, TypeError) as exc:
        raise SpotifyError("Unexpected Spotify metadata structure.") from exc


def _cover_from(obj: dict) -> str:
    """Extract the best cover URL from an embed entity/item.

    Spotify uses two shapes: `coverArt.sources` (legacy) and
    `visualIdentity.image` (current). We handle both.
    """
    if not isinstance(obj, dict):
        return ""
    sources = (obj.get("coverArt") or {}).get("sources") or []
    if sources:
        best = max(sources, key=lambda s: (s.get("width") or 0) * (s.get("height") or 0))
        if best.get("url"):
            return best["url"]
    images = (obj.get("visualIdentity") or {}).get("image") or []
    if images:
        best = max(images, key=lambda s: (s.get("maxWidth") or 0) * (s.get("maxHeight") or 0))
        if best.get("url"):
            return best["url"]
    return ""


def _artists_from(entity: dict) -> str:
    artists = entity.get("artists") or []
    names = [a.get("name", "") for a in artists if a.get("name")]
    if names:
        return ", ".join(names)
    # fallback: subtitle usually holds the artist
    return entity.get("subtitle", "") or ""


def get_collection(url: str) -> Collection:
    """Read a Spotify link and return the collection of tracks to download."""
    kind, sid = parse_url(url)
    entity = _entity(_fetch_embed_json(kind, sid))

    ctx_name = entity.get("name") or entity.get("title") or "Spotify"
    ctx_cover = _cover_from(entity)

    if kind == "track":
        track = Track(
            title=entity.get("name") or entity.get("title") or "Track",
            artist=_artists_from(entity),
            album=(entity.get("album") or {}).get("name", "") if isinstance(entity.get("album"), dict) else "",
            cover_url=ctx_cover,
            duration_ms=int(entity.get("duration") or 0),
            spotify_id=sid,
        )
        return Collection(kind="track", name=track.title, cover_url=ctx_cover, tracks=[track])

    # album or playlist -> trackList
    track_list = entity.get("trackList") or []
    if not track_list:
        raise SpotifyError("Empty or private collection — no tracks to download.")

    tracks: list[Track] = []
    for item in track_list:
        uri = item.get("uri", "")
        tid = uri.split(":")[-1] if uri else ""
        tracks.append(
            Track(
                title=item.get("title") or "Track",
                artist=item.get("subtitle") or "",
                album=ctx_name if kind == "album" else "",
                cover_url=_cover_from(item) or ctx_cover,
                duration_ms=int(item.get("duration") or 0),
                spotify_id=tid,
            )
        )

    return Collection(kind=kind, name=ctx_name, cover_url=ctx_cover, tracks=tracks)
