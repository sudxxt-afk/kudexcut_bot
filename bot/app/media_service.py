import asyncio
import json
import math
from dataclasses import dataclass
from pathlib import Path


class MediaValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class MediaMetadata:
    duration_seconds: float
    width: int
    height: int
    mime_type: str


async def probe_audio(path: Path, *, timeout_seconds: int = 30) -> MediaMetadata:
    command = [
        "ffprobe", "-v", "error", "-select_streams", "a:0",
        "-show_entries", "stream=codec_name:format=duration,format_name",
        "-of", "json", str(path),
    ]
    try:
        process = await asyncio.create_subprocess_exec(
            *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
    except (asyncio.TimeoutError, OSError) as exc:
        if isinstance(exc, asyncio.TimeoutError):
            process.kill()
            await process.communicate()
        raise MediaValidationError("Unable to inspect audio") from exc
    if process.returncode != 0:
        raise MediaValidationError(stderr.decode("utf-8", errors="replace").strip())
    try:
        payload = json.loads(stdout)
        stream = payload["streams"][0]
        duration = float(payload["format"]["duration"])
        codec = stream["codec_name"]
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise MediaValidationError("Audio metadata is incomplete") from exc
    if not math.isfinite(duration) or duration <= 0 or not codec:
        raise MediaValidationError("Audio metadata is invalid")
    return MediaMetadata(duration, 0, 0, "audio/mpeg")


async def extract_cover(source_path: Path, cover_path: Path, *, timeout_seconds: int = 30) -> bool:
    command = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(source_path), "-map", "0:v:0", "-an",
        "-frames:v", "1", "-q:v", "3", str(cover_path),
    ]
    process: asyncio.subprocess.Process | None = None
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(process.wait(), timeout=timeout_seconds)
    except (asyncio.TimeoutError, OSError):
        if process is not None and process.returncode is None:
            process.kill()
            await process.wait()
        cover_path.unlink(missing_ok=True)
        return False
    if process.returncode != 0 or not cover_path.is_file() or cover_path.stat().st_size == 0:
        cover_path.unlink(missing_ok=True)
        return False
    return True


async def probe_video(path: Path, *, timeout_seconds: int = 30) -> MediaMetadata:
    command = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height:format=duration,format_name",
        "-of", "json", str(path),
    ]
    try:
        process = await asyncio.create_subprocess_exec(
            *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
    except asyncio.TimeoutError as exc:
        process.kill()
        try:
            await process.communicate()
        except (asyncio.TimeoutError, OSError):
            pass
        raise MediaValidationError("Unable to inspect video") from exc
    except OSError as exc:
        raise MediaValidationError("Unable to inspect video") from exc
    if process.returncode != 0:
        raise MediaValidationError(stderr.decode("utf-8", errors="replace").strip())
    try:
        payload = json.loads(stdout)
        stream = payload["streams"][0]
        format_data = payload["format"]
        duration = float(format_data["duration"])
        width = int(stream["width"])
        height = int(stream["height"])
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise MediaValidationError("Video metadata is incomplete") from exc
    if not math.isfinite(duration) or duration <= 0 or width <= 0 or height <= 0:
        raise MediaValidationError("Video metadata is invalid")
    return MediaMetadata(duration, width, height, "video/mp4")
