"""
Motor de download: acha a faixa no YouTube, baixa o melhor áudio com yt-dlp,
converte pra MP3 com ffmpeg e grava as tags ID3 (título/artista/álbum) + capa.
"""
from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import requests
import yt_dlp
from mutagen.id3 import APIC, ID3, TALB, TCON, TIT2, TPE1, error as id3_error
from mutagen.mp3 import MP3

from .spotify import Track

ProgressCb = Callable[[float, str], None]  # (porcentagem 0-100, mensagem)


def find_ffmpeg() -> Optional[str]:
    """Localiza o ffmpeg: no PATH ou na pasta ./bin do projeto."""
    exe = shutil.which("ffmpeg")
    if exe:
        return os.path.dirname(exe)
    local = Path(__file__).resolve().parent.parent / "bin"
    candidate = local / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    if candidate.exists():
        return str(local)
    return None


def _sanitize(name: str) -> str:
    """Remove caracteres inválidos para nome de arquivo no Windows."""
    name = re.sub(r'[<>:"/\\|?*]', "", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name[:180] or "faixa"


# Palavras que indicam que o vídeo NÃO é a faixa de áudio limpa.
_BAD_WORDS = re.compile(
    r"\b(video|videoclipe|clipe|ao vivo|live|en vivo|cover|reaction|react|"
    r"sped up|slowed|nightcore|8d|karaoke|instrumental|tutorial|reverb|mashup)\b",
    re.IGNORECASE,
)
# Sinais de que É a faixa de áudio oficial.
_GOOD_WORDS = re.compile(r"(official audio|audio oficial|\baudio\b|provided to youtube)", re.IGNORECASE)


def _score_candidate(entry: dict, track: Track) -> float:
    """Pontua um resultado do YouTube: quanto maior, melhor.

    Sinais: proximidade da duração com a do Spotify (o mais forte — clipes
    costumam ser mais longos por causa de intro/outro), canal '- Topic'
    (áudio auto-gerado pela gravadora) e presença/ausência de palavras-chave.
    """
    score = 0.0
    title = entry.get("title") or ""
    uploader = entry.get("uploader") or entry.get("channel") or ""

    # 1) Duração — sinal mais confiável.
    yt_dur = entry.get("duration")  # segundos
    if yt_dur and track.duration_ms:
        diff = abs(yt_dur - track.duration_ms / 1000)
        if diff <= 2:
            score += 100
        elif diff <= 5:
            score += 60
        elif diff <= 10:
            score += 20
        else:
            score -= diff  # quanto mais longe, pior (clipes com intro/outro)

    # 2) Canal de áudio oficial.
    if uploader.endswith("- Topic") or uploader.endswith("- Tópico"):
        score += 50
    # Canal do próprio artista (re-uploads de terceiros pontuam menos).
    first_artist = track.artist.split(",")[0].strip().lower()
    if first_artist and first_artist in uploader.lower():
        score += 35
    if _GOOD_WORDS.search(title):
        score += 15

    # 3) Penaliza versões alternativas (a não ser que a própria faixa peça).
    spotify_title = track.title.lower()
    for m in _BAD_WORDS.finditer(title):
        if m.group(0).lower() not in spotify_title:
            score -= 40

    # 4) Leve preferência por mais views (popularidade -> versão certa).
    views = entry.get("view_count") or 0
    if views:
        score += min(views / 1_000_000, 10)

    return score


def _pick_best(entries: list[dict], track: Track) -> Optional[dict]:
    cands = [e for e in entries if e and e.get("id")]
    if not cands:
        return None
    return max(cands, key=lambda e: _score_candidate(e, track))


@dataclass
class DownloadResult:
    path: Path
    title: str
    artist: str


class Downloader:
    def __init__(self, out_dir: Path, bitrate: str = "320"):
        self.out_dir = out_dir
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.bitrate = bitrate
        self.ffmpeg_dir = find_ffmpeg()
        if not self.ffmpeg_dir:
            raise RuntimeError(
                "ffmpeg não encontrado. Rode setup_ffmpeg.py ou instale o ffmpeg no PATH."
            )

    def download_track(self, track: Track, progress: ProgressCb) -> DownloadResult:
        filename = _sanitize(f"{track.artist} - {track.title}")
        target = self.out_dir / f"{filename}.mp3"

        if target.exists():
            progress(100.0, "Já baixado")
            return DownloadResult(path=target, title=track.title, artist=track.artist)

        def hook(d: dict) -> None:
            if d.get("status") == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                done = d.get("downloaded_bytes") or 0
                pct = (done / total * 90.0) if total else 0.0
                progress(pct, "Baixando áudio…")
            elif d.get("status") == "finished":
                progress(92.0, "Convertendo para MP3…")

        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": str(self.out_dir / f"{filename}.%(ext)s"),
            "ffmpeg_location": self.ffmpeg_dir,
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": self.bitrate,
                }
            ],
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "default_search": "ytsearch",
            "progress_hooks": [hook],
        }

        progress(2.0, "Procurando a melhor versão no YouTube…")
        try:
            # 1) Busca vários candidatos (sem baixar) e escolhe a faixa de áudio
            #    certa pela duração + tipo de canal — evita pegar o videoclipe.
            with yt_dlp.YoutubeDL(
                {"quiet": True, "no_warnings": True, "extract_flat": False, "skip_download": True}
            ) as probe:
                search = probe.extract_info(
                    f"ytsearch6:{track.search_query}", download=False
                )
            entries = (search or {}).get("entries") or []
            best = _pick_best(entries, track)

            progress(5.0, "Baixando áudio…")
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                if best:
                    ydl.process_ie_result(best, download=True)
                else:
                    # fallback: sem candidatos avaliáveis, baixa o 1º resultado
                    ydl.extract_info(f"ytsearch1:{track.search_query} audio", download=True)
        except yt_dlp.utils.DownloadError as exc:
            raise RuntimeError(f"Falha ao baixar '{track.search_query}': {exc}") from exc

        if not target.exists():
            # fallback: acha o mp3 recém-criado com esse prefixo
            matches = list(self.out_dir.glob(f"{filename}.mp3"))
            if not matches:
                raise RuntimeError(f"Conversão falhou para '{track.search_query}'.")
            target = matches[0]

        progress(96.0, "Gravando tags e capa…")
        self._tag(target, track)
        progress(100.0, "Concluído")
        return DownloadResult(path=target, title=track.title, artist=track.artist)

    def _tag(self, mp3_path: Path, track: Track) -> None:
        """Escreve tags ID3 e embute a capa do álbum."""
        try:
            audio = MP3(mp3_path, ID3=ID3)
            if audio.tags is None:
                audio.add_tags()
            tags = audio.tags
            tags.add(TIT2(encoding=3, text=track.title))
            tags.add(TPE1(encoding=3, text=track.artist))
            if track.album:
                tags.add(TALB(encoding=3, text=track.album))

            if track.cover_url:
                try:
                    img = requests.get(track.cover_url, timeout=15)
                    if img.ok:
                        mime = img.headers.get("Content-Type", "image/jpeg")
                        tags.add(
                            APIC(
                                encoding=3,
                                mime=mime,
                                type=3,  # front cover
                                desc="Cover",
                                data=img.content,
                            )
                        )
                except requests.RequestException:
                    pass  # capa é opcional

            audio.save(v2_version=3)
        except id3_error:
            pass  # tags são best-effort; o mp3 já está pronto
