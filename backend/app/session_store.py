import json
from dataclasses import asdict, dataclass
from pathlib import Path

from redis.asyncio import Redis
from redis.exceptions import WatchError


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
    media_type: str = "video"
    created_at: str = ""
    status: str = "editing"


class SessionStore:
    JOB_QUEUE = "videocut:jobs:trim"

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def get(self, session_id: str) -> MediaSession | None:
        payload = await self._redis.get(self._key(session_id))
        if payload is None:
            return None
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        return MediaSession(**json.loads(payload))

    async def update_status(self, session_id: str, status: str) -> MediaSession | None:
        session = await self.get(session_id)
        if session is None:
            return None
        payload = asdict(session)
        payload["status"] = status
        ttl = await self._redis.ttl(self._key(session_id))
        await self._redis.set(self._key(session_id), json.dumps(payload), ex=max(ttl, 1))
        return MediaSession(**payload)

    async def claim_for_processing(self, session_id: str) -> MediaSession | None:
        key = self._key(session_id)
        for _ in range(3):
            try:
                async with self._redis.pipeline(transaction=True) as pipeline:
                    await pipeline.watch(key)
                    raw = await pipeline.get(key)
                    if raw is None:
                        await pipeline.reset()
                        return None
                    if isinstance(raw, bytes):
                        raw = raw.decode("utf-8")
                    payload = json.loads(raw)
                    if payload["status"] != "editing":
                        await pipeline.reset()
                        return None
                    payload["status"] = "queued"
                    ttl = await pipeline.ttl(key)
                    pipeline.multi()
                    pipeline.set(key, json.dumps(payload), ex=max(ttl, 1))
                    await pipeline.execute()
                    return MediaSession(**payload)
            except WatchError:
                continue
        return None

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
        "media_type": session.media_type,
        "media_url": f"/api/sessions/{session.session_id}/media",
        "video_url": f"/api/sessions/{session.session_id}/video",
        "cover_url": (
            f"/api/sessions/{session.session_id}/cover"
            if session.media_type == "audio" and (Path(session.file_path).parent / "cover.jpg").is_file()
            else None
        ),
    }
