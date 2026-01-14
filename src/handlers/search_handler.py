from time import perf_counter

from aiogram import Router
from aiogram.types import CallbackQuery, Message

from bot.constants import (
    MEDIA_LIST_CALLBACK,
    MEDIA_SELECT_CALLBACK,
    SEASON_LIST_CALLBACK,
    SEASON_SELECT_CALLBACK,
    SEARCH_MOVIE_CALLBACK,
)
from services.exceptions import KinopoiskApiError, NoResultsFoundError, TmdbApiError
from utilities import media_utils
from utilities.handlers_utils import (
    check_action,
    redis_callback_get,
    redis_callback_save,
)
from utilities.media_search_utils import (
    get_details_from_callback,
    show_cached_torrent_results,
    show_media_results,
    show_season_choices,
)
from utilities.torrent_search_utils import perform_torrent_search
from utilities.logger_utils import get_handler_logger
from torrents import get_active_providers
from . import movie_detail_handler

logger = get_handler_logger("search")
router = Router(name=__name__)
router.include_routers(movie_detail_handler.router)


@router.message()
async def handle_search_query(message: Message):
    started_at = perf_counter()
    user_id = message.from_user.id if message.from_user else None
    handler_logger = logger.bind(user_id=user_id, operation="search_query")
    
    query = (message.text or "").strip()
    if not query:
        await message.answer("Введите название фильма или сериала.")
        return

    status_message = await message.answer(f"Ищу «{query}»...")
    handler_logger.info("Search query received", query=query)

    try:
        await show_media_results(query, status_message)
        duration_ms = int((perf_counter() - started_at) * 1000)
        handler_logger.info("Search query completed", query=query, duration_ms=duration_ms)
    except NoResultsFoundError:
        duration_ms = int((perf_counter() - started_at) * 1000)
        handler_logger.info("Search returned no results", query=query, duration_ms=duration_ms)
        await status_message.edit_text(
            f"К сожалению, по запросу «{query}» ничего не найдено."
        )
    except (KinopoiskApiError, TmdbApiError) as exc:
        duration_ms = int((perf_counter() - started_at) * 1000)
        error_type = type(exc).__name__
        handler_logger.warning(
            "Search API error",
            query=query,
            error_type=error_type,
            error_message=str(exc),
            duration_ms=duration_ms,
        )
        await status_message.edit_text(
            "Произошла ошибка при обращении к сервису поиска."
        )
    except Exception as exc:
        duration_ms = int((perf_counter() - started_at) * 1000)
        error_type = type(exc).__name__
        handler_logger.error(
            "Unexpected error during search",
            query=query,
            error_type=error_type,
            error_message=str(exc),
            duration_ms=duration_ms,
            exc_info=True,
        )
        await status_message.edit_text("Произошла непредвиденная ошибка при поиске.")


@router.callback_query(lambda c: check_action(c.data, SEARCH_MOVIE_CALLBACK))
async def handle_search_callback(callback_query: CallbackQuery):
    if not (search_info := redis_callback_get(callback_query.data)):
        await callback_query.answer(
            "Не удалось получить данные для поиска.", show_alert=True
        )
        return

    if (
        cache_key := search_info.get("results_cache_key")
    ) and await show_cached_torrent_results(callback_query.message, cache_key):
        await callback_query.answer()
        return

    if not (query := search_info.get("query")):
        await callback_query.answer(
            "Недостаточно данных для нового поиска.", show_alert=True
        )
        return

    movie_details = await get_details_from_callback(search_info)

    await perform_torrent_search(
        query,
        callback_query.message,
        callback_query,
        requested_item=search_info.get("requested_item"),
        requested_type=search_info.get("requested_type"),
        media_details=movie_details,
    )
    await callback_query.answer()


@router.callback_query(lambda c: check_action(c.data, MEDIA_LIST_CALLBACK))
async def handle_media_results_list(callback_query: CallbackQuery):
    redis_data = redis_callback_get(callback_query.data)
    query = redis_data.get("query") if redis_data else None

    if not query:
        await callback_query.answer("Не удалось обновить список.", show_alert=True)
        return

    try:
        await show_media_results(query, callback_query.message)
    except NoResultsFoundError:
        await callback_query.message.edit_text(
            f"По запросу «{query}» ничего не найдено."
        )
    except (KinopoiskApiError, TmdbApiError):
        await callback_query.answer(
            "Сервис поиска временно недоступен.", show_alert=True
        )
    finally:
        await callback_query.answer()


