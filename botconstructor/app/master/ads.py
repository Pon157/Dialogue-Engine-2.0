from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.config import settings
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


@router.message(Command("approve_ad"))
async def approve_ad(message: Message):
    if message.from_user.id not in settings.platform_admin_ids:
        return
    if not message.text or " " not in message.text or not message.text.split()[1].isdigit():
        await message.answer("Формат: <code>/approve_ad ID</code>")
        return
    order_id = int(message.text.split()[1])

    async with async_session() as session:
        result = await session.execute(select(AdOrder).where(AdOrder.id == order_id))
        order = result.scalar_one_or_none()
        if order is None:
            await message.answer("Заявка не найдена.")
            return
        if order.status != AdStatus.PENDING_PAYMENT:
            await message.answer(f"Заявка уже в статусе {order.status.value}.")
            return

        now = datetime.now(timezone.utc)
        order.status = AdStatus.ACTIVE
        order.starts_at = now
        order.expires_at = now + timedelta(hours=order.duration_hours)
        await session.commit()

    await message.answer(f"Реклама №{order_id} активирована до {order.expires_at:%d.%m.%Y %H:%M} UTC ✅")

    try:
        from aiogram import Bot as AiogramBot

        notify = AiogramBot(token=settings.MASTER_BOT_TOKEN)
        await notify.send_message(order.buyer_tg_id, f"{tg('check','✅')} Ваша реклама №{order_id} оплачена и активирована!")
        await notify.session.close()
    except Exception:
        pass



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
