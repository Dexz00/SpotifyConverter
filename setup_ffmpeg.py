"""
Baixa um build estático do ffmpeg para ./bin (Windows) caso ele não exista
no PATH. Roda uma vez; depois o SpotifyConverter o encontra automaticamente.
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
        print("[OK] ffmpeg ja esta no PATH.")
        return True
    if (BIN / "ffmpeg.exe").exists():
        print(f"[OK] ffmpeg ja esta em {BIN}.")
        return True
    return False


def main() -> int:
    if already_have():
        return 0
    if os.name != "nt":
        print("Sistema não-Windows: instale o ffmpeg pelo gerenciador de pacotes "
              "(ex.: 'sudo apt install ffmpeg' ou 'brew install ffmpeg').")
        return 1

    BIN.mkdir(exist_ok=True)
    print("Baixando ffmpeg (~30 MB)… isso pode levar um minuto.")
    req = Request(URL, headers={"User-Agent": "SpotifyConverter"})
    with urlopen(req) as resp:  # noqa: S310 — URL fixa e confiável
        data = resp.read()

    print("Extraindo…")
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for member in zf.namelist():
            name = os.path.basename(member)
            if name in {"ffmpeg.exe", "ffprobe.exe"}:
                with zf.open(member) as src, open(BIN / name, "wb") as dst:
                    shutil.copyfileobj(src, dst)

    if (BIN / "ffmpeg.exe").exists():
        print(f"[OK] ffmpeg instalado em {BIN}")
        return 0
    print("[ERRO] Nao consegui extrair o ffmpeg do pacote.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
