import asyncio
import json
import time
from pathlib import Path
from uuid import uuid4

from sqlalchemy import and_
from sqlalchemy.orm import Session
from telethon import TelegramClient, events

from app.core.config import settings
from app.models.notification import Notification
from app.models.telegram_account import TelegramAccount
from app.services.push_service import push_new_message_to_all

SESSIONS_DIR = Path("telegram_sessions")
SESSIONS_DIR.mkdir(exist_ok=True)
MEDIA_DIR = Path("media") / "telegram"
MEDIA_DIR.mkdir(parents=True, exist_ok=True)
ACCOUNT_AVATARS_DIR = MEDIA_DIR / "account_avatars"
ACCOUNT_AVATARS_DIR.mkdir(parents=True, exist_ok=True)


def _reply_to_msg_id(message_obj) -> int | None:
    if message_obj is None:
        return None
    direct = getattr(message_obj, "reply_to_msg_id", None)
    if direct is not None:
        return int(direct)
    reply_to = getattr(message_obj, "reply_to", None)
    if reply_to is None:
        return None
    nested = getattr(reply_to, "reply_to_msg_id", None)
    return int(nested) if nested is not None else None


def _message_display_text(event) -> str:
    text = (event.raw_text or "").strip()
    if text:
        return text

    message = getattr(event, "message", None)
    if message is None:
        return "(no content)"

    if getattr(message, "sticker", None):
        return "Sticker"
    if getattr(message, "gif", None):
        return "GIF"
    if getattr(message, "video", None):
        return "Video file"
    if getattr(message, "video_note", None):
        return "Video note"
    if getattr(message, "voice", None):
        return "Voice message"
    if getattr(message, "audio", None):
        return "Audio file"
    if getattr(message, "photo", None):
        return "Photo"
    if getattr(message, "poll", None):
        return "Poll"
    if getattr(message, "contact", None):
        return "Contact"
    if getattr(message, "location", None):
        return "Location"
    if getattr(message, "document", None):
        filename = getattr(getattr(message, "file", None), "name", None)
        return f"File: {filename}" if filename else "File"
    if getattr(message, "media", None):
        return "Media message"
    return "(no content)"


async def _save_media_and_get_url(event, account_id: int) -> str | None:
    message = getattr(event, "message", None)
    if message is None or getattr(message, "media", None) is None:
        return None
    file_meta = getattr(message, "file", None)
    ext = (getattr(file_meta, "ext", None) or "").strip()
    if not ext:
        if getattr(message, "photo", None):
            ext = ".jpg"
        elif getattr(message, "video", None):
            ext = ".mp4"
        elif getattr(message, "voice", None) or getattr(message, "audio", None):
            ext = ".ogg"
        elif getattr(message, "sticker", None):
            ext = ".webp"
        else:
            ext = ".bin"
    account_dir = MEDIA_DIR / str(account_id)
    account_dir.mkdir(parents=True, exist_ok=True)
    message_id = getattr(event, "id", None) or uuid4().hex
    filename = f"{message_id}-{uuid4().hex[:8]}{ext}"
    target = account_dir / filename
    try:
        await event.download_media(file=str(target))
    except Exception as exc:
        print(f"[telegram] media download failed for account {account_id}: {exc}")
        return None
    base = settings.public_base_url.rstrip("/")
    return f"{base}/media/telegram/{account_id}/{filename}"


