import enum
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ButtonKind(str, enum.Enum):
    URL = "url"
    TRIGGER = "trigger"   # при нажатии срабатывает триггер (см. Trigger.key)


class InlineButton(Base):
    __tablename__ = "inline_buttons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"), index=True)
    context: Mapped[str] = mapped_column(String(64))  # напр. 'welcome', 'menu', 'ticket_open'
    text: Mapped[str] = mapped_column(String(256))    # уже готовый форматированный текст кнопки (эмодзи и т.п.)
    kind: Mapped[ButtonKind] = mapped_column(Enum(ButtonKind))
    url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    trigger_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    row: Mapped[int] = mapped_column(Integer, default=0)
    col: Mapped[int] = mapped_column(Integer, default=0)


class KeyboardButton(Base):
    __tablename__ = "keyboard_buttons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"), index=True)
    context: Mapped[str] = mapped_column(String(64))
    text: Mapped[str] = mapped_column(String(256))
    trigger_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    row: Mapped[int] = mapped_column(Integer, default=0)
    col: Mapped[int] = mapped_column(Integer, default=0)


class Trigger(Base):
    """Триггер-команда: срабатывает либо на текст/команду от юзера, либо на нажатие кнопки (trigger_key)."""

    __tablename__ = "triggers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(64), index=True)  # напр. '/price' или 'trg_menu_1'
    match_text: Mapped[str | None] = mapped_column(String(256), nullable=True)  # точный текст-триггер, если не команда
    response_text: Mapped[str | None] = mapped_column(Text, nullable=True)  # уже готовый HTML (parse_mode=HTML)
    response_photo_file_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PostingSettings(Base):
    """1-к-1 с ботом типа POSTING."""

    __tablename__ = "posting_settings"

    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"), primary_key=True)
    accept_posts: Mapped[bool] = mapped_column(Boolean, default=True)
    target_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    review_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # куда падают посты на модерацию
    # шаблон оформления, {text} — обязательная переменная с исходным текстом
    post_template: Mapped[str] = mapped_column(Text, default="{text}")


class PostReview(Base):
    __tablename__ = "post_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"), index=True)
    submitter_tg_id: Mapped[int] = mapped_column(BigInteger)
    admin_tg_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending/approved/rejected
    original_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_file_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    media_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
