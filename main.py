"""Run Telegram bot + FastAPI admin panel together."""
from __future__ import annotations

import asyncio
import logging
import sys

import uvicorn

from config import settings
from database.database import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("main")


async def start_bot():
    from bot.main import run_bot

    try:
        await run_bot()
    except Exception:
        logger.exception("Bot crashed")


async def start_web():
    config = uvicorn.Config(
        "web.main:app",
        host=settings.host,
        port=settings.port,
        log_level="info",
        reload=False,
    )
    server = uvicorn.Server(config)
    await server.serve()


async def main():
    await init_db()
    logger.info("DB ready. Starting bot + admin on %s:%s", settings.host, settings.port)
    await asyncio.gather(start_web(), start_bot())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Stopped")
