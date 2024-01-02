import logging

from aiogram.types import CallbackQuery, URLInputFile
from aiogram import Router

from bot.config import KINOZAL_CREDENTIALS
from services.kinozal_auth_service import KinozalAuthService
from services.movie_detail_service import MovieDetailService

logger = logging.getLogger(__name__)
router = Router(name=__name__)


@router.callback_query(lambda c: c.data and c.data.startswith("select-movie_"))
async def handle_movie_selection(callback_query: CallbackQuery):
    movie_id = callback_query.data.split("_")[1]
    logger.info(f"Movie selected with ID: {movie_id}")

    try:
        logger.info("Movie details retrieved.")
        auth_cookies = await KinozalAuthService(**KINOZAL_CREDENTIALS).authenticate()
        response = await MovieDetailService(auth_cookies).get_movie_detail(movie_id)
        await callback_query.message.delete()
        await callback_query.message.answer_photo(response["image_url"],
                                                  format_message(response))
    except Exception as e:
        logger.error(f"Error in fetching movie details: {e}", exc_info=True)
        await callback_query.message.answer("Failed to retrieve movie details.")
        await callback_query.answer()


def format_message(movie_detail: dict) -> str:
    return f"""**Название**: {movie_detail['name']}
**Год**: {movie_detail['year']}
**Жанр**: {", ".join(movie_detail['genres'])}
**Director**: {", ".join(movie_detail['directors'])}
**Actors**: {", ".join(movie_detail['actors'])}

Description: "{movie_detail['description']}"

**Ratings**:
IMDb: `7.0`
Kinopoisk: `6.6`

**Torrent Details**:
- **Quality**: BDRip (1080p)
- **Video Codec**: MPEG-4 AVC, 11.7 Mbit/s, 1920x960
- **Audio**: Russian (AC3, 6 ch, 448 Kbit/s), English (E-AC3+Atmos, 6 ch, 768 Kbit/s)
- **File Size**: 8.14 GB
- **Duration**: 01:55:05
- **Seeders**: `74`
- **Leechers**: `241`
- **Downloads**: `9004`"""
