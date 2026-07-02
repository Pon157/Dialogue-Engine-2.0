import enum
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class BotType(str, enum.Enum):
    SUPPORT = "support"   # бот общения / обратной связи
    POSTING = "posting"   # бот-постер для каналов


class ForwardMode(str, enum.Enum):
    FORWARD = "forward"
    COPY = "copy"


class Bot(Base):
    """Реестр всех ботов, созданных через конструктор.
    Одна строка = один реальный Telegram-бот, которого движок запускает отдельным polling-процессом (asyncio task).
    """

    __tablename__ = "bots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_tg_id: Mapped[int] = mapped_column(BigInteger, index=True)
    token: Mapped[str] = mapped_column(String(128), unique=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    bot_type: Mapped[BotType] = mapped_column(Enum(BotType), default=BotType.SUPPORT)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)   # владелец включил/выключил бота
    is_running: Mapped[bool] = mapped_column(Boolean, default=False)  # текущее фактическое состояние в движке

    # --- общие настройки ---
    welcome_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    welcome_photo_file_id: Mapped[str | None] = mapped_column(String(256), nullable=True)

    open_ticket_on_start: Mapped[bool] = mapped_column(Boolean, default=True)
    open_ticket_on_first_message: Mapped[bool] = mapped_column(Boolean, default=True)
    open_ticket_on_button: Mapped[bool] = mapped_column(Boolean, default=False)

    target_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # куда падают обращения
    use_topics: Mapped[bool] = mapped_column(Boolean, default=False)               # режим топиков в target_chat

    forward_mode: Mapped[ForwardMode] = mapped_column(Enum(ForwardMode), default=ForwardMode.FORWARD)
    copy_show_username: Mapped[bool] = mapped_column(Boolean, default=True)
    copy_show_id: Mapped[bool] = mapped_column(Boolean, default=True)
    copy_show_name: Mapped[bool] = mapped_column(Boolean, default=False)

    warns_before_autoban: Mapped[int] = mapped_column(Integer, default=3)

    donate_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    donate_button_kind: Mapped[str | None] = mapped_column(String(16), nullable=True)  # 'inline' | 'keyboard'

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    admins: Mapped[list["BotAdmin"]] = relationship(back_populates="bot", cascade="all, delete-orphan")
    users: Mapped[list["BotUser"]] = relationship(back_populates="bot", cascade="all, delete-orphan")


class BotAdmin(Base):
    __tablename__ = "bot_admins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"), index=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, index=True)
    added_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    bot: Mapped["Bot"] = relationship(back_populates="admins")


class BotUser(Base):
    """Пользователь конкретного созданного бота (не путать с владельцем конструктора)."""

    __tablename__ = "bot_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"), index=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, index=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    full_name: Mapped[str | None] = mapped_column(String(256), nullable=True)

    is_blocked_bot: Mapped[bool] = mapped_column(Boolean, default=False)  # юзер заблокировал бота (узнаём при рассылке)
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False)
    ban_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # null = perm
    ban_reason: Mapped[str | None] = mapped_column(String(256), nullable=True)
    warns_count: Mapped[int] = mapped_column(Integer, default=0)

    active_topic_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # id топика в target_chat
    has_open_ticket: Mapped[bool] = mapped_column(Boolean, default=False)

    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    bot: Mapped["Bot"] = relationship(back_populates="users")


class Warn(Base):
    __tablename__ = "warns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"), index=True)
    user_tg_id: Mapped[int] = mapped_column(BigInteger, index=True)
    admin_tg_id: Mapped[int] = mapped_column(BigInteger)
    reason: Mapped[str | None] = mapped_column(String(256), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)  # снят через /unwarn?
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BanLog(Base):
    __tablename__ = "ban_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"), index=True)
    user_tg_id: Mapped[int] = mapped_column(BigInteger, index=True)
    admin_tg_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # null = автобан
    reason: Mapped[str | None] = mapped_column(String(256), nullable=True)
    until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    action: Mapped[str] = mapped_column(String(16))  # 'ban' | 'unban'
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MessageLog(Base):
    """По одной строке на каждое сообщение — основа для статистики (всего/неделя/день, по админам)."""

    __tablename__ = "message_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"), index=True)
    direction: Mapped[str] = mapped_column(String(8))  # 'in' (от юзера) | 'out' (от админа)
    user_tg_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    admin_tg_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    admin_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class Broadcast(Base):
    __tablename__ = "broadcasts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"), index=True)
    admin_tg_id: Mapped[int] = mapped_column(BigInteger)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_file_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    media_type: Mapped[str | None] = mapped_column(String(16), nullable=True)  # photo/video/document
    target: Mapped[str] = mapped_column(String(16))  # 'all' | 'active'
    sent_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending/running/done
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
