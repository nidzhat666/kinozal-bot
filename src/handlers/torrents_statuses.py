import logging

from aiogram.exceptions import TelegramBadRequest
from math import floor

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery

from bot.config import QBT_CREDENTIALS
from bot.constants import STATUS_COMMAND
from services.qbt_services import get_client
from services.qbt_services.qbt_status import torrents_info
from utilities.common import truncate_string

router = Router(name=__name__)
logger = logging.getLogger(__name__)


def format_status_message(torrents):
    return "\n".join([f"{truncate_string(torrent.name, 40)} | "
                      f"[{'■' * floor(torrent.progress * 10) + '□' * (10 - int(torrent.progress * 10))}] "
                      f"{torrent.progress * 100:.1f}%\n"
                      for torrent in torrents])


async def get_status_message():
    try:
        async with await get_client(**QBT_CREDENTIALS) as qbt_client:
            torrents = await torrents_info(qbt_client, sort="added_on")
            response_message = format_status_message(torrents)
            return response_message
    except Exception as e:
        logger.error(f"Error in getting status: {e}", exc_info=True)
        return "Error in getting status."


def get_inline_keyboard() -> InlineKeyboardMarkup:
    buttons = [[
        InlineKeyboardButton(text="Refresh", callback_data="refresh-status")
    ]]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    return keyboard


async def send_status_message(message: Message):
    response_message = await get_status_message()
    await message.answer(response_message, reply_markup=get_inline_keyboard())


@router.message(Command(STATUS_COMMAND))
async def handle_status_command(message: Message):
    await send_status_message(message)


@router.callback_query(lambda c: c.data and c.data == "refresh-status")
async def refresh_status(callback_query: CallbackQuery):
    try:
        await callback_query.message.edit_text(await get_status_message(), reply_markup=get_inline_keyboard())
    except TelegramBadRequest as e:
        logger.warning("Error in refreshing status: %s", e)
