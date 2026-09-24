import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
from redis.asyncio import Redis

from .config import Settings
from .session_store import COVER_NAMES, MediaSession, SessionStore, find_cover, session_metadata
from .telegram_auth import TelegramAuthError, TelegramUser, validate_init_data

settings = Settings()


@asynccontextmanager
async def lifespan(application: FastAPI):
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    application.state.redis = redis
    try:
        yield
    finally:
        await redis.aclose()


app = FastAPI(title="VideoCut API", version="0.2.0", lifespan=lifespan)


class TrimRequest(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    title: str = Field(default="", max_length=120)
    artist: str = Field(default="", max_length=120)

    @field_validator("title", "artist")
    @classmethod
    def clean_text(cls, value: str) -> str:
        return " ".join(value.split())


async def current_user(
    request: Request,
    init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
) -> TelegramUser:
    try:
        return validate_init_data(
            init_data or "",
            bot_token=settings.bot_token,
            max_age_seconds=settings.telegram_init_data_max_age_seconds,
        )
    except TelegramAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc


async def get_session_store(request: Request) -> SessionStore:
    return SessionStore(request.app.state.redis)


async def owned_session(
    session_id: str,
    user: TelegramUser,
    store: SessionStore,
) -> MediaSession:
    session = await store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found or expired")
    if session.telegram_user_id != user.id:
        raise HTTPException(status_code=403, detail="Session does not belong to user")
    return session


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/sessions/{session_id}")
async def get_session(
    session_id: str,
    user: TelegramUser = Depends(current_user),
    store: SessionStore = Depends(get_session_store),
) -> dict[str, object]:
    session = await owned_session(session_id, user, store)
    return session_metadata(session)


@app.get("/api/sessions/{session_id}/media")
@app.get("/api/sessions/{session_id}/video")
async def get_media(
    session_id: str,
    user: TelegramUser = Depends(current_user),
    store: SessionStore = Depends(get_session_store),
) -> FileResponse:
    session = await owned_session(session_id, user, store)
    path = Path(session.file_path)
    if not path.is_file():
        raise HTTPException(status_code=410, detail="Media file is no longer available")
    return FileResponse(
        path,
        media_type=session.mime_type,
        filename=session.file_name,
    )


@app.get("/api/sessions/{session_id}/cover")
async def get_cover(
    session_id: str,
    user: TelegramUser = Depends(current_user),
    store: SessionStore = Depends(get_session_store),
) -> FileResponse:
    session = await owned_session(session_id, user, store)
    path = find_cover(Path(session.file_path).parent)
    if path is None:
        raise HTTPException(status_code=404, detail="Cover is not available")
    media_types = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
    return FileResponse(path, media_type=media_types.get(path.suffix.lower(), "application/octet-stream"), filename=path.name)


MAX_COVER_BYTES = 5 * 1024 * 1024
COVER_CONTENT_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


@app.post("/api/sessions/{session_id}/cover")
async def replace_cover(
    session_id: str,
    request: Request,
    user: TelegramUser = Depends(current_user),
    store: SessionStore = Depends(get_session_store),
) -> dict[str, str]:
    session = await owned_session(session_id, user, store)
    if session.media_type != "audio":
        raise HTTPException(status_code=422, detail="Обложку можно менять только у аудио")
    if session.status != "editing":
        raise HTTPException(status_code=409, detail="Сессия уже обрабатывается")
    content_type = (request.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    suffix = COVER_CONTENT_TYPES.get(content_type)
    if suffix is None:
        raise HTTPException(status_code=415, detail="Обложка должна быть JPEG, PNG или WebP")
    body = await request.body()
    if not body:
        raise HTTPException(status_code=422, detail="Файл обложки пустой")
    if len(body) > MAX_COVER_BYTES:
        raise HTTPException(status_code=413, detail="Обложка больше 5 МБ")
    if not _looks_like_image(body, content_type):
        raise HTTPException(status_code=415, detail="Файл не похож на изображение")
    directory = Path(session.file_path).parent
    for name in COVER_NAMES:
        (directory / name).unlink(missing_ok=True)
    (directory / f"cover{suffix}").write_bytes(body)
    return {"cover_url": f"/api/sessions/{session.session_id}/cover"}


def _looks_like_image(body: bytes, content_type: str) -> bool:
    if content_type == "image/jpeg":
        return body.startswith(b"\xff\xd8\xff")
    if content_type == "image/png":
        return body.startswith(b"\x89PNG\r\n\x1a\n")
    return len(body) >= 12 and body.startswith(b"RIFF") and body[8:12] == b"WEBP"


@app.get("/api/sessions/{session_id}/status")
async def get_status(
    session_id: str,
    user: TelegramUser = Depends(current_user),
    store: SessionStore = Depends(get_session_store),
) -> dict[str, str]:
    session = await owned_session(session_id, user, store)
    return {"session_id": session.session_id, "status": session.status}


@app.post("/api/sessions/{session_id}/trim")
async def trim_video(
    request: Request,
    session_id: str,
    payload: TrimRequest,
    user: TelegramUser = Depends(current_user),
    store: SessionStore = Depends(get_session_store),
) -> dict[str, str]:
    session = await owned_session(session_id, user, store)
    if payload.end <= payload.start:
        raise HTTPException(status_code=422, detail="End must be greater than start")
    if payload.end > session.duration_seconds:
        raise HTTPException(status_code=422, detail="End exceeds video duration")
    if session.media_type == "audio":
        updated = await store.update_fields(session.session_id, title=payload.title, artist=payload.artist)
        if updated is not None:
            session = updated
    claimed = await store.claim_for_processing(session.session_id)
    if claimed is None:
        raise HTTPException(status_code=409, detail="Session is not editable")
    job = {
        "session_id": claimed.session_id,
        "telegram_user_id": claimed.telegram_user_id,
        "chat_id": claimed.chat_id,
        "input_path": claimed.file_path,
        "media_type": claimed.media_type,
        "title": claimed.title,
        "artist": claimed.artist,
        "start": payload.start,
        "end": payload.end,
    }
    await request.app.state.redis.rpush(SessionStore.JOB_QUEUE, json.dumps(job))
    return {"session_id": claimed.session_id, "status": "queued"}
