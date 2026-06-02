"use strict";

const form = document.getElementById("convert-form");
const urlInput = document.getElementById("url");
const bitrateSel = document.getElementById("bitrate");
const goBtn = document.getElementById("go");
const goText = goBtn.querySelector(".go-text");
const goSpin = goBtn.querySelector(".spinner");
const errorBox = document.getElementById("error");
const resultBox = document.getElementById("result");
const tracksEl = document.getElementById("tracks");
const zipBtn = document.getElementById("zip-btn");
const ffmpegWarn = document.getElementById("ffmpeg-warn");

let currentJob = null;
let eventSource = null;

// Check ffmpeg and metadata source on load
fetch("/api/health")
  .then((r) => r.json())
  .then((d) => {
    if (!d.ffmpeg) ffmpegWarn.hidden = false;
    const badge = document.getElementById("source-badge");
    if (badge) {
      badge.textContent = d.source === "api" ? "official Spotify API" : "no-signup mode";
      badge.classList.toggle("on", d.source === "api");
    }
  })
  .catch(() => {});

function setBusy(busy) {
  goBtn.disabled = busy;
  goText.textContent = busy ? "Reading…" : "Convert";
  goSpin.hidden = !busy;
}

function showError(msg) {
  errorBox.textContent = msg;
  errorBox.hidden = false;
}

function clearError() {
  errorBox.hidden = true;
}

function escapeHtml(s) {
  return (s || "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

// Trigger a download without navigating the page (keeps the SSE connection alive).
function triggerDownload(url) {
  const a = document.createElement("a");
  a.href = url;
  a.download = "";
  document.body.appendChild(a);
  a.click();
  a.remove();
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const url = urlInput.value.trim();
  if (!url) return;
  clearError();
  setBusy(true);

  if (eventSource) { eventSource.close(); eventSource = null; }

  try {
    const resp = await fetch("/api/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, bitrate: bitrateSel.value }),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "Failed to process the link.");
    currentJob = data;
    renderCollection(data);
    listenProgress(data.id);
  } catch (err) {
    showError(err.message || String(err));
  } finally {
    setBusy(false);
  }
});

function renderCollection(job) {
  document.getElementById("col-cover").src = job.cover_url || "";
  document.getElementById("col-kind").textContent =
    { track: "Track", album: "Album", playlist: "Playlist" }[job.kind] || job.kind;
  document.getElementById("col-name").textContent = job.name;
  document.getElementById("col-count").textContent =
    job.tracks.length === 1 ? "1 track" : `${job.tracks.length} tracks`;

  zipBtn.hidden = job.tracks.length < 2;
  zipBtn.onclick = () => {
    triggerDownload(`/api/jobs/${job.id}/zip`);
    job.tracks.forEach((_, i) => markDownloaded(i));
    zipBtn.disabled = true;
    zipBtn.textContent = "✓ Downloaded";
  };

  tracksEl.innerHTML = "";
  job.tracks.forEach((t, i) => {
    const li = document.createElement("li");
    li.className = "track";
    li.id = `track-${i}`;
    li.innerHTML = `
      <img class="t-cover" src="${escapeHtml(t.cover_url)}" alt="" onerror="this.style.visibility='hidden'"/>
      <div class="t-info">
        <div class="t-title">${escapeHtml(t.title)}</div>
        <div class="t-artist">${escapeHtml(t.artist)}</div>
        <div class="t-status" id="status-${i}">Queued…</div>
      </div>
      <div class="t-dur">${escapeHtml(t.duration)}</div>
      <div class="t-action" id="action-${i}"><span class="mini-spin"></span></div>
      <div class="t-bar" id="bar-${i}"></div>
    `;
    tracksEl.appendChild(li);
  });

  resultBox.hidden = false;
}

function listenProgress(jobId) {
  eventSource = new EventSource(`/api/jobs/${jobId}/events`);
  eventSource.onmessage = (ev) => {
    const snap = JSON.parse(ev.data);
    snap.tracks.forEach((t, i) => updateTrack(jobId, i, t));
    if (snap.status === "done" || snap.status === "error") {
      eventSource.close();
      eventSource = null;
    }
  };
  eventSource.onerror = () => {
    if (eventSource) { eventSource.close(); eventSource = null; }
  };
}

// Files are deleted from the server right after download, so reflect that in the UI.
function markDownloaded(i) {
  const statusEl = document.getElementById(`status-${i}`);
  const actionEl = document.getElementById(`action-${i}`);
  if (!statusEl || !actionEl) return;
  if (statusEl.dataset.done === "1") return; // avoid double-marking (e.g. zip + click)
  statusEl.dataset.done = "1";
  statusEl.textContent = "✓ Downloaded";
  actionEl.innerHTML = `<span title="Saved to your computer">✓</span>`;
}

function updateTrack(jobId, i, t) {
  const statusEl = document.getElementById(`status-${i}`);
  const barEl = document.getElementById(`bar-${i}`);
  const actionEl = document.getElementById(`action-${i}`);
  if (!statusEl) return;

  statusEl.classList.toggle("err", t.status === "error");

  if (t.status === "done") {
    statusEl.textContent = "✓ Ready";
    barEl.style.width = "100%";
    actionEl.innerHTML = `<button class="dl-btn" title="Download MP3 (removed from server afterwards)">⬇</button>`;
    actionEl.querySelector("button").onclick = () => {
      triggerDownload(`/api/jobs/${jobId}/file/${i}`);
      markDownloaded(i);
    };
  } else if (t.status === "error") {
    statusEl.textContent = "Error: " + (t.message || "failed");
    barEl.style.width = "0";
    actionEl.innerHTML = `<span title="${escapeHtml(t.message)}">⚠️</span>`;
  } else if (t.status === "working") {
    statusEl.textContent = t.message || "Working…";
    barEl.style.width = t.progress + "%";
  } else {
    statusEl.textContent = "Queued…";
  }
}
