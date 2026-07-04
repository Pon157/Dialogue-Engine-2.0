from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select, update

from app.db import async_session
from app.emoji import btn_emoji, tg
from app.master.states import AddButton, EditAntispam, EditWelcome
from app.models import Bot, ButtonKind, ButtonStyle, ForwardMode, InlineButton

router = Router(name="master_bot")


async def _get_bot(bot_id: int, owner_tg_id: int) -> Bot | None:
    async with async_session() as session:
        result = await session.execute(
            select(Bot).where(Bot.id == bot_id, Bot.owner_tg_id == owner_tg_id)
        )
        return result.scalar_one_or_none()


def bot_menu_kb(b: Bot) -> InlineKeyboardMarkup:
    toggle_text = f"{btn_emoji('red_circle','🔴')} Выключить" if b.is_active else f"{btn_emoji('green_circle','🟢')} Включить"
    antispam_text = f"{btn_emoji('shield','🛡')} Антиспам: {'вкл' if b.antispam_enabled else 'выкл'}"
    captcha_text = f"{btn_emoji('lock','🔒')} Капча: {'вкл' if b.captcha_enabled else 'выкл'}"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=toggle_text, callback_data=f"bot:{b.id}:toggle")],
            [InlineKeyboardButton(text=f"{btn_emoji('pencil','✏️')} Приветственный текст", callback_data=f"bot:{b.id}:welcome")],
            [InlineKeyboardButton(text=antispam_text, callback_data=f"bot:{b.id}:antispam")],
            [InlineKeyboardButton(text=captcha_text, callback_data=f"bot:{b.id}:captcha")],
            [InlineKeyboardButton(text=f"{btn_emoji('plus','➕')} Добавить inline-кнопку", callback_data=f"bot:{b.id}:addbtn")],
            [InlineKeyboardButton(text=f"{btn_emoji('loudspeaker','📣')} Рассылка", callback_data=f"bot:{b.id}:broadcast")],
            [InlineKeyboardButton(text=f"{btn_emoji('chart','📊')} Статистика", callback_data=f"bot:{b.id}:stats")],
            [InlineKeyboardButton(text=f"{btn_emoji('link','🔗')} Пересылка/копирование", callback_data=f"bot:{b.id}:forward")],
            [InlineKeyboardButton(text=f"{btn_emoji('dollar','💵')} Донат", callback_data=f"bot:{b.id}:donate")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="mybots")],
        ]
    )


@router.callback_query(F.data.regexp(r"^bot:(\d+)$"))
async def bot_menu(call: CallbackQuery):
    bot_id = int(call.data.split(":")[1])
    b = await _get_bot(bot_id, call.from_user.id)
    if not b:
        await call.answer("Бот не найден", show_alert=True)
        return
    status = "работает" if b.is_active else "остановлен"
    extra = f"\n\n{tg('warning','⚠️')} {b.auto_stopped_reason}" if b.auto_stopped_reason else ""
    hint = (
        f"\n\n<i>Чтобы назначить чат обращений — отправьте /setchat в нужной группе.\n"
        f"Чтобы назначить канал для постинга — перешлите любой пост из канала боту в личку.\n"
        f"Чтобы назначить группу модерации — отправьте /setreviewchat в этой группе.</i>"
    )
    await call.message.edit_text(f"Бот @{b.username} — {status}{extra}{hint}", reply_markup=bot_menu_kb(b), parse_mode="HTML")


def forward_kb(b: Bot) -> InlineKeyboardMarkup:
    mode_label = "Пересылка (forward)" if b.forward_mode.value == "forward" else "Копирование (copy)"
    rows = [
        [InlineKeyboardButton(text=f"Режим: {mode_label} (нажмите, чтобы сменить)", callback_data=f"bot:{b.id}:forward:toggle_mode")],
    ]
    if b.forward_mode.value == "copy":
        rows += [
            [InlineKeyboardButton(text=f"Показывать имя: {'да' if b.copy_show_name else 'нет'}", callback_data=f"bot:{b.id}:forward:toggle_name")],
            [InlineKeyboardButton(text=f"Показывать @username: {'да' if b.copy_show_username else 'нет'}", callback_data=f"bot:{b.id}:forward:toggle_username")],
            [InlineKeyboardButton(text=f"Показывать ID: {'да' if b.copy_show_id else 'нет'}", callback_data=f"bot:{b.id}:forward:toggle_id")],
        ]
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"bot:{b.id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data.regexp(r"^bot:(\d+):forward$"))
async def forward_menu(call: CallbackQuery):
    bot_id = int(call.data.split(":")[1])
    b = await _get_bot(bot_id, call.from_user.id)
    if not b:
        return
    await call.message.edit_text(
        "Настройки пересылки обращений в чат обращений.\n"
        "«Пересылка» сохраняет исходное сообщение как forward (виден автор для Telegram, "
        "но не редактируется). «Копирование» шлёт копию с настраиваемой шапкой.",
        reply_markup=forward_kb(b),
    )


