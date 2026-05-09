from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import SessionLocal, get_db
from app.models.telegram_account import TelegramAccount
from app.schemas.telegram import (
    TelegramAccountCreate,
    TelegramAccountOut,
    TelegramDeleteMessageRequest,
    TelegramEditMessageRequest,
    TelegramMarkReadRequest,
    TelegramPinMessageRequest,
    TelegramSendCodeRequest,
    TelegramSendMessageRequest,
    TelegramVerifyCodeRequest,
)
from app.services.telegram_connect_service import send_code, verify_code
from app.services.telegram_service import telegram_listener_manager

router = APIRouter(prefix="/telegram", tags=["telegram"])


@router.get("/accounts", response_model=list[TelegramAccountOut])
def list_accounts(db: Session = Depends(get_db), _user=Depends(get_current_user)):
    return db.query(TelegramAccount).order_by(TelegramAccount.id.desc()).all()


@router.post("/accounts", response_model=TelegramAccountOut)
def add_account(payload: TelegramAccountCreate, db: Session = Depends(get_db), _user=Depends(get_current_user)):
    if db.query(TelegramAccount).filter(TelegramAccount.session_name == payload.session_name).first():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="session_name already exists")
    row = TelegramAccount(
        label=payload.label,
        session_name=payload.session_name,
        phone_number=payload.phone_number,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.post("/connect/send-code")
async def connect_send_code(payload: TelegramSendCodeRequest, _user=Depends(get_current_user)):
    await send_code(payload.session_name, payload.phone_number)
    return {"ok": True}


@router.post("/connect/verify")
async def connect_verify_code(
    payload: TelegramVerifyCodeRequest,
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    verified = await verify_code(
        session_name=payload.session_name,
        phone_number=payload.phone_number,
        code=payload.code,
        password=payload.password,
    )
    if not verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Telegram 2FA password required",
        )

    row = db.query(TelegramAccount).filter(TelegramAccount.session_name == payload.session_name).first()
    if not row:
        row = TelegramAccount(
            label=payload.display_name,
            session_name=payload.session_name,
            phone_number=payload.phone_number,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
    else:
        row.label = payload.display_name
        row.phone_number = payload.phone_number
        db.commit()
        db.refresh(row)
    await telegram_listener_manager.add_account_listener(row, SessionLocal)
    return {"ok": True, "account_id": row.id}


@router.post("/messages/send")
async def send_telegram_message(
    payload: TelegramSendMessageRequest,
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    account = db.query(TelegramAccount).filter(TelegramAccount.id == payload.account_id).first()
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    if not account.is_connected:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Account disconnected")
    peer = payload.peer.strip() if payload.peer else None
    if payload.chat_id is None and not peer:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="chat_id or peer is required")

    sent = await telegram_listener_manager.send_message(
        account=account,
        message_text=payload.message_text,
        chat_id=payload.chat_id,
        peer=peer,
        reply_to_message_id=payload.reply_to_message_id,
        db_factory=SessionLocal,
    )
    return {"ok": True, "message_id": sent.external_message_id_int or sent.id}


@router.post("/messages/send-media")
async def send_telegram_media(
    account_id: int = Form(...),
    media: UploadFile = File(...),
    chat_id: int | None = Form(None),
    peer: str | None = Form(None),
    caption: str | None = Form(None),
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    account = db.query(TelegramAccount).filter(TelegramAccount.id == account_id).first()
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    if not account.is_connected:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Account disconnected")
    peer_clean = peer.strip() if peer else None
    if chat_id is None and not peer_clean:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="chat_id or peer is required")
    media_bytes = await media.read()
    if not media_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Media file is empty")

    sent = await telegram_listener_manager.send_media(
        account=account,
        db_factory=SessionLocal,
        media_bytes=media_bytes,
        media_filename=media.filename,
        caption=caption,
        chat_id=chat_id,
        peer=peer_clean,
    )
    return {"ok": True, "message_id": sent.external_message_id_int or sent.id}


@router.post("/messages/read")
async def mark_telegram_messages_read(
    payload: TelegramMarkReadRequest,
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    account = db.query(TelegramAccount).filter(TelegramAccount.id == payload.account_id).first()
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    if not account.is_connected:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Account disconnected")
    peer = payload.peer.strip() if payload.peer else None
    if payload.chat_id is None and not peer:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="chat_id or peer is required")

    marked = await telegram_listener_manager.mark_chat_read(
        account=account,
        db_factory=SessionLocal,
        chat_id=payload.chat_id,
        peer=peer,
    )
    return {"ok": True, "marked": marked}


@router.post("/messages/edit")
async def edit_telegram_message(
    payload: TelegramEditMessageRequest,
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    account = db.query(TelegramAccount).filter(TelegramAccount.id == payload.account_id).first()
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    if not account.is_connected:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Account disconnected")
    peer = payload.peer.strip() if payload.peer else None
    if payload.chat_id is None and not peer:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="chat_id or peer is required")

    edited = await telegram_listener_manager.edit_message(
        account=account,
        db_factory=SessionLocal,
        message_id=payload.message_id,
        message_text=payload.message_text,
        chat_id=payload.chat_id,
        peer=peer,
    )
    return {"ok": True, "notification_id": edited.id}


@router.post("/messages/delete")
async def delete_telegram_message(
    payload: TelegramDeleteMessageRequest,
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    account = db.query(TelegramAccount).filter(TelegramAccount.id == payload.account_id).first()
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    if not account.is_connected:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Account disconnected")
    peer = payload.peer.strip() if payload.peer else None
    if payload.chat_id is None and not peer:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="chat_id or peer is required")

    deleted = await telegram_listener_manager.delete_message(
        account=account,
        db_factory=SessionLocal,
        message_id=payload.message_id,
        chat_id=payload.chat_id,
        peer=peer,
        revoke=payload.revoke,
    )
    return {"ok": True, "deleted": deleted}


@router.post("/messages/pin")
async def pin_telegram_message(
    payload: TelegramPinMessageRequest,
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    account = db.query(TelegramAccount).filter(TelegramAccount.id == payload.account_id).first()
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    if not account.is_connected:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Account disconnected")
    peer = payload.peer.strip() if payload.peer else None
    if payload.chat_id is None and not peer:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="chat_id or peer is required")

    await telegram_listener_manager.pin_message(
        account=account,
        message_id=payload.message_id,
        chat_id=payload.chat_id,
        peer=peer,
        notify=payload.notify,
    )
    return {"ok": True}
