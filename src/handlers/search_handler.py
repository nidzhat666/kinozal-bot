import logging

from aiogram import Router
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from pydantic import ValidationError

from bot.constants import (
    KINOPOISK_RESULT_SELECT_CALLBACK,
    KINOPOISK_RESULTS_LIST_CALLBACK,
    KINOPOISK_SEASON_SELECT_CALLBACK,
    MOVIE_DETAILED_CALLBACK,
    SEARCH_MOVIE_CALLBACK,
)
from custom_types.kinopoisk_types import KinopoiskMovieBase, KinopoiskMovieDetails
from custom_types.movie_detail_service_types import MovieSearchResult
from services.exceptions import KinopoiskApiError
from services.kinopoisk_service import kinopoisk_client
from torrents import get_torrent_provider
from utilities import kinopoisk_utils
from utilities.handlers_utils import check_action, redis_callback_get, redis_callback_save
from . import movie_detail_handler

logger = logging.getLogger(__name__)
router = Router(name=__name__)
router.include_routers(movie_detail_handler.router)


@router.message()
async def handle_search_query(message: Message):
    query = (message.text or "").strip()
    if not query:
        await message.answer("Введите название фильма или сериала.")
        return

    status_message = await message.answer(f"Ищу «{query}» в Кинопоиске...")

    try:
        await show_kinopoisk_results(query, status_message)
    except KinopoiskApiError as exc:
        logger.warning("Kinopoisk search failed for '%s': %s", query, exc)
        await status_message.edit_text(
            "Не удалось найти результаты в Кинопоиске. Выполняю прямой поиск по торрентам..."
        )
        await perform_search(query, status_message)
    except Exception as exc:  # noqa: BLE001
        logger.error("Unexpected error during Kinopoisk search for '%s': %s", query, exc, exc_info=True)
        await status_message.edit_text("Произошла ошибка при поиске. Попробуйте позже.")


@router.callback_query(lambda c: check_action(c.data, SEARCH_MOVIE_CALLBACK))
async def handle_search_callback(callback_query: CallbackQuery):
    quality_info = redis_callback_get(callback_query.data)
    if quality_info:
        query = quality_info.get("query")
        if not query:
            await callback_query.answer("Недостаточно данных для повтора поиска.", show_alert=True)
            return
        await perform_search(query, callback_query.message, callback_query)
        await callback_query.answer()
    else:
        await callback_query.answer("Error retrieving quality data.", show_alert=True)


async def show_kinopoisk_results(
    query: str,
    message: Message,
) -> None:
    logger.info("Searching Kinopoisk for query '%s'", query)
    search_response = await kinopoisk_client.search(query)
    movies = search_response.docs
    if not movies:
        raise KinopoiskApiError(f"Kinopoisk search returned no results for '{query}'.")

    buttons: list[list[InlineKeyboardButton]] = []
    for movie in movies[:10]:
        callback_key = redis_callback_save(
            {
                "action": KINOPOISK_RESULT_SELECT_CALLBACK,
                "query": query,
                "movie_id": movie.id,
                "movie": movie.model_dump(mode="json", by_alias=True, exclude_none=True),
            }
        )
        caption = kinopoisk_utils.format_button_caption(movie)
        buttons.append([InlineKeyboardButton(text=caption, callback_data=callback_key)])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.edit_text(
        f"Результаты Кинопоиска для «{query}». Выберите подходящий вариант:",
        reply_markup=keyboard,
    )


@router.callback_query(lambda c: check_action(c.data, KINOPOISK_RESULTS_LIST_CALLBACK))
async def handle_kinopoisk_results_list(callback_query: CallbackQuery):
    redis_data = redis_callback_get(callback_query.data)
    if not redis_data:
        await callback_query.answer("Не удалось восстановить результаты поиска.", show_alert=True)
        return

    query = redis_data.get("query")
    if not query:
        await callback_query.answer("Недостаточно данных для обновления списка.", show_alert=True)
        return

    try:
        await show_kinopoisk_results(query, callback_query.message)
    except KinopoiskApiError as exc:
        logger.warning("Failed to reload Kinopoisk results for '%s': %s", query, exc)
        await callback_query.answer("Кинопоиск временно недоступен.", show_alert=True)
        return

    await callback_query.answer()


