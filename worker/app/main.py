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
    start: float = Field(ge=0)
    end: float = Field(gt=0)


async def run_ffmpeg(job: TrimJob, output_path: Path, timeout: int) -> None:
    duration = job.end - job.start
    command = [
        "ffmpeg",
        "-y",
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
    output_path = session_dir / "output.mp4"
    try:
        await update_status(redis, job.session_id, "processing")
        await run_ffmpeg(job, output_path, settings.ffmpeg_timeout_seconds)
        if output_path.stat().st_size > settings.max_output_size_bytes:
            raise RuntimeError("Processed video exceeds Telegram size limit")
        await update_status(redis, job.session_id, "sending")
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
