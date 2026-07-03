from collections import defaultdict
from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import func, select

from app.db import async_session
from app.emoji import tg
from app.engine.charts import draw_bar_chart
from app.models import Bot, BotUser, MessageLog, PostReview

router = Router(name="master_stats")


@router.callback_query(F.data.regexp(r"^bot:(\d+):stats$"))
async def stats(call: CallbackQuery):
    bot_id = int(call.data.split(":")[1])

    async with async_session() as session:
        bot_row = (await session.execute(select(Bot).where(Bot.id == bot_id, Bot.owner_tg_id == call.from_user.id))).scalar_one_or_none()
        if not bot_row:
            await call.answer("Бот не найден", show_alert=True)
            return

        total_users = (await session.execute(select(func.count()).select_from(BotUser).where(BotUser.bot_id == bot_id))).scalar()
        blocked_users = (await session.execute(select(func.count()).select_from(BotUser).where(BotUser.bot_id == bot_id, BotUser.is_blocked_bot.is_(True)))).scalar()
        banned_users = (await session.execute(select(func.count()).select_from(BotUser).where(BotUser.bot_id == bot_id, BotUser.is_banned.is_(True)))).scalar()
        total_messages = (await session.execute(select(func.count()).select_from(MessageLog).where(MessageLog.bot_id == bot_id))).scalar()

        now = datetime.now(timezone.utc)
        week_ago = now - timedelta(days=7)
        day_ago = now - timedelta(days=1)

        result = await session.execute(
            select(MessageLog.created_at).where(MessageLog.bot_id == bot_id, MessageLog.created_at >= week_ago)
        )
        per_day: dict[str, int] = defaultdict(int)
        for (created_at,) in result:
            per_day[created_at.strftime("%d.%m")] += 1
        labels = [(now - timedelta(days=i)).strftime("%d.%m") for i in range(6, -1, -1)]
        values = [per_day.get(lbl, 0) for lbl in labels]

        admin_rows = await session.execute(
            select(MessageLog.admin_tg_id, MessageLog.created_at)
            .where(MessageLog.bot_id == bot_id, MessageLog.direction == "out", MessageLog.admin_tg_id.is_not(None))
        )
        admin_total: dict[int, int] = defaultdict(int)
        admin_week: dict[int, int] = defaultdict(int)
        admin_day: dict[int, int] = defaultdict(int)
        for admin_id, created_at in admin_rows:
            admin_total[admin_id] += 1
            if created_at >= week_ago:
                admin_week[admin_id] += 1
            if created_at >= day_ago:
                admin_day[admin_id] += 1

        posts_published = None
        if bot_row.bot_type.value == "posting":
            posts_published = (
                await session.execute(select(func.count()).select_from(PostReview).where(PostReview.bot_id == bot_id, PostReview.status == "approved"))
            ).scalar()

    chart_png = draw_bar_chart(labels, values, "Сообщений в день (7 дней)")

    text = (
        f"{tg('chart','📊')} <b>Статистика @{bot_row.username}</b>\n\n"
        f"Пользователей всего: {total_users}\n"
        f"Заблокировали бота: {blocked_users}\n"
        f"Забанено: {banned_users}\n"
        f"Сообщений всего: {total_messages}\n"
    )
    if posts_published is not None:
        text += f"Постов опубликовано: {posts_published}\n"

    if admin_total:
        text += f"\n{tg('speaking','🗣️')} <b>По админам</b> (всего / неделя / сегодня):\n"
        for admin_id in admin_total:
            text += f"• <code>{admin_id}</code>: {admin_total[admin_id]} / {admin_week.get(admin_id, 0)} / {admin_day.get(admin_id, 0)}\n"

    await call.message.answer_photo(
        BufferedInputFile(chart_png, "stats.png"),
        caption=text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data=f"bot:{bot_id}")]]),
    )
    await call.answer()
