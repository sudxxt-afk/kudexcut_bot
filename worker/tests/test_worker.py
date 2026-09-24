import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.main import TrimJob, run_ffmpeg


@pytest.mark.asyncio
async def test_run_ffmpeg_builds_trim_command(tmp_path: Path) -> None:
    output_path = tmp_path / "output.mp4"
    output_path.write_bytes(b"result")
    process = type("Process", (), {"returncode": 0})()
    process.communicate = AsyncMock(return_value=(b"", b""))

    with patch(
        "app.main.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=process),
    ) as create_process:
        await run_ffmpeg(
            TrimJob(
                session_id="session",
                telegram_user_id=1,
                chat_id=2,
                input_path=tmp_path / "input.mp4",
                start=1.5,
                end=4.5,
            ),
            output_path,
            timeout=30,
        )

    command = create_process.await_args.args
    assert command[0] == "ffmpeg"
    assert "-ss" in command and "1.5" in command
    assert "-t" in command and "3.0" in command
    assert str(output_path) in command


@pytest.mark.asyncio
async def test_run_ffmpeg_kills_process_on_timeout(tmp_path: Path) -> None:
    process = type("Process", (), {"returncode": None})()
    process.communicate = AsyncMock(side_effect=[asyncio.TimeoutError, (b"", b"")])
    process.kill = Mock()

    with patch(
        "app.main.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=process),
    ):
        with pytest.raises(RuntimeError, match="timed out"):
            await run_ffmpeg(
                TrimJob(
                    session_id="session",
                    telegram_user_id=1,
                    chat_id=2,
                    input_path=tmp_path / "input.mp4",
                    start=0,
                    end=1,
                ),
                tmp_path / "output.mp4",
                timeout=1,
            )

    process.kill.assert_called_once()


@pytest.mark.asyncio
async def test_run_ffmpeg_audio_command(tmp_path: Path) -> None:
    output_path = tmp_path / "output.mp3"
    output_path.write_bytes(b"audio")
    process = type("Process", (), {"returncode": 0})()
    process.communicate = AsyncMock(return_value=(b"", b""))

    with patch(
        "app.main.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=process),
    ) as create_process:
        await run_ffmpeg(
            TrimJob(
                session_id="session",
                telegram_user_id=1,
                chat_id=2,
                input_path=tmp_path / "input.mp3",
                media_type="audio",
                start=2,
                end=5,
            ),
            output_path,
            timeout=30,
        )

    command = create_process.await_args.args
    assert "-vn" in command
    assert "libmp3lame" in command
    assert "0:v:0" not in command
    assert str(output_path) in command
