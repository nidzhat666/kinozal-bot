import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand, Update
from fastapi import FastAPI, Request
from sulguk import AiogramSulgukMiddleware

from bot.config import (
    TELEGRAM_BOT_TOKEN,
    BASE_URL,
    WEBHOOK_PATH,
    USE_POLLING,
)
from bot.constants import REFRESH_PLEX_COMMAND, STATUS_COMMAND
from bot.logger_config import setup_logging
from handlers import (
    search_handler,
    movie_download_handler,
    torrents_statuses_handler,
    torrent_detailed_handler,
    pause_torrent_handler,
    start_torrent_handler,
    delete_torrent_handler,
    refresh_plex_handler,
)

# Initialize logging configuration
setup_logging()
logger = structlog.get_logger(__name__)

# Initialize Bot and Dispatcher
bot = Bot(token=TELEGRAM_BOT_TOKEN)
bot.session.middleware(AiogramSulgukMiddleware())

dp = Dispatcher()

# Register routers
dp.include_routers(
    movie_download_handler.router,
    torrents_statuses_handler.router,
    torrent_detailed_handler.router,
    pause_torrent_handler.router,
    start_torrent_handler.router,
    delete_torrent_handler.router,
    refresh_plex_handler.router,
    search_handler.router,
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Manages the lifespan of the application.
    Handles startup (webhook/polling setup) and shutdown (cleanup) events.
    """
    # Startup
    logger.info("Starting up application...")
    
    # Set bot commands for menu
    await bot.set_my_commands(
        [
            BotCommand(command=f"/{STATUS_COMMAND}", description="qBittorrent Status"),
            BotCommand(
                command=f"/{REFRESH_PLEX_COMMAND}", description="Refresh Plex libraries"
            ),
        ]
    )

    polling_task = None

    if USE_POLLING:
        logger.info("🚀 USE_POLLING=True. Starting in POLLING mode...")
        await bot.delete_webhook(drop_pending_updates=True)
        # Start polling as a background task
        # handle_signals=False is required as Uvicorn handles system signals
        polling_task = asyncio.create_task(dp.start_polling(bot, handle_signals=False))
    elif BASE_URL:
        webhook_uri = f"{BASE_URL}{WEBHOOK_PATH}"
        logger.info(f"🌍 Setting webhook to {webhook_uri}")
        await bot.set_webhook(webhook_uri)
    else:
        logger.warning("⚠️ BASE_URL is not set and USE_POLLING=False. Bot will not receive updates.")

    yield

    # Shutdown
    logger.info("Shutting down application...")
    
    if polling_task:
        logger.info("Stopping polling task...")
        polling_task.cancel()
        try:
            await polling_task
        except asyncio.CancelledError:
            pass
    else:
        logger.info("Deleting webhook...")
        await bot.delete_webhook()
        
    await bot.session.close()
    logger.info("Bot session closed.")


app = FastAPI(lifespan=lifespan)


@app.post(WEBHOOK_PATH)
async def bot_webhook(update: dict) -> None:
    """
    Webhook endpoint to receive updates from Telegram.
    """
    telegram_update = Update.model_validate(update, context={"bot": bot})
    await dp.feed_update(bot, telegram_update)


@app.get("/health")
async def health_check() -> dict[str, str]:
    """
    Health check endpoint to verify service status.
    """
    return {"status": "ok"}
