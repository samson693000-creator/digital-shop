from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from bot.keyboards import profile_kb
from database import crud
from database.database import async_session

router = Router()


@router.message(F.text == "👤 Кабинет")
async def profile(message: Message):
    async with async_session() as session:
        user, _ = await crud.get_or_create_user(
            session,
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            full_name=message.from_user.full_name,
        )
        orders = await crud.list_orders(session, user_id=user.id, limit=5)
        ref = await crud.get_referral_stats(session, user.id)

    lines = [
        "👤 <b>Личный кабинет</b>\n",
        f"ID: <code>{user.telegram_id}</code>",
        f"Баланс: <b>{user.balance} ₽</b>",
        f"Рефералов: {ref['referrals']}",
        f"Заработано с рефералов: {ref['earned']} ₽",
        "",
        "<b>Последние заказы:</b>",
    ]
    if not orders:
        lines.append("— пока нет")
    else:
        for o in orders:
            pname = o.product.name if o.product else "?"
            lines.append(f"#{o.id} · {pname} · {o.amount} ₽ · {o.status}")

    await message.answer("\n".join(lines), reply_markup=profile_kb())


@router.callback_query(F.data == "orders")
async def orders_history(callback: CallbackQuery):
    async with async_session() as session:
        user = await crud.get_user_by_tg(session, callback.from_user.id)
        if not user:
            await callback.answer("Сначала /start", show_alert=True)
            return
        orders = await crud.list_orders(session, user_id=user.id, limit=20)

    if not orders:
        text = "📜 История пуста."
    else:
        parts = ["📜 <b>История заказов</b>\n"]
        for o in orders:
            pname = o.product.name if o.product else "?"
            parts.append(
                f"#{o.id} · {pname}\n"
                f"   {o.amount} ₽ · {o.payment_method} · <b>{o.status}</b>"
            )
            if o.status == "paid" and o.delivered_content:
                parts.append(f"   🔑 <code>{o.delivered_content}</code>")
        text = "\n".join(parts)

    await callback.message.answer(text)
    await callback.answer()
