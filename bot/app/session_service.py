import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

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


class SessionService:
    def __init__(self, redis: Redis, temp_dir: Path, ttl_seconds: int) -> None:
        self._redis = redis
        self._temp_dir = temp_dir
        self._ttl_seconds = ttl_seconds

    async def create(
        self,
        *,
        telegram_user_id: int,
        chat_id: int,
        source_path: Path,
        file_name: str,
        mime_type: str,
        file_size: int,
        duration_seconds: float,
        width: int,
        height: int,
    ) -> MediaSession:
        session_id = uuid4().hex
        session = MediaSession(
            session_id=session_id,
            telegram_user_id=telegram_user_id,
            chat_id=chat_id,
            file_path=str(source_path),
            file_name=file_name,
            mime_type=mime_type,
            file_size=file_size,
            duration_seconds=duration_seconds,
            width=width,
            height=height,
            created_at=datetime.now(UTC).isoformat(),
        )
        await self._redis.set(
            self._key(session_id),
            json.dumps(asdict(session)),
            ex=self._ttl_seconds,
        )
        return session

    async def get(self, session_id: str) -> MediaSession | None:
        payload = await self._redis.get(self._key(session_id))
        if payload is None:
            return None
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        return MediaSession(**json.loads(payload))

    async def update_file_path(self, session_id: str, file_path: Path) -> None:
        session = await self.get(session_id)
        if session is None:
            raise KeyError(session_id)
        payload = asdict(session)
        payload["file_path"] = str(file_path)
        await self._redis.set(
            self._key(session_id),
            json.dumps(payload),
            ex=self._ttl_seconds,
        )

    async def delete(self, session_id: str) -> None:
        await self._redis.delete(self._key(session_id))

    @staticmethod
    def _key(session_id: str) -> str:
        return f"videocut:session:{session_id}"
