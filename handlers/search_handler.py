import logging

from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
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


@router.callback_query(lambda c: c.data and c.data.startswith('select_'))
async def handle_movie_selection(callback_query: CallbackQuery):
    movie_id = callback_query.data.split('_')[1]  # Extract movie ID from callback data
    logger.info(f"Movie selected with ID: {movie_id}")

    try:
        # Assume you have a method in MovieSearchService to get movie details by ID
        # movie_details = await search_service.get_movie_details(movie_id)
        logger.info("Movie details retrieved.")

        # Format and send the movie details to the user
        # details_message = format_movie_details(movie_details)
        # await callback_query.message.answer(details_message)
        # await callback_query.answer()  # To remove the loading state on the button
    except Exception as e:
        logger.error(f"Error in fetching movie details: {e}")
        await callback_query.message.answer("Failed to retrieve movie details.")
        await callback_query.answer()


def format_search_results(results: list[dict]) -> InlineKeyboardMarkup:
    buttons = []
    for el in results[:10]:
        txt = el.get("name").split(" / ")
        button_text = " | ".join([txt[0], txt[-1]]) + f" ({el.get('size')})"
        callback_data = f"select_{el.get('id')}"
        buttons.append([InlineKeyboardButton(text=button_text, callback_data=callback_data)])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    return keyboard