@router.callback_query(lambda c: check_action(c.data, MEDIA_SELECT_CALLBACK))
async def handle_media_selection(callback_query: CallbackQuery):
    if not (redis_data := redis_callback_get(callback_query.data)):
        await callback_query.answer("Не удалось обработать выбор.", show_alert=True)
        return

    if not (movie_details := await get_details_from_callback(redis_data)):
        await callback_query.answer("Не удалось получить детали.", show_alert=True)
        return

    seasons = [
        s.season_number for s in movie_details.seasons if s.season_number is not None
    ]

    if movie_details.is_series and seasons:
        await show_season_choices(
            callback_query,
            movie_details,
            seasons,
            original_query=redis_data.get("query"),
            requested_item=redis_data.get("requested_item"),
            requested_type=redis_data.get("requested_type", "series"),
        )
        await callback_query.answer()
        return

    # Handle movie search or series without seasons
    # Get max_query_length from first available provider (all providers should have same limit)
    active_providers = get_active_providers()
    if not active_providers:
        await callback_query.answer(
            "Нет активных торрент-провайдеров. Проверьте настройки.",
            show_alert=True
        )
        return
    max_query_length = active_providers[0].max_query_length
    
    search_query = media_utils.build_torrent_query_from_media_details(
        movie_details, max_length=max_query_length
    )
    search_context = (
        (redis_data.get("query") or "").strip()
        or (redis_data.get("requested_item") or "").strip()
        or movie_details.title
    )

    back_callback_key = None
    if search_context:
        back_callback_key = redis_callback_save(
            {
                "action": MEDIA_LIST_CALLBACK,
                "query": search_context,
            }
        )

    await perform_torrent_search(
        search_query,
        callback_query.message,
        callback_query,
        requested_item=redis_data.get("requested_item"),
        requested_type=redis_data.get("requested_type", "movie"),
        back_callback_key=back_callback_key,
        back_button_text="⬅️ Назад к результатам поиска",
        media_details=movie_details,
    )
    await callback_query.answer()


@router.callback_query(lambda c: check_action(c.data, SEASON_SELECT_CALLBACK))
async def handle_season_selection(callback_query: CallbackQuery):
    if not (
        redis_data := redis_callback_get(callback_query.data)
    ) or not redis_data.get("season"):
        await callback_query.answer("Не удалось определить сезон.", show_alert=True)
        return

    if not (movie_details := await get_details_from_callback(redis_data)):
        await callback_query.answer(
            "Не удалось получить детали для сезона.", show_alert=True
        )
        return

    season_number = int(redis_data["season"])
    season_year = next(
        (s.year for s in movie_details.seasons if s.season_number == season_number),
        None,
    )

    # Get max_query_length from first available provider (all providers should have same limit)
    active_providers = get_active_providers()
    if not active_providers:
        await callback_query.answer(
            "Нет активных торрент-провайдеров. Проверьте настройки.",
            show_alert=True
        )
        return
    max_query_length = active_providers[0].max_query_length
    
    search_query = media_utils.build_torrent_query_from_media_details(
        movie_details,
        season_number=season_number if len(movie_details.seasons) > 1 else None,
        season_year=season_year,
        max_length=max_query_length,
    )

    requested_item = redis_data.get("requested_item", movie_details.title)
    validation_item = (
        f"{requested_item} {season_number} сезон" if requested_item else None
    )

    back_callback_key = redis_callback_save(
        {
            "action": SEASON_LIST_CALLBACK,
            "movie_id": movie_details.provider_id,
            "movie": redis_data.get("movie"),
            "movie_details": redis_data.get("movie_details") or redis_data.get("movie"),
            "original_query": redis_data.get("original_query"),
            "requested_item": redis_data.get("requested_item") or movie_details.title,
            "requested_type": redis_data.get("requested_type", "series"),
        }
    )

    await perform_torrent_search(
        search_query,
        callback_query.message,
        callback_query,
        requested_item=validation_item,
        requested_type=redis_data.get("requested_type", "series"),
        back_callback_key=back_callback_key,
        back_button_text="⬅️ Назад к сезонам",
        media_details=movie_details,
        season_number=season_number,
        season_year=season_year,
    )
    await callback_query.answer()


@router.callback_query(lambda c: check_action(c.data, SEASON_LIST_CALLBACK))
async def handle_season_list(callback_query: CallbackQuery):
    if not (redis_data := redis_callback_get(callback_query.data)):
        await callback_query.answer(
            "Не удалось вернуть список сезонов.", show_alert=True
        )
        return

    if not (movie_details := await get_details_from_callback(redis_data)):
        await callback_query.answer(
            "Не удалось получить информацию о сериале.", show_alert=True
        )
        return

    seasons = [
        s.season_number for s in movie_details.seasons if s.season_number is not None
    ]
    if not seasons:
        await callback_query.answer("Список сезонов недоступен.", show_alert=True)
        return

    await show_season_choices(
        callback_query,
        movie_details,
        seasons,
        original_query=redis_data.get("original_query"),
        requested_item=redis_data.get("requested_item") or movie_details.title,
        requested_type=redis_data.get("requested_type", "series"),
    )
    await callback_query.answer()
