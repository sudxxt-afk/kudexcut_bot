import asyncio
import logging

from aiogram import Bot, Dispatcher
from redis.asyncio import Redis

from .config import Settings
from .handlers import register_handlers
from .session_service import SessionService

logging.basicConfig(level=logging.INFO)


async def main() -> None:
    settings = Settings()
    bot = Bot(settings.bot_token)
    dispatcher = Dispatcher()
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    session_service = SessionService(
        redis=redis,
        temp_dir=settings.temp_dir,
        ttl_seconds=settings.session_ttl_seconds,
    )
    settings.temp_dir.mkdir(parents=True, exist_ok=True)
    register_handlers(
        dispatcher,
        bot=bot,
        settings=settings,
        session_service=session_service,
    )

    try:
        await dispatcher.start_polling(bot)
    finally:
        await redis.aclose()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
