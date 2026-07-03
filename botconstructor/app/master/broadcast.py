import asyncio
from datetime import datetime, timedelta, timezone

from aiogram import Bot as AiogramBot
from aiogram import F, Router
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select

from app.db import async_session
from app.emoji import tg
from app.master.states import Broadcast as BroadcastState
from app.models import Bot, BotUser, Broadcast, MessageLog

router = Router(name="master_broadcast")

ACTIVE_WINDOW_DAYS = 30


@router.callback_query(F.data.regexp(r"^bot:(\d+):broadcast$"))
async def broadcast_start(call: CallbackQuery, state: FSMContext):
    bot_id = int(call.data.split(":")[1])
    await state.update_data(bot_id=bot_id)
    await state.set_state(BroadcastState.waiting_content)
    await call.message.edit_text(
        "Пришлите содержимое рассылки: текст, или фото/видео с подписью.\n"
        "Форматирование (HTML) сохранится как есть."
    )


@router.message(BroadcastState.waiting_content)
async def broadcast_content(message: Message, state: FSMContext):
    content = {
        "text": message.html_text if message.text else (message.caption or ""),
        "media_type": None,
        "media_bytes": None,
    }
    if message.photo:
        content["media_type"] = "photo"
        content["media_bytes"] = (await message.bot.download(message.photo[-1].file_id)).read()
    elif message.video:
        content["media_type"] = "video"
        content["media_bytes"] = (await message.bot.download(message.video.file_id)).read()

    await state.update_data(**content)
    await state.set_state(BroadcastState.waiting_target)
    await message.answer(
        "Кому отправить?",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=f"{tg('house','👥')} Всем пользователям", callback_data="bcast:all")],
                [InlineKeyboardButton(text=f"{tg('fire','🔥')} Только активным", callback_data="bcast:active")],
            ]
        ),
    )


@router.callback_query(BroadcastState.waiting_target, F.data.startswith("bcast:"))
async def broadcast_target(call: CallbackQuery, state: FSMContext):
    target = call.data.split(":")[1]
    data = await state.get_data()

    async with async_session() as session:
        order = Broadcast(
            bot_id=data["bot_id"],
            admin_tg_id=call.from_user.id,
            text=data.get("text") or None,
            media_type=data.get("media_type"),
            target=target,
            status="running",
        )
        session.add(order)
        await session.commit()
        await session.refresh(order)
        bot_row_result = await session.execute(select(Bot).where(Bot.id == data["bot_id"]))
        bot_row = bot_row_result.scalar_one()

    await state.clear()
    await call.message.edit_text(f"Рассылка №{order.id} запущена, это может занять время ⏳")

    asyncio.create_task(
        _run_broadcast(bot_row, order.id, data.get("text"), data.get("media_type"), data.get("media_bytes"), target)
    )


async def _run_broadcast(bot_row: Bot, order_id: int, text: str | None, media_type: str | None, media_bytes: bytes | None, target: str):
    async with async_session() as session:
        query = select(BotUser).where(BotUser.bot_id == bot_row.id, BotUser.is_blocked_bot.is_(False), BotUser.is_banned.is_(False))
        if target == "active":
            cutoff = datetime.now(timezone.utc) - timedelta(days=ACTIVE_WINDOW_DAYS)
            query = query.where(BotUser.last_seen >= cutoff)
        result = await session.execute(query)
        users = result.scalars().all()

    temp_bot = AiogramBot(token=bot_row.token)
    sent, failed = 0, 0
    try:
        for user in users:
            try:
                if media_type == "photo":
                    await temp_bot.send_photo(user.tg_id, BufferedInputFile(media_bytes, "broadcast.jpg"), caption=text, parse_mode="HTML")
                elif media_type == "video":
                    await temp_bot.send_video(user.tg_id, BufferedInputFile(media_bytes, "broadcast.mp4"), caption=text, parse_mode="HTML")
                else:
                    await temp_bot.send_message(user.tg_id, text or "", parse_mode="HTML")
                sent += 1
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after)
                failed += 1
            except TelegramForbiddenError:
                failed += 1
                async with async_session() as session:
                    result = await session.execute(select(BotUser).where(BotUser.id == user.id))
                    fresh = result.scalar_one()
                    fresh.is_blocked_bot = True
                    await session.commit()
            except Exception:
                failed += 1
            await asyncio.sleep(0.05)  # грубая защита от флуд-лимитов Telegram (~20 msg/sec)
    finally:
        await temp_bot.session.close()

    async with async_session() as session:
        session.add(MessageLog(bot_id=bot_row.id, direction="out", admin_tg_id=None))
        result = await session.execute(select(Broadcast).where(Broadcast.id == order_id))
        order = result.scalar_one()
        order.sent_count = sent
        order.failed_count = failed
        order.status = "done"
        admin_tg_id = order.admin_tg_id
        await session.commit()

    try:
        notify_bot = AiogramBot(token=bot_row.token)
        await notify_bot.send_message(
            admin_tg_id,
            f"{tg('check','✅')} Рассылка №{order_id} завершена.\nДоставлено: {sent}\nНе доставлено: {failed}",
        )
        await notify_bot.session.close()
    except Exception:
        pass
