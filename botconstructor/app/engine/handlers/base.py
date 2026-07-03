"""Базовые хэндлеры, которые вешаются на КАЖДЫЙ созданный ботом инстанс.

Данные о конкретном боте (его настройки из таблицы Bot) прокидываются через
dispatcher["bot_row"] при регистрации (см. engine/manager.py), поэтому один и тот же
код хэндлеров обслуживает всех ботов сразу — это и есть суть мультибот-движка.
"""

from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from app.db import async_session
from app.emoji import tg
from app.engine.middlewares.antispam import check_captcha_answer
from app.engine.keyboards import build_inline_markup
from app.models import AdOrder, AdStatus, Bot, BotUser, InlineButton, MessageLog, Trigger

router = Router(name="base")


async def _get_active_ad_text() -> str | None:
    now = datetime.now(timezone.utc)
    async with async_session() as session:
        result = await session.execute(
            select(AdOrder)
            .where(AdOrder.status == AdStatus.ACTIVE, AdOrder.expires_at > now)
            .order_by(AdOrder.created_at.desc())
            .limit(1)
        )
        ad = result.scalar_one_or_none()
    if ad is None:
        return None
    return f"\n\n{tg('loudspeaker', '📣')} <i>{ad.text}</i>"


@router.callback_query(F.data.startswith("captcha:"))
async def captcha_answer(call: CallbackQuery, bot_row: Bot):
    _, bot_id_str, user_id_str, given = call.data.split(":", 3)
    bot_id, user_id = int(bot_id_str), int(user_id_str)

    if call.from_user.id != user_id:
        await call.answer("Это не ваша капча 🙂", show_alert=True)
        return

    if check_captcha_answer(bot_id, user_id, given):
        await call.message.delete()
        await call.answer("Проверка пройдена ✅")
        if bot_row.welcome_text:
            await call.message.answer(bot_row.welcome_text, parse_mode="HTML")
    else:
        await call.answer("Неверно, попробуйте ещё раз ❌", show_alert=True)


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

    welcome_text = bot_row.welcome_text or ""
    if bot_row.ads_in_welcome_enabled:
        ad_text = await _get_active_ad_text()
        if ad_text:
            welcome_text = f"{welcome_text}{ad_text}"

    async with async_session() as session:
        btn_result = await session.execute(
            select(InlineButton).where(InlineButton.bot_id == bot_row.id, InlineButton.context == "welcome")
        )
        welcome_buttons = btn_result.scalars().all()
    markup = build_inline_markup(welcome_buttons)

    if bot_row.welcome_photo_file_id:
        await message.answer_photo(
            bot_row.welcome_photo_file_id,
            caption=welcome_text,
            parse_mode="HTML",
            reply_markup=markup,
        )
    elif welcome_text:
        await message.answer(welcome_text, parse_mode="HTML", reply_markup=markup)


@router.callback_query(F.data.startswith("trg:"))
async def trigger_button(call: CallbackQuery, bot_row: Bot):
    key = call.data.split(":", 1)[1]
    async with async_session() as session:
        result = await session.execute(
            select(Trigger).where(Trigger.bot_id == bot_row.id, Trigger.key == key)
        )
        trg = result.scalar_one_or_none()
    if trg is None:
        await call.answer("Не настроено", show_alert=True)
        return
    await call.answer()
    if trg.response_photo_file_id:
        await call.message.answer_photo(trg.response_photo_file_id, caption=trg.response_text or "", parse_mode="HTML")
    elif trg.response_text:
        await call.message.answer(trg.response_text, parse_mode="HTML")


@router.message(F.text.regexp(r"^/\w+"))
async def any_command_trigger(message: Message, bot_row: Bot):
    """Ловит любые команды типа /price, заведённые владельцем как триггер-команды."""
    command = message.text.split()[0].split("@")[0]  # '/price'
    async with async_session() as session:
        result = await session.execute(
            select(Trigger).where(Trigger.bot_id == bot_row.id, Trigger.key == command)
        )
        trg = result.scalar_one_or_none()
    if trg is None:
        return
    if trg.response_photo_file_id:
        await message.answer_photo(trg.response_photo_file_id, caption=trg.response_text or "", parse_mode="HTML")
    elif trg.response_text:
        await message.answer(trg.response_text, parse_mode="HTML")



@router.message(Command("restart"))
async def cmd_restart(message: Message, bot_row: Bot):
    async with async_session() as session:
        user = await _get_or_create_bot_user(session, bot_row.id, message)
        user.has_open_ticket = True
        await session.commit()
    await message.answer("Новое обращение открыто ✅")


@router.message(F.text | F.photo | F.video | F.document | F.voice)
async def any_user_message(message: Message, bot_row: Bot):
    """Ловит любое сообщение от пользователя. Для support-ботов — пересылает/копирует
    в target_chat_id. Для posting-ботов приём постов на модерацию обрабатывается
    отдельным роутером (engine/handlers/posting.py), сюда он не долетает благодаря
    более высокому приоритету include_router в manager.py."""
    async with async_session() as session:
        user = await _get_or_create_bot_user(session, bot_row.id, message)

        if user.is_banned:
            if user.ban_until and user.ban_until <= datetime.now(timezone.utc):
                user.is_banned = False
                user.ban_until = None
                user.ban_reason = None
                await session.commit()
            else:
                return  # забаненный юзер игнорируется

        if bot_row.open_ticket_on_first_message and not user.has_open_ticket:
            user.has_open_ticket = True

        session.add(
            MessageLog(bot_id=bot_row.id, direction="in", user_tg_id=message.from_user.id)
        )
        await session.commit()

    if bot_row.bot_type.value != "support" or not bot_row.target_chat_id:
        return

    thread_id = None
    if bot_row.use_topics:
        async with async_session() as session:
            result = await session.execute(select(BotUser).where(BotUser.bot_id == bot_row.id, BotUser.tg_id == message.from_user.id))
            u = result.scalar_one()
            if u.active_topic_id is None:
                try:
                    topic = await message.bot.create_forum_topic(
                        bot_row.target_chat_id,
                        name=f"{message.from_user.full_name} (ID {message.from_user.id})",
                    )
                    u.active_topic_id = topic.message_thread_id
                    await session.commit()
                except Exception:
                    pass  # чат не форум/нет прав — просто шлём без топика
            thread_id = u.active_topic_id

    if bot_row.forward_mode.value == "forward":
        sent = await message.forward(bot_row.target_chat_id, message_thread_id=thread_id)
    else:
        header_parts = []
        if bot_row.copy_show_name:
            header_parts.append(message.from_user.full_name)
        if bot_row.copy_show_username and message.from_user.username:
            header_parts.append(f"@{message.from_user.username}")
        if bot_row.copy_show_id:
            header_parts.append(f"ID: {message.from_user.id}")
        header = " | ".join(header_parts)
        sent = await message.copy_to(bot_row.target_chat_id, caption=header if header else None, message_thread_id=thread_id)

    async with async_session() as session:
        session.add(TicketMessage(bot_id=bot_row.id, group_message_id=sent.message_id, user_tg_id=message.from_user.id))
        await session.commit()
