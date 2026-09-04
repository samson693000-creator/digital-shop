from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database.models import Category, Product


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


def products_kb(products: list[Product], category_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for p in products:
        stock = p.available_count
        label = f"{p.name} — {p.price} ₽ ({stock} шт.)"
        builder.row(
            InlineKeyboardButton(text=label, callback_data=f"prod:{p.id}")
        )
    builder.row(InlineKeyboardButton(text="« Назад", callback_data="catalog"))
    return builder.as_markup()


def product_actions_kb(product_id: int, in_stock: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if in_stock:
        builder.row(
            InlineKeyboardButton(text="💳 Купить", callback_data=f"buy:{product_id}")
        )
    builder.row(InlineKeyboardButton(text="« Назад", callback_data="catalog"))
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
