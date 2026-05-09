from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.schemas.push import PushPayload, PushSubscriptionRequest
from app.services.push_service import push_new_message_to_all, save_subscription

router = APIRouter(prefix="/push", tags=["push"])


@router.get("/public-key")
def get_public_key():
    from app.core.config import settings

    return {"public_key": settings.vapid_public_key}


@router.post("/subscribe")
def subscribe(
    payload: PushSubscriptionRequest,
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    subscription = payload.model_dump()
    save_subscription(db, subscription)
    return {"ok": True}


@router.post("/test")
def send_test_push(
    payload: PushPayload,
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    sent = push_new_message_to_all(db, payload.title, payload.body, payload.url, payload.tag)
    return {"ok": True, "sent": sent}
