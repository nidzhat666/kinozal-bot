import logging

from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram import Router

from bot.constants import SEARCH_COMMAND, MOVIE_DETAILED_CALLBACK, SEARCH_MOVIE_QUALITY_CALLBACK, SEARCH_MOVIE_CALLBACK
from services.kinozal_services.movie_search_service import MovieSearchService
from utilities.handlers_utils import redis_callback_save, redis_callback_get, check_action, extract_text_without_command
from . import movie_detail_handler

logger = logging.getLogger(__name__)
router = Router(name=__name__)
router.include_routers(movie_detail_handler.router)


@router.message()
async def quality_choice(message: Message):
    query = message.text
    quality_4k_uuid = redis_callback_save({"quality": "4K",
                                           "action": SEARCH_MOVIE_QUALITY_CALLBACK,
                                           "id": 7, "query": query})
    quality_hd_uuid = redis_callback_save({"quality": "1080p",
                                           "action": SEARCH_MOVIE_QUALITY_CALLBACK,
                                           "id": 3, "query": query})

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="4K", callback_data=quality_4k_uuid)],
        [InlineKeyboardButton(text="1080p | 720p", callback_data=quality_hd_uuid)]
    ])
    await message.answer("Please choose the quality of the movie:", reply_markup=keyboard)


@router.callback_query(lambda c: check_action(c.data, SEARCH_MOVIE_QUALITY_CALLBACK))
async def handle_quality_response(callback_query: CallbackQuery):
    quality_info = redis_callback_get(callback_query.data)
    if quality_info:
        quality, id_, query = quality_info.get("quality"), quality_info.get("id"), quality_info.get("query")
        redis_callback_save({"quality": id_,
                             "user_id": callback_query.from_user.id,
                             "action": SEARCH_MOVIE_CALLBACK,
                             "query": query})
        await callback_query.message.edit_text(f"Quality selected: {quality}. Looking for the following movie: {query}")
        await perform_search(query, id_, callback_query.message)
    else:
        await callback_query.answer("Error retrieving quality data.", show_alert=True)


async def handle_search_after_quality(callback_query: CallbackQuery):
    quality_info = redis_callback_get(callback_query.data)
    if quality_info:
        quality, query = quality_info.get("id"), quality_info.get("query")
        await perform_search(query, quality, callback_query.message)
    else:
        await callback_query.answer("Error retrieving quality data.", show_alert=True)


async def perform_search(query: str, quality: str, message: Message):
    logger.info(f"Received search command with query: {query} and quality: {quality}")

    try:
        search_service = MovieSearchService()
        results = await search_service.search(query, quality)
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


def format_search_results(results: list[dict], query) -> InlineKeyboardMarkup:
    buttons = []
    for el in results[:10]:
        txt = el.get("name").split(" / ")
        button_text = " | ".join([txt[0], txt[-1]]) + f" ({el.get('size')})"
        movie_details_uuid = redis_callback_save({"action": MOVIE_DETAILED_CALLBACK, "movie_id": el.get("id"), "query": query})
        buttons.append([InlineKeyboardButton(text=button_text, callback_data=movie_details_uuid)])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    return keyboard
