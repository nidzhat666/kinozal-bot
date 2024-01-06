import logging

from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram import Router
from aiogram.enums.parse_mode import ParseMode
from aiogram.utils.text_decorations import html_decoration

from services.kinozal_services.movie_detail_service import MovieDetailService
from custom_types.movie_detail_service_types import MovieDetails
from services.qbt_services.qbt_get_categories import qbt_get_categories
from services.qbt_services.qbt_base_client import get_client
from utilities.kinozal_utils import get_url
from bot.config import QBT_CREDENTIALS

logger = logging.getLogger(__name__)
router = Router(name=__name__)

movie_detail_service = MovieDetailService()


@router.callback_query(lambda c: c.data and c.data.startswith("select-movie_"))
async def handle_movie_selection(callback_query: CallbackQuery):
    movie_id = callback_query.data.split("_")[1]
    query = callback_query.data.split("_")[2]
    logger.info(f"Movie selected with ID: {movie_id}")
    try:
        response = await fetch_movie_details(movie_id)
        await send_movie_details(callback_query, response, movie_id, query)
    except Exception as e:
        logger.error(f"Error in fetching movie details: {e}", exc_info=True)
        await callback_query.message.answer("Failed to retrieve movie details.")
        await callback_query.answer()


async def fetch_movie_details(movie_id: str) -> MovieDetails:
    logger.info("Retrieving movie details.")
    return await movie_detail_service.get_movie_detail(movie_id)


async def send_movie_details(callback_query: CallbackQuery,
                             movie_detail: MovieDetails,
                             movie_id: int | str, query: str) -> None:
    message_caption = format_message(movie_detail)
    logger.debug(f"Sending movie details: {message_caption}")
    qbt_client = await get_client(**QBT_CREDENTIALS)
    categories = await qbt_get_categories(qbt_client)
    await callback_query.message.edit_text(message_caption, parse_mode=ParseMode.HTML,
                                           reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                               [InlineKeyboardButton(text=f"Скачать торрент в {category} 🔽",
                                                                     callback_data=f"download-movie_{movie_id}_{category}")
                                                for category in categories],
                                               [InlineKeyboardButton(text="Назад к результатам поиска",
                                                                     callback_data=f"search-movie_{query}"), ],
                                               [InlineKeyboardButton(text="Открыть в Кинозале",
                                                                     url=get_url(f"/details.php?id={movie_id}"))]
                                           ]))


def format_message(movie_detail: MovieDetails) -> str:
    formatted_data = (
        f"{html_decoration.bold('Название')}: {movie_detail['name']}\n"
        f"{html_decoration.bold('Год')}: {movie_detail['year']}\n"
        f"{html_decoration.bold('Жанр')}: {', '.join(movie_detail['genres'])}\n"
        f"{html_decoration.bold('Режисер')}: {movie_detail['director']}\n"
        f"{html_decoration.bold('Актеры')}: {', '.join(movie_detail['actors'][:5])}\n\n"
        f"{html_decoration.bold('Рейтинги')}:\n"
        f"- IMDB: {html_decoration.code(movie_detail['ratings']['imdb'])}\n"
        f"- Kinopoisk: {html_decoration.code(movie_detail['ratings']['kinopoisk'])}\n\n"
        f"<b>Torrent Details</b>:\n"
    )
    for k, v in movie_detail["torrent_details"]:
        formatted_data += (
            f"- {html_decoration.bold(k)} {html_decoration.code(v)}\n"
        )
    return formatted_data
