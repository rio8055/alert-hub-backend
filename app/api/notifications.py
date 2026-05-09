from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.notification import Notification
from app.models.telegram_account import TelegramAccount
from app.schemas.notification_list import NotificationListResponse

router = APIRouter(prefix="/notifications", tags=["notifications"])


class NotificationDeleteSelectedRequest(BaseModel):
    ids: list[int]


@router.get("", response_model=NotificationListResponse)
def list_notifications(
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
    page: int = 1,
    page_size: int = 20,
    q: str | None = None,
    source: str | None = None,
    is_read: bool | None = None,
    include_outgoing: bool = False,
    for_chat: bool = False,
):
    page = max(1, page)
    page_size = max(1, min(page_size, 100))
    query = db.query(Notification)
    if not for_chat:
        query = query.filter(Notification.include_in_feed.is_(True))
    if source:
        query = query.filter(Notification.source == source)
    if not include_outgoing:
        query = query.filter(Notification.is_outgoing.is_(False))
    if is_read is not None:
        query = query.filter(Notification.is_read == is_read)
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                Notification.sender_name.ilike(like),
                Notification.chat_name.ilike(like),
                Notification.message_text.ilike(like),
                Notification.message_preview.ilike(like),
            )
        )
    total = query.count()
    items = (
        query.order_by(Notification.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post("/{notification_id}/read")
def mark_read(notification_id: int, db: Session = Depends(get_db), _user=Depends(get_current_user)):
    row = db.query(Notification).filter(Notification.id == notification_id).first()
    if not row:
        return {"ok": False}
    row.is_read = True
    db.commit()
    return {"ok": True}


@router.post("/read-all")
def mark_all_read(db: Session = Depends(get_db), _user=Depends(get_current_user)):
    db.query(Notification).filter(Notification.is_read.is_(False)).update({"is_read": True})
    db.commit()
    return {"ok": True}


@router.delete("/history")
def clear_history(db: Session = Depends(get_db), _user=Depends(get_current_user)):
    deleted = db.query(Notification).delete()
    db.commit()
    return {"ok": True, "deleted": deleted}


@router.post("/delete-selected")
def delete_selected(
    payload: NotificationDeleteSelectedRequest,
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    ids = [item for item in payload.ids if isinstance(item, int)]
    if not ids:
        return {"ok": True, "deleted": 0}
    deleted = db.query(Notification).filter(Notification.id.in_(ids)).delete(synchronize_session=False)
    db.commit()
    return {"ok": True, "deleted": deleted}


@router.get("/unread-count")
def unread_count(db: Session = Depends(get_db), _user=Depends(get_current_user)):
    muted_or_disconnected_ids = {
        row.id
        for row in db.query(TelegramAccount.id, TelegramAccount.is_muted, TelegramAccount.is_connected).all()
        if row.is_muted or not row.is_connected
    }
    query = db.query(Notification).filter(
        Notification.is_read.is_(False),
        Notification.is_outgoing.is_(False),
    )
    if muted_or_disconnected_ids:
        query = query.filter(
            (Notification.telegram_account_id.is_(None))
            | (~Notification.telegram_account_id.in_(muted_or_disconnected_ids))
        )
    return {"count": query.count()}
