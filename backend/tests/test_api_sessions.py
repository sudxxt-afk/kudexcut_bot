import hashlib
import hmac
import json
from pathlib import Path
import time
from urllib.parse import urlencode

import fakeredis.aioredis
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app


def make_init_data(token: str, user_id: int = 42, auth_date: int = 1_700_000_000) -> str:
    values = {
        "auth_date": str(auth_date),
        "query_id": "query-id",
        "user": json.dumps({"id": user_id, "first_name": "Test"}, separators=(",", ":")),
    }
    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
    secret_key = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


@pytest_asyncio.fixture
async def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    token = "bot-token"
    monkeypatch.setattr("app.main.settings.bot_token", token)
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    app.state.redis = redis
    session_id = "a" * 32
    video_path = tmp_path / "input.mp4"
    video_path.write_bytes(b"video-data")
    await redis.set(
        f"videocut:session:{session_id}",
        json.dumps(
            {
                "session_id": session_id,
                "telegram_user_id": 42,
                "chat_id": 99,
                "file_path": str(video_path),
                "file_name": "input.mp4",
                "mime_type": "video/mp4",
                "file_size": 10,
                "duration_seconds": 60.0,
                "width": 1280,
                "height": 720,
                "created_at": "2026-01-01T00:00:00+00:00",
                "status": "editing",
            }
        ),
    )
    init_data = make_init_data(token, user_id=42, auth_date=int(time.time()))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client, session_id, init_data
    await redis.aclose()


@pytest.mark.asyncio
async def test_session_metadata(client) -> None:
    http_client, session_id, init_data = client
    response = await http_client.get(
        f"/api/sessions/{session_id}", headers={"X-Telegram-Init-Data": init_data}
    )
    assert response.status_code == 200
    assert response.json()["duration_seconds"] == 60.0
    assert response.json()["video_url"].endswith("/video")


@pytest.mark.asyncio
async def test_video_is_streamed_to_owner(client) -> None:
    http_client, session_id, init_data = client
    response = await http_client.get(
        f"/api/sessions/{session_id}/video", headers={"X-Telegram-Init-Data": init_data}
    )
    assert response.status_code == 200
    assert response.content == b"video-data"
    assert response.headers["content-type"] == "video/mp4"


@pytest.mark.asyncio
async def test_invalid_auth_is_rejected(client) -> None:
    http_client, session_id, _ = client
    response = await http_client.get(f"/api/sessions/{session_id}")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_foreign_session_is_rejected(client) -> None:
    http_client, session_id, _ = client
    foreign_init_data = make_init_data("bot-token", user_id=7, auth_date=int(time.time()))
    response = await http_client.get(
        f"/api/sessions/{session_id}", headers={"X-Telegram-Init-Data": foreign_init_data}
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_trim_validates_range(client) -> None:
    http_client, session_id, init_data = client
    response = await http_client.post(
        f"/api/sessions/{session_id}/trim",
        headers={"X-Telegram-Init-Data": init_data},
        json={"start": 10, "end": 20},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "accepted"

    invalid = await http_client.post(
        f"/api/sessions/{session_id}/trim",
        headers={"X-Telegram-Init-Data": init_data},
        json={"start": 20, "end": 10},
    )
    assert invalid.status_code == 422
