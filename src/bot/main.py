import asyncio

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand

from bot.constants import REFRESH_PLEX_COMMAND, STATUS_COMMAND
from bot.logger_config import setup_logging
from config import TELEGRAM_BOT_TOKEN
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

dp = Dispatcher()


async def main() -> None:
    setup_logging()
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
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
    await bot.set_my_commands(
        [
            BotCommand(command=f"/{STATUS_COMMAND}", description="qBittorrent Status"),
            BotCommand(
                command=f"/{REFRESH_PLEX_COMMAND}", description="Refresh Plex libraries"
            ),
        ]
    )
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
