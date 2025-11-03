from __future__ import annotations

import logging
import tempfile
from multiprocessing import AuthenticationError

import aiofile
import aiohttp
from aiohttp import ClientSession
from bs4 import BeautifulSoup
from yarl import URL

from custom_types.movie_detail_service_types import (
    MovieDetails,
    MovieRatings,
    TorrentDetails,
)
from services.exceptions import KinozalApiError
from torrents.interfaces import (
    DownloadResult,
    SearchResult,
    TorrentAuthServiceProtocol,
    TorrentDetailServiceProtocol,
    TorrentDownloadServiceProtocol,
    TorrentProviderProtocol,
    TorrentSearchServiceProtocol,
)
from utilities import kinozal_utils
from utilities.kinozal_utils import get_url


logger = logging.getLogger(__name__)


class MovieSearchService(TorrentSearchServiceProtocol):
    async def search(self, query: str, quality: str | int) -> list[SearchResult]:
        url = get_url("/browse.php")
        params = {"s": query, "v": quality, "t": 1, "g": 3}
        logger.debug("Initiating search for query: %s", query)

        try:
            async with aiohttp.ClientSession() as session:
                return await self._fetch_and_parse(session, url, params)
        except aiohttp.ClientError as exc:
            error_message = f"HTTP client error during search: {exc}"
            logger.error(error_message)
            raise KinozalApiError(error_message) from exc
        except Exception as exc:  # noqa: BLE001 - re-raise as domain error
            error_message = f"Unexpected error during search: {exc}"
            logger.error(error_message)
            raise KinozalApiError(error_message) from exc

    async def _fetch_and_parse(
        self,
        session: aiohttp.ClientSession,
        url: str,
        params: dict[str, str | int],
    ) -> list[SearchResult]:
        async with session.get(url, params=params) as response:
            logger.debug("Request URL: %s", response.url)
            if response.status != 200:
                error_message = (
                    "Search request failed with status code: %s" % response.status
                )
                logger.error(error_message)
                raise KinozalApiError(error_message)

            response_text = await response.text()
            return self._parse_search_results(response_text)

    @staticmethod
    def _parse_search_results(text: str) -> list[SearchResult]:
        try:
            soup = BeautifulSoup(text, features="html.parser")
            results_list = soup.find_all("tr", class_="bg")
            result: list[SearchResult] = []

            for el in results_list:
                name = el.find("td", class_="nam")
                if name is None:
                    continue
                size_cells = el.find_all("td", class_="s")
                if len(size_cells) < 2:
                    logger.debug("Skipping malformed search result row: %s", el)
                    continue
                size = size_cells[1]
                id_ = name.find("a").get("href").split("=")[-1]
                result.append(
                    SearchResult(name=name.find("a").text, size=size.text, id=id_)
                )

            logger.debug("Found results: %d items", len(result))
            return result
        except Exception as exc:  # noqa: BLE001 - re-raise as domain error
            error_message = f"Error parsing search results: {exc}"
            logger.error(error_message)
            raise KinozalApiError(error_message) from exc


class MovieDownloadService(TorrentDownloadServiceProtocol):
    def __init__(self, movie_id: int | str, auth_cookies: dict[str, str]):
        self.auth_cookies = auth_cookies
        self.movie_id = movie_id
        self.url = get_url(f"/download.php?id={self.movie_id}")

    @property
    def filename(self) -> str:
        return f"{self.movie_id}.torrent"

    @property
    def file_path(self) -> str:
        path = tempfile.gettempdir()
        return f"{path}/{self.filename}"

    async def download_movie(self) -> DownloadResult:
        async with ClientSession(cookies=self.auth_cookies) as session:
            async with session.get(self.url) as response:
                if response.status != 200:
                    raise KinozalApiError(
                        "Failed to download movie with status code: %s"
                        % response.status
                    )
                response_file = await response.read()
                if "pay.php" in str(response_file):
                    raise KinozalApiError(
                        "You are not allowed to download this torrent."
                    )
                async with aiofile.async_open(self.file_path, "wb") as file_handle:
                    await file_handle.write(response_file)
        return DownloadResult(file_path=self.file_path, filename=self.filename)


class MovieDetailService:
    def __init__(self) -> None:
        self.base_url = get_url("/details.php")

    async def get_movie_detail(self, movie_id: int | str) -> MovieDetails:
        params = {"id": movie_id}
        response_text = await self._fetch_movie_data(params)
        movie = self._parse_movie_details(response_text)
        logger.debug("Retrieved movie details: %s", movie)
        return movie

    async def _fetch_movie_data(self, params: dict[str, str | int]) -> str:
        async with aiohttp.ClientSession() as session:
            try:
                response = await session.get(self.base_url, params=params)
                response.raise_for_status()
                return await response.text()
            except aiohttp.ClientError as exc:
                error_message = f"HTTP client error during movie retrieve: {exc}"
                logger.error(error_message)
                raise KinozalApiError(error_message) from exc

    @staticmethod
    def _parse_movie_details(html_text: str) -> MovieDetails:
        try:
            soup = BeautifulSoup(html_text, features="html.parser")
            return MovieDetailParser.parse(soup)
        except Exception as exc:  # noqa: BLE001 - re-raise as domain error
            error_message = f"Error parsing movie detail results: {exc}"
            logger.error(error_message)
            raise KinozalApiError(error_message) from exc