@router.callback_query(lambda c: check_action(c.data, KINOPOISK_RESULT_SELECT_CALLBACK))
async def handle_kinopoisk_selection(callback_query: CallbackQuery):
    redis_data = redis_callback_get(callback_query.data)
    if not redis_data:
        await callback_query.answer("Не удалось получить данные о выбранном тайтле.", show_alert=True)
        return

    movie_id = redis_data.get("movie_id")
    original_query = redis_data.get("query")
    movie_payload = redis_data.get("movie")

    if movie_id is None:
        await callback_query.answer("Недостаточно данных для обработки выбора.", show_alert=True)
        return

    movie_from_search: KinopoiskMovieBase | None = None
    if movie_payload:
        try:
            movie_from_search = KinopoiskMovieBase.model_validate(movie_payload)
        except ValidationError:
            logger.debug("Failed to validate cached Kinopoisk movie payload.", exc_info=True)

    try:
        movie_details = await kinopoisk_client.get_movie_details(movie_id)
    except KinopoiskApiError as exc:
        logger.warning("Failed to fetch Kinopoisk details for id %s: %s", movie_id, exc)
        if movie_from_search is None:
            await callback_query.answer("Не удалось получить информацию о тайтле.", show_alert=True)
            return
        movie_details = KinopoiskMovieDetails.model_validate(
            movie_from_search.model_dump(mode="json", by_alias=True, exclude_none=True)
        )

    seasons = kinopoisk_utils.extract_available_seasons(movie_details.seasons_info)
    if movie_details.is_series and seasons:
        await _show_season_choices(
            callback_query,
            movie_details,
            seasons,
            original_query,
        )
        await callback_query.answer()
        return

    search_query = kinopoisk_utils.build_torrent_query(movie_details)
    await perform_search(search_query, callback_query.message, callback_query)
    await callback_query.answer()


