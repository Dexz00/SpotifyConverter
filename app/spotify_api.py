"""
Cliente OPCIONAL da Web API oficial do Spotify (Client Credentials).

Quando o usuário fornece SPOTIFY_CLIENT_ID e SPOTIFY_CLIENT_SECRET, usamos
a API oficial — que pagina playlists/álbuns inteiros e traz metadados mais
ricos (capa por faixa, álbum correto, número da faixa). Sem credenciais, o
projeto cai no scraping da página de embed (ver spotify.py).

Como obter credenciais (grátis):
  1. https://developer.spotify.com/dashboard  ->  Create app
  2. Copie o Client ID e o Client Secret
  3. Coloque no arquivo .env (veja .env.example)
"""
from __future__ import annotations

import base64
import os
import time
from typing import Optional

import requests

from .spotify import Collection, SpotifyError, Track, parse_url

_TOKEN_URL = "https://accounts.spotify.com/api/token"
_API = "https://api.spotify.com/v1"


def credentials() -> Optional[tuple[str, str]]:
    """Devolve (client_id, client_secret) se ambos estiverem no ambiente."""
    cid = os.getenv("SPOTIFY_CLIENT_ID", "").strip()
    secret = os.getenv("SPOTIFY_CLIENT_SECRET", "").strip()
    if cid and secret:
        return cid, secret
    return None


class SpotifyAPI:
    """Cliente mínimo de leitura usando o fluxo Client Credentials."""

    def __init__(self, client_id: str, client_secret: str):
        self._id = client_id
        self._secret = client_secret
        self._token = ""
        self._expires_at = 0.0

    # ------------------------------------------------------------------ auth
    def _get_token(self, now: float) -> str:
        if self._token and now < self._expires_at - 30:
            return self._token
        auth = base64.b64encode(f"{self._id}:{self._secret}".encode()).decode()
        resp = requests.post(
            _TOKEN_URL,
            data={"grant_type": "client_credentials"},
            headers={"Authorization": f"Basic {auth}"},
            timeout=20,
        )
        if resp.status_code != 200:
            raise SpotifyError(
                "Credenciais do Spotify inválidas (confira CLIENT_ID/SECRET no .env)."
            )
        data = resp.json()
        self._token = data["access_token"]
        self._expires_at = now + int(data.get("expires_in", 3600))
        return self._token

    def _get(self, path: str, params: Optional[dict] = None) -> dict:
        token = self._get_token(time.time())
        resp = requests.get(
            f"{_API}{path}",
            headers={"Authorization": f"Bearer {token}"},
            params=params or {},
            timeout=20,
        )
        if resp.status_code == 404:
            raise SpotifyError("Conteúdo não encontrado (link errado ou privado).")
        if resp.status_code != 200:
            raise SpotifyError(f"Erro da API do Spotify ({resp.status_code}).")
        return resp.json()

    # --------------------------------------------------------------- helpers
    @staticmethod
    def _artists(obj: dict) -> str:
        return ", ".join(a.get("name", "") for a in obj.get("artists", []) if a.get("name"))

    @staticmethod
    def _cover(images: list[dict]) -> str:
        if not images:
            return ""
        best = max(images, key=lambda im: (im.get("width") or 0) * (im.get("height") or 0))
        return best.get("url", "")

    def _track_from(self, t: dict, album: Optional[dict] = None) -> Track:
        album = album or t.get("album") or {}
        return Track(
            title=t.get("name", "Faixa"),
            artist=self._artists(t),
            album=album.get("name", ""),
            cover_url=self._cover(album.get("images", [])),
            duration_ms=int(t.get("duration_ms") or 0),
            spotify_id=t.get("id", ""),
        )

    # ----------------------------------------------------------- coleções
    def get_collection(self, url: str) -> Collection:
        kind, sid = parse_url(url)

        if kind == "track":
            t = self._get(f"/tracks/{sid}")
            track = self._track_from(t)
            return Collection("track", track.title, track.cover_url, [track])

        if kind == "album":
            album = self._get(f"/albums/{sid}")
            cover = self._cover(album.get("images", []))
            tracks: list[Track] = []
            page = album.get("tracks", {})
            while True:
                for t in page.get("items", []):
                    track = self._track_from(t, album)
                    track.cover_url = track.cover_url or cover
                    tracks.append(track)
                nxt = page.get("next")
                if not nxt:
                    break
                page = self._get(nxt.replace(_API, ""))
            return Collection("album", album.get("name", "Álbum"), cover, tracks)

        # playlist
        pl = self._get(f"/playlists/{sid}")
        cover = self._cover(pl.get("images", []))
        tracks = []
        page = pl.get("tracks", {})
        while True:
            for item in page.get("items", []):
                t = item.get("track")
                if t and t.get("type") == "track":
                    tracks.append(self._track_from(t))
            nxt = page.get("next")
            if not nxt:
                break
            page = self._get(nxt.replace(_API, ""))
        return Collection("playlist", pl.get("name", "Playlist"), cover, tracks)
