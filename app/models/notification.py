from datetime import datetime

from sqlalchemy import BIGINT, Boolean, DateTime, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(30), default="telegram", nullable=False, index=True)
    telegram_account_id: Mapped[int | None] = mapped_column(ForeignKey("telegram_accounts.id"), nullable=True)
    sender_name: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    sender_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sender_avatar_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    chat_id: Mapped[int | None] = mapped_column(BIGINT, nullable=True, index=True)
    chat_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    message_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    message_preview: Mapped[str | None] = mapped_column(String(500), nullable=True)
    external_message_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    external_message_id_int: Mapped[int | None] = mapped_column(BIGINT, nullable=True, index=True)
    reply_to_external_message_id_int: Mapped[int | None] = mapped_column(BIGINT, nullable=True, index=True)
    message_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    raw_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    is_outgoing: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    peer_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    include_in_feed: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)
