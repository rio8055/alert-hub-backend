from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import SessionLocal, get_db
from app.models.telegram_account import TelegramAccount
from app.services.telegram_connect_service import send_code
from app.services.telegram_service import telegram_listener_manager

router = APIRouter(prefix="/accounts", tags=["accounts"])


def _serialize(account: TelegramAccount, avatar_url: str | None = None) -> dict:
    status = "active"
    if not account.is_connected:
        status = "disconnected"
    elif account.is_muted:
        status = "muted"
    return {
        "id": account.id,
        "type": "telegram",
        "label": account.label,
        "display_name": account.label,
        "username": account.session_name,
        "session_name": account.session_name,
        "avatar_url": avatar_url or "",
        "phone_number": account.phone_number,
        "status": status,
    }


@router.get("")
async def list_accounts(db: Session = Depends(get_db), _user=Depends(get_current_user)):
    rows = db.query(TelegramAccount).order_by(TelegramAccount.id.desc()).all()
    out = []
    for row in rows:
        await telegram_listener_manager.sync_account_session_status(row, db)
        avatar_url = await telegram_listener_manager.get_account_avatar_url(row)
        out.append(_serialize(row, avatar_url=avatar_url))
    return out


@router.post("/{account_id}/{action}")
async def account_action(
    account_id: int,
    action: str,
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    row = db.query(TelegramAccount).filter(TelegramAccount.id == account_id).first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")

    if action == "mute":
        row.is_muted = True
    elif action == "unmute":
        row.is_muted = False
    elif action == "disconnect":
        row.is_connected = False
    elif action == "reconnect":
        if not row.phone_number:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Phone number required to reconnect",
            )
        await send_code(row.session_name, row.phone_number)
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid action")

    db.commit()
    db.refresh(row)
    return _serialize(row)


@router.delete("/{account_id}")
def delete_account(account_id: int, db: Session = Depends(get_db), _user=Depends(get_current_user)):
    row = db.query(TelegramAccount).filter(TelegramAccount.id == account_id).first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    db.delete(row)
    db.commit()
    return {"ok": True}
