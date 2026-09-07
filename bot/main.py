"""Telegram bot runner (aiogram 3)."""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramConflictError, TelegramNetworkError

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
            "либо нажмите «Рестарт» в меню"
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

    dp = Dispatcher()
    dp.include_router(start.router)
    dp.include_router(catalog.router)
    dp.include_router(payment.router)
    dp.include_router(profile.router)
    dp.include_router(referral.router)

    from bot.services.payment_watch import watch_pending_payments

    watcher = asyncio.create_task(watch_pending_payments(bot))
    try:
        # После рестарта Telegram иногда ещё держит старый getUpdates — ждём и пробуем
        for attempt in range(1, 12):
            try:
                await bot.delete_webhook(drop_pending_updates=True)
                logger.info("Telegram bot polling started (try %s)", attempt)
                await dp.start_polling(bot, handle_signals=False)
                break
            except TelegramConflictError:
                wait = min(2 * attempt, 15)
                logger.warning(
                    "Telegram getUpdates conflict (try %s), wait %ss",
                    attempt,
                    wait,
                )
                await asyncio.sleep(wait)
            except TelegramNetworkError:
                logger.warning("Telegram network error, retry in 5s")
                await asyncio.sleep(5)
        else:
            raise RuntimeError("Не удалось запустить polling: Telegram conflict")
    finally:
        watcher.cancel()
        try:
            await watcher
        except asyncio.CancelledError:
            pass
        await bot.session.close()
