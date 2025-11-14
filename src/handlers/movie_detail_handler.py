import logging

from aiogram import Router
from aiogram.enums.parse_mode import ParseMode
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.text_decorations import html_decoration

from bot.config import QBT_CREDENTIALS
from bot.constants import MOVIE_DETAILED_CALLBACK, DOWNLOAD_TORRENT_CALLBACK, SEARCH_MOVIE_CALLBACK
from custom_types.movie_detail_service_types import MovieDetails
from torrents import get_torrent_provider
from services.qbt_services import qbt_get_categories, get_client
from utilities import kinozal_utils, handlers_utils
from utilities.handlers_utils import check_action

logger = logging.getLogger(__name__)
router = Router(name=__name__)

torrent_provider = get_torrent_provider()


@router.callback_query(lambda c: check_action(c.data, MOVIE_DETAILED_CALLBACK))
async def handle_movie_selection(callback_query: CallbackQuery):
    callback_data = handlers_utils.redis_callback_get(callback_query.data)
    movie_id, query, quality = callback_data.get("movie_id"), callback_data.get("query"), callback_data.get("quality")
    logger.info(f"Movie selected with ID: {movie_id}")

    try:
        movie_details = await fetch_movie_details(movie_id)
        await send_movie_details(callback_query, movie_details, movie_id, query, quality)
    except Exception as e:
        logger.error(f"Error in fetching movie details: {e}", exc_info=True)
        await callback_query.message.answer("Failed to retrieve movie details.")
        await callback_query.answer()


async def fetch_movie_details(movie_id: str) -> MovieDetails:
    logger.info("Retrieving movie details.")
    return await torrent_provider.get_movie_detail(movie_id)


async def send_movie_details(callback_query: CallbackQuery, movie_details: MovieDetails,
                             movie_id: int | str, query: str, quality: int) -> None:
    message_caption = format_movie_details_message(movie_details)
    logger.debug(f"Sending movie details: {message_caption}")

    qbt_client = await get_client(**QBT_CREDENTIALS)
    categories = await qbt_get_categories(qbt_client)

    reply_markup = create_reply_markup(movie_id, query, categories, quality)
    await callback_query.message.edit_text(message_caption, parse_mode=ParseMode.HTML, reply_markup=reply_markup)


def create_reply_markup(movie_id: int | str, query: str, categories: list, quality: int) -> InlineKeyboardMarkup:
    download_buttons = [
        InlineKeyboardButton(
            text=f"{category} 🔽",
            callback_data=handlers_utils.redis_callback_save(dict(action=DOWNLOAD_TORRENT_CALLBACK, movie_id=movie_id, category=category, quality=quality, query=query))
        ) for category in categories
    ]

    return InlineKeyboardMarkup(inline_keyboard=[
        download_buttons,
        [InlineKeyboardButton(text="Назад к результатам поиска",
                              callback_data=handlers_utils.redis_callback_save(dict(action=SEARCH_MOVIE_CALLBACK, query=query, quality=quality)))],
        [InlineKeyboardButton(text="Открыть в Кинозале",
                              url=kinozal_utils.get_url(f"/details.php?id={movie_id}"))]
    ])


def format_movie_details_message(movie_details: MovieDetails) -> str:
    formatted_message = (
        f"{html_decoration.bold('Название')}: {movie_details.name}\n"
        f"{html_decoration.bold('Год')}: {movie_details.year}\n"
        f"{html_decoration.bold('Жанр')}: {', '.join(movie_details.genres)}\n"
        f"{html_decoration.bold('Режисер')}: {movie_details.director}\n"
        f"{html_decoration.bold('Актеры')}: {', '.join(movie_details.actors[:5])}\n\n"
        f"{html_decoration.bold('Рейтинги')}:\n"
        f"- IMDB: {html_decoration.code(movie_details.ratings.imdb)}\n"
        f"- Kinopoisk: {html_decoration.code(movie_details.ratings.kinopoisk)}\n\n"
        f"<b>Torrent Details</b>:\n"
    )
    for detail in movie_details.torrent_details:
        value = detail.value or "-"
        formatted_message += (
            f"- {html_decoration.bold(detail.key)} {html_decoration.code(value)}\n"
        )

    return formatted_message
