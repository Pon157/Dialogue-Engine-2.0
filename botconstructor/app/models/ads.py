import enum
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class AdStatus(str, enum.Enum):
    PENDING_PAYMENT = "pending_payment"
    ACTIVE = "active"
    EXPIRED = "expired"
    REJECTED = "rejected"


# тариф: (лейбл, длительность в часах, цена в звёздах, цена в рублях)
AD_TARIFFS = [
    ("12 часов", 12, 25, 50),
    ("1 день", 24, 40, 80),
    ("3 дня", 72, 100, 200),
    ("7 дней", 168, 200, 400),
]

AD_PAYMENT_CONTACT = "@kotickr"
AD_MAX_TEXT_LEN = 100


class AdOrder(Base):
    __tablename__ = "ad_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    buyer_tg_id: Mapped[int] = mapped_column(BigInteger, index=True)
    buyer_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    text: Mapped[str] = mapped_column(String(AD_MAX_TEXT_LEN))
    tariff_label: Mapped[str] = mapped_column(String(32))
    duration_hours: Mapped[int] = mapped_column(Integer)
    price_stars: Mapped[int] = mapped_column(Integer)
    price_rub: Mapped[int] = mapped_column(Integer)
    status: Mapped[AdStatus] = mapped_column(Enum(AdStatus), default=AdStatus.PENDING_PAYMENT)

    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
