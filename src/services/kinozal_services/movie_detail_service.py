import logging

import aiohttp
from bs4 import BeautifulSoup

from services.exceptions import KinozalApiError
from custom_types.movie_detail_service_types import (
    MovieDetails,
    MovieRatings,
    TorrentDetails,
)
from utilities.kinozal_utils import get_url

logger = logging.getLogger(__name__)


class MovieDetailService:
    def __init__(self):
        self.base_url = get_url("/details.php")

    async def get_movie_detail(self, movie_id: int | str) -> MovieDetails:
        params = {"id": movie_id}
        response_text = await self._fetch_movie_data(params)
        movie = self._parse_movie_details(response_text)
        logger.debug(f"Retrieved movie details: {movie}")
        return movie

    async def _fetch_movie_data(self, params) -> str:
        async with aiohttp.ClientSession() as session:
            try:
                response = await session.get(self.base_url, params=params)
                response.raise_for_status()
                return await response.text()
            except aiohttp.ClientError as e:
                error_message = f"HTTP client error during movie retrieve: {e}"
                logger.error(error_message)
                raise KinozalApiError(error_message)

    @staticmethod
    def _parse_movie_details(html_text) -> MovieDetails:
        try:
            soup = BeautifulSoup(html_text, features="html.parser")
            return MovieDetailParser.parse(soup)
        except Exception as e:
            error_message = f"Error parsing movie detail results: {e}"
            logger.error(error_message)
            raise KinozalApiError(error_message)


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
        except Exception as e:
            error_message = f"Error parsing movie detail results: {e}"
            logger.error(error_message)
            raise KinozalApiError(error_message)

    @staticmethod
    def _parse_name(soup) -> str:
        return soup.find("h1").find("a").text

    @staticmethod
    def _parse_year(soup) -> str:
        year_tag = soup.find(lambda tag: tag.name == "b" and "Год выпуска:" in tag.text)
        return year_tag.next_sibling.strip() if year_tag else ""

    @staticmethod
    def _parse_genres(soup) -> list[str]:
        genre_tag = soup.find(lambda tag: tag.name == "b" and "Жанр:" in tag.text)
        result = genre_tag.find_next_sibling("span").text.split(", ")
        logger.debug(f"Retrieved genres: {result}")
        return result

    @staticmethod
    def _parse_director(soup) -> str:
        director_tag = soup.find(lambda tag: tag.name == "b" and "Режиссер:" in tag.text)
        return director_tag.find_next_sibling("span").get_text(strip=True) if director_tag else ""

    @staticmethod
    def _parse_actors(soup) -> list[str]:
        actors_tag = soup.find(lambda tag: tag.name == "b" and "В ролях:" in tag.text)
        result = actors_tag.find_next_sibling("span").text.split(", ")
        logger.debug(f"Retrieved actors: {result}")
        return result

    @staticmethod
    def _parse_image_url(soup) -> str:
        image_tag = soup.find("img", class_="p200")
        return get_url(image_tag["src"]) if image_tag else ""

    @staticmethod
    def _parse_ratings(soup) -> MovieRatings:
        imdb_rating = soup.find("a", href=lambda href: href and "imdb.com" in href)
        if imdb_rating:
            imdb_rating = imdb_rating.find("span").text
        else:
            imdb_rating = "-"

        kinopoisk_rating = soup.find("a", href=lambda href: href and "kinopoisk.ru" in href)
        if kinopoisk_rating:
            kinopoisk_rating = kinopoisk_rating.find("span").text
        else:
            kinopoisk_rating = "-"

        return MovieRatings(imdb=imdb_rating, kinopoisk=kinopoisk_rating)

    @staticmethod
    def _parse_torrent_details(soup) -> list[TorrentDetails]:
        video_details: list[TorrentDetails] = []
        tab_div = soup.find('div', {'id': 'tabs'})
        if not tab_div:
            return video_details

        for b_tag in tab_div.find_all('b'):
            key = b_tag.get_text(strip=True)
            value_node = b_tag.next_sibling
            if value_node is None:
                value_text = None
            elif hasattr(value_node, 'get_text'):
                value_text = value_node.get_text(strip=True)
            else:
                value_text = str(value_node).strip()

            if value_text == "":
                value_text = None

            video_details.append(TorrentDetails(key=key, value=value_text))

        return video_details
