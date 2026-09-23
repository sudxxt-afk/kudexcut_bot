import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
from redis.asyncio import Redis

from .config import Settings
from .handlers import register_handlers
from .session_service import SessionService

logging.basicConfig(
    level=logging.INFO,
    format='{"level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}',
)
logger = logging.getLogger(__name__)


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
        if settings.webhook_url:
            if not settings.webhook_secret:
                raise ValueError("WEBHOOK_SECRET is required when WEBHOOK_URL is set")
            await bot.set_webhook(
                url=settings.webhook_url,
                secret_token=settings.webhook_secret,
                drop_pending_updates=True,
            )
            application = web.Application()
            SimpleRequestHandler(
                dispatcher=dispatcher,
                bot=bot,
                secret_token=settings.webhook_secret,
            ).register(application, path="/telegram/webhook")
            setup_application(application, dispatcher, bot=bot)
            runner = web.AppRunner(application)
            await runner.setup()
            site = web.TCPSite(runner, "0.0.0.0", settings.webhook_port)
            await site.start()
            logger.info("Webhook server started on port %s", settings.webhook_port)
            await asyncio.Event().wait()
        else:
            await bot.delete_webhook(drop_pending_updates=True)
            await dispatcher.start_polling(bot)
    finally:
        await redis.aclose()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
