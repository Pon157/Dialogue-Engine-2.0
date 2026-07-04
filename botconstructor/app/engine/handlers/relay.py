from aiogram import F, Router
from aiogram.types import Message
from sqlalchemy import select

from app.db import async_session
from app.engine.admin_check import is_bot_admin
from app.models import Bot, MessageLog, TicketMessage

router = Router(name="relay")
router.message.filter(F.chat.type.in_({"group", "supergroup"}), F.reply_to_message)


@router.message()
async def admin_reply_relay(message: Message, bot_row: Bot):
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
