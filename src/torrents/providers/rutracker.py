from __future__ import annotations

import asyncio
import contextlib
import tempfile
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING

import bleach
import httpx
from bs4 import BeautifulSoup

from bot.config import RUTRACKER_URL
from models.movie_detail_service_types import (
    MovieDetails,
    MovieRatings,
    MovieSearchResult,
)
from services.exceptions import RutrackerApiError
from torrents.interfaces import DownloadResult, TorrentProviderProtocol
from utilities.logger_utils import get_provider_logger
from utilities.query_builders import build_flat_queries

if TYPE_CHECKING:
    from models.search_provider_types import MediaDetails

PROVIDER_NAME = "rutracker"

_MAX_RETRIES = 2
_RETRY_BACKOFF_SECONDS = (0.5, 1.5)
_AUTH_TTL_SECONDS = 30 * 60
_LOGIN_TOKEN = "%E2%F5%EE%E4"


def get_url(path: str = "") -> str:
    return f"https://{RUTRACKER_URL}{path}"


class _TransientApiError(RutrackerApiError):
    """Marker for 5xx / transport errors so the retry loop can target them."""


def _backoff_delay(attempt: int) -> float:
    index = min(attempt, len(_RETRY_BACKOFF_SECONDS) - 1)
    return _RETRY_BACKOFF_SECONDS[index]


def _is_transient_status(status_code: int) -> bool:
    return 500 <= status_code < 600


def _is_transient_http_error(exc: BaseException) -> bool:
    return isinstance(exc, httpx.TransportError | httpx.RemoteProtocolError)


async def _authenticate_once(credentials: dict[str, str]) -> dict[str, str]:
    """Perform one login attempt; raises ``_TransientApiError`` on retryable failures."""
    started_at = perf_counter()
    logger = get_provider_logger(PROVIDER_NAME).bind(operation="auth_start")
    logger.info("Authentication started")

    url = get_url("/forum/login.php")
    data = {
        "login_username": credentials.get("username"),
        "login_password": credentials.get("password"),
        "login": _LOGIN_TOKEN,
    }

    http_start = perf_counter()
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, data=data)
    except httpx.HTTPError as exc:
        http_duration_ms = int((perf_counter() - http_start) * 1000)
        error_message = f"HTTP client error during Rutracker authentication: {exc}"
        logger.bind(operation="http_error").error(
            "HTTP error",
            method="POST",
            url=url,
            error_type=type(exc).__name__,
            error_message=error_message,
            duration_ms=http_duration_ms,
            exc_info=True,
        )
        if _is_transient_http_error(exc):
            raise _TransientApiError(error_message) from exc
        raise RutrackerApiError(error_message) from exc

    http_duration_ms = int((perf_counter() - http_start) * 1000)
    logger.bind(operation="http_request").info(
        "HTTP request",
        method="POST",
        url=url,
        status_code=response.status_code,
        duration_ms=http_duration_ms,
    )

    if _is_transient_status(response.status_code):
        message = f"Failed to authenticate: HTTP {response.status_code}"
        logger.bind(operation="http_error").error(
            "HTTP error",
            method="POST",
            url=url,
            error_type="HTTPError",
            error_message=message,
            status_code=response.status_code,
        )
        raise _TransientApiError(message)

    if response.status_code != 302:
        logger.bind(operation="http_error").error(
            "HTTP error",
            method="POST",
            url=url,
            error_type="HTTPError",
            error_message="Failed to authenticate",
            status_code=response.status_code,
        )
        raise RutrackerApiError("Failed to authenticate")

    bb_session = response.cookies.get("bb_session")
    if not bb_session:
        raise RutrackerApiError("Failed to authenticate: bb_session cookie missing")

    duration_ms = int((perf_counter() - started_at) * 1000)
    logger.bind(operation="auth_success").info("Authentication success", duration_ms=duration_ms)
    return {"bb_session": bb_session}


