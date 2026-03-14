from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

import aiofile
import httpx
from bs4 import BeautifulSoup

from models.movie_detail_service_types import (
    MovieDetails,
    MovieRatings,
    MovieSearchResult,
    TorrentDetails,
)
from services.exceptions import KinozalApiError
from torrents.interfaces import DownloadResult, TorrentProviderProtocol
from utilities import kinozal_utils
from utilities.kinozal_utils import get_url
from utilities.logger_utils import get_provider_logger

PROVIDER_NAME = "kinozal"


@dataclass(slots=True)
class _RawSearchItem:
    movie_id: str
    title: str
    size: str
    seeds: int | None = None
    peers: int | None = None


async def _search_movies(
    query: str,
    *,
    requested_item: str | None = None,
    requested_type: str | None = None,
) -> list[MovieSearchResult]:
    started_at = perf_counter()
    logger = get_provider_logger(PROVIDER_NAME).bind(operation="search_start")
    logger.info(
        "Search started",
        query=query,
        requested_item=requested_item,
        requested_type=requested_type,
    )

    raw_items = await _fetch_search_items(query)
    if not raw_items:
        duration_ms = int((perf_counter() - started_at) * 1000)
        logger = logger.bind(operation="search_no_results")
        logger.info("Search no results", query=query, duration_ms=duration_ms)
        return []

    logger = logger.bind(operation="search_raw_results")
    logger.info("Search raw results found", query=query, count=len(raw_items))

    movies: list[MovieSearchResult] = []
    count_before = len(raw_items)

    for item in raw_items:
        try:
            result = _build_movie_search_result(item)
            movies.append(result)
        except Exception as exc:
            error_type = type(exc).__name__
            logger = logger.bind(operation="parse_error")
            logger.error(
                "Failed to enrich search result",
                item_id=item.movie_id,
                error_type=error_type,
                error_message=str(exc),
                exc_info=True,
            )
            continue

    count_after = len(movies)
    logger = logger.bind(operation="search_processing")
    logger.info(
        "Search processing completed",
        query=query,
        count_before=count_before,
        count_after=count_after,
    )

    duration_ms = int((perf_counter() - started_at) * 1000)
    logger = logger.bind(operation="search_completed")
    logger.info(
        "Search completed",
        query=query,
        count=count_after,
        duration_ms=duration_ms,
    )
    return movies


async def _fetch_search_items(query: str) -> list[_RawSearchItem]:
    params = {"s": query, "t": 1, "g": 3}
    html = await _get_text("/browse.php", params=params)
    return _parse_search_results(html)


def _build_movie_search_result(
    item: _RawSearchItem,
) -> MovieSearchResult:
    details = _build_stub_movie_details(item)
    return MovieSearchResult.from_search_data(
        search_id=item.movie_id,
        size=item.size,
        search_name=item.title,
        details=details,
        seeds=item.seeds,
        peers=item.peers,
        provider_name="kinozal",
    )


async def _fetch_movie_details(movie_id: int | str) -> MovieDetails:
    logger = get_provider_logger(PROVIDER_NAME).bind(operation="fetch_details")
    logger.debug("Fetching movie details", movie_id=str(movie_id))
    html = await _get_text("/details.php", params={"id": movie_id})
    return _parse_movie_details(html, movie_id)


async def _get_text(path: str, *, params: dict[str, str | int] | None = None) -> str:
    url = get_url(path)
    logger = get_provider_logger(PROVIDER_NAME).bind(operation="http_request")
    start_time = perf_counter()
    
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            response = await client.get(url, params=params)
            duration_ms = int((perf_counter() - start_time) * 1000)
            logger.info(
                "HTTP request",
                method="GET",
                url=str(response.url),
                status_code=response.status_code,
                duration_ms=duration_ms,
            )
            if response.status_code != 200:
                error_type = "HTTPError"
                error_message = f"Kinozal request to {response.url} failed with status {response.status_code}."
                logger = logger.bind(operation="http_error")
                logger.error(
                    "HTTP error",
                    method="GET",
                    url=str(response.url),
                    error_type=error_type,
                    error_message=error_message,
                )
                raise KinozalApiError(error_message)
            return response.text
    except httpx.HTTPError as exc:
        duration_ms = int((perf_counter() - start_time) * 1000)
        error_type = type(exc).__name__
        error_message = f"HTTP client error while requesting {url}: {exc}"
        logger = logger.bind(operation="http_error")
        logger.error(
            "HTTP error",
            method="GET",
            url=url,
            error_type=error_type,
            error_message=error_message,
            duration_ms=duration_ms,
            exc_info=True,
        )
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

        seeds_cell = row.find("td", class_="sl_s")
        seeds = int(seeds_cell.get_text(strip=True)) if seeds_cell else None
        peers_cell = row.find("td", class_="sl_p")
        peers = int(peers_cell.get_text(strip=True)) if peers_cell else None

        movie_id = link.get("href", "").split("=")[-1]
        if not movie_id:
            continue

        results.append(
            _RawSearchItem(
                movie_id=movie_id,
                title=link.text.strip(),
                size=size_cells[1].text.strip(),
                seeds=seeds,
                peers=peers,
            )
        )

    logger = get_provider_logger(PROVIDER_NAME).bind(operation="parse_results")
    logger.debug("Parsed search results", count=len(results))
    return results


