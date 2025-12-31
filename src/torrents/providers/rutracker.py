from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path

import bleach
import httpx
from bs4 import BeautifulSoup

from bot.config import RUTRACKER_URL
from services.exceptions import RutrackerApiError
from models.movie_detail_service_types import (
    MovieDetails,
    MovieRatings,
    MovieSearchResult,
)
from torrents.interfaces import DownloadResult, TorrentProviderProtocol

logger = logging.getLogger(__name__)


def get_url(path: str = "") -> str:
    return f"https://{RUTRACKER_URL}{path}"


async def _build_auth_cookies(credentials: dict[str, str] | None) -> dict[str, str]:
    if not credentials:
        return {}

    try:
        return await _authenticate(credentials)
    except Exception as exc:
        logger.warning("[rutracker] Failed to authenticate, using guest access: %s", exc)
        return {}


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
    query: str, *, credentials: dict[str, str] | None = None
) -> list[MovieSearchResult]:
    """Search for torrents on Rutracker."""
    provider_name = "rutracker"
    logger.debug("[%s] Starting search for query '%s'", provider_name, query)

    raw_items = await _fetch_search_items(query, credentials)
    if not raw_items:
        logger.info("[%s] No raw search results found for query '%s'", provider_name, query)
        return []

    logger.info("[%s] Found %d raw search results for query '%s'", provider_name, len(raw_items), query)

    movies: list[MovieSearchResult] = []

    for item in raw_items:
        try:
            result = _build_movie_search_result(item)
        except Exception as exc:
            logger.error(
                "[%s] Failed to enrich search result for id %s: %s",
                provider_name,
                item.movie_id,
                exc,
            )
            continue
        movies.append(result)

    logger.info("[%s] Successfully processed %d results for query '%s'", provider_name, len(movies), query)
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
    cookies = await _build_auth_cookies(credentials)
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
        logger.error("[rutracker] %s", error_message)
        raise RutrackerApiError(error_message) from exc


async def _fetch_torrent_page(
    movie_id: int | str, credentials: dict[str, str] | None = None
) -> str:
    """Get HTML content from Rutracker torrent page."""
    cookies = await _build_auth_cookies(credentials)
    url = get_url(f"/forum/viewtopic.php?t={movie_id}")

    try:
        async with httpx.AsyncClient(cookies=cookies, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
            # Rutracker typically uses cp1251 encoding
            return response.text
    except httpx.HTTPError as exc:
        error_message = f"HTTP error while requesting {url}: {exc}"
        logger.error("[rutracker] %s", error_message)
        raise RutrackerApiError(error_message) from exc


async def _download_movie(
    movie_id: int | str,
    credentials: dict[str, str] | None = None,
) -> DownloadResult:
    """Download torrent file from Rutracker."""
    logger.debug("[rutracker] Downloading torrent for movie id %s", movie_id)
    cookies = await _build_auth_cookies(credentials)
    url = get_url(f"/forum/dl.php?t={movie_id}")

    try:
        async with httpx.AsyncClient(cookies=cookies, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
            
            # Check if we got a torrent file (should start with 'd8:announce' for bencoded torrent)
            # or if we got redirected to an error page
            content_type = response.headers.get("content-type", "").lower()
            if "text/html" in content_type:
                # Likely an error page or login required
                raise RutrackerApiError(
                    f"Failed to download torrent {movie_id}: received HTML instead of torrent file. "
                    "This may indicate authentication is required or the torrent is not available."
                )
            
            payload = response.content
    except httpx.HTTPError as exc:
        error_message = (
            f"HTTP error while downloading Rutracker movie {movie_id}: {exc}"
        )
        logger.error("[rutracker] %s", error_message)
        raise RutrackerApiError(error_message) from exc

    # Validate that we got a torrent file
    if not payload or len(payload) < 10:
        raise RutrackerApiError(
            f"Invalid torrent file received for movie {movie_id}: file is too small or empty"
        )

    # Save torrent file to temporary directory
    target = Path(tempfile.gettempdir()) / f"rutracker_{movie_id}.torrent"
    target.write_bytes(payload)

    logger.info("[rutracker] Torrent file for movie %s saved to %s", movie_id, target)
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
    post_body = soup.find("div", class_="post_body")
    if not post_body:
        logger.warning("[rutracker] post_body element not found on page")
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
        "a", "b", "strong", "i", "em", "s", "strike", "del", "u", "ins",
        "span", "tg-spoiler", "pre", "code", "details", "summary",
        "br", "hr", "wbr", "ul", "ol", "li", "div", "p", "q", "blockquote",
        "h1", "h2", "h3", "h4", "h5", "h6", "noscript", "cite", "var",
        "progress", "meter", "kbd", "samp", "img", "tt", "input",
        "footer", "header", "main", "nav", "section", "html", "body",
        "output", "data", "time"
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
        logger.warning("[rutracker] Failed to process HTML structure: %s", exc)
        return cleaned_html


def _parse_search_results(html: str) -> list[_RawSearchItem]:
    """Parse Rutracker search results HTML."""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", id="tor-tbl")
    if not table:
        logger.debug("[rutracker] No torrent table found in response")
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
            logger.error("[rutracker] Error parsing search row: %s", exc)
            continue

    logger.debug("[rutracker] Parsed %d search results", len(results))
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

    @property
    def base_url(self) -> str:
        """Return the base URL of the Rutracker tracker."""
        return get_url()

    def get_torrent_url(self, movie_id: int | str) -> str:
        """Get the full URL to the torrent page on Rutracker."""
        return f"{self.base_url}/forum/viewtopic.php?t={movie_id}"

    async def search(
        self,
        query: str,
        *,
        requested_item: str | None = None,
        requested_type: str | None = None,
    ) -> list[MovieSearchResult]:
        """Search for torrents on Rutracker."""
        return await _search_movies(query, credentials=self._credentials)

    async def get_movie_detail(self, movie_id: int | str) -> MovieDetails:
        """Get detailed information about a torrent from Rutracker."""
        logger.debug("[rutracker] Fetching movie details for id %s", movie_id)
        
        try:
            # Fetch the torrent page HTML
            html = await _fetch_torrent_page(movie_id, self._credentials)
            
            # Parse with BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")
            
            # Extract post_body HTML
            post_body_html = _extract_post_body_html(soup)
            
            # Clean and convert HTML
            cleaned_html = None
            if post_body_html:
                cleaned_html = _clean_and_convert_html(post_body_html)
            
            # Try to extract title from page
            title = ""
            title_tag = soup.find("h1")
            if title_tag:
                title_link = title_tag.find("a")
                if title_link:
                    title = title_link.get_text(strip=True)
                else:
                    title = title_tag.get_text(strip=True)
            
            # Create MovieDetails with HTML content
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
            error_message = f"Error fetching Rutracker movie detail for id {movie_id}: {exc}"
            logger.error("[rutracker] %s", error_message, exc_info=True)
            raise RutrackerApiError(error_message) from exc

    async def download_movie(self, movie_id: int | str) -> DownloadResult:
        """Download torrent file from Rutracker."""
        return await _download_movie(movie_id, self._credentials)
