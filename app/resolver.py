"""
Resolve a Spotify link into a Collection, choosing the best source:

  • If credentials are present (SPOTIFY_CLIENT_ID/SECRET) -> official Web API
    (full playlists/albums, richer metadata).
  • Otherwise -> embed-page scraping (no sign-up).

If the official API fails for some reason, we still fall back to the embed as a
safety net.
"""
from __future__ import annotations

from .spotify import Collection, SpotifyError
from .spotify import get_collection as _embed_collection
from .spotify_api import SpotifyAPI, credentials

_api_client: SpotifyAPI | None = None


def using_official_api() -> bool:
    return credentials() is not None


def _client() -> SpotifyAPI | None:
    global _api_client
    creds = credentials()
    if not creds:
        return None
    if _api_client is None:
        _api_client = SpotifyAPI(*creds)
    return _api_client


def resolve(url: str) -> Collection:
    client = _client()
    if client is not None:
        try:
            return client.get_collection(url)
        except SpotifyError:
            # fall back to the embed if the API refuses (e.g. a private playlist)
            pass
    return _embed_collection(url)
