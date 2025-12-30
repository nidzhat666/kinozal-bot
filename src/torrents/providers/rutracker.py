from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup

from bot.config import RUTRACKER_URL
from services.exceptions import RutrackerApiError
from models.movie_detail_service_types import (
    MovieDetails,
    MovieRatings,
    MovieSearchResult,
    TorrentDetails,
)
from torrents.interfaces import DownloadResult, TorrentProviderProtocol

logger = logging.getLogger(__name__)


def get_url(path: str = "") -> str:
    return f"https://{RUTRACKER_URL}{path}"


async def _authenticate(credentials: dict[str, str]) -> dict[str, str]:
    username = credentials.get("username")
    password = credentials.get("password")
    async with httpx.AsyncClient() as client:
        url = get_url("/forum/login.php")
        data = {
            "login_username": username,
            "login_password": password,
            "login": "%E2%F5%EE%E4",
        }
        response = await client.post(url, data=data)
        if response.status_code != 302:
            raise RutrackerApiError("Failed to authenticate")
    return {"bb_session": response.cookies.get("bb_session")}


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
    credentials: dict[str, str] | None = None,
) -> list[MovieSearchResult]:
    """Search for torrents on Rutracker."""
    logger.debug(
        "Starting Rutracker search for query '%s' (requested_item=%s, requested_type=%s)",
        query,
        requested_item,
        requested_type,
    )

    raw_items = await _fetch_search_items(query, credentials)
    if not raw_items:
        logger.info("No Rutracker search results found for query '%s'", query)
        return []

    movies: list[MovieSearchResult] = []

    for item in raw_items:
        try:
            result = _build_movie_search_result(item)
        except Exception as exc:
            logger.error(
                "Failed to enrich search result for id %s: %s",
                item.movie_id,
                exc,
            )
            continue
        movies.append(result)

    logger.info("Rutracker search completed: %d results for query '%s'", len(movies), query)
    return movies


async def _fetch_search_items(
    query: str, credentials: dict[str, str] | None = None
) -> list[_RawSearchItem]:
    """Fetch search results from Rutracker."""
    html = await _get_search_text(query, credentials)
    return _parse_search_results(html)


async def _get_search_text(
    query: str, credentials: dict[str, str] | None = None
) -> str:
    """Get HTML content from Rutracker search page."""
    cookies = {}
    if credentials:
        try:
            auth_cookies = await _authenticate(credentials)
            cookies.update(auth_cookies)
        except Exception as e:
            logger.warning(
                "Failed to authenticate with Rutracker, trying guest search: %s", e
            )

    url = get_url("/forum/tracker.php")
    params = {"nm": query}

    try:
        async with httpx.AsyncClient(cookies=cookies, follow_redirects=True) as client:
            response = await client.post(url, params=params)
            response.raise_for_status()
            # Rutracker typically uses cp1251 encoding
            return response.text
    except httpx.HTTPError as exc:
        error_message = f"HTTP error while requesting {url}: {exc}"
        logger.error(error_message)
        raise RutrackerApiError(error_message) from exc


def _parse_search_results(html: str) -> list[_RawSearchItem]:
    """Parse Rutracker search results HTML."""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", id="tor-tbl")
    if not table:
        logger.debug("No torrent table found in Rutracker response")
        return []

    results: list[_RawSearchItem] = []
    rows = table.find_all("tr", class_="hl-tr")

    for row in rows:
        try:
            movie_id = row.get("data-topic_id")
            if not movie_id:
                continue

            # Title is in div.t-title -> a.tLink
            title_div = row.find("div", class_="t-title")
            if not title_div:
                continue

            title_link = title_div.find("a", class_="tLink")
            if not title_link:
                continue

            title = title_link.get_text(strip=True)

            # Size is in td.tor-size
            size_cell = row.find("td", class_="tor-size")
            size = size_cell.get_text(strip=True) if size_cell else "N/A"
            # Cleanup size text (remove arrow symbols)
            size = size.replace("↓", "").replace("↑", "").strip()

            # Seeds - try to find by class seedmed, or by cell index
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

            # Peers - try to find by class leechmed, or by cell index
            peers_cell = row.find("td", class_="leechmed")
            if not peers_cell:
                cells = row.find_all("td")
                if len(cells) > 7:
                    peers_cell = cells[7]

            peers = None
            if peers_cell:
                try:
                    peers = int(peers_cell.get_text(strip=True))
                except (ValueError, AttributeError):
                    pass

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
            logger.error("Error parsing Rutracker search row: %s", exc)
            continue

    logger.debug("Parsed %d Rutracker search results", len(results))
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
    )


class RutrackerTorrentProvider(TorrentProviderProtocol):
    name = "rutracker"
    max_query_length = None  # No query length limit for Rutracker
    requires_authentication = True

    def __init__(self, *, credentials: dict[str, str] | None = None) -> None:
        self._credentials = credentials or {}

    @property
    def base_url(self) -> str:
        """Return the base URL of the Rutracker tracker."""
        return get_url()

    def get_torrent_url(self, movie_id: int | str) -> str:
        """Get the full URL to the torrent page on Rutracker."""
        return f"{self.base_url}/viewtopic.php?t={movie_id}"

    async def search(
        self,
        query: str,
        *,
        requested_item: str | None = None,
        requested_type: str | None = None,
    ) -> list[MovieSearchResult]:
        """Search for torrents on Rutracker."""
        return await _search_movies(
            query,
            requested_item=requested_item,
            requested_type=requested_type,
            credentials=self._credentials,
        )

    async def get_movie_detail(self, movie_id: int | str) -> MovieDetails:
        """Get detailed information about a torrent from Rutracker.
        
        TODO: Implement HTML parsing for Rutracker torrent details page.
        """
        raise NotImplementedError(
            "Rutracker torrent detail parsing is not yet implemented. "
            "HTML parsing needs to be added."
        )

    async def download_movie(self, movie_id: int | str) -> DownloadResult:
        """Download torrent file from Rutracker.
        
        TODO: Implement torrent file download from Rutracker.
        """
        raise NotImplementedError(
            "Rutracker torrent download is not yet implemented. "
            "Download functionality needs to be added."
        )
