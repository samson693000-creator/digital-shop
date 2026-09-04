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
    from config import settings

    async with async_session() as session:
        token = await crud.get_setting(session, "bot_token", "")
    token = (token or "").strip()
    if not token:
        token = (settings.bot_token or "").strip()
    return token


async def run_bot() -> None:
    await init_db()
    token = await get_bot_token()
    if not token:
        logger.error(
            "BOT_TOKEN не задан. Укажите в админке (Настройки) и подождите, "
            "либо: systemctl restart digital-shop"
        )
        while not token:
            await asyncio.sleep(5)
            token = await get_bot_token()
            if token:
                logger.info("Токен бота получен из БД, запускаю...")

    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    try:
        me = await bot.get_me()
        logger.info("Бот авторизован: @%s (id=%s)", me.username, me.id)
    except Exception:
        logger.exception(
            "Невалидный BOT_TOKEN. Проверьте токен в админке и перезапустите сервис."
        )
        await bot.session.close()
        raise

    # Иначе polling не получает апдейты, если раньше был webhook
    await bot.delete_webhook(drop_pending_updates=True)

    dp = Dispatcher()
    dp.include_router(start.router)
    dp.include_router(catalog.router)
    dp.include_router(payment.router)
    dp.include_router(profile.router)
    dp.include_router(referral.router)

    logger.info("Telegram bot polling started")
    await dp.start_polling(bot)
