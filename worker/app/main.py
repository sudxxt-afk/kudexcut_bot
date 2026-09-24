import asyncio
import json
import logging
import shutil
from pathlib import Path

from aiogram import Bot
from aiogram.types import FSInputFile
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from redis.asyncio import Redis

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    bot_token: str = Field(min_length=1)
    redis_url: str = "redis://redis:6379/0"
    temp_dir: Path = Path("/tmp/videocut")
    ffmpeg_timeout_seconds: int = 600
    max_output_size_bytes: int = 50 * 1024 * 1024
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


class TrimJob(BaseModel):
    session_id: str
    telegram_user_id: int
    chat_id: int
    input_path: Path
    media_type: str = "video"
    title: str = ""
    artist: str = ""
    start: float = Field(ge=0)
    end: float = Field(gt=0)


async def run_ffmpeg(job: TrimJob, output_path: Path, timeout: int, cover_path: Path | None = None) -> None:
    duration = job.end - job.start
    if job.media_type == "audio":
        command = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", str(job.start),
            "-i", str(job.input_path),
        ]
        if cover_path is not None and cover_path.is_file():
            command.extend([
                "-i", str(cover_path),
                "-map", "0:a:0",
                "-map", "1:v:0",
                "-c:v", "mjpeg",
                "-disposition:v:0", "attached_pic",
            ])
        else:
            command.extend(["-vn"])
        command.extend(["-t", str(duration), "-c:a", "libmp3lame"])
        if job.title:
            command.extend(["-metadata", f"title={_metadata_value(job.title)}"])
        if job.artist:
            command.extend(["-metadata", f"artist={_metadata_value(job.artist)}"])
        command.extend(["-id3v2_version", "3", str(output_path)])
    else:
        command = [
            "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        str(job.start),
        "-i",
        str(job.input_path),
        "-t",
        str(duration),
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        process.kill()
        await process.communicate()
        raise RuntimeError("FFmpeg processing timed out")
    if process.returncode != 0:
        raise RuntimeError(stderr.decode("utf-8", errors="replace")[-2000:])
    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise RuntimeError("FFmpeg produced no output")


async def update_status(redis: Redis, session_id: str, status: str) -> None:
    key = f"videocut:session:{session_id}"
    raw = await redis.get(key)
    if raw is None:
        return
    payload = json.loads(raw)
    payload["status"] = status
    ttl = await redis.ttl(key)
    await redis.set(key, json.dumps(payload), ex=max(ttl, 1))


async def process_job(job: TrimJob, redis: Redis, bot: Bot, settings: Settings) -> None:
    input_path = job.input_path
    session_dir = input_path.parent
    output_path = session_dir / ("output.mp3" if job.media_type == "audio" else "output.mp4")
    try:
        await update_status(redis, job.session_id, "processing")
        embed_cover: Path | None = None
        if job.media_type == "audio":
            source_cover = _find_cover(session_dir)
            if source_cover is not None:
                embed_cover = session_dir / "cover-embed.jpg"
                await prepare_cover(source_cover, embed_cover, settings.ffmpeg_timeout_seconds)
        await run_ffmpeg(job, output_path, settings.ffmpeg_timeout_seconds, cover_path=embed_cover)
        if output_path.stat().st_size > settings.max_output_size_bytes:
            raise RuntimeError("Processed video exceeds Telegram size limit")
        await update_status(redis, job.session_id, "sending")
        if job.media_type == "audio":
            original_name = "audio.mp3"
            title = job.title
            performer = job.artist
            key = f"videocut:session:{job.session_id}"
            raw = await redis.get(key)
            if raw:
                payload = json.loads(raw)
                source_name = Path(str(payload.get("file_name") or original_name))
                if not title:
                    title = str(payload.get("title") or source_name.stem or "audio")
                if not performer:
                    performer = str(payload.get("artist") or "")
            title = title or "audio"
            original_name = f"{_safe_filename(title)}.mp3"
            await bot.send_audio(
                chat_id=job.chat_id,
                audio=FSInputFile(output_path, filename=original_name),
                title=title,
                performer=performer or None,
                thumbnail=FSInputFile(embed_cover) if embed_cover is not None and embed_cover.is_file() and embed_cover.stat().st_size <= 200 * 1024 else None,
                caption="Готово. Вот обрезанное аудио.",
            )
        else:
            await bot.send_video(
                chat_id=job.chat_id,
                video=FSInputFile(output_path),
                caption="Готово. Вот обрезанное видео.",
            )
        await update_status(redis, job.session_id, "completed")
    except Exception:
        logger.exception("Failed to process job %s", job.session_id)
        await update_status(redis, job.session_id, "failed")
    finally:
        shutil.rmtree(session_dir, ignore_errors=True)


def _safe_filename(value: str) -> str:
    cleaned = "".join("_" if char in '\\/:*?"<>|' else char for char in value).strip().strip(".")
    return cleaned[:80] or "audio"


def _metadata_value(value: str) -> str:
    return " ".join(value.split())


def _find_cover(directory: Path) -> Path | None:
    for name in ("cover.jpg", "cover.jpeg", "cover.png", "cover.webp"):
        path = directory / name
        if path.is_file() and path.stat().st_size > 0:
            return path
    return None


async def prepare_cover(source: Path, dest: Path, timeout: int) -> None:
    command = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(source),
        "-vf", "scale=320:320:force_original_aspect_ratio=decrease",
        "-frames:v", "1",
        "-q:v", "5",
        str(dest),
    ]
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        process.kill()
        await process.communicate()
        raise RuntimeError("Cover conversion timed out")
    if process.returncode != 0 or not dest.is_file() or dest.stat().st_size == 0:
        raise RuntimeError(stderr.decode("utf-8", errors="replace")[-2000:] or "Cover conversion failed")


async def main() -> None:
    settings = Settings()
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    bot = Bot(settings.bot_token)
    try:
        while True:
            result = await redis.blpop("videocut:jobs:trim", timeout=5)
            if result is None:
                continue
            _, raw_job = result
            try:
                job = TrimJob.model_validate_json(raw_job)
                await process_job(job, redis, bot, settings)
            except Exception:
                logger.exception("Invalid trim job")
    finally:
        await redis.aclose()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
