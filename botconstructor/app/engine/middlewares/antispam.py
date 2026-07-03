import random
import time
from collections import defaultdict, deque

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, TelegramObject

from app.engine.captcha import generate_captcha
from app.models import Bot as BotRow

# --- состояние в памяти процесса (на бот+юзера) ---
_request_windows: dict[tuple[int, int], deque] = defaultdict(deque)  # (bot_id, user_id) -> deque[timestamps]
_muted_until: dict[tuple[int, int], float] = {}
_msg_counters: dict[tuple[int, int], int] = defaultdict(int)  # для "капча каждые N сообщений"
_pending_captcha: dict[tuple[int, int], str] = {}  # (bot_id, user_id) -> правильный ответ

# --- счётчик нагрузки по боту целиком, читает load_monitor в manager.py ---
load_counters: dict[int, deque] = defaultdict(deque)  # bot_id -> deque[timestamps за последние 10 мин]


def register_load(bot_id: int) -> None:
    now = time.monotonic()
    dq = load_counters[bot_id]
    dq.append(now)
    cutoff = now - 600  # 10 минут
    while dq and dq[0] < cutoff:
        dq.popleft()


def load_last_10min(bot_id: int) -> int:
    dq = load_counters[bot_id]
    cutoff = time.monotonic() - 600
    while dq and dq[0] < cutoff:
        dq.popleft()
    return len(dq)


def _is_addressed_to_bot(message: Message, bot_username: str | None) -> bool:
    """В группах бот должен реагировать только когда к нему реально обращаются:
    команда/упоминание/реплай на его сообщение. Личку — всегда обрабатываем."""
    if message.chat.type == "private":
        return True

    if message.reply_to_message and message.reply_to_message.from_user and message.reply_to_message.from_user.is_bot:
        return True

    text = message.text or message.caption or ""
    if bot_username and f"@{bot_username}".lower() in text.lower():
        return True

    if text.startswith("/"):
        # /command@botname или просто /command в группе, где бот единственный админ-бот
        if bot_username and f"@{bot_username}".lower() in text.lower():
            return True
        # голая команда без упоминания в группе - пропускаем как не адресованную боту,
        # чтобы не триггериться на команды других ботов в том же чате
        return False

    return False


def _build_captcha_keyboard(bot_id: int, user_id: int, correct: str) -> InlineKeyboardMarkup:
    options = [correct]
    while len(options) < 4:
        fake = "".join(random.choices(correct, k=len(correct))) if random.random() < 0.5 else correct[::-1]
        fake = list(fake)
        random.shuffle(fake)
        fake = "".join(fake)
        if fake not in options:
            options.append(fake)
    random.shuffle(options)

    buttons = [
        InlineKeyboardButton(text=opt, callback_data=f"captcha:{bot_id}:{user_id}:{opt}")
        for opt in options
    ]
    return InlineKeyboardMarkup(inline_keyboard=[buttons])


class AntiSpamMiddleware(BaseMiddleware):
    """Вешается outer-мидлварью на Dispatcher каждого созданного бота.
    Настройки лимитов берутся из bot_row (задаются владельцем в панели)."""

    async def __call__(self, handler, event: TelegramObject, data: dict):
        bot_row: BotRow = data["bot_row"]

        if isinstance(event, CallbackQuery) and event.data and event.data.startswith("captcha:"):
            return await handler(event, data)  # ответы на капчу всегда пропускаем дальше в свой хэндлер

        if not isinstance(event, Message):
            return await handler(event, data)

        me = data.get("bot_username")  # прокидывается менеджером при старте бота
        if not _is_addressed_to_bot(event, me):
            return  # это переписка юзеров между собой в группе — бот не должен даже логировать это

        user_id = event.from_user.id
        key = (bot_row.id, user_id)

        register_load(bot_row.id)  # для DDoS-монитора считаем вообще все дошедшие до бота апдейты

        # --- активный мут после превышения лимита ---
        now = time.monotonic()
        if key in _muted_until:
            if now < _muted_until[key]:
                return  # молчим, юзер в антиспам-муте
            del _muted_until[key]

        # --- рейт-лимит ---
        if bot_row.antispam_enabled:
            dq = _request_windows[key]
            dq.append(now)
            cutoff = now - bot_row.antispam_window_seconds
            while dq and dq[0] < cutoff:
                dq.popleft()
            if len(dq) > bot_row.antispam_max_requests:
                _muted_until[key] = now + bot_row.antispam_mute_seconds
                try:
                    await event.answer(
                        f"Слишком много сообщений. Подождите {bot_row.antispam_mute_seconds} сек. ⏳"
                    )
                except Exception:
                    pass
                return

        # --- капча каждые N обращений ---
        if bot_row.captcha_enabled and bot_row.captcha_every_n > 0:
            _msg_counters[key] += 1
            if _msg_counters[key] % bot_row.captcha_every_n == 1:
                if key not in _pending_captcha:
                    answer, png = generate_captcha()
                    _pending_captcha[key] = answer
                    from aiogram.types import BufferedInputFile

                    await event.answer_photo(
                        BufferedInputFile(png, filename="captcha.png"),
                        caption="Подтвердите, что вы не бот — выберите правильный код:",
                        reply_markup=_build_captcha_keyboard(bot_row.id, user_id, answer),
                    )
                    return

        if key in _pending_captcha:
            return  # ждём, пока юзер пройдёт капчу — остальные сообщения игнорим

        return await handler(event, data)


def check_captcha_answer(bot_id: int, user_id: int, given: str) -> bool:
    key = (bot_id, user_id)
    correct = _pending_captcha.get(key)
    if correct is None:
        return True  # капчи не было в ожидании
    ok = given == correct
    if ok:
        _pending_captcha.pop(key, None)
    return ok
