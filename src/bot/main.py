import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand, Update
from fastapi import FastAPI, Request

from bot.config import (
    TELEGRAM_BOT_TOKEN,
    BASE_URL,
    WEBHOOK_PATH,
    USE_POLLING,
)
from bot.constants import REFRESH_PLEX_COMMAND, STATUS_COMMAND, TRANSCODE_STATUS_COMMAND
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
    transcode_status_handler,
)
from services.transcoding.config import get_config as get_transcode_config
from services.transcoding.worker_pool import start_worker_pool, stop_worker_pool
from services.transcoding.scanner import start_scanner, stop_scanner
from services.transcoding.api import router as transcode_router
from services.transcoding.redis_client import close_redis

# Initialize logging configuration
setup_logging()
logger = logging.getLogger(__name__)

# Initialize Bot and Dispatcher
bot = Bot(token=TELEGRAM_BOT_TOKEN)
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
    transcode_status_handler.router,
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
    
    # Build bot commands list
    commands = [
        BotCommand(command=f"/{STATUS_COMMAND}", description="qBittorrent Status"),
        BotCommand(
            command=f"/{REFRESH_PLEX_COMMAND}", description="Refresh Plex libraries"
        ),
    ]
    
    # Add transcoding command if enabled
    transcode_config = get_transcode_config()
    if transcode_config.enabled:
        commands.append(
            BotCommand(
                command=f"/{TRANSCODE_STATUS_COMMAND}", 
                description="Transcoding Status"
            )
        )
    
    # Set bot commands for menu
    await bot.set_my_commands(commands)

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

    # Start transcoding services if enabled
    if transcode_config.enabled:
        logger.info("🎬 Starting transcoding services...")
        await start_worker_pool()
        await start_scanner()
        logger.info(f"🎬 Transcoding enabled: {transcode_config.workers} workers")
    else:
        logger.info("🎬 Transcoding is disabled")

    yield

    # Shutdown
    logger.info("Shutting down application...")
    
    # Stop transcoding services
    if transcode_config.enabled:
        logger.info("Stopping transcoding services...")
        await stop_scanner()
        await stop_worker_pool()
        await close_redis()
        logger.info("Transcoding services stopped.")
    
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

# Include transcoding API router
app.include_router(transcode_router)


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
