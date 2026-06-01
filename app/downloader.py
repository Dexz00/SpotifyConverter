"""
Download engine: finds the track on YouTube, downloads the best audio with
yt-dlp, converts it to MP3 with ffmpeg and writes ID3 tags (title/artist/album)
plus the album cover.
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

ProgressCb = Callable[[float, str], None]  # (percent 0-100, message)


def find_ffmpeg() -> Optional[str]:
    """Locate ffmpeg: on PATH or in the project's ./bin folder."""
    exe = shutil.which("ffmpeg")
    if exe:
        return os.path.dirname(exe)
    local = Path(__file__).resolve().parent.parent / "bin"
    candidate = local / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    if candidate.exists():
        return str(local)
    return None


def _sanitize(name: str) -> str:
    """Strip characters that are invalid in Windows filenames."""
    name = re.sub(r'[<>:"/\\|?*]', "", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name[:180] or "track"


# Words that signal the video is NOT the clean audio track.
_BAD_WORDS = re.compile(
    r"\b(video|videoclip|clip|live|en vivo|cover|reaction|react|"
    r"sped up|slowed|nightcore|8d|karaoke|instrumental|tutorial|reverb|mashup)\b",
    re.IGNORECASE,
)
# Signals that this IS the official audio track.
_GOOD_WORDS = re.compile(r"(official audio|\baudio\b|provided to youtube)", re.IGNORECASE)


def _score_candidate(entry: dict, track: Track) -> float:
    """Score a YouTube result: higher is better.

    Signals: how close the duration is to Spotify's (the strongest one — music
    videos tend to be longer because of intros/outros), a '- Topic' channel
    (label-provided auto-generated audio) and the presence/absence of keywords.
    """
    score = 0.0
    title = entry.get("title") or ""
    uploader = entry.get("uploader") or entry.get("channel") or ""

    # 1) Duration — most reliable signal.
    yt_dur = entry.get("duration")  # seconds
    if yt_dur and track.duration_ms:
        diff = abs(yt_dur - track.duration_ms / 1000)
        if diff <= 2:
            score += 100
        elif diff <= 5:
            score += 60
        elif diff <= 10:
            score += 20
        else:
            score -= diff  # the further off, the worse (clips with intro/outro)

    # 2) Official audio channel.
    if uploader.endswith("- Topic"):
        score += 50
    # The artist's own channel (third-party re-uploads score lower).
    first_artist = track.artist.split(",")[0].strip().lower()
    if first_artist and first_artist in uploader.lower():
        score += 35
    if _GOOD_WORDS.search(title):
        score += 15

    # 3) Penalize alternate versions (unless the track itself asks for it).
    spotify_title = track.title.lower()
    for m in _BAD_WORDS.finditer(title):
        if m.group(0).lower() not in spotify_title:
            score -= 40

    # 4) Slight preference for more views (popularity -> the right version).
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
                "ffmpeg not found. Run setup_ffmpeg.py or install ffmpeg on your PATH."
            )

    def download_track(self, track: Track, progress: ProgressCb) -> DownloadResult:
        filename = _sanitize(f"{track.artist} - {track.title}")
        target = self.out_dir / f"{filename}.mp3"

        if target.exists():
            progress(100.0, "Already downloaded")
            return DownloadResult(path=target, title=track.title, artist=track.artist)

        def hook(d: dict) -> None:
            if d.get("status") == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                done = d.get("downloaded_bytes") or 0
                pct = (done / total * 90.0) if total else 0.0
                progress(pct, "Downloading audio…")
            elif d.get("status") == "finished":
                progress(92.0, "Converting to MP3…")

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

        progress(2.0, "Finding the best version on YouTube…")
        try:
            # 1) Search several candidates (without downloading) and pick the
            #    right audio track by duration + channel type — avoids the video clip.
            with yt_dlp.YoutubeDL(
                {"quiet": True, "no_warnings": True, "extract_flat": False, "skip_download": True}
            ) as probe:
                search = probe.extract_info(
                    f"ytsearch6:{track.search_query}", download=False
                )
            entries = (search or {}).get("entries") or []
            best = _pick_best(entries, track)

            progress(5.0, "Downloading audio…")
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                if best:
                    ydl.process_ie_result(best, download=True)
                else:
                    # fallback: no scorable candidates, grab the first result
                    ydl.extract_info(f"ytsearch1:{track.search_query} audio", download=True)
        except yt_dlp.utils.DownloadError as exc:
            raise RuntimeError(f"Failed to download '{track.search_query}': {exc}") from exc

        if not target.exists():
            # fallback: find the freshly created mp3 with this prefix
            matches = list(self.out_dir.glob(f"{filename}.mp3"))
            if not matches:
                raise RuntimeError(f"Conversion failed for '{track.search_query}'.")
            target = matches[0]

        progress(96.0, "Writing tags and cover…")
        self._tag(target, track)
        progress(100.0, "Done")
        return DownloadResult(path=target, title=track.title, artist=track.artist)

    def _tag(self, mp3_path: Path, track: Track) -> None:
        """Write ID3 tags and embed the album cover."""
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
                    pass  # cover is optional

            audio.save(v2_version=3)
        except id3_error:
            pass  # tags are best-effort; the mp3 is already ready
