from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy import select, update

from app.db import async_session
from app.engine.admin_check import is_bot_admin
from app.engine.duration import parse_duration
from app.models import BanLog, Bot, BotUser, Warn

router = Router(name="moderation")


def _parse_args(command: CommandObject, need_duration: bool) -> tuple[int, str, str | None] | None:
    if not command.args:
        return None
    parts = command.args.split(maxsplit=2)
    if not parts[0].lstrip("-").isdigit():
        return None
    user_id = int(parts[0])

    duration = None
    reason = None
    if need_duration and len(parts) >= 2:
        # последний токен может быть длительностью (7d/perm/...)
        maybe_duration = parts[-1]
        try:
            parse_duration(maybe_duration)
            duration = maybe_duration
            reason = " ".join(parts[1:-1]) or None
        except ValueError:
            reason = " ".join(parts[1:]) or None
    elif len(parts) >= 2:
        reason = " ".join(parts[1:])

    return user_id, reason, duration


@router.message(Command("ban"))
async def cmd_ban(message: Message, bot_row: Bot):
    async with async_session() as session:
        if not await is_bot_admin(session, bot_row, message.from_user.id):
            return

        command = CommandObject(command="ban", args=message.text.split(maxsplit=1)[1] if " " in message.text else None)
        parsed = _parse_args(command, need_duration=True)
        if not parsed:
            await message.answer("Формат: <code>/ban ID причина 7d</code> (или perm/1h/2w/1y)")
            return
        user_id, reason, duration_raw = parsed

        until = None
        label = "навсегда"
        if duration_raw:
            try:
                until, label = parse_duration(duration_raw)
            except ValueError as e:
                await message.answer(str(e))
                return

        result = await session.execute(select(BotUser).where(BotUser.bot_id == bot_row.id, BotUser.tg_id == user_id))
        user = result.scalar_one_or_none()
        if user is None:
            user = BotUser(bot_id=bot_row.id, tg_id=user_id)
            session.add(user)

        user.is_banned = True
        user.ban_until = until
        user.ban_reason = reason
        session.add(BanLog(bot_id=bot_row.id, user_tg_id=user_id, admin_tg_id=message.from_user.id, reason=reason, until=until, action="ban"))
        await session.commit()

    await message.answer(f"Пользователь {user_id} забанен на {label}." + (f"\nПричина: {reason}" if reason else ""))


@router.message(Command("unban"))
async def cmd_unban(message: Message, bot_row: Bot):
    async with async_session() as session:
        if not await is_bot_admin(session, bot_row, message.from_user.id):
            return
        if not message.text or " " not in message.text or not message.text.split()[1].isdigit():
            await message.answer("Формат: <code>/unban ID</code>")
            return
        user_id = int(message.text.split()[1])

        await session.execute(
            update(BotUser).where(BotUser.bot_id == bot_row.id, BotUser.tg_id == user_id).values(is_banned=False, ban_until=None, ban_reason=None)
        )
        session.add(BanLog(bot_id=bot_row.id, user_tg_id=user_id, admin_tg_id=message.from_user.id, action="unban"))
        await session.commit()
    await message.answer(f"Пользователь {user_id} разбанен.")


@router.message(Command("warn"))
async def cmd_warn(message: Message, bot_row: Bot):
    async with async_session() as session:
        if not await is_bot_admin(session, bot_row, message.from_user.id):
            return

        command = CommandObject(command="warn", args=message.text.split(maxsplit=1)[1] if " " in message.text else None)
        parsed = _parse_args(command, need_duration=False)
        if not parsed:
            await message.answer("Формат: <code>/warn ID причина</code>")
            return
        user_id, reason, _ = parsed

        result = await session.execute(select(BotUser).where(BotUser.bot_id == bot_row.id, BotUser.tg_id == user_id))
        user = result.scalar_one_or_none()
        if user is None:
            user = BotUser(bot_id=bot_row.id, tg_id=user_id)
            session.add(user)

        user.warns_count += 1
        session.add(Warn(bot_id=bot_row.id, user_tg_id=user_id, admin_tg_id=message.from_user.id, reason=reason))

        auto_banned = False
        if bot_row.warns_before_autoban and user.warns_count >= bot_row.warns_before_autoban:
            user.is_banned = True
            user.ban_reason = "Автобан: превышен лимит предупреждений"
            session.add(BanLog(bot_id=bot_row.id, user_tg_id=user_id, admin_tg_id=None, reason=user.ban_reason, action="ban"))
            auto_banned = True

        await session.commit()
        warns_count = user.warns_count

    text = f"Пользователю {user_id} выдан варн ({warns_count}/{bot_row.warns_before_autoban})."
    if reason:
        text += f"\nПричина: {reason}"
    if auto_banned:
        text += "\n\n⛔ Достигнут лимит варнов — пользователь автоматически забанен."
    await message.answer(text)


@router.message(Command("unwarn"))
async def cmd_unwarn(message: Message, bot_row: Bot):
    async with async_session() as session:
        if not await is_bot_admin(session, bot_row, message.from_user.id):
            return
        if not message.text or " " not in message.text or not message.text.split()[1].isdigit():
            await message.answer("Формат: <code>/unwarn ID</code>")
            return
        user_id = int(message.text.split()[1])

        result = await session.execute(select(BotUser).where(BotUser.bot_id == bot_row.id, BotUser.tg_id == user_id))
        user = result.scalar_one_or_none()
        if user is None or user.warns_count == 0:
            await message.answer("У пользователя нет активных варнов.")
            return
        user.warns_count -= 1

        last_warn = await session.execute(
            select(Warn).where(Warn.bot_id == bot_row.id, Warn.user_tg_id == user_id, Warn.is_active.is_(True)).order_by(Warn.created_at.desc()).limit(1)
        )
        w = last_warn.scalar_one_or_none()
        if w:
            w.is_active = False
        await session.commit()
        warns_count = user.warns_count

    await message.answer(f"Снят 1 варн у {user_id}. Осталось: {warns_count}/{bot_row.warns_before_autoban}.")
