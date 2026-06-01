"""
Extração de metadados do Spotify SEM precisar de credenciais.

Estratégia (a mesma usada por sites tipo spotidownloader): a página de
"embed" do Spotify (open.spotify.com/embed/...) traz um blob JSON
(`__NEXT_DATA__`) com todos os metadados da faixa / álbum / playlist:
nome, artista, duração, capa e — no caso de coleções — a lista de faixas.

Nada de DRM é tocado aqui: só lemos informação pública. O áudio em si é
obtido depois a partir do YouTube (ver downloader.py).
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
    """Erro ao ler metadados do Spotify."""


@dataclass
class Track:
    """Uma faixa a ser baixada."""

    title: str
    artist: str
    album: str = ""
    cover_url: str = ""
    duration_ms: int = 0
    spotify_id: str = ""

    @property
    def search_query(self) -> str:
        """Consulta usada para achar a faixa no YouTube."""
        return f"{self.artist} - {self.title}".strip(" -")

    @property
    def duration_str(self) -> str:
        if not self.duration_ms:
            return ""
        s = self.duration_ms // 1000
        return f"{s // 60}:{s % 60:02d}"


@dataclass
class Collection:
    """Resultado da leitura de um link: 1+ faixas com um título de contexto."""

    kind: str  # track | album | playlist
    name: str
    cover_url: str
    tracks: list[Track] = field(default_factory=list)


# ---------------------------------------------------------------------------


def parse_url(url: str) -> tuple[str, str]:
    """Extrai (kind, id) de uma URL/URI do Spotify."""
    m = _URL_RE.search(url.strip())
    if not m:
        raise SpotifyError("Link do Spotify inválido. Cole um link de faixa, álbum ou playlist.")
    return m.group(1).lower(), m.group(2)


def _fetch_embed_json(kind: str, sid: str) -> dict:
    """Baixa a página de embed e devolve o JSON do __NEXT_DATA__."""
    url = f"https://open.spotify.com/embed/{kind}/{sid}"
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as exc:  # rede / 404
        raise SpotifyError(f"Não consegui acessar o Spotify: {exc}") from exc

    m = _NEXT_DATA_RE.search(resp.text)
    if not m:
        raise SpotifyError("Não achei os metadados na página do Spotify (conteúdo pode ser privado).")
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as exc:
        raise SpotifyError("Metadados do Spotify ilegíveis.") from exc


def _entity(next_data: dict) -> dict:
    try:
        return next_data["props"]["pageProps"]["state"]["data"]["entity"]
    except (KeyError, TypeError) as exc:
        raise SpotifyError("Estrutura de metadados inesperada do Spotify.") from exc


def _cover_from(obj: dict) -> str:
    """Extrai a melhor URL de capa de um entity/item de embed.

    O Spotify usa dois formatos: `coverArt.sources` (antigo) e
    `visualIdentity.image` (atual). Cobrimos ambos.
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
    # fallback: subtitle costuma trazer o artista
    return entity.get("subtitle", "") or ""


def get_collection(url: str) -> Collection:
    """Lê um link do Spotify e devolve a coleção de faixas a baixar."""
    kind, sid = parse_url(url)
    entity = _entity(_fetch_embed_json(kind, sid))

    ctx_name = entity.get("name") or entity.get("title") or "Spotify"
    ctx_cover = _cover_from(entity)

    if kind == "track":
        track = Track(
            title=entity.get("name") or entity.get("title") or "Faixa",
            artist=_artists_from(entity),
            album=(entity.get("album") or {}).get("name", "") if isinstance(entity.get("album"), dict) else "",
            cover_url=ctx_cover,
            duration_ms=int(entity.get("duration") or 0),
            spotify_id=sid,
        )
        return Collection(kind="track", name=track.title, cover_url=ctx_cover, tracks=[track])

    # álbum ou playlist -> trackList
    track_list = entity.get("trackList") or []
    if not track_list:
        raise SpotifyError("Coleção vazia ou privada — não há faixas para baixar.")

    tracks: list[Track] = []
    for item in track_list:
        uri = item.get("uri", "")
        tid = uri.split(":")[-1] if uri else ""
        tracks.append(
            Track(
                title=item.get("title") or "Faixa",
                artist=item.get("subtitle") or "",
                album=ctx_name if kind == "album" else "",
                cover_url=_cover_from(item) or ctx_cover,
                duration_ms=int(item.get("duration") or 0),
                spotify_id=tid,
            )
        )

    return Collection(kind=kind, name=ctx_name, cover_url=ctx_cover, tracks=tracks)
