"""Telegram bot runner (aiogram 3)."""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot.handlers import catalog, payment, profile, referral, start
from database import crud
from database.database import async_session, init_db

logger = logging.getLogger(__name__)


async def get_bot_token() -> str:
    async with async_session() as session:
        token = await crud.get_setting(session, "bot_token", "")
    return token.strip()


async def run_bot() -> None:
    await init_db()
    token = await get_bot_token()
    if not token:
        logger.error(
            "BOT_TOKEN не задан. Укажите в .env или в админке (Настройки бота)."
        )
        # Wait and retry so web panel can set token without restart race
        while not token:
            await asyncio.sleep(5)
            token = await get_bot_token()
            if token:
                logger.info("Токен бота получен из БД, запускаю...")

    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(start.router)
    dp.include_router(catalog.router)
    dp.include_router(payment.router)
    dp.include_router(profile.router)
    dp.include_router(referral.router)

    logger.info("Telegram bot started")
    await dp.start_polling(bot)
