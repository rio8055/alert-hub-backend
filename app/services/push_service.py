import json

from pywebpush import WebPushException, webpush
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.push_subscription import PushSubscription


def remove_subscription_by_endpoint(db: Session, endpoint: str) -> int:
    deleted = db.query(PushSubscription).filter(PushSubscription.endpoint == endpoint).delete()
    db.commit()
    return int(deleted)


def save_subscription(db: Session, subscription: dict) -> PushSubscription:
    existing = db.query(PushSubscription).filter(PushSubscription.endpoint == subscription["endpoint"]).first()
    if existing:
        existing.subscription_json = subscription
        db.commit()
        db.refresh(existing)
        return existing
    row = PushSubscription(endpoint=subscription["endpoint"], subscription_json=subscription)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def push_new_message_to_all(
    db: Session, title: str, body: str, url: str = "/", tag: str | None = None
) -> int:
    if not settings.vapid_public_key or not settings.vapid_private_key:
        return 0
    payload: dict = {"title": title, "body": body, "url": url}
    if tag is not None:
        payload["tag"] = tag
    payload_json = json.dumps(payload)
    sent = 0
    subscriptions = db.query(PushSubscription).all()
    for sub in subscriptions:
        try:
            webpush(
                subscription_info=sub.subscription_json,
                data=payload_json,
                vapid_private_key=settings.vapid_private_key,
                vapid_claims={"sub": settings.vapid_claims_sub},
            )
            sent += 1
        except WebPushException:
            continue
    return sent
