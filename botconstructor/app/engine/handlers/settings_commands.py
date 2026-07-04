from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import select, update

from app.db import async_session
from app.engine.admin_check import is_bot_admin
from app.models import Bot, PostingSettings

router = Router(name="settings_commands")


@router.message(Command("setchat"))
async def set_target_chat(message: Message, bot_row: Bot):
    """Выполняется прямо в группе/топике, куда должны падать обращения (support-боты)."""
    if message.chat.type not in ("group", "supergroup"):
        await message.answer("Эту команду нужно отправить в группе, которую вы хотите назначить чатом обращений.")
        return
    async with async_session() as session:
        if not await is_bot_admin(session, bot_row, message.from_user.id):
            return
        await session.execute(update(Bot).where(Bot.id == bot_row.id).values(target_chat_id=message.chat.id))
        await session.commit()
    await message.answer(f"✅ Этот чат назначен как чат обращений (ID {message.chat.id}).")


@router.message(Command("setreviewchat"))
async def set_review_chat(message: Message, bot_row: Bot):
    """Выполняется в группе модерации постов (posting-боты)."""
    if message.chat.type not in ("group", "supergroup"):
        await message.answer("Эту команду нужно отправить в группе модерации постов.")
        return
    async with async_session() as session:
        if not await is_bot_admin(session, bot_row, message.from_user.id):
            return
        result = await session.execute(select(PostingSettings).where(PostingSettings.bot_id == bot_row.id))
        settings_row = result.scalar_one_or_none()
        if settings_row is None:
            settings_row = PostingSettings(bot_id=bot_row.id, review_chat_id=message.chat.id)
            session.add(settings_row)
        else:
            settings_row.review_chat_id = message.chat.id
        await session.commit()
    await message.answer(f"✅ Эта группа назначена для модерации постов (ID {message.chat.id}).")


@router.message(F.forward_from_chat, F.chat.type == "private")
async def set_target_channel_by_forward(message: Message, bot_row: Bot):
    """Владелец форвардит любой пост из канала боту в личку — так канал назначается
    целевым для публикации (posting-боты). Надёжнее, чем просить вручную вводить ID."""
    if message.forward_from_chat.type != "channel":
        return
    async with async_session() as session:
        if not await is_bot_admin(session, bot_row, message.from_user.id):
            return
        result = await session.execute(select(PostingSettings).where(PostingSettings.bot_id == bot_row.id))
        settings_row = result.scalar_one_or_none()
        if settings_row is None:
            settings_row = PostingSettings(bot_id=bot_row.id, target_channel_id=message.forward_from_chat.id)
            session.add(settings_row)
        else:
            settings_row.target_channel_id = message.forward_from_chat.id
        await session.commit()
    await message.answer(
        f"✅ Канал «{message.forward_from_chat.title}» назначен для публикации постов.\n"
        "Не забудьте сделать бота администратором этого канала с правом публикации."
    )
