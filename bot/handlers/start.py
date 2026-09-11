from aiogram import Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.types import Message

from bot.keyboards import main_menu
from database import crud
from database.database import async_session

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject):
    ref_code = None
    if command.args and command.args.startswith("ref_"):
        ref_code = command.args[4:]

    async with async_session() as session:
        await crud.get_or_create_user(
            session,
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            full_name=message.from_user.full_name,
            referral_code=ref_code,
        )
        welcome = await crud.get_setting(
            session,
            "welcome_text",
            "👋 Добро пожаловать!",
        )

    try:
        await message.answer(welcome, reply_markup=main_menu())
    except Exception:
        # если в тексте сломан HTML — шлём без разметки
        await message.answer(welcome, reply_markup=main_menu(), parse_mode=None)