def _parse_movie_details(html: str, movie_id: int | str) -> MovieDetails:
    logger = get_provider_logger(PROVIDER_NAME).bind(operation="parse_details")
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
        error_type = type(exc).__name__
        error_message = f"Error parsing Kinozal movie detail results: {exc}"
        logger = logger.bind(operation="parse_error")
        logger.error(
            "Parse error",
            item_id=str(movie_id),
            error_type=error_type,
            error_message=error_message,
            exc_info=True,
        )
        raise KinozalApiError(error_message) from exc


def _build_stub_movie_details(item: _RawSearchItem) -> MovieDetails:
    return MovieDetails(
        name=item.title,
        year="",
        genres=[],
        director="",
        actors=[],
        season=None,
        image_url=None,
        video_quality=None,
        audio_quality=None,
        audio_language=[],
        ratings=MovieRatings(),
        torrent_details=[],
        torrent_html_content=None,
    )


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
    if not image_tag or not isinstance(src := image_tag.get("src"), str):
        return ""
    return get_url(src)


def _parse_ratings(soup: BeautifulSoup) -> MovieRatings:
    imdb_value = "-"
    if imdb_anchor := soup.find("a", href=lambda href: href and "imdb.com" in href):
        if imdb_span := imdb_anchor.find("span"):
            imdb_value = imdb_span.get_text(strip=True)

    return MovieRatings(imdb=imdb_value)


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




async def _download_movie(
    movie_id: int | str,
    credentials: dict[str, str],
) -> DownloadResult:
    started_at = perf_counter()
    logger = get_provider_logger(PROVIDER_NAME).bind(operation="download_start")
    logger.info("Download started", movie_id=str(movie_id))
    
    cookies = await _authenticate(credentials)
    url = get_url(f"/download.php?id={movie_id}")

    try:
        http_start = perf_counter()
        async with httpx.AsyncClient(cookies=cookies, follow_redirects=True) as client:
            response = await client.get(url)
            http_duration_ms = int((perf_counter() - http_start) * 1000)
            logger = logger.bind(operation="http_request")
            logger.info(
                "HTTP request",
                method="GET",
                url=str(response.url),
                status_code=response.status_code,
                duration_ms=http_duration_ms,
            )
            if response.status_code != 200:
                error_type = "HTTPError"
                error_message = f"Failed to download movie {movie_id}: HTTP {response.status_code}."
                logger = logger.bind(operation="http_error")
                logger.error(
                    "HTTP error",
                    method="GET",
                    url=str(response.url),
                    error_type=error_type,
                    error_message=error_message,
                )
                raise KinozalApiError(error_message)
            payload = response.content
    except httpx.HTTPError as exc:
        http_duration_ms = int((perf_counter() - http_start) * 1000)
        error_type = type(exc).__name__
        error_message = f"HTTP client error while downloading Kinozal movie {movie_id}: {exc}"
        logger = logger.bind(operation="http_error")
        logger.error(
            "HTTP error",
            method="GET",
            url=url,
            error_type=error_type,
            error_message=error_message,
            duration_ms=http_duration_ms,
            exc_info=True,
        )
        raise KinozalApiError(error_message) from exc

    if b"pay.php" in payload:
        duration_ms = int((perf_counter() - started_at) * 1000)
        error_type = "DownloadError"
        error_message = "You are not allowed to download this torrent."
        logger = logger.bind(operation="download_error")
        logger.error(
            "Download error",
            movie_id=str(movie_id),
            error_type=error_type,
            error_message=error_message,
            duration_ms=duration_ms,
        )
        raise KinozalApiError(error_message)

    target = Path(tempfile.gettempdir()) / f"{movie_id}.torrent"
    async with aiofile.async_open(target, "wb") as file_handle:
        await file_handle.write(payload)

    duration_ms = int((perf_counter() - started_at) * 1000)
    file_size = len(payload)
    logger = logger.bind(operation="download_success")
    logger.info(
        "Download success",
        movie_id=str(movie_id),
        file_path=str(target),
        file_size=file_size,
        duration_ms=duration_ms,
    )
    return DownloadResult(file_path=str(target), filename=target.name)