@router.callback_query(F.data.regexp(r"^bot:(\d+):forward:toggle_(mode|name|username|id)$"))
async def forward_toggle(call: CallbackQuery):
    bot_id = int(call.data.split(":")[1])
    field = call.data.split(":")[-1]
    b = await _get_bot(bot_id, call.from_user.id)
    if not b:
        return

    async with async_session() as session:
        if field == "mode":
            new_mode = ForwardMode.COPY if b.forward_mode == ForwardMode.FORWARD else ForwardMode.FORWARD
            await session.execute(update(Bot).where(Bot.id == bot_id).values(forward_mode=new_mode))
            b.forward_mode = new_mode
        else:
            col = {"name": "copy_show_name", "username": "copy_show_username", "id": "copy_show_id"}[field]
            new_val = not getattr(b, col)
            await session.execute(update(Bot).where(Bot.id == bot_id).values(**{col: new_val}))
            setattr(b, col, new_val)
        await session.commit()

    await call.message.edit_text("Настройки пересылки обновлены:", reply_markup=forward_kb(b))


def donate_kb(b: Bot) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text=f"Донат: {'ВКЛ' if b.donate_enabled else 'ВЫКЛ'} (нажмите, чтобы переключить)",
                callback_data=f"bot:{b.id}:donate:toggle",
            )],
            [InlineKeyboardButton(
                text=f"Тип кнопки: {b.donate_button_kind or 'inline'} (нажмите, чтобы сменить)",
                callback_data=f"bot:{b.id}:donate:kind",
            )],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"bot:{b.id}")],
        ]
    )


@router.callback_query(F.data.regexp(r"^bot:(\d+):donate$"))
async def donate_menu(call: CallbackQuery):
    bot_id = int(call.data.split(":")[1])
    b = await _get_bot(bot_id, call.from_user.id)
    if not b:
        return
    await call.message.edit_text(
        f"{tg('dollar','💵')} Донат через Telegram Stars: пользователь сам вводит "
        "количество звёзд, бот присылает счёт (invoice) на оплату.",
        reply_markup=donate_kb(b),
        parse_mode="HTML",
    )


@router.callback_query(F.data.regexp(r"^bot:(\d+):donate:toggle$"))
async def donate_toggle(call: CallbackQuery):
    bot_id = int(call.data.split(":")[1])
    b = await _get_bot(bot_id, call.from_user.id)
    if not b:
        return
    async with async_session() as session:
        await session.execute(update(Bot).where(Bot.id == bot_id).values(donate_enabled=not b.donate_enabled))
        await session.commit()
    b.donate_enabled = not b.donate_enabled
    await call.message.edit_text("Настройки доната обновлены:", reply_markup=donate_kb(b))


@router.callback_query(F.data.regexp(r"^bot:(\d+):donate:kind$"))
async def donate_kind_toggle(call: CallbackQuery):
    bot_id = int(call.data.split(":")[1])
    b = await _get_bot(bot_id, call.from_user.id)
    if not b:
        return
    new_kind = "keyboard" if (b.donate_button_kind or "inline") == "inline" else "inline"
    async with async_session() as session:
        await session.execute(update(Bot).where(Bot.id == bot_id).values(donate_button_kind=new_kind))
        await session.commit()
    b.donate_button_kind = new_kind
    await call.message.edit_text("Настройки доната обновлены:", reply_markup=donate_kb(b))


@router.callback_query(F.data.regexp(r"^bot:(\d+):toggle$"))
async def bot_toggle(call: CallbackQuery):
    bot_id = int(call.data.split(":")[1])
    b = await _get_bot(bot_id, call.from_user.id)
    if not b:
        await call.answer("Бот не найден", show_alert=True)
        return
    async with async_session() as session:
        await session.execute(
            update(Bot).where(Bot.id == bot_id).values(is_active=not b.is_active, auto_stopped_reason=None)
        )
        await session.commit()
    b.is_active = not b.is_active
    await call.answer("Готово")
    await call.message.edit_text(f"Бот @{b.username} — {'работает' if b.is_active else 'остановлен'}", reply_markup=bot_menu_kb(b))


