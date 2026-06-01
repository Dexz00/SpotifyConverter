"""
Ponto de entrada do servidor.

No Windows trocamos o event loop padrão (Proactor) pelo Selector: o Proactor
emite mensagens barulhentas de 'socket.send() raised exception' toda vez que um
download/stream é cancelado pelo navegador. Funcionalmente é inofensivo, mas
polui o terminal. O Selector lida com desconexões silenciosamente.
"""
from __future__ import annotations

import asyncio
import sys

import uvicorn

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, log_level="info")
