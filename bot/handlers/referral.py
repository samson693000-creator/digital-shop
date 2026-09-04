from aiogram import F, Router
from aiogram.types import Message

from database import crud
from database.database import async_session

router = Router()


@router.message(F.text == "🎁 Рефералы")
async def referrals(message: Message):
    async with async_session() as session:
        user, _ = await crud.get_or_create_user(
            session,
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            full_name=message.from_user.full_name,
        )
        stats = await crud.get_referral_stats(session, user.id)
        pay = await crud.get_payment_settings(session)
        percent = pay.referral_percent
        me = await message.bot.get_me()
        link = f"https://t.me/{me.username}?start=ref_{user.referral_code}"

    await message.answer(
        "🎁 <b>Реферальная программа</b>\n\n"
        f"Ваш процент: <b>{percent}%</b> с покупок приглашённых.\n"
        f"Бонус зачисляется на баланс.\n\n"
        f"Приглашено: <b>{stats['referrals']}</b>\n"
        f"Заработано: <b>{stats['earned']} ₽</b>\n"
        f"Текущий баланс: <b>{user.balance} ₽</b>\n\n"
        f"Ваша ссылка:\n<code>{link}</code>"
    )