# ---------- приветственный текст ----------

@router.callback_query(F.data.regexp(r"^bot:(\d+):welcome$"))
async def welcome_start(call: CallbackQuery, state: FSMContext):
    bot_id = int(call.data.split(":")[1])
    await state.update_data(bot_id=bot_id)
    await state.set_state(EditWelcome.waiting_text)
    await call.message.edit_text(
        "Пришлите новый приветственный текст. Поддерживается HTML-форматирование "
        "(<b>жирный</b>, <i>курсив</i>, готовые эмодзи прямо в тексте) и фото — "
        "просто пришлите фото с этим текстом в подписи."
    )


@router.message(EditWelcome.waiting_text)
async def welcome_save(message: Message, state: FSMContext):
    data = await state.get_data()
    bot_id = data["bot_id"]
    text = message.html_text if message.text else (message.caption or "")
    photo_id = message.photo[-1].file_id if message.photo else None

    async with async_session() as session:
        await session.execute(
            update(Bot).where(Bot.id == bot_id).values(welcome_text=text, welcome_photo_file_id=photo_id)
        )
        await session.commit()

    await state.clear()
    await message.answer("Приветственный текст сохранён ✅")


# ---------- антиспам ----------

def antispam_kb(b: Bot) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text=f"Антиспам: {'ВКЛ' if b.antispam_enabled else 'ВЫКЛ'} (нажмите чтобы переключить)",
                callback_data=f"bot:{b.id}:antispam:toggle",
            )],
            [InlineKeyboardButton(
                text=f"Лимит: {b.antispam_max_requests} запросов / {b.antispam_window_seconds} сек",
                callback_data=f"bot:{b.id}:antispam:setlimit",
            )],
            [InlineKeyboardButton(
                text=f"Мут после превышения: {b.antispam_mute_seconds} сек",
                callback_data=f"bot:{b.id}:antispam:setmute",
            )],
            [InlineKeyboardButton(
                text=f"Порог автостопа бота: {b.ddos_threshold_msgs_10min} сообщ. / 10 мин",
                callback_data=f"bot:{b.id}:antispam:setddos",
            )],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"bot:{b.id}")],
        ]
    )


@router.callback_query(F.data.regexp(r"^bot:(\d+):antispam$"))
async def antispam_menu(call: CallbackQuery):
    bot_id = int(call.data.split(":")[1])
    b = await _get_bot(bot_id, call.from_user.id)
    if not b:
        return
    await call.message.edit_text("Настройки антиспама:", reply_markup=antispam_kb(b))


@router.callback_query(F.data.regexp(r"^bot:(\d+):antispam:toggle$"))
async def antispam_toggle(call: CallbackQuery):
    bot_id = int(call.data.split(":")[1])
    b = await _get_bot(bot_id, call.from_user.id)
    if not b:
        return
    async with async_session() as session:
        await session.execute(update(Bot).where(Bot.id == bot_id).values(antispam_enabled=not b.antispam_enabled))
        await session.commit()
    b.antispam_enabled = not b.antispam_enabled
    await call.message.edit_text("Настройки антиспама:", reply_markup=antispam_kb(b))


@router.callback_query(F.data.regexp(r"^bot:(\d+):antispam:setlimit$"))
async def antispam_setlimit_start(call: CallbackQuery, state: FSMContext):
    bot_id = int(call.data.split(":")[1])
    await state.update_data(bot_id=bot_id)
    await state.set_state(EditAntispam.waiting_max_requests)
    await call.message.edit_text(
        "Пришлите лимит в формате <code>кол-во запросов/секунды окна</code>, например:\n<code>5/10</code>\n"
        "(не больше 5 запросов за 10 секунд от одного пользователя)"
    )


@router.message(EditAntispam.waiting_max_requests)
async def antispam_setlimit_save(message: Message, state: FSMContext):
    data = await state.get_data()
    try:
        count_str, window_str = message.text.strip().split("/")
        count, window = int(count_str), int(window_str)
        assert count > 0 and window > 0
    except Exception:
        await message.answer("Неверный формат. Пример: <code>5/10</code>")
        return

    async with async_session() as session:
        await session.execute(
            update(Bot).where(Bot.id == data["bot_id"]).values(antispam_max_requests=count, antispam_window_seconds=window)
        )
        await session.commit()
    await state.clear()
    await message.answer(f"Сохранено: не больше {count} запросов за {window} сек ✅")


