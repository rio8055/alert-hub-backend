from pydantic import BaseModel, Field


class TelegramAccountCreate(BaseModel):
    label: str = Field(min_length=1, max_length=100)
    session_name: str = Field(min_length=1, max_length=120)
    phone_number: str | None = Field(default=None, max_length=30)


class TelegramAccountOut(BaseModel):
    id: int
    type: str = "telegram"
    label: str
    session_name: str
    phone_number: str | None
    status: str = "active"

    class Config:
        from_attributes = True


class TelegramSendCodeRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=100)
    username: str | None = Field(default=None, max_length=100)
    session_name: str = Field(min_length=1, max_length=120)
    phone_number: str = Field(min_length=5, max_length=30)


class TelegramVerifyCodeRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=100)
    username: str | None = Field(default=None, max_length=100)
    session_name: str = Field(min_length=1, max_length=120)
    phone_number: str = Field(min_length=5, max_length=30)
    code: str = Field(min_length=3, max_length=20)
    password: str | None = None


class TelegramSendMessageRequest(BaseModel):
    account_id: int
    message_text: str = Field(min_length=1, max_length=4000)
    chat_id: int | None = None
    peer: str | None = Field(default=None, max_length=100)
    reply_to_message_id: int | None = None


class TelegramMarkReadRequest(BaseModel):
    account_id: int
    chat_id: int | None = None
    peer: str | None = Field(default=None, max_length=100)


class TelegramEditMessageRequest(BaseModel):
    account_id: int
    message_id: int
    message_text: str = Field(min_length=1, max_length=4000)
    chat_id: int | None = None
    peer: str | None = Field(default=None, max_length=100)


class TelegramDeleteMessageRequest(BaseModel):
    account_id: int
    message_id: int
    chat_id: int | None = None
    peer: str | None = Field(default=None, max_length=100)
    revoke: bool = True


class TelegramPinMessageRequest(BaseModel):
    account_id: int
    message_id: int
    chat_id: int | None = None
    peer: str | None = Field(default=None, max_length=100)
    notify: bool = False
