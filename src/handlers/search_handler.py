import logging

from aiogram import Router
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.constants import KINOZAL_QUALITY_MAP, MOVIE_DETAILED_CALLBACK, SEARCH_MOVIE_CALLBACK, SEARCH_MOVIE_QUALITY_CALLBACK
from custom_types.movie_detail_service_types import MovieSearchResult
from torrents import get_torrent_provider
from utilities.handlers_utils import check_action, redis_callback_get, redis_callback_save
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


async def perform_search(
    query: str,
    quality: str | int,
    message: Message,
    callback_query: CallbackQuery = None,
):
    logger.info(f"Received search command with query: {query} and quality: {quality}")

    try:
        provider = get_torrent_provider()
        results = await provider.search(query, quality)
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


def format_search_results(
    results: list[MovieSearchResult], query: str, quality: str | int
) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    for result in results[:10]:
        title_source = result.search_name or result.name
        title_parts = title_source.split(" / ")
        if len(title_parts) > 1:
            button_label = " | ".join([title_parts[0], title_parts[-1]])
        else:
            button_label = title_source
        button_text = f"{button_label} ({result.size})"
        movie_details_uuid = redis_callback_save({
            "action": MOVIE_DETAILED_CALLBACK,
            "movie_id": result.id,
            "query": query,
            "quality": quality,
            "movie_details": result.model_dump(mode="json", by_alias=True, exclude_none=True),
        })
        buttons.append([InlineKeyboardButton(text=button_text, callback_data=movie_details_uuid)])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    return keyboard