@router.callback_query(F.data.regexp(r"^bot:(\d+):antispam:setmute$"))
async def antispam_setmute_start(call: CallbackQuery, state: FSMContext):
    bot_id = int(call.data.split(":")[1])
    await state.update_data(bot_id=bot_id)
    await state.set_state(EditAntispam.waiting_mute)
    await call.message.edit_text("Пришлите, на сколько секунд молчать пользователю после превышения лимита (число):")


@router.message(EditAntispam.waiting_mute)
async def antispam_setmute_save(message: Message, state: FSMContext):
    data = await state.get_data()
    if not message.text.strip().isdigit():
        await message.answer("Пришлите число секунд.")
        return
    seconds = int(message.text.strip())
    async with async_session() as session:
        await session.execute(update(Bot).where(Bot.id == data["bot_id"]).values(antispam_mute_seconds=seconds))
        await session.commit()
    await state.clear()
    await message.answer(f"Сохранено: мут {seconds} сек ✅")


@router.callback_query(F.data.regexp(r"^bot:(\d+):antispam:setddos$"))
async def antispam_setddos_start(call: CallbackQuery, state: FSMContext):
    bot_id = int(call.data.split(":")[1])
    await state.update_data(bot_id=bot_id)
    await state.set_state(EditAntispam.waiting_ddos_threshold)
    await call.message.edit_text(
        "Пришлите порог автоостановки бота: сколько ВСЕГО входящих сообщений за 10 минут "
        "считать признаком DDoS/спам-атаки (число, по умолчанию 600):"
    )


@router.message(EditAntispam.waiting_ddos_threshold)
async def antispam_setddos_save(message: Message, state: FSMContext):
    data = await state.get_data()
    if not message.text.strip().isdigit():
        await message.answer("Пришлите число.")
        return
    threshold = int(message.text.strip())
    async with async_session() as session:
        await session.execute(update(Bot).where(Bot.id == data["bot_id"]).values(ddos_threshold_msgs_10min=threshold))
        await session.commit()
    await state.clear()
    await message.answer(f"Сохранено: автостоп при {threshold}+ сообщ./10 мин ✅")


# ---------- капча ----------

def captcha_kb(b: Bot) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text=f"Капча: {'ВКЛ' if b.captcha_enabled else 'ВЫКЛ'} (нажмите чтобы переключить)",
                callback_data=f"bot:{b.id}:captcha:toggle",
            )],
            [InlineKeyboardButton(
                text=f"Показывать каждые {b.captcha_every_n or 1} обращений",
                callback_data=f"bot:{b.id}:captcha:setn",
            )],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"bot:{b.id}")],
        ]
    )


@router.callback_query(F.data.regexp(r"^bot:(\d+):captcha$"))
async def captcha_menu(call: CallbackQuery):
    bot_id = int(call.data.split(":")[1])
    b = await _get_bot(bot_id, call.from_user.id)
    if not b:
        return
    await call.message.edit_text(
        f"{tg('lock','🔒')} Капча на Pillow (наклонные буквы/цифры), показывается каждые N обращений юзера.",
        reply_markup=captcha_kb(b),
    )


@router.callback_query(F.data.regexp(r"^bot:(\d+):captcha:toggle$"))
async def captcha_toggle(call: CallbackQuery):
    bot_id = int(call.data.split(":")[1])
    b = await _get_bot(bot_id, call.from_user.id)
    if not b:
        return
    new_val = not b.captcha_enabled
    async with async_session() as session:
        values = {"captcha_enabled": new_val}
        if new_val and b.captcha_every_n == 0:
            values["captcha_every_n"] = 1
        await session.execute(update(Bot).where(Bot.id == bot_id).values(**values))
        await session.commit()
    b.captcha_enabled = new_val
    await call.message.edit_text("Настройки капчи обновлены:", reply_markup=captcha_kb(b))


@router.callback_query(F.data.regexp(r"^bot:(\d+):captcha:setn$"))
async def captcha_setn_start(call: CallbackQuery, state: FSMContext):
    bot_id = int(call.data.split(":")[1])
    await state.update_data(bot_id=bot_id)
    await state.set_state(EditAntispam.waiting_captcha_every_n)
    await call.message.edit_text("Пришлите число N — показывать капчу каждые N обращений от юзера:")


