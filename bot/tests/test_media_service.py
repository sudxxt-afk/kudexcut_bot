import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.media_service import MediaMetadata, MediaValidationError, probe_video


class FakeProcess:
    def __init__(self, *, returncode: int, stdout: bytes, stderr: bytes = b"") -> None:
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr
        self.communicate = AsyncMock(return_value=(stdout, stderr))


@pytest.mark.asyncio
async def test_probe_video_returns_metadata() -> None:
    payload = {
        "streams": [{"width": 1920, "height": 1080}],
        "format": {"duration": "12.5", "format_name": "mov,mp4"},
    }
    process = FakeProcess(returncode=0, stdout=json.dumps(payload).encode())

    with patch(
        "app.media_service.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=process),
    ) as create_process:
        result = await probe_video(Path("input.mov"))

    assert result == MediaMetadata(12.5, 1920, 1080, "video/mp4")
    command = create_process.await_args.args
    assert command[0] == "ffprobe"
    assert "-select_streams" in command
    assert "v:0" in command
    assert command[-1] == "input.mov"


@pytest.mark.asyncio
async def test_probe_video_rejects_process_error() -> None:
    process = FakeProcess(returncode=1, stdout=b"", stderr=b"bad input")

    with patch(
        "app.media_service.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=process),
    ):
        with pytest.raises(MediaValidationError, match="bad input"):
            await probe_video(Path("input.mp4"))


@pytest.mark.asyncio
async def test_probe_video_wraps_spawn_error() -> None:
    with patch(
        "app.media_service.asyncio.create_subprocess_exec",
        new=AsyncMock(side_effect=OSError("ffprobe missing")),
    ):
        with pytest.raises(MediaValidationError, match="Unable to inspect video"):
            await probe_video(Path("input.mp4"))


@pytest.mark.asyncio
async def test_probe_video_wraps_timeout() -> None:
    process = FakeProcess(returncode=0, stdout=b"")
    process.communicate = AsyncMock(side_effect=asyncio.TimeoutError)

    with patch(
        "app.media_service.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=process),
    ):
        with pytest.raises(MediaValidationError, match="Unable to inspect video"):
            await probe_video(Path("input.mp4"))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"streams": []},
        {"streams": [{}], "format": {"duration": "1"}},
        {"streams": [{"width": 1, "height": 1}], "format": {}},
        {"streams": [{"width": 1, "height": 1}], "format": {"duration": "nope"}},
    ],
)
async def test_probe_video_rejects_incomplete_metadata(payload: dict) -> None:
    process = FakeProcess(returncode=0, stdout=json.dumps(payload).encode())

    with patch(
        "app.media_service.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=process),
    ):
        with pytest.raises(MediaValidationError, match="Video metadata is incomplete"):
            await probe_video(Path("input.mp4"))


@pytest.mark.asyncio
@pytest.mark.parametrize("duration", ["0", "-1", "NaN", "Infinity"])
async def test_probe_video_rejects_invalid_duration(duration: str) -> None:
    payload = {
        "streams": [{"width": 1, "height": 1}],
        "format": {"duration": duration},
    }
    process = FakeProcess(returncode=0, stdout=json.dumps(payload).encode())

    with patch(
        "app.media_service.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=process),
    ):
        with pytest.raises(MediaValidationError, match="Video metadata is invalid"):
            await probe_video(Path("input.mp4"))


@pytest.mark.asyncio
@pytest.mark.parametrize("width,height", [(0, 100), (-1, 100), (100, 0), (100, -1)])
async def test_probe_video_rejects_invalid_dimensions(width: int, height: int) -> None:
    payload = {
        "streams": [{"width": width, "height": height}],
        "format": {"duration": "1"},
    }
    process = FakeProcess(returncode=0, stdout=json.dumps(payload).encode())

    with patch(
        "app.media_service.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=process),
    ):
        with pytest.raises(MediaValidationError, match="Video metadata is invalid"):
            await probe_video(Path("input.mp4"))
