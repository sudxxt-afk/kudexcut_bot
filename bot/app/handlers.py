import logging
import shutil
from pathlib import Path
from uuid import uuid4

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo

from .config import Settings
from .media_service import MediaValidationError, extract_cover, probe_audio, probe_video
from .session_service import SessionService

logger = logging.getLogger(__name__)


def register_handlers(
    dispatcher: Dispatcher,
    *,
    bot: Bot,
    settings: Settings,
    session_service: SessionService,
) -> None:
    @dispatcher.message(CommandStart())
    async def start(message: Message) -> None:
        await message.answer(
            "Привет! Отправь аудио или видео, выбери нужный фрагмент, "
            "и я верну готовый файл сюда."
        )

    @dispatcher.message(F.audio | F.video | F.document)
    async def receive_media(message: Message) -> None:
        media = message.audio or message.video or message.document
        if media is None:
            return
        media_type = "audio" if message.audio or (message.document and (media.mime_type or "").startswith("audio/")) else "video"
        mime_type = media.mime_type or ("audio/mpeg" if media_type == "audio" else "video/mp4")
        if message.document and media_type == "video" and not mime_type.startswith("video/"):
            await message.answer("Пожалуйста, отправь аудио или видеофайл.")
            return
        file_size = media.file_size
        if file_size is not None and file_size > settings.max_file_size_bytes:
            await message.answer(
                "Файл слишком большой. Отправь видео меньшего размера."
            )
            return

        user_id = message.from_user.id if message.from_user else message.chat.id
        session_dir: Path | None = None
        final_dir: Path | None = None
        await message.answer("Проверяю файл…")

        try:
            session_dir = settings.temp_dir / f"pending-{uuid4().hex}"
            session_dir.mkdir(parents=True, exist_ok=False)
            source_path = session_dir / "input"
            telegram_file = await bot.get_file(media.file_id)
            await bot.download_file(telegram_file.file_path, source_path)

            downloaded_size = source_path.stat().st_size
            if downloaded_size > settings.max_file_size_bytes:
                await message.answer(
                    "Файл слишком большой. Отправь видео меньшего размера."
                )
                return

            metadata = await (probe_audio(source_path) if media_type == "audio" else probe_video(source_path))
            if metadata.duration_seconds > settings.max_duration_seconds:
                limit_minutes = settings.max_duration_seconds / 60
                await message.answer(
                    f"Видео слишком длинное. Отправь ролик длительностью до {limit_minutes:g} минут."
                )
                return

            if media_type == "audio":
                await extract_cover(source_path, session_dir / "cover.jpg")

            fallback_name = "audio.mp3" if media_type == "audio" else "video.mp4"
            session = await session_service.create(
                telegram_user_id=user_id,
                chat_id=message.chat.id,
                source_path=source_path,
                file_name=media.file_name or fallback_name,
                mime_type=mime_type,
                file_size=downloaded_size,
                duration_seconds=metadata.duration_seconds,
                width=metadata.width,
                height=metadata.height,
                media_type=media_type,
            )
            final_dir = settings.temp_dir / session.session_id
            session_dir.rename(final_dir)
            session_dir = None
            await session_service.update_file_path(
                session.session_id,
                final_dir / "input",
            )

            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Открыть редактор",
                            web_app=WebAppInfo(
                                url=f"{settings.mini_app_url}/?session={session.session_id}"
                            ),
                        )
                    ]
                ]
            )
            ready = (
                "Аудио готово. Открой редактор и выбери нужный фрагмент."
                if media_type == "audio"
                else "Видео готово. Открой редактор и выбери нужный фрагмент."
            )
            await message.answer(ready, reply_markup=keyboard)
            final_dir = None
        except MediaValidationError:
            await message.answer("Не удалось прочитать видео. Попробуй другой файл.")
        except Exception:
            logger.exception("Failed to create video session")
            if session_dir is None and final_dir is not None:
                await session_service.delete(session.session_id)
            await message.answer("Не удалось принять видео. Попробуй ещё раз.")
        finally:
            for directory in (session_dir, final_dir):
                if directory and directory.exists():
                    shutil.rmtree(directory, ignore_errors=True)