async def _authenticate(credentials: dict[str, str]) -> dict[str, str]:
    """Authenticate, retrying on transient 5xx / network errors."""
    for attempt in range(_MAX_RETRIES + 1):
        try:
            return await _authenticate_once(credentials)
        except _TransientApiError:
            if attempt >= _MAX_RETRIES:
                raise
            await asyncio.sleep(_backoff_delay(attempt))
    raise RutrackerApiError("Authentication failed: retries exhausted")


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
    cookies: dict[str, str] | None = None,
) -> list[MovieSearchResult]:
    """Search for torrents on Rutracker."""
    started_at = perf_counter()
    logger = get_provider_logger(PROVIDER_NAME).bind(operation="search_start")
    logger.info(
        "Search started",
        query=query,
        requested_item=requested_item,
        requested_type=requested_type,
    )

    raw_items = await _fetch_search_items(query, cookies)
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


async def _fetch_search_items(
    query: str, cookies: dict[str, str] | None = None
) -> list[_RawSearchItem]:
    """Fetch search results from Rutracker."""
    html = await _get_search_text(query, cookies)
    return _parse_search_results(html)


async def _get_search_text(query: str, cookies: dict[str, str] | None = None) -> str:
    """Fetch the Rutracker search page HTML, retrying on transient 5xx."""
    url = get_url("/forum/tracker.php")
    params = {"nm": query}
    data = {"f[]": "-1", "o": "10", "s": "2", "pn": "", "nm": query}
    logger = get_provider_logger(PROVIDER_NAME)

    last_status: int | None = None
    last_exc: httpx.HTTPError | None = None

    for attempt in range(_MAX_RETRIES + 1):
        start_time = perf_counter()
        try:
            async with httpx.AsyncClient(cookies=cookies or {}, follow_redirects=True) as client:
                response = await client.post(url, params=params, data=data)
        except httpx.HTTPError as exc:
            duration_ms = int((perf_counter() - start_time) * 1000)
            last_exc = exc
            if attempt < _MAX_RETRIES and _is_transient_http_error(exc):
                logger.bind(operation="http_retry").warning(
                    "HTTP transient error, retrying",
                    method="POST",
                    url=url,
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                    duration_ms=duration_ms,
                    attempt=attempt + 1,
                )
                await asyncio.sleep(_backoff_delay(attempt))
                continue
            error_message = f"HTTP error while requesting {url}: {exc}"
            logger.bind(operation="http_error").error(
                "HTTP error",
                method="POST",
                url=url,
                error_type=type(exc).__name__,
                error_message=error_message,
                duration_ms=duration_ms,
                exc_info=True,
            )
            raise RutrackerApiError(error_message) from exc

        duration_ms = int((perf_counter() - start_time) * 1000)
        last_status = response.status_code

        if _is_transient_status(response.status_code) and attempt < _MAX_RETRIES:
            logger.bind(operation="http_retry").warning(
                "HTTP transient error, retrying",
                method="POST",
                url=str(response.url),
                status_code=response.status_code,
                duration_ms=duration_ms,
                attempt=attempt + 1,
            )
            await asyncio.sleep(_backoff_delay(attempt))
            continue

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            error_message = f"HTTP error while requesting {url}: {exc}"
            logger.bind(operation="http_error").error(
                "HTTP error",
                method="POST",
                url=url,
                error_type=type(exc).__name__,
                error_message=error_message,
                duration_ms=duration_ms,
                exc_info=True,
            )
            raise RutrackerApiError(error_message) from exc

        logger.bind(operation="http_request").info(
            "HTTP request",
            method="POST",
            url=str(response.url),
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        return response.text

    error_message = (
        f"HTTP error while requesting {url}: retries exhausted (last_status={last_status})"
    )
    logger.bind(operation="http_error").error(
        "HTTP error",
        method="POST",
        url=url,
        error_type="HTTPStatusError",
        error_message=error_message,
        status_code=last_status,
    )
    if last_exc is not None:
        raise RutrackerApiError(error_message) from last_exc
    raise RutrackerApiError(error_message)


async def _fetch_torrent_page(movie_id: int | str, cookies: dict[str, str] | None = None) -> str:
    """Get HTML content from Rutracker torrent page."""
    url = get_url(f"/forum/viewtopic.php?t={movie_id}")
    cookies = cookies or {}
    logger = get_provider_logger(PROVIDER_NAME).bind(operation="http_request")
    start_time = perf_counter()

    try:
        async with httpx.AsyncClient(cookies=cookies, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
            duration_ms = int((perf_counter() - start_time) * 1000)
            logger.info(
                "HTTP request",
                method="GET",
                url=str(response.url),
                status_code=response.status_code,
                duration_ms=duration_ms,
            )
            return response.text
    except httpx.HTTPError as exc:
        duration_ms = int((perf_counter() - start_time) * 1000)
        error_type = type(exc).__name__
        error_message = f"HTTP error while requesting {url}: {exc}"
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
        raise RutrackerApiError(error_message) from exc


async def _download_movie(
    movie_id: int | str,
    cookies: dict[str, str] | None = None,
) -> DownloadResult:
    """Download torrent file from Rutracker."""
    started_at = perf_counter()
    logger = get_provider_logger(PROVIDER_NAME).bind(operation="download_start")
    logger.info("Download started", movie_id=str(movie_id))

    cookies = cookies or {}
    url = get_url(f"/forum/dl.php?t={movie_id}")

    try:
        http_start = perf_counter()
        async with httpx.AsyncClient(cookies=cookies, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
            http_duration_ms = int((perf_counter() - http_start) * 1000)
            logger = logger.bind(operation="http_request")
            logger.info(
                "HTTP request",
                method="GET",
                url=str(response.url),
                status_code=response.status_code,
                duration_ms=http_duration_ms,
            )

            content_type = response.headers.get("content-type", "").lower()
            if "text/html" in content_type:
                error_type = "DownloadError"
                error_message = (
                    f"Failed to download torrent {movie_id}: received HTML instead of torrent file. "
                    "This may indicate authentication is required or the torrent is not available."
                )
                logger = logger.bind(operation="http_error")
                logger.error(
                    "HTTP error",
                    method="GET",
                    url=str(response.url),
                    error_type=error_type,
                    error_message=error_message,
                )
                raise RutrackerApiError(error_message)

            payload = response.content
    except httpx.HTTPError as exc:
        http_duration_ms = int((perf_counter() - http_start) * 1000)
        error_type = type(exc).__name__
        error_message = f"HTTP error while downloading Rutracker movie {movie_id}: {exc}"
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
        raise RutrackerApiError(error_message) from exc

    if not payload or len(payload) < 10:
        duration_ms = int((perf_counter() - started_at) * 1000)
        error_type = "DownloadError"
        error_message = (
            f"Invalid torrent file received for movie {movie_id}: file is too small or empty"
        )
        logger = logger.bind(operation="download_error")
        logger.error(
            "Download error",
            movie_id=str(movie_id),
            error_type=error_type,
            error_message=error_message,
            duration_ms=duration_ms,
        )
        raise RutrackerApiError(error_message)

    target = Path(tempfile.gettempdir()) / f"rutracker_{movie_id}.torrent"
    target.write_bytes(payload)

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


def _remove_links_with_parents(soup: BeautifulSoup) -> None:
    """Remove all links (<a> tags) with their parent blocks until only text remains.

    Iterates through all links, removes them, and then recursively removes
    their parent containers if they become effectively empty (contain only
    whitespace or common separators).
    """
    # Create a list copy to safely iterate while modifying the tree
    for link in list(soup.find_all("a")):
        # Skip if link is already removed
        if link.parent is None:
            continue

        parent = link.parent
        link.decompose()

        # Walk up the tree removing empty parents
        current = parent
        while current and current != soup:
            # Check for other significant tags
            # We treat <br> as non-significant for container removal decision
            # if the text is also empty/separators
            has_significant_tags = False
            for child in current.find_all(recursive=False):
                if child.name != "br":
                    has_significant_tags = True
                    break

            if has_significant_tags:
                break

            # Check text content
            text = current.get_text(strip=True)
            # Allow removal if text is empty or consists only of separators
            # Separators: | / \ - . , : ; and whitespace
            if not text or all(c in "|/\\-.,:; \t\n\r" for c in text):
                # Element is effectively empty -> remove it and check parent
                parent_to_remove = current
                current = current.parent
                parent_to_remove.decompose()
            else:
                # Contains significant text
                break


def _deduplicate_hr(soup: BeautifulSoup) -> None:
    """Remove duplicate <hr> tags (consecutive horizontal lines).

    Removes an <hr> tag if:
    1. It follows immediately after another <hr> (ignoring whitespace).
    2. It is the first significant element in the container.
    3. It is the last significant element in the container.
    """
    hrs = soup.find_all("hr")
    if not hrs:
        return

    def is_empty_text(node):
        """Check if node is a text node containing only whitespace."""
        return isinstance(node, str) and not node.strip()

    for hr in hrs:
        # Check previous sibling
        prev_node = hr.previous_sibling
        while prev_node and is_empty_text(prev_node):
            prev_node = prev_node.previous_sibling

        # 1. Remove if previous significant node is also hr
        if prev_node and prev_node.name == "hr":
            hr.decompose()
            continue

        # 2. Remove if it's the first significant element (prev_node is None)
        if prev_node is None:
            hr.decompose()
            continue

        # Check next sibling
        next_node = hr.next_sibling
        while next_node and is_empty_text(next_node):
            next_node = next_node.next_sibling

        # 3. Remove if it's the last significant element (next_node is None)
        if next_node is None:
            hr.decompose()


def _extract_post_body_html(soup: BeautifulSoup) -> str | None:
    """Extract HTML content from the first post_body element."""
    logger = get_provider_logger(PROVIDER_NAME).bind(operation="parse_details")
    post_body = soup.find("div", class_="post_body")
    if not post_body:
        logger.warning("post_body element not found on page")
        return None

    # Remove all elements with class="sp-wrap"
    for sp_wrap in post_body.find_all(class_="sp-wrap"):
        sp_wrap.decompose()

    # Remove all links with their parent blocks
    _remove_links_with_parents(post_body)

    # Get the inner HTML as string
    return str(post_body)


def _clean_and_convert_html(html: str) -> str:
    """Clean HTML with bleach and normalize common Rutracker markup."""
    # Define allowed tags for Telegram HTML
    # Based on Telegram's supported tags
    allowed_tags = [
        "a",
        "b",
        "strong",
        "i",
        "em",
        "s",
        "strike",
        "del",
        "u",
        "ins",
        "span",
        "tg-spoiler",
        "pre",
        "code",
        "details",
        "summary",
        "br",
        "hr",
        "wbr",
        "ul",
        "ol",
        "li",
        "div",
        "p",
        "q",
        "blockquote",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "noscript",
        "cite",
        "var",
        "progress",
        "meter",
        "kbd",
        "samp",
        "img",
        "tt",
        "input",
        "footer",
        "header",
        "main",
        "nav",
        "section",
        "html",
        "body",
        "output",
        "data",
        "time",
    ]

    # Define allowed attributes
    allowed_attributes = {
        "a": ["href"],
        "span": ["class"],
        "pre": ["class"],
        "code": ["class"],
        "ol": ["reversed", "type", "start"],
        "li": ["value"],
        "img": ["alt", "src"],
        "input": ["type", "value"],
        "blockquote": ["expandable"],
    }

    # Clean HTML with bleach
    cleaned_html = bleach.clean(
        html,
        tags=allowed_tags,
        attributes=allowed_attributes,
        strip=False,  # Don't strip whitespace to preserve layout
    )

    # Deduplicate <hr> tags and fix formatting after cleaning
    try:
        soup = BeautifulSoup(cleaned_html, "html.parser")
        _deduplicate_hr(soup)

        # Convert span.post-b to <b> tags for bold text (Rutracker style)
        for span in soup.find_all("span", class_="post-b"):
            bold_tag = soup.new_tag("b")
            # Move all contents from span to b
            # We need to copy contents because replace_with might modify the tree during iteration
            # But extend works fine here
            bold_tag.extend(span.contents)
            span.replace_with(bold_tag)

        return str(soup)
    except Exception as exc:
        logger = get_provider_logger(PROVIDER_NAME).bind(operation="parse_error")
        error_type = type(exc).__name__
        logger.warning(
            "Failed to process HTML structure",
            error_type=error_type,
            error_message=str(exc),
        )
        return cleaned_html


def _parse_search_results(html: str) -> list[_RawSearchItem]:
    """Parse Rutracker search results HTML."""
    logger = get_provider_logger(PROVIDER_NAME).bind(operation="parse_results")
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", id="tor-tbl")
    if not table:
        logger.debug("No torrent table found in response", count=0)
        return []

    results: list[_RawSearchItem] = []
    rows = table.find_all("tr", class_="hl-tr")

    for row in rows:
        try:
            movie_id = row.get("data-topic_id")
            if not movie_id:
                continue

            title_div = row.find("div", class_="t-title")
            if not title_div:
                continue

            title_link = title_div.find("a", class_="tLink")
            if not title_link:
                continue

            title = title_link.get_text(strip=True)

            size_cell = row.find("td", class_="tor-size")
            size = size_cell.get_text(strip=True) if size_cell else "N/A"
            size = size.replace("↓", "").replace("↑", "").strip()

            seeds_cell = row.find("td", class_="seedmed")
            if not seeds_cell:
                cells = row.find_all("td")
                if len(cells) > 6:
                    seeds_cell = cells[6]

            seeds = None
            if seeds_cell:
                try:
                    seed_val = seeds_cell.get_text(strip=True)
                    seeds = int(seed_val)
                except (ValueError, AttributeError):
                    pass

            peers_cell = row.find("td", class_="leechmed")
            if not peers_cell:
                cells = row.find_all("td")
                if len(cells) > 7:
                    peers_cell = cells[7]

            peers = None
            if peers_cell:
                with contextlib.suppress(ValueError, AttributeError):
                    peers = int(peers_cell.get_text(strip=True))

            results.append(
                _RawSearchItem(
                    movie_id=movie_id,
                    title=title,
                    size=size,
                    seeds=seeds,
                    peers=peers,
                )
            )
        except Exception as exc:
            error_type = type(exc).__name__
            logger = logger.bind(operation="parse_error")
            logger.error(
                "Error parsing search row",
                error_type=error_type,
                error_message=str(exc),
                exc_info=True,
            )
            continue

    logger.debug("Parsed search results", count=len(results))
    return results


def _build_movie_search_result(
    item: _RawSearchItem,
) -> MovieSearchResult:
    """Build MovieSearchResult from raw search item."""
    details = _build_stub_movie_details(item)
    return MovieSearchResult.from_search_data(
        search_id=item.movie_id,
        size=item.size,
        search_name=item.title,
        details=details,
        seeds=item.seeds,
        peers=item.peers,
        provider_name="rutracker",
    )


def _build_stub_movie_details(item: _RawSearchItem) -> MovieDetails:
    """Build stub MovieDetails from search item."""
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


class RutrackerTorrentProvider(TorrentProviderProtocol):
    name = "rutracker"
    max_query_length = None  # No query length limit for Rutracker
    requires_authentication = True

    def __init__(self, *, credentials: dict[str, str] | None = None) -> None:
        self._credentials = credentials or {}
        self._cached_cookies: dict[str, str] = {}
        self._cookies_expire_at: float = 0.0
        self._auth_lock = asyncio.Lock()

    @property
    def base_url(self) -> str:
        """Return the base URL of the Rutracker tracker."""
        return get_url()

    def get_torrent_url(self, movie_id: int | str) -> str:
        """Get the full URL to the torrent page on Rutracker."""
        return f"{self.base_url}/forum/viewtopic.php?t={movie_id}"

    async def _get_cookies(self) -> dict[str, str]:
        """Return cached auth cookies, refreshing under a lock when stale."""
        if not self._credentials:
            return {}

        loop = asyncio.get_running_loop()
        if self._cached_cookies and loop.time() < self._cookies_expire_at:
            return self._cached_cookies

        async with self._auth_lock:
            if self._cached_cookies and loop.time() < self._cookies_expire_at:
                return self._cached_cookies

            try:
                cookies = await _authenticate(self._credentials)
            except Exception as exc:
                get_provider_logger(PROVIDER_NAME).bind(operation="auth_failed").warning(
                    "Authentication failed, using guest access",
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                )
                self._cached_cookies = {}
                self._cookies_expire_at = loop.time() + 60
                return {}

            self._cached_cookies = cookies
            self._cookies_expire_at = loop.time() + _AUTH_TTL_SECONDS
            return cookies

    async def search(
        self,
        query: str,
        *,
        requested_item: str | None = None,
        requested_type: str | None = None,
    ) -> list[MovieSearchResult]:
        """Search for torrents on Rutracker."""
        cookies = await self._get_cookies()
        return await _search_movies(
            query,
            requested_item=requested_item,
            requested_type=requested_type,
            cookies=cookies,
        )

    def build_queries(
        self,
        *,
        media_details: MediaDetails,
        season_number: int | None = None,
        season_year: int | None = None,
        season_pack_only: bool = False,
    ) -> list[str]:
        """Rutracker treats ``(|)`` literally — emit flat queries."""
        return build_flat_queries(
            media_details,
            season_number=season_number,
            season_year=season_year,
            season_pack_only=season_pack_only,
            max_length=self.max_query_length,
        )

    async def get_movie_detail(self, movie_id: int | str) -> MovieDetails:
        """Get detailed information about a torrent from Rutracker."""
        logger = get_provider_logger(PROVIDER_NAME).bind(operation="fetch_details")
        logger.debug("Fetching movie details", movie_id=str(movie_id))

        try:
            cookies = await self._get_cookies()
            html = await _fetch_torrent_page(movie_id, cookies)
            soup = BeautifulSoup(html, "html.parser")
            post_body_html = _extract_post_body_html(soup)

            cleaned_html = None
            if post_body_html:
                cleaned_html = _clean_and_convert_html(post_body_html)

            title = ""
            title_tag = soup.find("h1")
            if title_tag:
                title_link = title_tag.find("a")
                if title_link:
                    title = title_link.get_text(strip=True)
                else:
                    title = title_tag.get_text(strip=True)

            return MovieDetails(
                name=title or f"Torrent {movie_id}",
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
                torrent_html_content=cleaned_html,
            )
        except Exception as exc:
            error_type = type(exc).__name__
            error_message = f"Error fetching Rutracker movie detail for id {movie_id}: {exc}"
            logger = logger.bind(operation="parse_error")
            logger.error(
                "Parse error",
                item_id=str(movie_id),
                error_type=error_type,
                error_message=error_message,
                exc_info=True,
            )
            raise RutrackerApiError(error_message) from exc

    async def download_movie(self, movie_id: int | str) -> DownloadResult:
        """Download torrent file from Rutracker."""
        cookies = await self._get_cookies()
        return await _download_movie(movie_id, cookies)
