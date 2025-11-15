from __future__ import annotations

import asyncio
import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

import aiofile
import aiohttp
from bs4 import BeautifulSoup
from yarl import URL

from custom_types.movie_detail_service_types import (
    MovieDetails,
    MovieRatings,
    MovieSearchResult,
    TorrentDetails,
)
from services.exceptions import KinozalApiError
from torrents.interfaces import DownloadResult, TorrentProviderProtocol
from utilities import kinozal_utils
from utilities.groq_utils import get_movie_search_result
from utilities.kinozal_utils import get_url


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _RawSearchItem:
    movie_id: str
    title: str
    size: str


async def _search_movies(
    query: str,
    *,
    requested_item: str | None = None,
    requested_type: str | None = None,
) -> list[MovieSearchResult]:
    started_at = perf_counter()
    logger.debug(
        "Starting Kinozal search for query '%s' (requested_item=%s, requested_type=%s)",
        query,
        requested_item,
        requested_type,
    )

    raw_items = await _fetch_search_items(query)
    if not raw_items:
        _log_search_duration(query, 0, started_at)
        return []

    enriched_results = await asyncio.gather(
        *(_build_movie_search_result(item) for item in raw_items),
        return_exceptions=True,
    )

    movies: list[MovieSearchResult] = []
    for item, result in zip(raw_items, enriched_results):
        if isinstance(result, Exception):
            logger.error(
                "Failed to enrich search result for id %s: %s",
                item.movie_id,
                result,
            )
            continue
        movies.append(result)

    if requested_item and requested_type:
        movies = await _filter_movies_with_groq(
            movies,
            requested_item=requested_item,
            requested_type=requested_type,
        )

    _log_search_duration(query, len(movies), started_at)
    return movies


async def _fetch_search_items(query: str) -> list[_RawSearchItem]:
    params = {"s": query, "t": 1, "g": 3}
    html = await _get_text("/browse.php", params=params)
    return _parse_search_results(html)


async def _build_movie_search_result(item: _RawSearchItem) -> MovieSearchResult:
    details = await _fetch_movie_details(item.movie_id)
    return MovieSearchResult.from_search_data(
        search_id=item.movie_id,
        size=item.size,
        search_name=item.title,
        details=details,
    )


async def _fetch_movie_details(movie_id: int | str) -> MovieDetails:
    logger.debug("Fetching movie details for Kinozal id %s", movie_id)
    html = await _get_text("/details.php", params={"id": movie_id})
    return _parse_movie_details(html)


async def _get_text(
    path: str, *, params: dict[str, str | int] | None = None
) -> str:
    url = get_url(path)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as response:
                logger.debug("GET %s -> %s", response.url, response.status)
                if response.status != 200:
                    raise KinozalApiError(
                        f"Kinozal request to {response.url} failed with status {response.status}."
                    )
                return await response.text()
    except aiohttp.ClientError as exc:
        error_message = f"HTTP client error while requesting {url}: {exc}"
        logger.error(error_message)
        raise KinozalApiError(error_message) from exc


def _parse_search_results(html: str) -> list[_RawSearchItem]:
    soup = BeautifulSoup(html, "html.parser")
    results: list[_RawSearchItem] = []

    for row in soup.find_all("tr", class_="bg"):
        name_cell = row.find("td", class_="nam")
        if name_cell is None:
            continue
        link = name_cell.find("a")
        if link is None:
            continue
        size_cells = row.find_all("td", class_="s")
        if len(size_cells) < 2:
            continue

        movie_id = link.get("href", "").split("=")[-1]
        if not movie_id:
            continue

        results.append(
            _RawSearchItem(
                movie_id=movie_id,
                title=link.text.strip(),
                size=size_cells[1].text.strip(),
            )
        )

    logger.debug("Parsed %d Kinozal search results", len(results))
    return results


def _parse_movie_details(html: str) -> MovieDetails:
    try:
        soup = BeautifulSoup(html, "html.parser")
        return MovieDetails(
            name=_parse_name(soup),
            year=_parse_year(soup),
            genres=_parse_genres(soup),
            director=_parse_director(soup),
            actors=_parse_actors(soup),
            image_url=_parse_image_url(soup),
            ratings=_parse_ratings(soup),
            torrent_details=_parse_torrent_details(soup),
        )
    except Exception as exc:  # noqa: BLE001
        error_message = f"Error parsing Kinozal movie detail results: {exc}"
        logger.error(error_message)
        raise KinozalApiError(error_message) from exc


