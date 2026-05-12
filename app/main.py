import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect, text
from sqlalchemy.exc import OperationalError

from app.api.auth import router as auth_router
from app.api.accounts import router as accounts_router
from app.api.notifications import router as notifications_router
from app.api.profile import router as profile_router
from app.api.push import router as push_router
from app.api.test import router as test_router
from app.api.telegram import router as telegram_router
from app.core.config import settings
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.services.telegram_service import telegram_listener_manager


def _ensure_notification_columns():
    inspector = inspect(engine)
    if "notifications" not in inspector.get_table_names():
        return
    existing_columns = {column["name"] for column in inspector.get_columns("notifications")}
    with engine.begin() as conn:
        if "sender_avatar_url" not in existing_columns:
            conn.execute(text("ALTER TABLE notifications ADD COLUMN sender_avatar_url VARCHAR(1000)"))
        if "chat_id" not in existing_columns:
            conn.execute(text("ALTER TABLE notifications ADD COLUMN chat_id BIGINT"))
        if "external_message_id_int" not in existing_columns:
            conn.execute(text("ALTER TABLE notifications ADD COLUMN external_message_id_int BIGINT"))
        if "reply_to_external_message_id_int" not in existing_columns:
            conn.execute(text("ALTER TABLE notifications ADD COLUMN reply_to_external_message_id_int BIGINT"))
        if "edited_at" not in existing_columns:
            conn.execute(text("ALTER TABLE notifications ADD COLUMN edited_at TIMESTAMP"))
        if "is_outgoing" not in existing_columns:
            conn.execute(
                text("ALTER TABLE notifications ADD COLUMN is_outgoing BOOLEAN NOT NULL DEFAULT FALSE")
            )
        if "peer_read" not in existing_columns:
            conn.execute(
                text("ALTER TABLE notifications ADD COLUMN peer_read BOOLEAN NOT NULL DEFAULT FALSE")
            )
        if "include_in_feed" not in existing_columns:
            conn.execute(
                text(
                    "ALTER TABLE notifications ADD COLUMN include_in_feed BOOLEAN NOT NULL DEFAULT TRUE"
                )
            )
        conn.execute(
            text(
                """
                UPDATE notifications
                SET external_message_id_int = CAST(external_message_id AS BIGINT)
                WHERE external_message_id_int IS NULL
                  AND external_message_id ~ '^[0-9]+$'
                """
            )
        )


def _ensure_telegram_account_columns():
    inspector = inspect(engine)
    if "telegram_accounts" not in inspector.get_table_names():
        return
    existing_columns = {column["name"] for column in inspector.get_columns("telegram_accounts")}
    with engine.begin() as conn:
        if "is_muted" not in existing_columns:
            conn.execute(text("ALTER TABLE telegram_accounts ADD COLUMN is_muted BOOLEAN NOT NULL DEFAULT FALSE"))
        if "is_connected" not in existing_columns:
            conn.execute(text("ALTER TABLE telegram_accounts ADD COLUMN is_connected BOOLEAN NOT NULL DEFAULT TRUE"))


def _ensure_user_columns():
    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        return
    existing_columns = {column["name"] for column in inspector.get_columns("users")}
    with engine.begin() as conn:
        if "full_name" not in existing_columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN full_name VARCHAR(120)"))
        if "avatar_url" not in existing_columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN avatar_url VARCHAR(500)"))
        if "push_enabled" not in existing_columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN push_enabled BOOLEAN NOT NULL DEFAULT FALSE"))


async def _init_database_with_retry(max_attempts: int = 6, initial_delay: float = 1.5) -> bool:
    """Initialize DB schema with retries to tolerate Neon cold-start."""
    delay = initial_delay
    for attempt in range(1, max_attempts + 1):
        try:
            Base.metadata.create_all(bind=engine)
            _ensure_notification_columns()
            _ensure_telegram_account_columns()
            _ensure_user_columns()
            print(f"[db] schema ready (attempt {attempt})")
            return True
        except OperationalError as exc:
            print(f"[db] connection failed (attempt {attempt}/{max_attempts}): {exc}")
        except Exception as exc:
            print(f"[db] init failed (attempt {attempt}/{max_attempts}): {exc}")
        if attempt < max_attempts:
            await asyncio.sleep(delay)
            delay = min(delay * 2, 15.0)
    print("[db] giving up DB init for now; API will start, requests may 500 until DB is up")
    return False


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db_ready = await _init_database_with_retry()
    if db_ready:
        try:
            await telegram_listener_manager.start(SessionLocal)
        except Exception as exc:
            print(f"[telegram] manager start failed: {exc}")
    else:
        print("[telegram] skipping listener start because DB is unavailable")
    yield
    try:
        await telegram_listener_manager.stop()
    except Exception as exc:
        print(f"[telegram] manager stop failed: {exc}")


app = FastAPI(title=settings.app_name, lifespan=lifespan)
MEDIA_DIR = Path("media")
MEDIA_DIR.mkdir(exist_ok=True)
app.mount("/media", StaticFiles(directory=str(MEDIA_DIR)), name="media")

configured_origins = [item.strip() for item in settings.cors_origins.split(",") if item.strip()]

if settings.cors_allow_any_origin:
    # Any browser origin can read responses (OK here: auth uses Bearer in header/localStorage, not cookies).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=configured_origins,
        # Local dev (any port) + Vercel (*.vercel.app) + Render Web Services (*.onrender.com).
        allow_origin_regex=(
            r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"
            r"|^https://[^/]+\.vercel\.app$"
            r"|^https://[^/]+\.onrender\.com$"
        ),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(auth_router, prefix=settings.api_prefix)
app.include_router(profile_router, prefix=settings.api_prefix)
app.include_router(notifications_router, prefix=settings.api_prefix)
app.include_router(telegram_router, prefix=settings.api_prefix)
app.include_router(accounts_router, prefix=settings.api_prefix)
app.include_router(push_router, prefix=settings.api_prefix)
app.include_router(test_router, prefix=settings.api_prefix)


@app.get("/health")
def health_check():
    return {"ok": True}
