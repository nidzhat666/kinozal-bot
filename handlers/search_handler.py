import logging

from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram import Router

from bot.constants import SEARCH_COMMAND
from services.movie_search_service import MovieSearchService
from services.kinozal_auth_service import KinozalAuthService
from bot.config import KINOZAL_CREDENTIALS
from utilities.handlers_utils import extract_text_without_command

logger = logging.getLogger(__name__)
router = Router(name=__name__)


@router.message(Command(SEARCH_COMMAND))
async def handle_search_command(message: Message):
    query = extract_text_without_command(message.text, SEARCH_COMMAND)
    logger.info(f"Received search command with query: {query}")

    try:
        auth_service = KinozalAuthService(**KINOZAL_CREDENTIALS)
        auth_cookies = await auth_service.authenticate()
        logger.info("Authentication successful.")
    except Exception as e:
        logger.error(f"Authentication failed: {e}")
        await message.answer("Failed to authenticate. Please try again later.")
        return

    try:
        search_service = MovieSearchService(auth_cookies)
        results = await search_service.search(query)
        logger.info(f"Search completed with {len(results)} results.")
    except Exception as e:
        logger.error(f"Search failed: {e}")
        await message.answer("Search failed. Please try again later.")
        return

    try:
        response_message = format_search_results(results)
        await message.answer("Выберите результат:", reply_markup=response_message)
        logger.info("Search results sent to user.")
    except Exception as e:
        logger.error(f"Error in sending search results: {e}")
        await message.answer("Error in processing search results.", exc_info=True)


def format_search_results(results: list[dict]) -> InlineKeyboardMarkup:
    buttons = []
    for el in results[:10]:
        txt = el.get("name").split(" / ")
        button_text = " | ".join([txt[0], txt[-1]]) + f" ({el.get('size')})"
        callback_data = f"select_{el.get('id')}"
        buttons.append([InlineKeyboardButton(text=button_text, callback_data=callback_data)])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    return keyboard
