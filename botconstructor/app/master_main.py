import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from app.config import settings
from app.master.ads import router as ads_router
from app.master.broadcast import router as broadcast_router
from app.master.handlers_bot import router as bot_router
from app.master.handlers_menu import router as menu_router
from app.master.stats import router as stats_router


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")

    bot = Bot(token=settings.MASTER_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(menu_router)
    dp.include_router(bot_router)
    dp.include_router(broadcast_router)
    dp.include_router(stats_router)
    dp.include_router(ads_router)

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
