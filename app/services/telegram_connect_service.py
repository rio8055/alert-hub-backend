from pathlib import Path

from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError

from app.core.config import settings
from app.services.r2_storage import ensure_telegram_session_from_r2, push_telegram_session_to_r2

SESSIONS_DIR = Path("telegram_sessions")
SESSIONS_DIR.mkdir(exist_ok=True)

_PENDING: dict[str, TelegramClient] = {}


def _session_path(session_name: str) -> str:
    return str(SESSIONS_DIR / session_name)


async def send_code(session_name: str, phone_number: str) -> None:
    if not settings.telegram_api_id or not settings.telegram_api_hash:
        raise ValueError("Telegram API credentials are not configured")
    await ensure_telegram_session_from_r2(session_name)
    client = TelegramClient(_session_path(session_name), settings.telegram_api_id, settings.telegram_api_hash)
    await client.connect()
    await client.send_code_request(phone_number)
    _PENDING[session_name] = client


async def verify_code(session_name: str, phone_number: str, code: str, password: str | None = None) -> bool:
    await ensure_telegram_session_from_r2(session_name)
    client = _PENDING.get(session_name)
    if not client:
        client = TelegramClient(_session_path(session_name), settings.telegram_api_id, settings.telegram_api_hash)
        await client.connect()
    ok = False
    try:
        try:
            await client.sign_in(phone=phone_number, code=code)
        except SessionPasswordNeededError:
            if not password:
                return False
            await client.sign_in(password=password)
        ok = True
    finally:
        await client.disconnect()
        _PENDING.pop(session_name, None)
    if ok:
        await push_telegram_session_to_r2(session_name)
    return ok
