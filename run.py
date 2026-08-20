"""
Server entry point.

On Windows we swap the default event loop (Proactor) for the Selector one: the
Proactor emits noisy 'socket.send() raised exception' messages whenever a
download/stream is cancelled by the browser. It is functionally harmless but
clutters the terminal. The Selector loop handles disconnects silently.
"""
from __future__ import annotations

import asyncio
import os
import sys

import uvicorn

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


if __name__ == "__main__":
    # HOST/PORT are overridable via env (Docker/Railway sets HOST=0.0.0.0).
    # Default to 0.0.0.0 for better compatibility with containerized environments.
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("app.main:app", host=host, port=port, log_level="info", reload=False)

