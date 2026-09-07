"""Order delivery helpers."""
from __future__ import annotations

from pathlib import Path

from aiogram import Bot
from aiogram.types import FSInputFile
from sqlalchemy.ext.asyncio import AsyncSession

from database import crud
from web.uploads import IMAGE_EXTS, parse_file_key


async def deliver_order(
    session: AsyncSession,
    bot: Bot,
    order_id: int,
    payment_ref: str | None = None,
) -> bool:
    order = await crud.complete_order(session, order_id, payment_ref=payment_ref)
    if not order or order.status != "paid" or not order.delivered_content:
        return False

    user = order.user
    product_name = order.product.name if order.product else "товар"
    content = order.delivered_content
    header = (
        f"✅ <b>Оплата подтверждена!</b>\n\n"
        f"📦 Товар: <b>{product_name}</b>\n"
        f"🧾 Заказ #{order.id}\n\n"
    )

    try:
        parsed = parse_file_key(content)
        if parsed:
            path, display_name = parsed
            if not path.is_file():
                await bot.send_message(
                    user.telegram_id,
                    header + "⚠️ Файл товара не найден на сервере. Напишите в поддержку.",
                )
                return False
            caption = header + f"📎 Файл: <b>{display_name}</b>"
            file = FSInputFile(str(path), filename=display_name)
            ext = path.suffix.lower()
            if ext in IMAGE_EXTS:
                await bot.send_photo(user.telegram_id, photo=file, caption=caption)
            else:
                await bot.send_document(user.telegram_id, document=file, caption=caption)
            return True

        text = (
            header
            + f"<b>Ваш товар:</b>\n"
            + f"<code>{content}</code>\n\n"
            + "Сохраните данные — повторная выдача только через поддержку."
        )
        await bot.send_message(user.telegram_id, text)
    except Exception:
        return False
    return True


def product_image_abs(image_path: str | None) -> Path | None:
    if not image_path:
        return None
    from config import DATA_DIR

    path = (DATA_DIR / image_path).resolve()
    if path.is_file():
        return path
    return None
