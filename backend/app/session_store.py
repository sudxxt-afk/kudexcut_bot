import json
from dataclasses import dataclass
from pathlib import Path

from redis.asyncio import Redis


@dataclass(frozen=True, slots=True)
class MediaSession:
    session_id: str
    telegram_user_id: int
    chat_id: int
    file_path: str
    file_name: str
    mime_type: str
    file_size: int
    duration_seconds: float
    width: int
    height: int
    created_at: str
    status: str = "editing"


class SessionStore:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def get(self, session_id: str) -> MediaSession | None:
        payload = await self._redis.get(self._key(session_id))
        if payload is None:
            return None
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        return MediaSession(**json.loads(payload))

    @staticmethod
    def _key(session_id: str) -> str:
        return f"videocut:session:{session_id}"


def session_metadata(session: MediaSession) -> dict[str, object]:
    return {
        "session_id": session.session_id,
        "file_name": session.file_name,
        "mime_type": session.mime_type,
        "file_size": session.file_size,
        "duration_seconds": session.duration_seconds,
        "width": session.width,
        "height": session.height,
        "status": session.status,
        "video_url": f"/api/sessions/{session.session_id}/video",
    }
