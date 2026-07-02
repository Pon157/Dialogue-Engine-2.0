"""Базовые хэндлеры, которые вешаются на КАЖДЫЙ созданный ботом инстанс.

Данные о конкретном боте (его настройки из таблицы Bot) прокидываются через
dispatcher["bot_row"] при регистрации (см. engine/manager.py), поэтому один и тот же
код хэндлеров обслуживает всех ботов сразу — это и есть суть мультибот-движка.
"""

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy import select

from app.db import async_session
from app.models import Bot, BotUser, MessageLog

router = Router(name="base")


async def _get_or_create_bot_user(session, bot_id: int, message: Message) -> BotUser:
    result = await session.execute(
        select(BotUser).where(BotUser.bot_id == bot_id, BotUser.tg_id == message.from_user.id)
    )
    user = result.scalar_one_or_none()
    if user is None:
        user = BotUser(
            bot_id=bot_id,
            tg_id=message.from_user.id,
            username=message.from_user.username,
            full_name=message.from_user.full_name,
        )
        session.add(user)
        await session.flush()
    return user


@router.message(Command("start"))
async def cmd_start(message: Message, bot_row: Bot):
    async with async_session() as session:
        user = await _get_or_create_bot_user(session, bot_row.id, message)
        if bot_row.open_ticket_on_start:
            user.has_open_ticket = True
        await session.commit()

    if bot_row.welcome_photo_file_id:
        await message.answer_photo(
            bot_row.welcome_photo_file_id,
            caption=bot_row.welcome_text or "",
            parse_mode="HTML",
        )
    elif bot_row.welcome_text:
        await message.answer(bot_row.welcome_text, parse_mode="HTML")


@router.message(Command("restart"))
async def cmd_restart(message: Message, bot_row: Bot):
    async with async_session() as session:
        user = await _get_or_create_bot_user(session, bot_row.id, message)
        user.has_open_ticket = True
        await session.commit()
    await message.answer("Новое обращение открыто ✅")


@router.message(F.text | F.photo | F.video | F.document | F.voice)
async def any_user_message(message: Message, bot_row: Bot):
    """Ловит любое сообщение от пользователя: логирует и (для support-ботов)
    пересылает/копирует в target_chat_id согласно настройкам forward_mode.
    Полная логика построения топиков/копи-шапки — следующий этап разработки.
    """
    async with async_session() as session:
        user = await _get_or_create_bot_user(session, bot_row.id, message)

        if user.is_banned:
            return  # забаненный юзер просто игнорируется

        if bot_row.open_ticket_on_first_message and not user.has_open_ticket:
            user.has_open_ticket = True

        session.add(
            MessageLog(bot_id=bot_row.id, direction="in", user_tg_id=message.from_user.id)
        )
        await session.commit()

    if not bot_row.target_chat_id:
        return

    if bot_row.forward_mode.value == "forward":
        await message.forward(bot_row.target_chat_id)
    else:
        header_parts = []
        if bot_row.copy_show_name:
            header_parts.append(message.from_user.full_name)
        if bot_row.copy_show_username and message.from_user.username:
            header_parts.append(f"@{message.from_user.username}")
        if bot_row.copy_show_id:
            header_parts.append(f"ID: {message.from_user.id}")
        header = " | ".join(header_parts)
        await message.copy_to(bot_row.target_chat_id, caption=header if header else None)
