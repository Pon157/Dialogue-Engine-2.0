from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
 
class BotContextMiddleware(BaseMiddleware):
    """Единый Dispatcher обслуживает все боты сразу (см. manager.py). Поэтому bot_row
    нельзя один раз положить в workflow_data при старте — вместо этого на каждый апдейт
    подставляем актуальную строку из кэша менеджера по bot.token. Заодно это даёт
    бонус: изменения настроек в БД (welcome_text, антиспам и т.п.) подхватываются
    мгновенно, без пересоздания бота."""

    def __init__(self, manager):
        self.manager = manager

 
    def __init__(self, manager):
        self.manager = manager
 
    async def __call__(self, handler, event: TelegramObject, data: dict):
        bot = data["bot"]
        bot_row = self.manager.get_bot_row(bot.token)
        if bot_row is None:
            return  # бот уже остановлен/удалён между апдейтами — просто игнорируем
        data["bot_row"] = bot_row
        data["bot_username"] = self.manager.get_username(bot.token)
        return await handler(event, data)
