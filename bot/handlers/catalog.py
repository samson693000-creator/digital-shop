from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from bot.keyboards import (
    categories_kb,
    product_actions_kb,
    products_kb,
)
from database import crud
from database.database import async_session

router = Router()


async def _show_catalog(target, edit: bool = False):
    async with async_session() as session:
        cats = await crud.list_categories(session, parent_id=None)

    text = "🛒 <b>Каталог</b>\n\nВыберите категорию:"
    kb = categories_kb(cats) if cats else None
    if not cats:
        text = "🛒 Каталог пуст. Загляните позже."

    if edit and isinstance(target, CallbackQuery):
        await target.message.edit_text(text, reply_markup=kb)
        await target.answer()
    elif isinstance(target, CallbackQuery):
        await target.message.answer(text, reply_markup=kb)
        await target.answer()
    else:
        await target.answer(text, reply_markup=kb)


@router.message(F.text == "🛒 Каталог")
async def catalog_msg(message: Message):
    await _show_catalog(message)


@router.callback_query(F.data == "catalog")
async def catalog_cb(callback: CallbackQuery):
    await _show_catalog(callback, edit=True)


@router.callback_query(F.data.startswith("cat:"))
async def open_category(callback: CallbackQuery):
    cat_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        category = await crud.get_category(session, cat_id)
        if not category:
            await callback.answer("Категория не найдена", show_alert=True)
            return

        subcats = await crud.list_categories(session, parent_id=cat_id)
        products = await crud.list_products(session, category_id=cat_id)

    if subcats:
        text = f"📁 <b>{category.name}</b>\n\nВыберите подкатегорию:"
        await callback.message.edit_text(
            text, reply_markup=categories_kb(subcats, back_to="catalog")
        )
        await callback.answer()
        return

    if not products:
        await callback.message.edit_text(
            f"📁 <b>{category.name}</b>\n\nТоваров пока нет.",
            reply_markup=categories_kb([], back_to="catalog"),
        )
        await callback.answer()
        return

    text = f"📁 <b>{category.name}</b>\n\nВыберите товар:"
    await callback.message.edit_text(
        text, reply_markup=products_kb(products, cat_id)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("prod:"))
async def open_product(callback: CallbackQuery):
    product_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        product = await crud.get_product(session, product_id)
        if not product or not product.is_active:
            await callback.answer("Товар не найден", show_alert=True)
            return
        stock = product.available_count
        name = product.name
        desc = product.description or "Без описания"
        price = product.price

    stock_line = f"✅ В наличии: {stock} шт." if stock else "❌ Нет в наличии"
    text = (
        f"📦 <b>{name}</b>\n\n"
        f"{desc}\n\n"
        f"💰 Цена: <b>{price} ₽</b>\n"
        f"{stock_line}"
    )
    await callback.message.edit_text(
        text, reply_markup=product_actions_kb(product_id, stock > 0)
    )
    await callback.answer()
