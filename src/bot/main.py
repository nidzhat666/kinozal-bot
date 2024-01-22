import asyncio

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand

from bot.logger_config import setup_logging
from config import TELEGRAM_BOT_TOKEN
from handlers import (search_handler, movie_download_handler,
                      torrents_statuses_handler, torrent_detailed_handler,
                      pause_torrent_handler, start_torrent_handler, delete_torrent_handler)

dp = Dispatcher()


async def main() -> None:
    setup_logging()
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    dp.include_routers(search_handler.router,
                       movie_download_handler.router,
                       torrents_statuses_handler.router,
                       torrent_detailed_handler.router,
                       pause_torrent_handler.router,
                       start_torrent_handler.router,
                       delete_torrent_handler.router,)
    await bot.set_my_commands([BotCommand(command="/search", description="Kinozal Search"),
                               BotCommand(command="/status", description="qBittorrent Status")])
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