async def _show_season_choices(
    callback_query: CallbackQuery,
    movie_details: KinopoiskMovieDetails,
    seasons: list[int],
    original_query: str,
) -> None:
    buttons: list[list[InlineKeyboardButton]] = []
    movie_dump = movie_details.model_dump(mode="json", by_alias=True, exclude_none=True)
    search_context = original_query or kinopoisk_utils.get_preferred_title(movie_details)

    season_year_map: dict[int, int | None] = {}
    try:
        season_metadata = await kinopoisk_client.get_seasons(movie_details.id)
    except KinopoiskApiError as exc:
        logger.warning(
            "Failed to load seasons metadata for movie id %s: %s",
            movie_details.id,
            exc,
        )
    else:
        for season in season_metadata:
            year = season.air_date.year if season.air_date else None
            season_year_map[season.number] = year

    for season in seasons:
        season_year = season_year_map.get(season)
        button_label = f"Сезон {season}"
        if season_year:
            button_label += f" ({season_year})"

        callback_key = redis_callback_save(
            {
                "action": KINOPOISK_SEASON_SELECT_CALLBACK,
                "season": season,
                "movie_id": movie_details.id,
                "movie": movie_dump,
                "season_year": season_year,
            }
        )
        buttons.append(
            [InlineKeyboardButton(text=button_label, callback_data=callback_key)]
        )

    back_callback = redis_callback_save(
        {
            "action": KINOPOISK_RESULTS_LIST_CALLBACK,
            "query": search_context,
        }
    )
    buttons.append(
        [InlineKeyboardButton(text="Назад к результатам поиска", callback_data=back_callback)]
    )

    title = kinopoisk_utils.get_preferred_title(movie_details)
    header = f"{title}"
    if movie_details.year:
        header += f" ({movie_details.year})"

    description = movie_details.short_description or movie_details.description or ""
    text_parts = [header]
    if description:
        text_parts.extend(["", description])
    text_parts.extend(["", "Выберите сезон:"])

    await callback_query.message.edit_text(
        "\n".join(filter(None, text_parts)),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@router.callback_query(lambda c: check_action(c.data, KINOPOISK_SEASON_SELECT_CALLBACK))
async def handle_kinopoisk_season_selection(callback_query: CallbackQuery):
    redis_data = redis_callback_get(callback_query.data)
    if not redis_data:
        await callback_query.answer("Не удалось определить выбранный сезон.", show_alert=True)
        return

    season = redis_data.get("season")
    movie_payload = redis_data.get("movie")
    movie_id = redis_data.get("movie_id")
    season_year_raw = redis_data.get("season_year")

    try:
        season_number = int(season)
    except (TypeError, ValueError):
        await callback_query.answer("Некорректный номер сезона.", show_alert=True)
        return

    try:
        season_year: int | None = int(season_year_raw) if season_year_raw is not None else None
    except (TypeError, ValueError):
        season_year = None

    movie_details: KinopoiskMovieDetails | None = None
    if movie_payload:
        try:
            movie_details = KinopoiskMovieDetails.model_validate(movie_payload)
        except ValidationError:
            logger.debug("Failed to validate cached Kinopoisk movie details.", exc_info=True)

    if movie_details is None and movie_id is not None:
        try:
            movie_details = await kinopoisk_client.get_movie_details(movie_id)
        except KinopoiskApiError as exc:
            logger.error("Failed to fetch Kinopoisk details for id %s: %s", movie_id, exc)
            await callback_query.answer("Не удалось получить данные сезона.", show_alert=True)
            return
    if season_year is None and movie_id is not None:
        try:
            season_metadata = await kinopoisk_client.get_seasons(movie_id)
        except KinopoiskApiError as season_exc:
            logger.warning(
                "Failed to load seasons metadata for movie id %s: %s",
                movie_id,
                season_exc,
            )
        else:
            for season_info in season_metadata:
                if season_info.number == season_number and season_info.air_date:
                    season_year = season_info.air_date.year
                    break

    if movie_details is None:
        await callback_query.answer("Не удалось обработать выбор сезона.", show_alert=True)
        return

    search_query = kinopoisk_utils.build_torrent_query(
        movie_details,
        season_number=season_number,
        season_year=season_year,
        include_year_for_movie=False,
    )
    await perform_search(search_query, callback_query.message, callback_query)
    await callback_query.answer()


async def perform_search(
    query: str,
    message: Message,
    callback_query: CallbackQuery | None = None,
) -> None:
    logger.info("Searching torrents for query '%s'", query)

    provider = get_torrent_provider()
    target_message = callback_query.message if callback_query else message

    try:
        raw_results = await provider.search(query)
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Torrent search failed for query '%s': %s",
            query,
            exc,
            exc_info=True,
        )
        await target_message.edit_text("Не удалось выполнить поиск по торрентам.")
        return

    results: list[MovieSearchResult] = []
    seen_movie_ids: set[str] = set()
    for result in raw_results:
        if result.id in seen_movie_ids:
            continue
        seen_movie_ids.add(result.id)
        results.append(result)

    if not results:
        logger.info("No torrent results found for query '%s'", query)
        await target_message.edit_text("По запросу ничего не найдено.")
        return

    try:
        keyboard = format_search_results(results, query)
        await target_message.edit_text("Выберите результат:", reply_markup=keyboard)
        logger.info(
            "Sent %d torrent search results for query '%s'",
            len(results),
            query,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Failed to send torrent search results for query '%s': %s",
            query,
            exc,
            exc_info=True,
        )
        await target_message.edit_text("Не удалось отобразить результаты поиска.")


def format_search_results(
    results: list[MovieSearchResult], query: str
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
            "movie_details": result.model_dump(mode="json", by_alias=True, exclude_none=True),
        })
        buttons.append([InlineKeyboardButton(text=button_text, callback_data=movie_details_uuid)])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    return keyboard
