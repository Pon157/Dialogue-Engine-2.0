from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select

from app.db import async_session
from app.emoji import btn_emoji, tg
from app.master.states import CreateBot
from app.models import Bot, BotType

router = Router(name="master_menu")


def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"{btn_emoji('gear','⚙️')} Мои боты", callback_data="mybots")],
            [InlineKeyboardButton(text=f"{btn_emoji('plus','➕')} Создать бота", callback_data="createbot")],
            [InlineKeyboardButton(text=f"{btn_emoji('loudspeaker','📣')} Купить рекламу /ads", callback_data="ads_start")],
        ]
    )


@router.message(Command("start"))
async def start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        f"{tg('smile','🙂')} Привет! Это конструктор Telegram-ботов.\n"
        "Выбирай действие:",
        reply_markup=main_menu_kb(),
    )


@router.callback_query(F.data == "mainmenu")
async def back_to_main(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("Главное меню:", reply_markup=main_menu_kb())


@router.callback_query(F.data == "mybots")
async def my_bots(call: CallbackQuery):
    async with async_session() as session:
        result = await session.execute(select(Bot).where(Bot.owner_tg_id == call.from_user.id))
        bots = result.scalars().all()

    if not bots:
        await call.message.edit_text(
            "У вас пока нет ботов.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text=f"{btn_emoji('plus','➕')} Создать бота", callback_data="createbot")],
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="mainmenu")],
                ]
            ),
        )
        return

    rows = []
    for b in bots:
        status = btn_emoji("green_circle", "🟢") if b.is_active else btn_emoji("red_circle", "🔴")
        rows.append([InlineKeyboardButton(text=f"{status} @{b.username or b.id}", callback_data=f"bot:{b.id}")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="mainmenu")])
    await call.message.edit_text("Ваши боты:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data == "createbot")
async def create_bot_start(call: CallbackQuery, state: FSMContext):
    await state.set_state(CreateBot.waiting_token)
    await call.message.edit_text(
        "Пришлите токен бота, полученный от @BotFather.\n\n"
        "Токен выглядит так: <code>123456789:AAExampleTokenHere</code>",
    )


@router.message(CreateBot.waiting_token)
async def create_bot_token(message: Message, state: FSMContext):
    token = message.text.strip()
    if ":" not in token or len(token) < 20:
        await message.answer("Похоже, это не токен. Пришлите токен от @BotFather ещё раз.")
        return

    from aiogram import Bot as AiogramBot

    tmp_bot = AiogramBot(token=token)
    try:
        me = await tmp_bot.get_me()
    except Exception:
        await message.answer("Не удалось подключиться с этим токеном. Проверьте и пришлите снова.")
        return
    finally:
        await tmp_bot.session.close()

    async with async_session() as session:
        exists = await session.execute(select(Bot).where(Bot.token == token))
        if exists.scalar_one_or_none():
            await message.answer("Этот бот уже добавлен в конструктор.")
            await state.clear()
            return

    await state.update_data(token=token, username=me.username)
    await state.set_state(CreateBot.waiting_type)
    await message.answer(
        f"Бот @{me.username} найден ✅\nВыберите тип бота:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=f"{btn_emoji('chat','💬')} Общение / поддержка", callback_data="type:support")],
                [InlineKeyboardButton(text=f"{btn_emoji('loudspeaker','📣')} Постинг в канал", callback_data="type:posting")],
            ]
        ),
    )


@router.callback_query(CreateBot.waiting_type, F.data.startswith("type:"))
async def create_bot_type(call: CallbackQuery, state: FSMContext):
    bot_type = BotType.SUPPORT if call.data == "type:support" else BotType.POSTING
    data = await state.get_data()

    async with async_session() as session:
        new_bot = Bot(
            owner_tg_id=call.from_user.id,
            token=data["token"],
            username=data["username"],
            bot_type=bot_type,
        )
        session.add(new_bot)
        await session.commit()
        await session.refresh(new_bot)

    await state.clear()
    await call.message.edit_text(
        f"Готово! Бот @{data['username']} создан и через несколько секунд запустится "
        f"(движок сам подхватит его из БД).",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="⚙️ Настроить", callback_data=f"bot:{new_bot.id}")]]
        ),
    )
