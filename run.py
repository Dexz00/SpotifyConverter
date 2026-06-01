"""
Server entry point.

On Windows we swap the default event loop (Proactor) for the Selector one: the
Proactor emits noisy 'socket.send() raised exception' messages whenever a
download/stream is cancelled by the browser. It is functionally harmless but
clutters the terminal. The Selector loop handles disconnects silently.
"""
from __future__ import annotations

import asyncio
import sys

import uvicorn

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, log_level="info")