class MovieDetailParser:
    @classmethod
    def parse(cls, soup: BeautifulSoup) -> MovieDetails:
        try:
            return MovieDetails(
                name=cls._parse_name(soup),
                year=cls._parse_year(soup),
                genres=cls._parse_genres(soup),
                director=cls._parse_director(soup),
                actors=cls._parse_actors(soup),
                image_url=cls._parse_image_url(soup),
                ratings=cls._parse_ratings(soup),
                torrent_details=cls._parse_torrent_details(soup),
            )
        except Exception as exc:  # noqa: BLE001 - re-raise as domain error
            error_message = f"Error parsing movie detail results: {exc}"
            logger.error(error_message)
            raise KinozalApiError(error_message) from exc

    @staticmethod
    def _parse_name(soup: BeautifulSoup) -> str:
        return soup.find("h1").find("a").text

    @staticmethod
    def _parse_year(soup: BeautifulSoup) -> str:
        year_tag = soup.find(lambda tag: tag.name == "b" and "Год выпуска:" in tag.text)
        return year_tag.next_sibling.strip() if year_tag else ""

    @staticmethod
    def _parse_genres(soup: BeautifulSoup) -> list[str]:
        genre_tag = soup.find(lambda tag: tag.name == "b" and "Жанр:" in tag.text)
        if not genre_tag:
            return []
        result = genre_tag.find_next_sibling("span").text.split(", ")
        logger.debug("Retrieved genres: %s", result)
        return result

    @staticmethod
    def _parse_director(soup: BeautifulSoup) -> str:
        director_tag = soup.find(lambda tag: tag.name == "b" and "Режиссер:" in tag.text)
        return (
            director_tag.find_next_sibling("span").get_text(strip=True)
            if director_tag
            else ""
        )

    @staticmethod
    def _parse_actors(soup: BeautifulSoup) -> list[str]:
        actors_tag = soup.find(lambda tag: tag.name == "b" and "В ролях:" in tag.text)
        if not actors_tag:
            return []
        result = actors_tag.find_next_sibling("span").text.split(", ")
        logger.debug("Retrieved actors: %s", result)
        return result

    @staticmethod
    def _parse_image_url(soup: BeautifulSoup) -> str:
        image_tag = soup.find("img", class_="p200")
        return get_url(image_tag["src"]) if image_tag else ""

    @staticmethod
    def _parse_ratings(soup: BeautifulSoup) -> MovieRatings:
        imdb_rating = soup.find("a", href=lambda href: href and "imdb.com" in href)
        if imdb_rating:
            imdb_rating = imdb_rating.find("span").text
        else:
            imdb_rating = "-"

        kinopoisk_rating = soup.find(
            "a", href=lambda href: href and "kinopoisk.ru" in href
        )
        if kinopoisk_rating:
            kinopoisk_rating = kinopoisk_rating.find("span").text
        else:
            kinopoisk_rating = "-"

        return MovieRatings(imdb=imdb_rating, kinopoisk=kinopoisk_rating)

    @staticmethod
    def _parse_torrent_details(soup: BeautifulSoup) -> list[TorrentDetails]:
        video_details: list[TorrentDetails] = []
        tab_div = soup.find("div", {"id": "tabs"})
        if not tab_div:
            return video_details

        for b_tag in tab_div.find_all("b"):
            key = b_tag.get_text(strip=True)
            value_node = b_tag.next_sibling
            if value_node is None:
                value_text = None
            elif hasattr(value_node, "get_text"):
                value_text = value_node.get_text(strip=True)
            else:
                value_text = str(value_node).strip()

            if value_text == "":
                value_text = None

            video_details.append(TorrentDetails(key=key, value=value_text))

        return video_details


class KinozalAuthService(TorrentAuthServiceProtocol):
    def __init__(self, username: str, password: str) -> None:
        self.username = username
        self.password = password

    async def authenticate(self) -> dict[str, str]:
        url = kinozal_utils.get_url("/takelogin.php")
        data = {"username": self.username, "password": self.password}
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, data=data, headers=headers) as response:
                    if response.status != 200:
                        error_message = (
                            "Authentication failed with status code: %s"
                            % response.status
                        )
                        logger.error(error_message)
                        raise AuthenticationError(error_message)
                    kinozal_url = URL(kinozal_utils.get_url())
                    cookies = session.cookie_jar.filter_cookies(kinozal_url)
                    uid = cookies["uid"].value
                    pass_ = cookies["pass"].value
                    return {"uid": uid, "pass": pass_}
        except aiohttp.ClientError as exc:
            error_message = f"HTTP client error during authentication: {exc}"
            logger.error(error_message)
            raise AuthenticationError(error_message) from exc
        except Exception as exc:  # noqa: BLE001 - re-raise as auth error
            error_message = f"Unexpected error during authentication: {exc}"
            logger.error(error_message)
            raise AuthenticationError(error_message) from exc


class KinozalTorrentProvider(TorrentProviderProtocol):
    name = "kinozal"

    def __init__(self, *, credentials: dict[str, str] | None = None) -> None:
        self._credentials = credentials or {}

    def get_auth_service(self) -> TorrentAuthServiceProtocol | None:
        if not self._credentials:
            return None
        username = self._credentials.get("username")
        password = self._credentials.get("password")
        if not username or not password:
            return None
        return KinozalAuthService(username=username, password=password)

    def get_search_service(self) -> TorrentSearchServiceProtocol:
        return MovieSearchService()

    def get_detail_service(self) -> TorrentDetailServiceProtocol:
        return MovieDetailService()

    def get_download_service(
        self, movie_id: int | str, auth_data: dict[str, str] | None = None
    ) -> TorrentDownloadServiceProtocol:
        if auth_data is None:
            raise ValueError("Kinozal download service requires auth data.")
        return MovieDownloadService(movie_id, auth_data)