def _parse_name(soup: BeautifulSoup) -> str:
    title_tag = soup.find("h1")
    if not title_tag:
        return ""
    link = title_tag.find("a")
    if link:
        return link.get_text(strip=True)
    return title_tag.get_text(strip=True)


def _parse_year(soup: BeautifulSoup) -> str:
    tag = _find_metadata_tag(soup, "Год выпуска:")
    sibling = getattr(tag, "next_sibling", "") if tag else ""
    return sibling.strip() if isinstance(sibling, str) else ""


def _parse_genres(soup: BeautifulSoup) -> list[str]:
    text = _extract_span_text(soup, "Жанр:")
    return [item.strip() for item in text.split(",")] if text else []


def _parse_director(soup: BeautifulSoup) -> str:
    return _extract_span_text(soup, "Режиссер:")


def _parse_actors(soup: BeautifulSoup) -> list[str]:
    text = _extract_span_text(soup, "В ролях:")
    return [item.strip() for item in text.split(",")] if text else []


def _parse_image_url(soup: BeautifulSoup) -> str:
    image_tag = soup.find("img", class_="p200")
    if not image_tag:
        return ""
    src = image_tag.get("src")
    return get_url(src) if src else ""


def _parse_ratings(soup: BeautifulSoup) -> MovieRatings:
    imdb_anchor = soup.find("a", href=lambda href: href and "imdb.com" in href)
    imdb_value = (
        imdb_anchor.find("span").get_text(strip=True) if imdb_anchor and imdb_anchor.find("span") else "-"
    )

    kinopoisk_anchor = soup.find("a", href=lambda href: href and "kinopoisk.ru" in href)
    kinopoisk_value = (
        kinopoisk_anchor.find("span").get_text(strip=True)
        if kinopoisk_anchor and kinopoisk_anchor.find("span")
        else "-"
    )

    return MovieRatings(imdb=imdb_value, kinopoisk=kinopoisk_value)


def _parse_torrent_details(soup: BeautifulSoup) -> list[TorrentDetails]:
    tab_div = soup.find("div", {"id": "tabs"})
    if not tab_div:
        return []

    details: list[TorrentDetails] = []
    for bold in tab_div.find_all("b"):
        key = bold.get_text(strip=True)
        value_node = bold.next_sibling
        if value_node is None:
            value_text = None
        elif hasattr(value_node, "get_text"):
            value_text = value_node.get_text(strip=True)
        else:
            value_text = str(value_node).strip()

        if value_text == "":
            value_text = None

        details.append(TorrentDetails(key=key, value=value_text))

    return details


def _find_metadata_tag(soup: BeautifulSoup, label: str):
    return soup.find(lambda tag: tag.name == "b" and label in tag.text)


def _extract_span_text(soup: BeautifulSoup, label: str) -> str:
    tag = _find_metadata_tag(soup, label)
    if not tag:
        return ""
    span = tag.find_next_sibling("span")
    if span:
        return span.get_text(strip=True)
    sibling = getattr(tag, "next_sibling", "")
    return sibling.strip() if isinstance(sibling, str) else ""


def _log_search_duration(
    query: str,
    result_count: int,
    started_at: float,
) -> None:
    duration = perf_counter() - started_at
    logger.info(
        "Search completed for query '%s' with %d results in %.2fs",
        query,
        result_count,
        duration,
    )


async def _filter_movies_with_groq(
    movies: list[MovieSearchResult],
    *,
    requested_item: str,
    requested_type: str,
) -> list[MovieSearchResult]:
    movies_to_validate = [
        movie for movie in movies if (movie.search_name or movie.name)
    ]
    if not movies_to_validate:
        return []

    validation_tasks = [
        _validate_movie_with_groq(movie, requested_item, requested_type)
        for movie in movies_to_validate
    ]
    validation_results = await asyncio.gather(
        *validation_tasks,
        return_exceptions=True,
    )

    filtered: list[MovieSearchResult] = []
    for movie, validation in zip(movies_to_validate, validation_results):
        if isinstance(validation, Exception):
            logger.warning(
                "Groq validation raised for Kinozal movie id %s: %s",
                movie.id,
                validation,
            )
            continue
        if validation is not None:
            filtered.append(validation)
        else:
            logger.warning("Groq validation failed for Kinozal movie title %s", movie.name)

    logger.debug(
        "Groq validation filtered %d/%d Kinozal results",
        len(filtered),
        len(movies_to_validate),
    )
    return filtered


