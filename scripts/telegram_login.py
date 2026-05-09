import asyncio
from pathlib import Path

from telethon import TelegramClient

from app.core.config import settings


async def login(session_name: str, phone_number: str):
    session_dir = Path("telegram_sessions")
    session_dir.mkdir(exist_ok=True)
    session_path = str(session_dir / session_name)
    client = TelegramClient(session_path, settings.telegram_api_id, settings.telegram_api_hash)
    await client.connect()
    if not await client.is_user_authorized():
        await client.send_code_request(phone_number)
        code = input("Telegram code: ").strip()
        try:
            await client.sign_in(phone_number, code)
        except Exception:
            password = input("2FA password: ").strip()
            await client.sign_in(password=password)
    print("Login successful for session:", session_name)
    await client.disconnect()


if __name__ == "__main__":
    session = input("Session name: ").strip()
    phone = input("Phone number (e.g. +628...): ").strip()
    asyncio.run(login(session, phone))
