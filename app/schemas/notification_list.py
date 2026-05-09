from pydantic import BaseModel

from app.schemas.notification import NotificationOut


class NotificationListResponse(BaseModel):
    items: list[NotificationOut]
    total: int
    page: int
    page_size: int