async def _authenticate(credentials: dict[str, str]) -> dict[str, str]:
    started_at = perf_counter()
    logger = get_provider_logger(PROVIDER_NAME).bind(operation="auth_start")
    logger.info("Authentication started")
    
    username = credentials.get("username")
    password = credentials.get("password")
    if not username or not password:
        error_type = "AuthenticationError"
        error_message = "Kinozal download requires username and password credentials."
        logger = logger.bind(operation="auth_failed")
        logger.error(
            "Authentication failed",
            error_type=error_type,
            error_message=error_message,
        )
        raise KinozalApiError(error_message)

    url = kinozal_utils.get_url("/takelogin.php")
    data = {"username": username, "password": password}
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    try:
        http_start = perf_counter()
        async with httpx.AsyncClient(follow_redirects=True) as client:
            response = await client.post(url, data=data, headers=headers)
            http_duration_ms = int((perf_counter() - http_start) * 1000)
            logger = logger.bind(operation="http_request")
            logger.info(
                "HTTP request",
                method="POST",
                url=url,
                status_code=response.status_code,
                duration_ms=http_duration_ms,
            )
            if response.status_code != 200:
                error_type = "HTTPError"
                error_message = f"Kinozal authentication failed with status {response.status_code}."
                logger = logger.bind(operation="http_error")
                logger.error(
                    "HTTP error",
                    method="POST",
                    url=url,
                    error_type=error_type,
                    error_message=error_message,
                )
                raise KinozalApiError(error_message)
            
            # Extract cookies from response and client cookie jar
            cookies = {}
            for cookie_name, cookie_value in response.cookies.items():
                cookies[cookie_name] = cookie_value
            try:
                client_cookies = dict(client.cookies)
                cookies.update(client_cookies)
            except (AttributeError, TypeError, ValueError):
                try:
                    if hasattr(client.cookies, 'jar'):
                        for cookie in client.cookies.jar:
                            cookies[cookie.name] = cookie.value
                except (AttributeError, TypeError):
                    pass
    except httpx.HTTPError as exc:
        http_duration_ms = int((perf_counter() - http_start) * 1000)
        error_type = type(exc).__name__
        error_message = f"HTTP client error during Kinozal authentication: {exc}"
        logger = logger.bind(operation="http_error")
        logger.error(
            "HTTP error",
            method="POST",
            url=url,
            error_type=error_type,
            error_message=error_message,
            duration_ms=http_duration_ms,
            exc_info=True,
        )
        raise KinozalApiError(error_message) from exc

    uid_cookie = cookies.get("uid")
    pass_cookie = cookies.get("pass")
    if not uid_cookie or not pass_cookie:
        duration_ms = int((perf_counter() - started_at) * 1000)
        error_type = "AuthenticationError"
        error_message = "Kinozal authentication cookies are missing."
        logger = logger.bind(operation="auth_failed")
        logger.error(
            "Authentication failed",
            error_type=error_type,
            error_message=error_message,
            duration_ms=duration_ms,
        )
        raise KinozalApiError(error_message)

    duration_ms = int((perf_counter() - started_at) * 1000)
    logger = logger.bind(operation="auth_success")
    logger.info("Authentication success", duration_ms=duration_ms)
    return {"uid": uid_cookie, "pass": pass_cookie}


class KinozalTorrentProvider(TorrentProviderProtocol):
    name = "kinozal"
    max_query_length = 64
    requires_authentication = True

    def __init__(self, *, credentials: dict[str, str] | None = None) -> None:
        self._credentials = credentials or {}

    @property
    def base_url(self) -> str:
        """Return the base URL of the Kinozal tracker."""
        return kinozal_utils.get_url()

    def get_torrent_url(self, movie_id: int | str) -> str:
        """Get the full URL to the torrent page on Kinozal."""
        return f"{self.base_url}/details.php?id={movie_id}"

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
