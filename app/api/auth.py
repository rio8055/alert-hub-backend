from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    hash_token,
    verify_password,
)
from app.db.session import get_db
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    RegisterResponse,
    TokenResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already exists")
    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        full_name=payload.name,
        is_active=False,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return RegisterResponse(email=user.email, is_active=user.is_active)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is not active. Please contact an administrator.",
        )
    access = create_access_token(user.email)
    refresh, expires_at = create_refresh_token(user.email)
    db.add(RefreshToken(user_id=user.id, token_hash=hash_token(refresh), expires_at=expires_at))
    db.commit()
    return TokenResponse(access_token=access, refresh_token=refresh)


@router.post("/refresh", response_model=TokenResponse)
def refresh_tokens(payload: RefreshRequest, db: Session = Depends(get_db)):
    token_hash_value = hash_token(payload.refresh_token)
    row = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash_value).first()
    if not row or row.expires_at < datetime.now(UTC).replace(tzinfo=None):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    user = db.query(User).filter(User.id == row.user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    if not user.is_active:
        db.delete(row)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is not active. Please contact an administrator.",
        )
    db.delete(row)
    access = create_access_token(user.email)
    refresh, expires_at = create_refresh_token(user.email)
    db.add(RefreshToken(user_id=user.id, token_hash=hash_token(refresh), expires_at=expires_at))
    db.commit()
    return TokenResponse(access_token=access, refresh_token=refresh)
