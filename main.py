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
    """Бот крутится в цикле: если упал (conflict и т.п.) — поднимаем снова."""
    from bot.main import run_bot

    while True:
        try:
            await run_bot()
            logger.warning("Bot polling stopped cleanly, restarting in 3s")
        except Exception:
            logger.exception("Bot crashed, restarting in 5s")
            await asyncio.sleep(5)
            continue
        await asyncio.sleep(3)


async def start_web():
    config = uvicorn.Config(
        "web.main:app",
        host=settings.host,
        port=settings.port,
        log_level="info",
        reload=False,
    )
    server = uvicorn.Server(config)
    # Не перехватываем сигналы сами — иначе SIGTERM гасит только web, а процесс живёт
    server.install_signal_handlers = False
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