class TelegramListenerManager:
    def __init__(self) -> None:
        self._clients: dict[int, TelegramClient] = {}
        self._tasks: dict[int, asyncio.Task] = {}
        self._running = False

    async def start(self, db_factory):
        if self._running or not settings.telegram_api_id or not settings.telegram_api_hash:
            return
        self._running = True
        db: Session = db_factory()
        accounts = db.query(TelegramAccount).all()
        db.close()

        for account in accounts:
            try:
                await self.add_account_listener(account, db_factory)
            except Exception as exc:
                print(f"[telegram] failed to start listener for account {account.id}: {exc}")

    async def add_account_listener(self, account: TelegramAccount, db_factory):
        if not settings.telegram_api_id or not settings.telegram_api_hash:
            return
        if account.id in self._clients:
            return
        session_path = str(SESSIONS_DIR / account.session_name)
        client = TelegramClient(session_path, settings.telegram_api_id, settings.telegram_api_hash)
        try:
            await client.connect()
        except Exception as exc:
            print(f"[telegram] connect failed for account {account.id} ({account.session_name}): {exc}")
            try:
                await client.disconnect()
            except Exception:
                pass
            return
        try:
            authorized = await client.is_user_authorized()
        except Exception as exc:
            print(f"[telegram] auth check failed for account {account.id}: {exc}")
            authorized = False
        if not authorized:
            print(
                f"[telegram] skipping listener for account {account.id} "
                f"({account.session_name}) - session not authorized. "
                "Re-run the connect flow to log in."
            )
            try:
                await client.disconnect()
            except Exception:
                pass
            return

        @client.on(events.NewMessage)
        async def on_message(event, account_id=account.id):
            # Ignore messages sent by the logged-in account itself.
            if getattr(event, "out", False):
                return
            display_text = _message_display_text(event)
            media_url = await _save_media_and_get_url(event, account_id)
            if media_url:
                display_text = f"{display_text}\n{media_url}"
            sender = await event.get_sender()
            chat = await event.get_chat()
            sender_display_name = "Unknown sender"
            sender_avatar_url = None
            if sender is not None:
                first = (getattr(sender, "first_name", None) or "").strip()
                last = (getattr(sender, "last_name", None) or "").strip()
                full_name = " ".join(part for part in (first, last) if part).strip()
                username = (getattr(sender, "username", None) or "").strip()
                sender_display_name = (
                    full_name
                    or (getattr(sender, "title", None) or "").strip()
                    or username
                    or "Unknown sender"
                )
                if username:
                    sender_avatar_url = f"https://t.me/i/userpic/320/{username}.jpg"
            # Telethon events may include objects that are not directly JSON serializable.
            payload = json.loads(json.dumps(event.to_dict(), default=str))
            db_local: Session = db_factory()
            acct_row = db_local.query(TelegramAccount).filter(TelegramAccount.id == account_id).first()
            is_muted = bool(acct_row and acct_row.is_muted)
            notification = Notification(
                source="telegram",
                telegram_account_id=account_id,
                sender_name=sender_display_name,
                sender_id=str(getattr(sender, "id", "")),
                sender_avatar_url=sender_avatar_url,
                chat_id=getattr(event, "chat_id", None),
                chat_name=getattr(chat, "title", None),
                message_text=display_text,
                message_preview=display_text[:200],
                external_message_id=str(event.id),
                external_message_id_int=event.id,
                reply_to_external_message_id_int=_reply_to_msg_id(getattr(event, "message", None)),
                message_at=event.message.date,
                raw_payload=payload,
                is_outgoing=False,
                peer_read=False,
                include_in_feed=not is_muted,
            )
            db_local.add(notification)
            db_local.commit()
            if not is_muted:
                push_new_message_to_all(
                    db_local,
                    title=sender_display_name,
                    body=notification.message_preview or "(no content)",
                    url="/chat",
                    tag=str(notification.id),
                )
            db_local.close()

        @client.on(events.MessageEdited)
        async def on_message_edited(event, account_id=account.id):
            display_text = _message_display_text(event)
            media_url = await _save_media_and_get_url(event, account_id)
            if media_url:
                display_text = f"{display_text}\n{media_url}"
            payload = json.loads(json.dumps(event.to_dict(), default=str))
            db_local: Session = db_factory()
            row = (
                db_local.query(Notification)
                .filter(
                    and_(
                        Notification.source == "telegram",
                        Notification.telegram_account_id == account_id,
                        Notification.external_message_id_int == int(getattr(event, "id", 0)),
                    )
                )
                .first()
            )
            if row:
                row.message_text = display_text
                row.message_preview = display_text[:200]
                row.message_at = getattr(event.message, "date", None)
                row.edited_at = getattr(event.message, "edit_date", None)
                row.reply_to_external_message_id_int = _reply_to_msg_id(getattr(event, "message", None))
                row.raw_payload = payload
                db_local.commit()
            db_local.close()

        @client.on(events.MessageRead(inbox=True))
        async def on_message_read(event, account_id=account.id):
            max_id = getattr(event, "max_id", None)
            chat_id = getattr(event, "chat_id", None)
            if not max_id or chat_id is None:
                return
            db_local: Session = db_factory()
            rows = (
                db_local.query(Notification)
                .filter(
                    and_(
                        Notification.source == "telegram",
                        Notification.telegram_account_id == account_id,
                        Notification.chat_id == chat_id,
                        Notification.is_read.is_(False),
                        Notification.external_message_id_int.isnot(None),
                        Notification.external_message_id_int <= int(max_id),
                    )
                )
                .all()
            )
            if rows:
                for row in rows:
                    row.is_read = True
                db_local.commit()
            db_local.close()

        @client.on(events.MessageRead(inbox=False))
        async def on_peer_read(event, account_id=account.id):
            max_id = getattr(event, "max_id", None)
            chat_id = getattr(event, "chat_id", None)
            if not max_id or chat_id is None:
                return
            db_local: Session = db_factory()
            rows = (
                db_local.query(Notification)
                .filter(
                    and_(
                        Notification.source == "telegram",
                        Notification.telegram_account_id == account_id,
                        Notification.chat_id == chat_id,
                        Notification.is_outgoing.is_(True),
                        Notification.peer_read.is_(False),
                        Notification.external_message_id_int.isnot(None),
                        Notification.external_message_id_int <= int(max_id),
                    )
                )
                .all()
            )
            if rows:
                for row in rows:
                    row.peer_read = True
                db_local.commit()
            db_local.close()

        self._clients[account.id] = client
        self._tasks[account.id] = asyncio.create_task(client.run_until_disconnected())

    async def send_message(
        self,
        account: TelegramAccount,
        message_text: str,
        db_factory,
        chat_id: int | None = None,
        peer: str | None = None,
        reply_to_message_id: int | None = None,
    ) -> Notification:
        if not settings.telegram_api_id or not settings.telegram_api_hash:
            raise ValueError("Telegram API credentials are not configured")
        if not message_text.strip():
            raise ValueError("Message cannot be empty")

        client = self._clients.get(account.id)
        owns_client = False
        if client is None:
            session_path = str(SESSIONS_DIR / account.session_name)
            client = TelegramClient(session_path, settings.telegram_api_id, settings.telegram_api_hash)
            await client.connect()
            authorized = await client.is_user_authorized()
            if not authorized:
                await client.disconnect()
                raise ValueError("Session is not authorized. Reconnect Telegram account.")
            owns_client = True

        entity = chat_id if chat_id is not None else peer
        sent = await client.send_message(
            entity=entity,
            message=message_text.strip(),
            reply_to=reply_to_message_id,
        )
        if owns_client:
            await client.disconnect()

        db_local: Session = db_factory()
        me = await client.get_me() if not owns_client else None
        sender_label = None
        if me is not None:
            sender_label = (
                " ".join(
                    part
                    for part in ((getattr(me, "first_name", None) or "").strip(), (getattr(me, "last_name", None) or "").strip())
                    if part
                ).strip()
                or (getattr(me, "username", None) or "").strip()
                or "You"
            )
        sent_chat = getattr(sent, "chat", None)
        sent_chat_username = (getattr(sent_chat, "username", None) or "").strip() if sent_chat else ""
        sent_avatar_url = (
            f"https://t.me/i/userpic/320/{sent_chat_username}.jpg" if sent_chat_username else None
        )
        notification = Notification(
            source="telegram",
            telegram_account_id=account.id,
            sender_name=peer or getattr(getattr(sent, "chat", None), "title", None) or sender_label or "Unknown",
            sender_id=str(getattr(sent, "chat_id", "")) if getattr(sent, "chat_id", None) is not None else None,
            sender_avatar_url=sent_avatar_url,
            chat_id=getattr(sent, "chat_id", chat_id),
            chat_name=getattr(getattr(sent, "chat", None), "title", None) or peer,
            message_text=message_text.strip(),
            message_preview=message_text.strip()[:200],
            external_message_id=str(getattr(sent, "id", "")),
            external_message_id_int=getattr(sent, "id", None),
            reply_to_external_message_id_int=_reply_to_msg_id(sent),
            message_at=getattr(sent, "date", None),
            raw_payload=json.loads(json.dumps(sent.to_dict(), default=str)),
            is_outgoing=True,
            peer_read=False,
            is_read=True,
        )
        db_local.add(notification)
        db_local.commit()
        db_local.refresh(notification)
        db_local.close()
        return notification

    async def edit_message(
        self,
        account: TelegramAccount,
        db_factory,
        message_id: int,
        message_text: str,
        chat_id: int | None = None,
        peer: str | None = None,
    ) -> Notification:
        if not settings.telegram_api_id or not settings.telegram_api_hash:
            raise ValueError("Telegram API credentials are not configured")
        if not message_text.strip():
            raise ValueError("Message cannot be empty")
        if chat_id is None and not (peer and peer.strip()):
            raise ValueError("chat_id or peer is required")

        client = self._clients.get(account.id)
        owns_client = False
        if client is None:
            session_path = str(SESSIONS_DIR / account.session_name)
            client = TelegramClient(session_path, settings.telegram_api_id, settings.telegram_api_hash)
            await client.connect()
            authorized = await client.is_user_authorized()
            if not authorized:
                await client.disconnect()
                raise ValueError("Session is not authorized. Reconnect Telegram account.")
            owns_client = True

        try:
            entity = chat_id if chat_id is not None else peer
            edited = await client.edit_message(entity=entity, message=message_id, text=message_text.strip())
        finally:
            if owns_client:
                await client.disconnect()

        db_local: Session = db_factory()
        row = (
            db_local.query(Notification)
            .filter(
                and_(
                    Notification.source == "telegram",
                    Notification.telegram_account_id == account.id,
                    Notification.external_message_id_int == int(message_id),
                )
            )
            .first()
        )
        if row is None:
            raise ValueError("Message not found in local history")
        row.message_text = message_text.strip()
        row.message_preview = message_text.strip()[:200]
        row.message_at = getattr(edited, "date", None) or row.message_at
        row.edited_at = getattr(edited, "edit_date", None)
        row.reply_to_external_message_id_int = _reply_to_msg_id(edited)
        row.raw_payload = json.loads(json.dumps(edited.to_dict(), default=str))
        db_local.commit()
        db_local.refresh(row)
        db_local.close()
        return row

    async def delete_message(
        self,
        account: TelegramAccount,
        db_factory,
        message_id: int,
        chat_id: int | None = None,
        peer: str | None = None,
        revoke: bool = True,
    ) -> bool:
        if not settings.telegram_api_id or not settings.telegram_api_hash:
            raise ValueError("Telegram API credentials are not configured")
        if chat_id is None and not (peer and peer.strip()):
            raise ValueError("chat_id or peer is required")

        client = self._clients.get(account.id)
        owns_client = False
        if client is None:
            session_path = str(SESSIONS_DIR / account.session_name)
            client = TelegramClient(session_path, settings.telegram_api_id, settings.telegram_api_hash)
            await client.connect()
            authorized = await client.is_user_authorized()
            if not authorized:
                await client.disconnect()
                raise ValueError("Session is not authorized. Reconnect Telegram account.")
            owns_client = True

        try:
            entity = chat_id if chat_id is not None else peer
            await client.delete_messages(entity=entity, message_ids=[message_id], revoke=revoke)
        finally:
            if owns_client:
                await client.disconnect()

        db_local: Session = db_factory()
        deleted = (
            db_local.query(Notification)
            .filter(
                and_(
                    Notification.source == "telegram",
                    Notification.telegram_account_id == account.id,
                    Notification.external_message_id_int == int(message_id),
                )
            )
            .delete(synchronize_session=False)
        )
        db_local.commit()
        db_local.close()
        return deleted > 0

    async def pin_message(
        self,
        account: TelegramAccount,
        message_id: int,
        chat_id: int | None = None,
        peer: str | None = None,
        notify: bool = False,
    ) -> None:
        if not settings.telegram_api_id or not settings.telegram_api_hash:
            raise ValueError("Telegram API credentials are not configured")
        if chat_id is None and not (peer and peer.strip()):
            raise ValueError("chat_id or peer is required")

        client = self._clients.get(account.id)
        owns_client = False
        if client is None:
            session_path = str(SESSIONS_DIR / account.session_name)
            client = TelegramClient(session_path, settings.telegram_api_id, settings.telegram_api_hash)
            await client.connect()
            authorized = await client.is_user_authorized()
            if not authorized:
                await client.disconnect()
                raise ValueError("Session is not authorized. Reconnect Telegram account.")
            owns_client = True

        try:
            entity = chat_id if chat_id is not None else peer
            await client.pin_message(entity=entity, message=message_id, notify=notify)
        finally:
            if owns_client:
                await client.disconnect()

    async def send_media(
        self,
        account: TelegramAccount,
        db_factory,
        media_bytes: bytes,
        media_filename: str | None = None,
        caption: str | None = None,
        chat_id: int | None = None,
        peer: str | None = None,
    ) -> Notification:
        if not settings.telegram_api_id or not settings.telegram_api_hash:
            raise ValueError("Telegram API credentials are not configured")
        if not media_bytes:
            raise ValueError("Media file is empty")

        client = self._clients.get(account.id)
        owns_client = False
        if client is None:
            session_path = str(SESSIONS_DIR / account.session_name)
            client = TelegramClient(session_path, settings.telegram_api_id, settings.telegram_api_hash)
            await client.connect()
            authorized = await client.is_user_authorized()
            if not authorized:
                await client.disconnect()
                raise ValueError("Session is not authorized. Reconnect Telegram account.")
            owns_client = True

        ext = Path(media_filename or "").suffix.lower()
        if not ext:
            ext = ".bin"
        account_dir = MEDIA_DIR / str(account.id) / "outgoing"
        account_dir.mkdir(parents=True, exist_ok=True)
        local_name = f"{uuid4().hex}{ext}"
        local_path = account_dir / local_name
        local_path.write_bytes(media_bytes)
        base = settings.public_base_url.rstrip("/")
        media_url = f"{base}/media/telegram/{account.id}/outgoing/{local_name}"

        entity = chat_id if chat_id is not None else peer
        sent = await client.send_file(entity=entity, file=str(local_path), caption=(caption or "").strip() or None)
        if owns_client:
            await client.disconnect()

        db_local: Session = db_factory()
        sent_chat = getattr(sent, "chat", None)
        sent_chat_username = (getattr(sent_chat, "username", None) or "").strip() if sent_chat else ""
        sent_avatar_url = (
            f"https://t.me/i/userpic/320/{sent_chat_username}.jpg" if sent_chat_username else None
        )
        caption_text = (caption or "").strip()
        display_text = f"{caption_text}\n{media_url}".strip() if caption_text else f"File\n{media_url}"
        notification = Notification(
            source="telegram",
            telegram_account_id=account.id,
            sender_name=peer or getattr(getattr(sent, "chat", None), "title", None) or "You",
            sender_id=str(getattr(sent, "chat_id", "")) if getattr(sent, "chat_id", None) is not None else None,
            sender_avatar_url=sent_avatar_url,
            chat_id=getattr(sent, "chat_id", chat_id),
            chat_name=getattr(getattr(sent, "chat", None), "title", None) or peer,
            message_text=display_text,
            message_preview=display_text[:200],
            external_message_id=str(getattr(sent, "id", "")),
            external_message_id_int=getattr(sent, "id", None),
            reply_to_external_message_id_int=_reply_to_msg_id(sent),
            message_at=getattr(sent, "date", None),
            raw_payload=json.loads(json.dumps(sent.to_dict(), default=str)),
            is_outgoing=True,
            peer_read=False,
            is_read=True,
        )
        db_local.add(notification)
        db_local.commit()
        db_local.refresh(notification)
        db_local.close()
        return notification

    async def get_account_avatar_url(self, account: TelegramAccount) -> str | None:
        avatar_path = ACCOUNT_AVATARS_DIR / f"{account.id}.jpg"
        base = settings.public_base_url.rstrip("/")
        avatar_url = f"{base}/media/telegram/account_avatars/{account.id}.jpg"
        # Cache for 1 hour to avoid downloading photo on every request.
        if avatar_path.exists():
            age = time.time() - avatar_path.stat().st_mtime
            if age < 3600:
                return avatar_url

        if not settings.telegram_api_id or not settings.telegram_api_hash:
            return avatar_url if avatar_path.exists() else None

        client = self._clients.get(account.id)
        owns_client = False
        if client is None:
            session_path = str(SESSIONS_DIR / account.session_name)
            client = TelegramClient(session_path, settings.telegram_api_id, settings.telegram_api_hash)
            await client.connect()
            authorized = await client.is_user_authorized()
            if not authorized:
                await client.disconnect()
                return avatar_url if avatar_path.exists() else None
            owns_client = True

        try:
            me = await client.get_me()
            if me is None:
                return avatar_url if avatar_path.exists() else None
            downloaded = await client.download_profile_photo(me, file=str(avatar_path))
            if downloaded:
                return avatar_url
            return avatar_url if avatar_path.exists() else None
        except Exception as exc:
            print(f"[telegram] failed to fetch account avatar for {account.id}: {exc}")
            return avatar_url if avatar_path.exists() else None
        finally:
            if owns_client:
                await client.disconnect()

    async def mark_chat_read(
        self,
        account: TelegramAccount,
        db_factory,
        chat_id: int | None = None,
        peer: str | None = None,
    ) -> int:
        if not settings.telegram_api_id or not settings.telegram_api_hash:
            raise ValueError("Telegram API credentials are not configured")
        if chat_id is None and not (peer and peer.strip()):
            raise ValueError("chat_id or peer is required")

        client = self._clients.get(account.id)
        owns_client = False
        if client is None:
            session_path = str(SESSIONS_DIR / account.session_name)
            client = TelegramClient(session_path, settings.telegram_api_id, settings.telegram_api_hash)
            await client.connect()
            authorized = await client.is_user_authorized()
            if not authorized:
                await client.disconnect()
                raise ValueError("Session is not authorized. Reconnect Telegram account.")
            owns_client = True

        try:
            entity = chat_id if chat_id is not None else peer
            await client.send_read_acknowledge(entity=entity)
        finally:
            if owns_client:
                await client.disconnect()

        db_local: Session = db_factory()
        try:
            query = db_local.query(Notification).filter(
                and_(
                    Notification.source == "telegram",
                    Notification.telegram_account_id == account.id,
                    Notification.is_outgoing.is_(False),
                    Notification.is_read.is_(False),
                )
            )
            if chat_id is not None:
                query = query.filter(Notification.chat_id == chat_id)
            elif peer:
                peer_like = peer.strip()
                query = query.filter(
                    (Notification.sender_name == peer_like) | (Notification.chat_name == peer_like)
                )
            rows = query.all()
            for row in rows:
                row.is_read = True
            if rows:
                db_local.commit()
            return len(rows)
        finally:
            db_local.close()

    async def stop(self):
        for client in self._clients.values():
            await client.disconnect()
        for task in self._tasks.values():
            task.cancel()
        self._clients.clear()
        self._tasks.clear()
        self._running = False


telegram_listener_manager = TelegramListenerManager()