@router.message(EditAntispam.waiting_captcha_every_n)
async def captcha_setn_save(message: Message, state: FSMContext):
    data = await state.get_data()
    if not message.text.strip().isdigit():
        await message.answer("Пришлите число.")
        return
    n = int(message.text.strip())
    async with async_session() as session:
        await session.execute(update(Bot).where(Bot.id == data["bot_id"]).values(captcha_every_n=n, captcha_enabled=True))
        await session.commit()
    await state.clear()
    await message.answer(f"Сохранено: капча каждые {n} обращений ✅")


# ---------- конструктор inline-кнопок с premium emoji + style ----------

@router.callback_query(F.data.regexp(r"^bot:(\d+):addbtn$"))
async def addbtn_start(call: CallbackQuery, state: FSMContext):
    bot_id = int(call.data.split(":")[1])
    await state.update_data(bot_id=bot_id)
    await state.set_state(AddButton.waiting_content)
    await call.message.edit_text(
        "Пришлите ГОТОВЫЙ текст кнопки — можно с обычным или премиум-эмодзи "
        "(просто вставьте эмодзи из клавиатуры Telegram как обычно, если он премиумный — "
        "я сам заберу его emoji-id). Пример: «🔥 Горячее предложение»."
    )


@router.message(AddButton.waiting_content)
async def addbtn_content(message: Message, state: FSMContext):
    icon_id = None
    if message.entities:
        for ent in message.entities:
            if ent.type == "custom_emoji":
                icon_id = ent.custom_emoji_id
                break

    await state.update_data(text=message.text or "", icon_custom_emoji_id=icon_id)
    await state.set_state(AddButton.waiting_url)
    await message.answer(
        "Это кнопка-ссылка или кнопка-триггер?",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔗 Ссылка", callback_data="addbtn:url")],
                [InlineKeyboardButton(text="⚡ Триггер", callback_data="addbtn:trigger")],
            ]
        ),
    )


@router.callback_query(AddButton.waiting_url, F.data.in_({"addbtn:url", "addbtn:trigger"}))
async def addbtn_kind(call: CallbackQuery, state: FSMContext):
    kind = "url" if call.data == "addbtn:url" else "trigger"
    await state.update_data(kind=kind)
    if kind == "url":
        await call.message.edit_text("Пришлите ссылку (https://...):")
        return  # ждём текстовое сообщение — см. addbtn_url_value ниже
    await state.set_state(AddButton.waiting_style)
    await call.message.edit_text("Выберите цвет кнопки (Bot API 9.4):", reply_markup=_style_kb())


def _style_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⚪ Обычная", callback_data="style:none"),
                InlineKeyboardButton(text="🔵 Primary", callback_data="style:primary"),
            ],
            [
                InlineKeyboardButton(text="🟢 Success", callback_data="style:success"),
                InlineKeyboardButton(text="🔴 Danger", callback_data="style:danger"),
            ],
        ]
    )


@router.message(AddButton.waiting_url)
async def addbtn_url_value(message: Message, state: FSMContext):
    data = await state.get_data()
    if data.get("kind") != "url":
        return
    url = message.text.strip()
    if not url.startswith("http"):
        await message.answer("Пришлите корректную ссылку, начинающуюся с http(s)://")
        return
    await state.update_data(url=url)
    await state.set_state(AddButton.waiting_style)
    await message.answer("Выберите цвет кнопки (Bot API 9.4):", reply_markup=_style_kb())


@router.callback_query(AddButton.waiting_style, F.data.startswith("style:"))
async def addbtn_style(call: CallbackQuery, state: FSMContext):
    style = ButtonStyle(call.data.split(":")[1])
    data = await state.get_data()

    async with async_session() as session:
        btn = InlineButton(
            bot_id=data["bot_id"],
            context="menu",
            text=data["text"],
            kind=ButtonKind(data["kind"]),
            url=data.get("url"),
            trigger_key=f"btn_{data['bot_id']}_{data['text'][:16]}" if data["kind"] == "trigger" else None,
            style=style,
            icon_custom_emoji_id=data.get("icon_custom_emoji_id"),
        )
        session.add(btn)
        await session.commit()

    await state.clear()
    await call.message.edit_text(
        f"Кнопка «{data['text']}» добавлена ✅ (стиль: {style.value})",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="⬅️ К настройкам бота", callback_data=f"bot:{data['bot_id']}")]]
        ),
    )
