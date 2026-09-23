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


async def probe_video(path: Path, *, timeout_seconds: int = 30) -> MediaMetadata:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height:format=duration,format_name",
        "-of",
        "json",
        str(path),
    ]
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=timeout_seconds
        )
    except (TimeoutError, OSError) as exc:
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

    return MediaMetadata(
        duration_seconds=duration,
        width=width,
        height=height,
        mime_type="video/mp4",
    )
