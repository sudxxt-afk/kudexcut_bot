from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from redis.asyncio import Redis

from .config import Settings
from .session_store import MediaSession, SessionStore, session_metadata
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


@app.get("/api/sessions/{session_id}/video")
async def get_video(
    session_id: str,
    user: TelegramUser = Depends(current_user),
    store: SessionStore = Depends(get_session_store),
) -> FileResponse:
    session = await owned_session(session_id, user, store)
    path = Path(session.file_path)
    if not path.is_file():
        raise HTTPException(status_code=410, detail="Video file is no longer available")
    return FileResponse(
        path,
        media_type=session.mime_type,
        filename=session.file_name,
    )


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
    if session.status != "editing":
        raise HTTPException(status_code=409, detail="Session is not editable")
    return {"session_id": session.session_id, "status": "accepted"}
