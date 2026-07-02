import asyncio
import logging

from aiogram import Bot as AiogramBot
from aiogram import Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy import select

from app.config import settings
from app.db import async_session
from app.engine.handlers.base import router as base_router
from app.models import Bot as BotRow

logger = logging.getLogger("multibot")


class RunningBot:
    def __init__(self, bot_row: BotRow, aiogram_bot: AiogramBot, dp: Dispatcher, task: asyncio.Task):
        self.bot_row = bot_row
        self.aiogram_bot = aiogram_bot
        self.dp = dp
        self.task = task
        self.token = bot_row.token


class MultiBotManager:
    """Держит в памяти словарь {bot_id: RunningBot} и синхронизирует его с таблицей `bots`
    в Postgres каждые BOT_POLL_INTERVAL секунд: новые/включённые боты — запускаются,
    отключённые/удалённые — останавливаются, у кого сменился токен — перезапускаются.
    Так добавление бота через админку конструктора (INSERT в таблицу bots) без перезапуска
    всего сервиса поднимает нового живого Telegram-бота.
    """

    def __init__(self):
        self._running: dict[int, RunningBot] = {}
        self._stopping = False

    async def start_bot(self, bot_row: BotRow) -> None:
        aiogram_bot = AiogramBot(
            token=bot_row.token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        dp = Dispatcher(storage=MemoryStorage())
        dp.include_router(base_router)

        # прокидываем строку конфигурации бота во все хэндлеры через workflow_data
        dp["bot_row"] = bot_row

        async def _poll():
            try:
                await aiogram_bot.delete_webhook(drop_pending_updates=True)
                await dp.start_polling(aiogram_bot, handle_signals=False)
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("Bot id=%s упал с ошибкой, будет перезапущен на след. цикле синка", bot_row.id)

        task = asyncio.create_task(_poll(), name=f"bot-{bot_row.id}")
        self._running[bot_row.id] = RunningBot(bot_row, aiogram_bot, dp, task)
        logger.info("Запущен бот id=%s (@%s)", bot_row.id, bot_row.username)

    async def stop_bot(self, bot_id: int) -> None:
        running = self._running.pop(bot_id, None)
        if running is None:
            return
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

        # остановить тех, кого больше нет в активных
        for bot_id in list(self._running.keys()):
            if bot_id not in active_bots:
                await self.stop_bot(bot_id)

        # запустить новых / перезапустить с изменённым токеном
        for bot_id, bot_row in active_bots.items():
            running = self._running.get(bot_id)
            if running is None:
                await self.start_bot(bot_row)
            elif running.token != bot_row.token:
                await self.reload_bot(bot_row)
            else:
                # настройки (welcome_text и т.п.) могли поменяться — обновляем workflow_data
                running.dp["bot_row"] = bot_row
                running.bot_row = bot_row

    async def sync_loop(self) -> None:
        while not self._stopping:
            try:
                await self.sync_once()
            except Exception:
                logger.exception("Ошибка синхронизации списка ботов с БД")
            await asyncio.sleep(settings.BOT_POLL_INTERVAL)

    async def shutdown(self) -> None:
        self._stopping = True
        for bot_id in list(self._running.keys()):
            await self.stop_bot(bot_id)


manager = MultiBotManager()
