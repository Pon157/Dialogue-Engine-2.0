from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.db import async_session
from app.emoji import tg
from app.master.states import BuyAd
from app.models import AD_MAX_TEXT_LEN, AD_PAYMENT_CONTACT, AD_TARIFFS, AdOrder, AdStatus

router = Router(name="master_ads")


def _tariffs_kb() -> InlineKeyboardMarkup:
    rows = []
    for idx, (label, hours, stars, rub) in enumerate(AD_TARIFFS):
        rows.append(
            [InlineKeyboardButton(text=f"{label} — {stars}⭐ / {rub}₽", callback_data=f"adstariff:{idx}")]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("ads"))
@router.callback_query(F.data == "ads_start")
async def ads_start(event: Message | CallbackQuery, state: FSMContext):
    await state.set_state(BuyAd.waiting_text)
    text = (
        f"{tg('loudspeaker','📣')} Покупка рекламы в приветственных сообщениях ботов.\n\n"
        f"Пришлите текст объявления — не более {AD_MAX_TEXT_LEN} символов."
    )
    if isinstance(event, CallbackQuery):
        await event.message.edit_text(text)
    else:
        await event.answer(text)


@router.message(BuyAd.waiting_text)
async def ads_text(message: Message, state: FSMContext):
    text = message.text.strip() if message.text else ""
    if not text or len(text) > AD_MAX_TEXT_LEN:
        await message.answer(f"Текст должен быть от 1 до {AD_MAX_TEXT_LEN} символов. Пришлите ещё раз.")
        return
    await state.update_data(text=text)
    await state.set_state(BuyAd.waiting_tariff)
    await message.answer("Выберите срок размещения:", reply_markup=_tariffs_kb())


@router.callback_query(BuyAd.waiting_tariff, F.data.startswith("adstariff:"))
async def ads_tariff(call: CallbackQuery, state: FSMContext):
    idx = int(call.data.split(":")[1])
    label, hours, stars, rub = AD_TARIFFS[idx]
    data = await state.get_data()

    async with async_session() as session:
        order = AdOrder(
            buyer_tg_id=call.from_user.id,
            buyer_username=call.from_user.username,
            text=data["text"],
            tariff_label=label,
            duration_hours=hours,
            price_stars=stars,
            price_rub=rub,
            status=AdStatus.PENDING_PAYMENT,
        )
        session.add(order)
        await session.commit()
        await session.refresh(order)

    await state.clear()
    await call.message.edit_text(
        f"{tg('check','✅')} Заявка №{order.id} создана.\n\n"
        f"Текст: «{order.text}»\nСрок: {label}\nЦена: {stars}⭐ ({rub}₽)\n\n"
        f"Для оплаты и запуска рекламы напишите {AD_PAYMENT_CONTACT}, указав номер заявки №{order.id}.\n"
        "После оплаты реклама появится в приветственных сообщениях ботов автоматически на весь оплаченный срок."
    )
