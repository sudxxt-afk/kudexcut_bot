import json
from pathlib import Path

import fakeredis.aioredis
import pytest
import pytest_asyncio

from app.session_service import MediaSession, SessionService


@pytest_asyncio.fixture
async def redis() -> fakeredis.aioredis.FakeRedis:
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield client
    await client.aclose()


@pytest.mark.asyncio
async def test_session_create_get_update_delete(redis: fakeredis.aioredis.FakeRedis) -> None:
    service = SessionService(redis, Path("/tmp/videocut"), ttl_seconds=120)

    session = await service.create(
        telegram_user_id=100,
        chat_id=200,
        source_path=Path("/tmp/input"),
        file_name="clip.mp4",
        mime_type="video/mp4",
        file_size=123,
        duration_seconds=12.5,
        width=1920,
        height=1080,
    )

    assert isinstance(session, MediaSession)
    assert len(session.session_id) == 32
    assert session.status == "editing"
    assert (await redis.ttl(f"videocut:session:{session.session_id}")) > 0

    loaded = await service.get(session.session_id)
    assert loaded == session

    await service.update_file_path(session.session_id, Path("/tmp/new-input"))
    updated = await service.get(session.session_id)
    assert updated is not None
    assert updated.file_path == "/tmp/new-input"
    assert updated.telegram_user_id == session.telegram_user_id

    await service.delete(session.session_id)
    assert await service.get(session.session_id) is None


@pytest.mark.asyncio
async def test_session_get_supports_bytes_payload(
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    service = SessionService(redis, Path("/tmp/videocut"), ttl_seconds=120)
    payload = {
        "session_id": "a" * 32,
        "telegram_user_id": 1,
        "chat_id": 2,
        "file_path": "/tmp/input",
        "file_name": "input.mp4",
        "mime_type": "video/mp4",
        "file_size": 1,
        "duration_seconds": 1.0,
        "width": 1,
        "height": 1,
        "created_at": "2026-01-01T00:00:00+00:00",
        "status": "processing",
    }
    await redis.set("videocut:session:" + "a" * 32, json.dumps(payload))

    result = await service.get("a" * 32)

    assert result is not None
    assert result.status == "processing"


@pytest.mark.asyncio
async def test_missing_session_returns_none_and_update_raises(
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    service = SessionService(redis, Path("/tmp/videocut"), ttl_seconds=120)

    assert await service.get("missing") is None
    with pytest.raises(KeyError, match="missing"):
        await service.update_file_path("missing", Path("/tmp/input"))
