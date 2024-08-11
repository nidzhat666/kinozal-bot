import logging

from aiogram import Router
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

from bot.constants import MOVIE_DETAILED_CALLBACK, SEARCH_MOVIE_QUALITY_CALLBACK, SEARCH_MOVIE_CALLBACK, KINOZAL_QUALITY_MAP
from services.kinozal_services.movie_search_service import MovieSearchService
from utilities.handlers_utils import redis_callback_save, redis_callback_get, check_action
from . import movie_detail_handler

logger = logging.getLogger(__name__)
router = Router(name=__name__)
router.include_routers(movie_detail_handler.router)


@router.message()
async def quality_choice(message: Message):
    query = message.text

    inline_keyboard = []

    for k, v in KINOZAL_QUALITY_MAP.items():
        uuid_ = redis_callback_save({"action": SEARCH_MOVIE_QUALITY_CALLBACK,
                                     "quality_id": k, "query": query})
        inline_keyboard.append([InlineKeyboardButton(text=v, callback_data=uuid_)])

    keyboard = InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
    await message.answer("Please choose the quality of the movie:", reply_markup=keyboard)


@router.callback_query(lambda c: check_action(c.data, SEARCH_MOVIE_QUALITY_CALLBACK))
async def handle_quality_response(callback_query: CallbackQuery):
    quality_info = redis_callback_get(callback_query.data)
    if quality_info:
        quality_id = quality_info.get("quality_id")
        query = quality_info.get("query")
        redis_callback_save({"quality_id": quality_id,
                             "user_id": callback_query.from_user.id,
                             "action": SEARCH_MOVIE_CALLBACK,
                             "query": query})
        await callback_query.message.edit_text(f"Quality selected: {KINOZAL_QUALITY_MAP[quality_id]}. Looking for the following movie: {query}")
        await perform_search(query, quality_id, callback_query.message)
    else:
        await callback_query.answer("Error retrieving quality data.", show_alert=True)


@router.callback_query(lambda c: check_action(c.data, SEARCH_MOVIE_CALLBACK))
async def handle_search_after_quality(callback_query: CallbackQuery):
    quality_info = redis_callback_get(callback_query.data)
    if quality_info:
        quality, query = quality_info.get("quality"), quality_info.get("query")
        await perform_search(query, quality, callback_query.message, callback_query)
    else:
        await callback_query.answer("Error retrieving quality data.", show_alert=True)


async def perform_search(query: str, quality: str, message: Message, callback_query: CallbackQuery = None):
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
        response_message = format_search_results(results, query, quality)
        if callback_query is not None:
            await callback_query.message.edit_text("Выберите результат:", reply_markup=response_message)
        else:
            await message.answer("Выберите результат:", reply_markup=response_message)
        logger.info("Search results sent to user.")
    except Exception as e:
        logger.error(f"Error in sending search results: {e}", exc_info=True)
        await message.answer("Error in processing search results.")


def format_search_results(results: list[dict], query, quality) -> InlineKeyboardMarkup:
    buttons = []
    for el in results[:10]:
        txt = el.get("name").split(" / ")
        button_text = " | ".join([txt[0], txt[-1]]) + f" ({el.get('size')})"
        movie_details_uuid = redis_callback_save({"action": MOVIE_DETAILED_CALLBACK, "movie_id": el.get("id"),
                                                  "query": query, "quality": quality})
        buttons.append([InlineKeyboardButton(text=button_text, callback_data=movie_details_uuid)])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    return keyboard
