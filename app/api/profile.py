from pydantic import BaseModel, EmailStr, Field
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.security import create_access_token, create_refresh_token, hash_token, verify_password
from app.db.session import get_db
from app.models.refresh_token import RefreshToken
from app.models.user import User

router = APIRouter(tags=["profile"])


class UpdateEmailRequest(BaseModel):
    new_email: EmailStr
    password: str


class UpdatePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


class PushStateRequest(BaseModel):
    enabled: bool


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    fallback_name = user.email.split("@")[0] if user.email else "User"
    return {"email": user.email, "name": user.full_name or fallback_name, "avatar_url": user.avatar_url}


@router.put("/me/email")
def update_email(
    payload: UpdateEmailRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Wrong password")
    if payload.new_email != user.email and db.query(User).filter(User.email == payload.new_email).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already exists")

    user.email = payload.new_email
    access = create_access_token(user.email)
    refresh, expires_at = create_refresh_token(user.email)
    db.add(RefreshToken(user_id=user.id, token_hash=hash_token(refresh), expires_at=expires_at))
    db.commit()
    return {"access_token": access, "refresh_token": refresh, "token_type": "bearer"}


@router.put("/me/password")
def update_password(
    payload: UpdatePasswordRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Wrong password")
    from app.core.security import hash_password

    user.password_hash = hash_password(payload.new_password)
    db.commit()
    return {"ok": True}


@router.get("/push/state")
def get_push_state(user: User = Depends(get_current_user)):
    return {"enabled": bool(user.push_enabled)}


@router.put("/push/state")
def set_push_state(
    payload: PushStateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    user.push_enabled = payload.enabled
    db.commit()
    return {"enabled": bool(user.push_enabled)}
