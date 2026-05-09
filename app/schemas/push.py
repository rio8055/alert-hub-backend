from pydantic import BaseModel


class PushSubscriptionRequest(BaseModel):
    endpoint: str
    keys: dict


class PushPayload(BaseModel):
    title: str
    body: str
    url: str = "/"
    tag: str | None = None
