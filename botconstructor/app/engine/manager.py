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


class RunningBot:
    def __init__(self, bot_row: BotRow, aiogram_bot: AiogramBot, task: asyncio.Task):
        self.bot_row = bot_row
        self.aiogram_bot = aiogram_bot
        self.task = task
        self.token = bot_row.token


class MultiBotManager:
    """ВАЖНО: используется ОДИН общий Dispatcher и ОДИН набор роутеров на все боты сразу —
    это единственно правильный способ в aiogram, т.к. Router можно прикрепить только
    к одному Dispatcher (иначе 'Router is already attached'). Какой именно bot_row
    относится к текущему апдейту, определяет BotContextMiddleware по bot.token.

    Менеджер синхронизирует список запущенных aiogram Bot-инстансов с таблицей `bots`
    в Postgres каждые BOT_POLL_INTERVAL секунд, следит за нагрузкой на каждого бота
    (load_monitor_loop) и автоматически останавливает бота при похожей на DDoS нагрузке."""

    def __init__(self):
        self._running: dict[int, RunningBot] = {}
        self._bot_rows_by_token: dict[str, BotRow] = {}
        self._usernames_by_token: dict[str, str] = {}
        self._stopping = False
        self._master_bot: AiogramBot | None = None

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

    async def start_bot(self, bot_row: BotRow) -> None:
        aiogram_bot = AiogramBot(
            token=bot_row.token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        me = await aiogram_bot.get_me()

        self._bot_rows_by_token[bot_row.token] = bot_row
        self._usernames_by_token[bot_row.token] = me.username

        async def _poll():
            try:
                await aiogram_bot.delete_webhook(drop_pending_updates=True)
                await self.dp.start_polling(aiogram_bot, handle_signals=False)
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("Bot id=%s упал с ошибкой, будет перезапущен на след. цикле синка", bot_row.id)

        task = asyncio.create_task(_poll(), name=f"bot-{bot_row.id}")
        self._running[bot_row.id] = RunningBot(bot_row, aiogram_bot, task)
        logger.info("Запущен бот id=%s (@%s)", bot_row.id, me.username)

    async def stop_bot(self, bot_id: int) -> None:
        running = self._running.pop(bot_id, None)
        if running is None:
            return
        self._bot_rows_by_token.pop(running.token, None)
        self._usernames_by_token.pop(running.token, None)
        running.task.cancel()
        try:
            await running.task
        except asyncio.CancelledError:
            pass
        await running.aiogram_bot.session.close()
        logger.info("Остановлен бот id=%s", bot_id)

    async def reload_bot(self, bot_row: BotRow) -> None:
        await self.stop_bot(bot_row.id)
        await self.start_bot(bot_row)

    async def sync_once(self) -> None:
        async with async_session() as session:
            result = await session.execute(select(BotRow).where(BotRow.is_active.is_(True)))
            active_bots = {b.id: b for b in result.scalars().all()}

        for bot_id in list(self._running.keys()):
            if bot_id not in active_bots:
                await self.stop_bot(bot_id)

        for bot_id, bot_row in active_bots.items():
            running = self._running.get(bot_id)
            if running is None:
                await self.start_bot(bot_row)
            elif running.token != bot_row.token:
                await self.reload_bot(bot_row)
            else:
                # настройки могли поменяться в БД — обновляем кэш, который читает
                # BotContextMiddleware на каждый апдейт (без пересоздания бота)
                self._bot_rows_by_token[bot_row.token] = bot_row
                running.bot_row = bot_row

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

        await self.stop_bot(bot_row.id)

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
            for bot_id, running in list(self._running.items()):
                count = load_last_10min(bot_id)
                if count > running.bot_row.ddos_threshold_msgs_10min:
                    logger.warning("Bot id=%s превысил порог нагрузки: %s сообщений/10мин", bot_id, count)
                    await self._auto_stop_bot(running.bot_row, count)

    async def shutdown(self) -> None:
        self._stopping = True
        for bot_id in list(self._running.keys()):
            await self.stop_bot(bot_id)
        if self._master_bot is not None:
            await self._master_bot.session.close()


manager = MultiBotManager()
