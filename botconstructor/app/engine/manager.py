import asyncio
import logging

from aiogram import Bot as AiogramBot
from aiogram import Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy import select, update

from app.config import settings
from app.db import async_session
from app.engine.handlers.base import router as base_router
from app.engine.handlers.moderation import router as moderation_router
from app.engine.handlers.posting import router as posting_router
from app.engine.handlers.relay import router as relay_router
from app.engine.handlers.settings_commands import router as settings_router
from app.engine.middlewares.antispam import AntiSpamMiddleware, load_last_10min
from app.engine.middlewares.context import BotContextMiddleware
from app.models import Bot as BotRow

logger = logging.getLogger("multibot")


class MultiBotManager:
    """ВАЖНО: aiogram не поддерживает параллельные независимые dp.start_polling(bot)
    вызовы на одном Dispatcher — они не изолированы и мешают друг другу (отсюда баг
    "первый бот работает, второй нет"). Правильный способ — ОДИН вызов
    dp.start_polling(bot1, bot2, ..., botN) со всеми активными ботами сразу.
    При любом изменении набора ботов (добавили/удалили/сменили токен) — этот единственный
    polling-таск полностью перезапускается с новым списком ботов."""

    def __init__(self):
        self._aiogram_bots: dict[int, AiogramBot] = {}   # bot_id -> aiogram Bot
        self._bot_rows: dict[int, BotRow] = {}            # bot_id -> текущая строка из БД
        self._bot_rows_by_token: dict[str, BotRow] = {}
        self._usernames_by_token: dict[str, str] = {}
        self._polling_task: asyncio.Task | None = None
        self._stopping = False
        self._master_bot: AiogramBot | None = None
        self._resync_lock = asyncio.Lock()

        self.dp = Dispatcher(storage=MemoryStorage())
        self.dp.message.outer_middleware(AntiSpamMiddleware())
        self.dp.callback_query.outer_middleware(AntiSpamMiddleware())
        self.dp.update.outer_middleware(BotContextMiddleware(self))
        self.dp.include_router(settings_router)
        self.dp.include_router(moderation_router)
        self.dp.include_router(relay_router)
        self.dp.include_router(posting_router)
        self.dp.include_router(base_router)

    def get_bot_row(self, token: str) -> BotRow | None:
        return self._bot_rows_by_token.get(token)

    def get_username(self, token: str) -> str | None:
        return self._usernames_by_token.get(token)

    def _get_master_bot(self) -> AiogramBot:
        if self._master_bot is None:
            self._master_bot = AiogramBot(
                token=settings.MASTER_BOT_TOKEN,
                default=DefaultBotProperties(parse_mode=ParseMode.HTML),
            )
        return self._master_bot

    async def _restart_polling(self) -> None:
        """Останавливает текущий общий polling-таск (если был) и запускает новый
        со свежим списком self._aiogram_bots. Вызывается при ЛЮБОМ изменении набора ботов."""
        if self._polling_task is not None:
            self._polling_task.cancel()
            try:
                await self._polling_task
            except asyncio.CancelledError:
                pass
            self._polling_task = None

        if not self._aiogram_bots:
            return

        bots = list(self._aiogram_bots.values())
        for b in bots:
            try:
                await b.delete_webhook(drop_pending_updates=True)
            except Exception:
                logger.exception("Не удалось снять webhook у бота")

        async def _poll():
            try:
                await self.dp.start_polling(*bots, handle_signals=False)
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("Общий polling-таск упал с ошибкой")

        self._polling_task = asyncio.create_task(_poll(), name="multibot-polling")
        logger.info("Polling перезапущен, активных ботов: %s", len(bots))

    async def sync_once(self) -> None:
        async with self._resync_lock:
            async with async_session() as session:
                result = await session.execute(select(BotRow).where(BotRow.is_active.is_(True)))
                active_bots = {b.id: b for b in result.scalars().all()}

            changed = False

            # убрать тех, кого больше нет / выключили
            for bot_id in list(self._aiogram_bots.keys()):
                if bot_id not in active_bots:
                    aiogram_bot = self._aiogram_bots.pop(bot_id)
                    old_row = self._bot_rows.pop(bot_id, None)
                    if old_row:
                        self._bot_rows_by_token.pop(old_row.token, None)
                        self._usernames_by_token.pop(old_row.token, None)
                    await aiogram_bot.session.close()
                    changed = True
                    logger.info("Бот id=%s остановлен", bot_id)

            # добавить новых / пересоздать с изменённым токеном
            for bot_id, bot_row in active_bots.items():
                old_row = self._bot_rows.get(bot_id)
                if old_row is None:
                    aiogram_bot = AiogramBot(
                        token=bot_row.token,
                        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
                    )
                    try:
                        me = await aiogram_bot.get_me()
                    except Exception:
                        logger.exception("Не удалось подключиться к боту id=%s, пропускаем", bot_id)
                        await aiogram_bot.session.close()
                        continue
                    self._aiogram_bots[bot_id] = aiogram_bot
                    self._usernames_by_token[bot_row.token] = me.username
                    changed = True
                    logger.info("Добавлен новый бот id=%s (@%s)", bot_id, me.username)
                elif old_row.token != bot_row.token:
                    old_aiogram_bot = self._aiogram_bots.pop(bot_id)
                    await old_aiogram_bot.session.close()
                    self._bot_rows_by_token.pop(old_row.token, None)
                    self._usernames_by_token.pop(old_row.token, None)

                    aiogram_bot = AiogramBot(
                        token=bot_row.token,
                        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
                    )
                    me = await aiogram_bot.get_me()
                    self._aiogram_bots[bot_id] = aiogram_bot
                    self._usernames_by_token[bot_row.token] = me.username
                    changed = True

                self._bot_rows[bot_id] = bot_row
                self._bot_rows_by_token[bot_row.token] = bot_row

            if changed:
                await self._restart_polling()

    async def sync_loop(self) -> None:
        while not self._stopping:
            try:
                await self.sync_once()
            except Exception:
                logger.exception("Ошибка синхронизации списка ботов с БД")
            await asyncio.sleep(settings.BOT_POLL_INTERVAL)

    async def _auto_stop_bot(self, bot_row: BotRow, msgs_in_10min: int) -> None:
        reason = (
            f"Автоматически остановлен: за 10 минут поймано {msgs_in_10min} сообщений "
            f"(порог {bot_row.ddos_threshold_msgs_10min}). Похоже на спам/DDoS."
        )
        async with async_session() as session:
            await session.execute(
                update(BotRow)
                .where(BotRow.id == bot_row.id)
                .values(is_active=False, auto_stopped_reason=reason)
            )
            await session.commit()

        await self.sync_once()  # немедленно применяем остановку, не дожидаясь следующего цикла

        try:
            master = self._get_master_bot()
            await master.send_message(
                bot_row.owner_tg_id,
                (
                    f"⛔ Бот <b>@{bot_row.username or bot_row.id}</b> автоматически остановлен.\n\n"
                    f"{reason}\n\n"
                    "Вы можете снова включить его в панели управления после проверки — "
                    "рекомендуем включить/ужесточить антиспам и капчу перед повторным запуском."
                ),
            )
        except Exception:
            logger.exception("Не удалось уведомить владельца bot_id=%s об автоостановке", bot_row.id)

    async def load_monitor_loop(self) -> None:
        while not self._stopping:
            await asyncio.sleep(60)
            for bot_id, bot_row in list(self._bot_rows.items()):
                count = load_last_10min(bot_id)
                if count > bot_row.ddos_threshold_msgs_10min:
                    logger.warning("Bot id=%s превысил порог нагрузки: %s сообщений/10мин", bot_id, count)
                    await self._auto_stop_bot(bot_row, count)

    async def shutdown(self) -> None:
        self._stopping = True
        if self._polling_task is not None:
            self._polling_task.cancel()
            try:
                await self._polling_task
            except asyncio.CancelledError:
                pass
        for aiogram_bot in self._aiogram_bots.values():
            await aiogram_bot.session.close()
        if self._master_bot is not None:
            await self._master_bot.session.close()


manager = MultiBotManager()