async def _validate_movie_with_groq(
    movie: MovieSearchResult,
    requested_item: str,
    requested_type: str,
) -> MovieSearchResult | None:
    title = movie.search_name or movie.name
    if not title:
        return None

    try:
        validation = await get_movie_search_result(
            movie,
            title=title,
            requested_item=requested_item,
            requested_type=requested_type,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Groq validation failed for Kinozal movie id %s (%s): %s",
            movie.id,
            title,
            exc,
        )
        return None

    return validation


async def _download_movie(
    movie_id: int | str,
    credentials: dict[str, str],
) -> DownloadResult:
    logger.debug("Downloading Kinozal torrent for movie id %s", movie_id)
    cookies = await _authenticate(credentials)
    url = get_url(f"/download.php?id={movie_id}")

    try:
        async with aiohttp.ClientSession(cookies=cookies) as session:
            async with session.get(url) as response:
                logger.debug("GET %s -> %s", response.url, response.status)
                if response.status != 200:
                    raise KinozalApiError(
                        f"Failed to download movie {movie_id}: HTTP {response.status}."
                    )
                payload = await response.read()
    except aiohttp.ClientError as exc:
        error_message = f"HTTP client error while downloading Kinozal movie {movie_id}: {exc}"
        logger.error(error_message)
        raise KinozalApiError(error_message) from exc

    if b"pay.php" in payload:
        raise KinozalApiError("You are not allowed to download this torrent.")

    target = Path(tempfile.gettempdir()) / f"{movie_id}.torrent"
    async with aiofile.async_open(target, "wb") as file_handle:
        await file_handle.write(payload)

    logger.info("Torrent file for movie %s saved to %s", movie_id, target)
    return DownloadResult(file_path=str(target), filename=target.name)


async def _authenticate(credentials: dict[str, str]) -> dict[str, str]:
    username = credentials.get("username")
    password = credentials.get("password")
    if not username or not password:
        raise KinozalApiError(
            "Kinozal download requires username and password credentials."
        )

    url = kinozal_utils.get_url("/takelogin.php")
    data = {"username": username, "password": password}
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=data, headers=headers) as response:
                logger.debug("POST %s -> %s", response.url, response.status)
                if response.status != 200:
                    raise KinozalApiError(
                        f"Kinozal authentication failed with status {response.status}."
                    )
            kinozal_url = URL(kinozal_utils.get_url())
            cookies = session.cookie_jar.filter_cookies(kinozal_url)
    except aiohttp.ClientError as exc:
        error_message = f"HTTP client error during Kinozal authentication: {exc}"
        logger.error(error_message)
        raise KinozalApiError(error_message) from exc

    uid_cookie = cookies.get("uid")
    pass_cookie = cookies.get("pass")
    if not uid_cookie or not pass_cookie:
        raise KinozalApiError("Kinozal authentication cookies are missing.")

    return {"uid": uid_cookie.value, "pass": pass_cookie.value}


class KinozalTorrentProvider(TorrentProviderProtocol):
    name = "kinozal"

    def __init__(self, *, credentials: dict[str, str] | None = None) -> None:
        self._credentials = credentials or {}

    async def search(
        self,
        query: str,
        *,
        requested_item: str | None = None,
        requested_type: str | None = None,
    ) -> list[MovieSearchResult]:
        return await _search_movies(
            query,
            requested_item=requested_item,
            requested_type=requested_type,
        )

    async def get_movie_detail(self, movie_id: int | str) -> MovieDetails:
        return await _fetch_movie_details(movie_id)

    async def download_movie(self, movie_id: int | str) -> DownloadResult:
        return await _download_movie(movie_id, self._credentials)

