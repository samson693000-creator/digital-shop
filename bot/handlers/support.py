"""Обратная связь: пользователь → админы → ответ пользователю."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database import crud
from database.database import async_session

router = Router()


class SupportStates(StatesGroup):
    waiting_user_message = State()
    waiting_admin_reply = State()


def _help_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✍️ Написать в поддержку",
                    callback_data="sup:write",
                )
            ]
        ]
    )


def _cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="sup:cancel")]
        ]
    )


def _admin_reply_kb(user_tg_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="💬 Ответить пользователю",
            callback_data=f"sup:reply:{user_tg_id}",
        )
    )
    return builder.as_markup()


async def _admin_ids() -> list[int]:
    async with async_session() as session:
        raw = await crud.get_setting(session, "admin_ids", "")
    ids: list[int] = []
    for part in (raw or "").replace(";", ",").split(","):
        part = part.strip()
        if part.isdigit():
            ids.append(int(part))
    return ids


def _is_admin(tg_id: int, admins: list[int]) -> bool:
    return tg_id in admins


@router.message(F.text == "ℹ️ Помощь")
async def help_msg(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "🛠 <b>Помощь</b>\n\n"
        "• <b>Каталог</b> — выбор и покупка цифровых товаров\n"
        "• <b>Кабинет</b> — баланс и история заказов\n"
        "• <b>Рефералы</b> — ваша ссылка и заработок\n\n"
        "Оплата: USDT TRC-20, ЮMoney или баланс.\n"
        "Товар выдаётся автоматически после подтверждения оплаты.\n\n"
        "Если нужна помощь — нажмите кнопку ниже и напишите сообщение.",
        reply_markup=_help_kb(),
    )


@router.callback_query(F.data == "sup:write")
async def support_write(callback: CallbackQuery, state: FSMContext):
    await state.set_state(SupportStates.waiting_user_message)
    await callback.message.answer(
        "✍️ <b>Обратная связь</b>\n\n"
        "Напишите одним сообщением ваш вопрос или проблему.\n"
        "Можно приложить фото (подпись к фото тоже уйдёт админу).",
        reply_markup=_cancel_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "sup:cancel")
async def support_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("❌ Отменено.")
    await callback.answer()


@router.message(Command("cancel"), StateFilter(SupportStates))
async def support_cancel_cmd(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Отменено.")


@router.message(StateFilter(SupportStates.waiting_user_message))
async def support_user_message(message: Message, state: FSMContext):
    admins = await _admin_ids()
    if not admins:
        await state.clear()
        await message.answer(
            "⚠️ Сейчас администраторы не настроены. "
            "Укажите <b>ID админов</b> в веб-админке → Настройки."
        )
        return

    user = message.from_user
    uname = f"@{user.username}" if user.username else "—"
    header = (
        "📩 <b>Новое сообщение в поддержку</b>\n\n"
        f"👤 {user.full_name or '—'}\n"
        f"Username: {uname}\n"
        f"ID: <code>{user.id}</code>\n\n"
        "Сообщение:"
    )

    await state.clear()
    sent = 0
    for admin_id in admins:
        try:
            await message.bot.send_message(
                admin_id,
                header,
                reply_markup=_admin_reply_kb(user.id),
            )
            # Пересылаем оригинал (текст/фото/документ), чтобы админ видел вложения
            await message.bot.forward_message(
                chat_id=admin_id,
                from_chat_id=message.chat.id,
                message_id=message.message_id,
            )
            sent += 1
        except Exception:
            continue

    if sent:
        await message.answer(
            "✅ Сообщение отправлено в поддержку. Ожидайте ответа здесь в боте."
        )
    else:
        await message.answer(
            "⚠️ Не удалось доставить сообщение админам. "
            "Проверьте, что админы нажали /start у бота."
        )


@router.callback_query(F.data.startswith("sup:reply:"))
async def support_admin_reply_start(callback: CallbackQuery, state: FSMContext):
    admins = await _admin_ids()
    if not _is_admin(callback.from_user.id, admins):
        await callback.answer("Только для администраторов", show_alert=True)
        return

    user_tg_id = int(callback.data.split(":")[2])
    await state.set_state(SupportStates.waiting_admin_reply)
    await state.update_data(reply_to=user_tg_id)
    await callback.message.answer(
        f"💬 Ответ пользователю <code>{user_tg_id}</code>\n\n"
        "Напишите текст ответа одним сообщением (можно с фото).",
        reply_markup=_cancel_kb(),
    )
    await callback.answer()


@router.message(StateFilter(SupportStates.waiting_admin_reply))
async def support_admin_reply_send(message: Message, state: FSMContext):
    admins = await _admin_ids()
    if not _is_admin(message.from_user.id, admins):
        await state.clear()
        await message.answer("Только для администраторов.")
        return

    data = await state.get_data()
    user_tg_id = int(data.get("reply_to") or 0)
    await state.clear()
    if not user_tg_id:
        await message.answer("Не найден получатель. Начните ответ заново из сообщения поддержки.")
        return

    prefix = "💬 <b>Ответ поддержки</b>\n\n"
    try:
        if message.photo:
            caption = (message.caption or "").strip()
            await message.bot.send_photo(
                user_tg_id,
                photo=message.photo[-1].file_id,
                caption=prefix + (caption or "Фото от поддержки"),
            )
        elif message.document:
            caption = (message.caption or "").strip()
            await message.bot.send_document(
                user_tg_id,
                document=message.document.file_id,
                caption=prefix + (caption or "Файл от поддержки"),
            )
        else:
            text = (message.text or message.caption or "").strip()
            if not text:
                await message.answer("Пустое сообщение. Напишите текст ответа.")
                await state.set_state(SupportStates.waiting_admin_reply)
                await state.update_data(reply_to=user_tg_id)
                return
            await message.bot.send_message(user_tg_id, prefix + text)
        await message.answer(f"✅ Ответ отправлен пользователю <code>{user_tg_id}</code>")
    except Exception:
        await message.answer(
            "⚠️ Не удалось отправить. Возможно, пользователь заблокировал бота."
        )
