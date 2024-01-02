import asyncio

from aiogram import Bot, Dispatcher
from aiogram.methods import SetMyCommands
from aiogram.types import BotCommand

from bot.logger_config import setup_logging
from config import TELEGRAM_BOT_TOKEN
from handlers import search_handler

dp = Dispatcher()


async def main() -> None:
    setup_logging()
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    dp.include_routers(search_handler.router)
    await bot.set_my_commands([BotCommand(command="/search", description="Kinozal Search")])
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == '__main__':
    asyncio.run(main())
