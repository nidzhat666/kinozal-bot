import logging
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram import Router

from bot.constants import SEARCH_COMMAND
from services.kinozal_services.movie_search_service import MovieSearchService
from utilities.handlers_utils import (extract_text_without_command, redis_callback_save,
                                      redis_callback_get, check_action)
from . import movie_detail_handler

logger = logging.getLogger(__name__)

router = Router(name=__name__)
router.include_routers(movie_detail_handler.router)


async def perform_search(query: str, message: Message):
    logger.info(f"Received search command with query: {query}")

    try:
        search_service = MovieSearchService()
        results = await search_service.search(query)
        logger.info(f"Search completed with {len(results)} results.")
    except Exception as e:
        logger.error(f"Search failed: {e}")
        await message.answer("Search failed. Please try again later.")
        return

    try:
        response_message = format_search_results(results, query)
        await message.answer("Выберите результат:", reply_markup=response_message)
        logger.info("Search results sent to user.")
    except Exception as e:
        logger.error(f"Error in sending search results: {e}", exc_info=True)
        await message.answer("Error in processing search results.")


@router.message(Command(SEARCH_COMMAND))
async def handle_search_command(message: Message):
    query = extract_text_without_command(message.text, SEARCH_COMMAND)
    await perform_search(query, message)


@router.callback_query(lambda c: check_action(c.data, "search_movie"))
async def handle_search_inline(callback_query: CallbackQuery):
    callback_data = redis_callback_get(callback_query.data)
    query = callback_data.get("query")
    await perform_search(query, callback_query.message)
    await callback_query.message.delete()


def format_search_results(results: list[dict], query) -> InlineKeyboardMarkup:
    buttons = []
    for el in results[:10]:
        txt = el.get("name").split(" / ")
        button_text = " | ".join([txt[0], txt[-1]]) + f" ({el.get('size')})"
        callback_data = dict(action="movie_detail", movie_id=el.get("id"), query=query)
        callback_key = redis_callback_save(callback_data)
        logger.debug(f"Callback data: {callback_data}")
        logger.debug(f"Callback key: {callback_key}")
        buttons.append([InlineKeyboardButton(text=button_text, callback_data=callback_key)])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    return keyboard
