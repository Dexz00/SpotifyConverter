"""
SpotifyConverter FastAPI app.

Flow:
  1. POST /api/jobs        { url, bitrate }  -> create job, return tracks
  2. GET  /api/jobs/{id}/events  (SSE)       -> real-time progress
  3. GET  /api/jobs/{id}/file/{index}        -> download one MP3
  4. GET  /api/jobs/{id}/zip                 -> download everything as a .zip
"""
from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
import threading
import time
import uuid
import zipfile
from dataclasses import asdict, dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from dotenv import load_dotenv

from .downloader import Downloader, find_ffmpeg
from .resolver import resolve, using_official_api
from .spotify import SpotifyError, Track

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

BASE_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = BASE_DIR / "web"

# Files are NOT kept in the project. We work in a temporary system folder and
# auto-delete each job shortly after it finishes — nothing is stored long-term.
DOWNLOAD_DIR = Path(tempfile.gettempdir()) / "spotifyconverter"
shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)  # wipe leftovers from previous runs
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

# How long a finished job's files stay available for download before deletion.
JOB_TTL_SECONDS = 900  # 15 minutes

app = FastAPI(title="SpotifyConverter", version="1.0.0")


# --------------------------------------------------------------------------- models


class JobRequest(BaseModel):
    url: str
    bitrate: str = "320"


@dataclass
class TrackState:
    title: str
    artist: str
    cover_url: str
    duration: str
    status: str = "pending"  # pending | working | done | error
    progress: float = 0.0
    message: str = ""
    filename: str = ""


@dataclass
class Job:
    id: str
    kind: str
    name: str
    cover_url: str
    bitrate: str
    tracks: list[TrackState] = field(default_factory=list)
    _raw: list[Track] = field(default_factory=list)
    status: str = "queued"  # queued | running | done | error
    error: str = ""


JOBS: dict[str, Job] = {}


# --------------------------------------------------------------------------- cleanup


def _cleanup_job(job_id: str) -> None:
    """Forget the job and delete its temporary files from disk."""
    JOBS.pop(job_id, None)
    shutil.rmtree(DOWNLOAD_DIR / job_id, ignore_errors=True)


def _schedule_cleanup(job_id: str) -> None:
    timer = threading.Timer(JOB_TTL_SECONDS, _cleanup_job, args=(job_id,))
    timer.daemon = True
    timer.start()


# --------------------------------------------------------------------------- worker


def _run_job(job: Job) -> None:
    job.status = "running"
    try:
        dl = Downloader(DOWNLOAD_DIR / job.id, bitrate=job.bitrate)
    except RuntimeError as exc:
        job.status = "error"
        job.error = str(exc)
        for ts in job.tracks:
            ts.status = "error"
            ts.message = str(exc)
        _schedule_cleanup(job.id)
        return

    for i, (state, raw) in enumerate(zip(job.tracks, job._raw)):
        state.status = "working"
        state.message = "Starting…"

        def cb(pct: float, msg: str, _state=state) -> None:
            _state.progress = round(pct, 1)
            _state.message = msg

        try:
            result = dl.download_track(raw, cb)
            state.status = "done"
            state.progress = 100.0
            state.message = "Done"
            state.filename = result.path.name
        except Exception as exc:  # noqa: BLE001 — one failing track must not kill the rest
            state.status = "error"
            state.message = str(exc)[:300]

    job.status = "done"
    _schedule_cleanup(job.id)  # files self-delete after JOB_TTL_SECONDS


# --------------------------------------------------------------------------- routes


@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "ffmpeg": find_ffmpeg() is not None,
        "source": "api" if using_official_api() else "embed",
    }


@app.post("/api/jobs")
def create_job(req: JobRequest) -> dict:
    try:
        collection = resolve(req.url)
    except SpotifyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    bitrate = req.bitrate if req.bitrate in {"128", "192", "256", "320"} else "320"
    job_id = uuid.uuid4().hex[:12]
    job = Job(
        id=job_id,
        kind=collection.kind,
        name=collection.name,
        cover_url=collection.cover_url,
        bitrate=bitrate,
        _raw=collection.tracks,
        tracks=[
            TrackState(
                title=t.title,
                artist=t.artist,
                cover_url=t.cover_url,
                duration=t.duration_str,
            )
            for t in collection.tracks
        ],
    )
    JOBS[job_id] = job

    threading.Thread(target=_run_job, args=(job,), daemon=True).start()

    return {
        "id": job.id,
        "kind": job.kind,
        "name": job.name,
        "cover_url": job.cover_url,
        "tracks": [
            {"title": t.title, "artist": t.artist, "cover_url": t.cover_url, "duration": t.duration}
            for t in job.tracks
        ],
    }


def _snapshot(job: Job) -> dict:
    return {
        "status": job.status,
        "error": job.error,
        "tracks": [
            {
                "status": t.status,
                "progress": t.progress,
                "message": t.message,
                "filename": t.filename,
            }
            for t in job.tracks
        ],
    }


@app.get("/api/jobs/{job_id}/events")
async def job_events(job_id: str, request: Request) -> StreamingResponse:
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    async def stream():
        last = None
        while True:
            # if the browser closed the tab / went away, stop without writing to a dead socket
            if await request.is_disconnected():
                break
            snap = _snapshot(job)
            payload = json.dumps(snap, ensure_ascii=False)
            if payload != last:
                yield f"data: {payload}\n\n"
                last = payload
            if job.status in {"done", "error"}:
                break
            await asyncio.sleep(0.4)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/jobs/{job_id}/file/{index}")
def get_file(job_id: str, index: int) -> FileResponse:
    job = JOBS.get(job_id)
    if not job or index < 0 or index >= len(job.tracks):
        raise HTTPException(status_code=404, detail="File not found")
    state = job.tracks[index]
    if state.status != "done" or not state.filename:
        raise HTTPException(status_code=409, detail="Track is not ready yet")
    path = DOWNLOAD_DIR / job.id / state.filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="File no longer exists")
    return FileResponse(path, media_type="audio/mpeg", filename=state.filename)


@app.get("/api/jobs/{job_id}/zip")
def get_zip(job_id: str) -> StreamingResponse:
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    done = [t for t in job.tracks if t.status == "done" and t.filename]
    if not done:
        raise HTTPException(status_code=409, detail="No tracks ready yet")

    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        for t in done:
            path = DOWNLOAD_DIR / job.id / t.filename
            if path.exists():
                zf.write(path, arcname=t.filename)
    buf.seek(0)

    safe = "".join(c for c in job.name if c.isalnum() or c in " -_").strip() or "spotify"
    headers = {"Content-Disposition": f'attachment; filename="{safe}.zip"'}
    return StreamingResponse(buf, media_type="application/zip", headers=headers)


# --------------------------------------------------------------------------- frontend


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse((WEB_DIR / "index.html").read_text(encoding="utf-8"))


app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
