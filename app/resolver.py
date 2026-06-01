"""
Resolve um link do Spotify numa Collection, escolhendo a melhor fonte:

  • Se houver credenciais (SPOTIFY_CLIENT_ID/SECRET) -> Web API oficial
    (playlists/álbuns completos, metadados ricos).
  • Caso contrário -> scraping da página de embed (sem cadastro).

Se a API oficial falhar por algum motivo, ainda tentamos o embed como rede
de segurança.
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
            # cai pro embed se a API recusar (ex.: playlist privada do usuário)
            pass
    return _embed_collection(url)
