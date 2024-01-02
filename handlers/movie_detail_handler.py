import logging

from aiogram.types import CallbackQuery
from aiogram import Router
from aiogram.enums.parse_mode import ParseMode
from aiogram.utils.markdown import markdown_decoration
from bot.config import KINOZAL_CREDENTIALS
from services.kinozal_auth_service import KinozalAuthService
from services.movie_detail_service import MovieDetailService
from custom_types.movie_detail_service_types import MovieDetails
from utilities.telegram_utils import escape_special_characters

logger = logging.getLogger(__name__)
router = Router(name=__name__)

auth_service = KinozalAuthService(**KINOZAL_CREDENTIALS)
movie_detail_service = MovieDetailService(None)


@router.callback_query(lambda c: c.data and c.data.startswith("select-movie_"))
async def handle_movie_selection(callback_query: CallbackQuery):
    movie_id = callback_query.data.split("_")[1]
    logger.info(f"Movie selected with ID: {movie_id}")

    try:
        response = await fetch_movie_details(movie_id)
        await send_movie_details(callback_query, response)
    except Exception as e:
        logger.error(f"Error in fetching movie details: {e}", exc_info=True)
        await callback_query.message.answer("Failed to retrieve movie details.")
        await callback_query.answer()


async def fetch_movie_details(movie_id: str) -> MovieDetails:
    logger.info("Retrieving movie details.")
    auth_cookies = await auth_service.authenticate()
    movie_detail_service.auth_cookies = auth_cookies
    return await movie_detail_service.get_movie_detail(movie_id)


async def send_movie_details(callback_query: CallbackQuery, movie_detail: MovieDetails):
    message_caption = format_message(movie_detail)
    logger.debug(f"Sending movie details: {message_caption}")
    await callback_query.message.edit_text(message_caption, parse_mode=ParseMode.MARKDOWN_V2)


def format_message(movie_detail: MovieDetails) -> str:
    movie_detail['name'] = escape_special_characters(movie_detail['name'])
    formatted_data = (f"[]({movie_detail['image_url']})"
                      f"{markdown_decoration.bold('Название')}: {movie_detail['name']}\n"
                      f"{markdown_decoration.bold('Год')}: {movie_detail['year']}\n"
                      f"{markdown_decoration.bold('Жанр')}: {', '.join(movie_detail['genres'])}\n"
                      f"{markdown_decoration.bold('Режисер')}: {movie_detail['director']}\n"
                      f"{markdown_decoration.bold('Актеры')}: {', '.join(movie_detail['actors'])}\n\n"
                      f"{markdown_decoration.bold('Рейтинги')}:\n"
                      f"IMDB: {markdown_decoration.code(movie_detail['ratings']['imdb'])}\n"
                      f"Kinopoisk: {markdown_decoration.code(movie_detail['ratings']['kinopoisk'])}\n\n"
                      f"**Torrent Details**:\n")
    return formatted_data
