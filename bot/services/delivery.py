"""Order delivery helpers."""
from __future__ import annotations

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession

from database import crud


async def deliver_order(session: AsyncSession, bot: Bot, order_id: int) -> bool:
    order = await crud.complete_order(session, order_id)
    if not order or order.status != "paid" or not order.delivered_content:
        return False

    user = order.user
    product_name = order.product.name if order.product else "товар"
    text = (
        f"✅ <b>Оплата подтверждена!</b>\n\n"
        f"📦 Товар: <b>{product_name}</b>\n"
        f"🧾 Заказ #{order.id}\n\n"
        f"<b>Ваш товар:</b>\n"
        f"<code>{order.delivered_content}</code>\n\n"
        f"Сохраните данные — повторная выдача только через поддержку."
    )
    try:
        await bot.send_message(user.telegram_id, text)
    except Exception:
        return False
    return True
