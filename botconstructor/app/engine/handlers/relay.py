from aiogram import F, Router
from aiogram.types import Message
from sqlalchemy import select

from app.db import async_session
from app.engine.admin_check import is_bot_admin
from app.models import Bot, BotUser, MessageLog, TicketMessage

router = Router(name="relay")


@router.message(F.chat.type.in_({"group", "supergroup"}), F.message_thread_id)
async def admin_reply_in_topic(message: Message, bot_row: Bot):
    """Режим топиков: всё, что админ пишет ВНУТРИ темы обращения, само по себе
    привязано к юзеру этой темой — реплай на конкретное сообщение не нужен."""
    if not bot_row.use_topics or message.chat.id != bot_row.target_chat_id:
        return

    async with async_session() as session:
        if not await is_bot_admin(session, bot_row, message.from_user.id):
            return

        result = await session.execute(
            select(BotUser).where(BotUser.bot_id == bot_row.id, BotUser.active_topic_id == message.message_thread_id)
        )
        user = result.scalar_one_or_none()
        if user is None:
            return  # это чужой топик/не тема обращения — не наше дело

        try:
            await message.copy_to(user.tg_id)
        except Exception:
            await message.reply("⚠️ Не удалось доставить ответ — пользователь мог заблокировать бота.")
            return

        session.add(
            MessageLog(
                bot_id=bot_row.id,
                direction="out",
                user_tg_id=user.tg_id,
                admin_tg_id=message.from_user.id,
                admin_username=message.from_user.username,
            )
        )
        await session.commit()


@router.message(F.chat.type.in_({"group", "supergroup"}), F.reply_to_message)
async def admin_reply_relay(message: Message, bot_row: Bot):
    """Режим без топиков: единственный способ привязать ответ к юзеру — явный
    реплай на пересланное/скопированное сообщение конкретного тикета."""
    async with async_session() as session:
        if not await is_bot_admin(session, bot_row, message.from_user.id):
            return  # реплаит не админ — не наше дело

        result = await session.execute(
            select(TicketMessage)
            .where(TicketMessage.bot_id == bot_row.id, TicketMessage.group_message_id == message.reply_to_message.message_id)
            .order_by(TicketMessage.id.desc())
        )
        ticket = result.scalar_one_or_none()
        if ticket is None:
            return  # реплай не на сообщение тикета — игнор

        try:
            await message.copy_to(ticket.user_tg_id)
        except Exception:
            await message.reply("⚠️ Не удалось доставить ответ — пользователь мог заблокировать бота.")
            return

        session.add(
            MessageLog(
                bot_id=bot_row.id,
                direction="out",
                user_tg_id=ticket.user_tg_id,
                admin_tg_id=message.from_user.id,
                admin_username=message.from_user.username,
            )
        )
        await session.commit()
