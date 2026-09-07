from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database.crud import CatalogGroup
from database.models import Category


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🛒 Каталог")],
            [KeyboardButton(text="👤 Кабинет"), KeyboardButton(text="🎁 Рефералы")],
            [KeyboardButton(text="ℹ️ Помощь")],
        ],
        resize_keyboard=True,
    )


def categories_kb(categories: list[Category], back_to: str | None = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for cat in categories:
        builder.row(
            InlineKeyboardButton(text=cat.name, callback_data=f"cat:{cat.id}")
        )
    if back_to:
        builder.row(InlineKeyboardButton(text="« Назад", callback_data=back_to))
    return builder.as_markup()


def products_kb(groups: list[CatalogGroup], category_id: int) -> InlineKeyboardMarkup:
    """Одна кнопка на группу товара (не на каждый ключ)."""
    builder = InlineKeyboardBuilder()
    for g in groups:
        if g.is_infinite:
            label = f"{g.name} — {g.price} ₽ | В наличии: ∞"
        else:
            label = f"{g.name} — {g.price} ₽ | В наличии: {g.stock} шт."
        # Telegram button text max ~64 chars
        if len(label) > 64:
            label = label[:61] + "…"
        builder.row(
            InlineKeyboardButton(text=label, callback_data=f"prod:{g.product_id}")
        )
    builder.row(
        InlineKeyboardButton(text="« Назад", callback_data="catalog")
    )
    return builder.as_markup()


def product_actions_kb(
    product_id: int,
    *,
    in_stock: bool,
    stock: int = 1,
    is_infinite: bool = False,
    category_id: int | None = None,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if in_stock:
        if is_infinite:
            builder.row(
                InlineKeyboardButton(
                    text="💳 Купить",
                    callback_data=f"buy:{product_id}:1",
                )
            )
        else:
            max_qty = min(int(stock), 5)
            if max_qty <= 1:
                builder.row(
                    InlineKeyboardButton(
                        text="💳 Купить",
                        callback_data=f"buy:{product_id}:1",
                    )
                )
            else:
                row: list[InlineKeyboardButton] = []
                for q in range(1, max_qty + 1):
                    row.append(
                        InlineKeyboardButton(
                            text=f"{q} шт.",
                            callback_data=f"buy:{product_id}:{q}",
                        )
                    )
                    if len(row) == 3:
                        builder.row(*row)
                        row = []
                if row:
                    builder.row(*row)
    back = f"cat:{category_id}" if category_id else "catalog"
    builder.row(InlineKeyboardButton(text="« Назад", callback_data=back))
    return builder.as_markup()


def payment_methods_kb(order_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="💎 USDT TRC-20", callback_data=f"pay:usdt:{order_id}")
    )
    builder.row(
        InlineKeyboardButton(text="💰 ЮMoney", callback_data=f"pay:yoomoney:{order_id}")
    )
    builder.row(
        InlineKeyboardButton(text="👛 Баланс", callback_data=f"pay:balance:{order_id}")
    )
    builder.row(
        InlineKeyboardButton(text="❌ Отмена", callback_data=f"cancel:{order_id}")
    )
    return builder.as_markup()


def check_payment_kb(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔄 Проверить оплату", callback_data=f"check:{order_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Отменить заказ", callback_data=f"cancel:{order_id}"
                )
            ],
        ]
    )


def profile_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📜 История заказов", callback_data="orders")],
        ]
    )
