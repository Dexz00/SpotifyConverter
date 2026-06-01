"""
Download a static ffmpeg build into ./bin (Windows) when it is not already on
the PATH. Run it once; afterwards SpotifyConverter finds it automatically.
"""
from __future__ import annotations

import io
import os
import shutil
import sys
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

BIN = Path(__file__).resolve().parent / "bin"
URL = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"


def already_have() -> bool:
    if shutil.which("ffmpeg"):
        print("[OK] ffmpeg is already on the PATH.")
        return True
    if (BIN / "ffmpeg.exe").exists():
        print(f"[OK] ffmpeg is already in {BIN}.")
        return True
    return False


def main() -> int:
    if already_have():
        return 0
    if os.name != "nt":
        print("Non-Windows system: install ffmpeg with your package manager "
              "(e.g. 'sudo apt install ffmpeg' or 'brew install ffmpeg').")
        return 1

    BIN.mkdir(exist_ok=True)
    print("Downloading ffmpeg (~30 MB)… this may take a minute.")
    req = Request(URL, headers={"User-Agent": "SpotifyConverter"})
    with urlopen(req) as resp:  # noqa: S310 — fixed, trusted URL
        data = resp.read()

    print("Extracting…")
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for member in zf.namelist():
            name = os.path.basename(member)
            if name in {"ffmpeg.exe", "ffprobe.exe"}:
                with zf.open(member) as src, open(BIN / name, "wb") as dst:
                    shutil.copyfileobj(src, dst)

    if (BIN / "ffmpeg.exe").exists():
        print(f"[OK] ffmpeg installed in {BIN}")
        return 0
    print("[ERROR] Could not extract ffmpeg from the package.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
