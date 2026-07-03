from aiogram.fsm.state import State, StatesGroup


class CreateBot(StatesGroup):
    waiting_token = State()
    waiting_type = State()


class EditWelcome(StatesGroup):
    waiting_text = State()


class EditAntispam(StatesGroup):
    waiting_max_requests = State()
    waiting_window = State()
    waiting_mute = State()
    waiting_captcha_every_n = State()
    waiting_ddos_threshold = State()


class AddButton(StatesGroup):
    waiting_content = State()   # ждём текст/эмодзи кнопки
    waiting_url = State()       # если кнопка типа url
    waiting_style = State()     # выбор цвета кнопки


class BuyAd(StatesGroup):
    waiting_text = State()
    waiting_tariff = State()


class Broadcast(StatesGroup):
    waiting_content = State()
    waiting_target = State()
