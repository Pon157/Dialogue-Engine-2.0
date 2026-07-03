from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Bot, BotAdmin


async def is_bot_admin(session: AsyncSession, bot_row: Bot, tg_id: int) -> bool:
    if tg_id == bot_row.owner_tg_id:
        return True
    result = await session.execute(
        select(BotAdmin).where(BotAdmin.bot_id == bot_row.id, BotAdmin.tg_id == tg_id)
    )
    return result.scalar_one_or_none() is not None
