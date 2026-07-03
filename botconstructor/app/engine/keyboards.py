from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.models import ButtonKind, InlineButton


def _make_button(b: InlineButton) -> InlineKeyboardButton:
    kwargs = {"text": b.text}
    if b.kind == ButtonKind.URL:
        kwargs["url"] = b.url
    else:
        kwargs["callback_data"] = f"trg:{b.trigger_key}"

    # style / icon_custom_emoji_id — поля Bot API 9.4. Если версия aiogram ещё их не
    # знает, конструктор упадёт с TypeError — тогда просто рендерим кнопку без цвета/иконки,
    # чтобы бот не переставал работать.
    extra = {}
    if b.style and b.style.value != "none":
        extra["style"] = b.style.value
    if b.icon_custom_emoji_id:
        extra["icon_custom_emoji_id"] = b.icon_custom_emoji_id

    try:
        return InlineKeyboardButton(**kwargs, **extra)
    except TypeError:
        return InlineKeyboardButton(**kwargs)


def build_inline_markup(buttons: list[InlineButton]) -> InlineKeyboardMarkup | None:
    if not buttons:
        return None
    rows: dict[int, list[InlineButton]] = {}
    for b in buttons:
        rows.setdefault(b.row, []).append(b)
    keyboard = [
        [_make_button(b) for b in sorted(row_buttons, key=lambda x: x.col)]
        for _, row_buttons in sorted(rows.items())
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)
