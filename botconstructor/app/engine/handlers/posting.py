from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select, update

from app.db import async_session
from app.emoji import tg
from app.engine.admin_check import is_bot_admin
from app.models import Bot, BotType, PostingSettings, PostReview

router = Router(name="posting")
router.message.filter(F.chat.type == "private")


async def _only_posting_bots(event, bot_row: Bot) -> bool:
    return bot_row.bot_type == BotType.POSTING


router.message.filter(_only_posting_bots)
router.callback_query.filter(_only_posting_bots)


def _review_kb(review_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=f"{tg('check','✅')} Опубликовать", callback_data=f"postrev:{review_id}:approve", style="success"),
                InlineKeyboardButton(text=f"{tg('cross','❌')} Отклонить", callback_data=f"postrev:{review_id}:reject", style="danger"),
            ]
        ]
    )


@router.message(F.text | F.photo | F.video)
async def submit_post(message: Message, bot_row: Bot):
    if bot_row.bot_type != BotType.POSTING:
        return  # не наш тип бота, пусть ловит base-роутер (support)
    if message.text and message.text.startswith("/"):
        return

    async with async_session() as session:
        result = await session.execute(select(PostingSettings).where(PostingSettings.bot_id == bot_row.id))
        settings_row = result.scalar_one_or_none()

        if settings_row is None or not settings_row.accept_posts:
            await message.answer("Приём постов сейчас отключён.")
            return

        media_file_id, media_type = None, None
        if message.photo:
            media_file_id, media_type = message.photo[-1].file_id, "photo"
        elif message.video:
            media_file_id, media_type = message.video.file_id, "video"

        review = PostReview(
            bot_id=bot_row.id,
            submitter_tg_id=message.from_user.id,
            original_text=message.html_text if message.text else (message.caption or ""),
            media_file_id=media_file_id,
            media_type=media_type,
        )
        session.add(review)
        await session.commit()
        await session.refresh(review)

        review_chat_id = settings_row.review_chat_id or bot_row.target_chat_id

    await message.answer("Пост отправлен на модерацию ✅")

    if not review_chat_id:
        return

    preview = review.original_text or ""
    caption = f"{tg('search','🔍')} Новый пост от {message.from_user.full_name} (ID {message.from_user.id}):\n\n{preview}"
    if review.media_file_id and review.media_type == "photo":
        await message.bot.send_photo(review_chat_id, review.media_file_id, caption=caption, reply_markup=_review_kb(review.id))
    elif review.media_file_id and review.media_type == "video":
        await message.bot.send_video(review_chat_id, review.media_file_id, caption=caption, reply_markup=_review_kb(review.id))
    else:
        await message.bot.send_message(review_chat_id, caption, reply_markup=_review_kb(review.id))


@router.callback_query(F.data.startswith("postrev:"))
async def review_decision(call: CallbackQuery, bot_row: Bot):
    _, review_id_str, action = call.data.split(":")
    review_id = int(review_id_str)

    async with async_session() as session:
        if not await is_bot_admin(session, bot_row, call.from_user.id):
            await call.answer("Недостаточно прав", show_alert=True)
            return

        result = await session.execute(select(PostReview).where(PostReview.id == review_id))
        review = result.scalar_one_or_none()
        if review is None or review.status != "pending":
            await call.answer("Уже обработано", show_alert=True)
            return

        if action == "approve":
            settings_result = await session.execute(select(PostingSettings).where(PostingSettings.bot_id == bot_row.id))
            settings_row = settings_result.scalar_one_or_none()
            template = settings_row.post_template if settings_row else "{text}"
            final_text = template.replace("{text}", review.original_text or "")

            if settings_row and settings_row.target_channel_id:
                if review.media_file_id and review.media_type == "photo":
                    await call.bot.send_photo(settings_row.target_channel_id, review.media_file_id, caption=final_text, parse_mode="HTML")
                elif review.media_file_id and review.media_type == "video":
                    await call.bot.send_video(settings_row.target_channel_id, review.media_file_id, caption=final_text, parse_mode="HTML")
                else:
                    await call.bot.send_message(settings_row.target_channel_id, final_text, parse_mode="HTML")

            review.status = "approved"
        else:
            review.status = "rejected"

        review.admin_tg_id = call.from_user.id
        from datetime import datetime, timezone

        review.reviewed_at = datetime.now(timezone.utc)
        await session.commit()

    label = "опубликован ✅" if action == "approve" else "отклонён ❌"
    await call.answer()
    try:
        await call.message.edit_reply_markup(reply_markup=None)
        await call.message.reply(f"Пост {label} (админ: {call.from_user.full_name})")
    except Exception:
        pass
