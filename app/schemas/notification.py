from datetime import datetime

from pydantic import BaseModel


class NotificationOut(BaseModel):
    id: int
    source: str
    telegram_account_id: int | None
    sender_name: str | None
    sender_id: str | None
    sender_avatar_url: str | None
    chat_id: int | None
    chat_name: str | None
    message_text: str | None
    message_preview: str | None
    external_message_id_int: int | None = None
    reply_to_external_message_id_int: int | None = None
    message_at: datetime | None
    edited_at: datetime | None
    is_outgoing: bool
    peer_read: bool
    is_read: bool
    include_in_feed: bool = True
    created_at: datetime

    class Config:
        from_attributes = True
