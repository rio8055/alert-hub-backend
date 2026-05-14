import mimetypes
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response

from app.core.config import settings
from app.services.r2_storage import r2_get_media_bytes

router = APIRouter()


@router.get("/{path:path}", response_model=None)
async def serve_media(path: str):
    if not path or path.startswith("/") or any(part == ".." for part in path.replace("\\", "/").split("/")):
        raise HTTPException(status_code=400, detail="Invalid path")
    safe = path.replace("\\", "/")
    if settings.r2_enabled:
        data = await r2_get_media_bytes(safe)
        if data is not None:
            mt, _ = mimetypes.guess_type(safe)
            return Response(content=data, media_type=mt or "application/octet-stream")
    local = Path("media") / safe
    if local.is_file():
        return FileResponse(local)
    raise HTTPException(status_code=404, detail="Not found")
