import logging

import aiohttp
from bs4 import BeautifulSoup

from services.exceptions import KinozalApiError
from custom_types.movie_detail_service_types import MovieDetails
from utilities.kinozal_utils import get_url

logger = logging.getLogger(__name__)


class MovieDetailService:
    def __init__(self, auth_cookies):
        self.auth_cookies = auth_cookies
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
                response = await session.get(self.base_url, params=params, cookies=self.auth_cookies)
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
    def parse(cls, soup: BeautifulSoup) -> dict:
        try:
            return {
                "name": cls._parse_name(soup),
                "year": cls._parse_year(soup),
                "genres": cls._parse_genres(soup),
                "director": cls._parse_director(soup),
                "actors": cls._parse_actors(soup),
                "image_url": cls._parse_image_url(soup),
                "ratings": cls._parse_ratings(soup),
                "torrent_details": cls._parse_torrent_details(soup),
            }
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
    def _parse_genres(soup) -> list:
        genre_tag = soup.find(lambda tag: tag.name == "b" and "Жанр:" in tag.text)
        result = genre_tag.find_next_sibling("span").text.split(", ")
        logger.debug(f"Retrieved genres: {result}")
        return result

    @staticmethod
    def _parse_director(soup) -> str:
        director_tag = soup.find(lambda tag: tag.name == "b" and "Режиссер:" in tag.text)
        return director_tag.find_next_sibling("span").get_text(strip=True) if director_tag else ""

    @staticmethod
    def _parse_actors(soup) -> list:
        actors_tag = soup.find(lambda tag: tag.name == "b" and "В ролях:" in tag.text)
        return [a.text for a in actors_tag.find_next_siblings("span")[0].find_all("a")] if actors_tag else []

    @staticmethod
    def _parse_image_url(soup) -> str:
        image_tag = soup.find("img", class_="p200")
        return get_url(image_tag["src"]) if image_tag else ""

    @staticmethod
    def _parse_ratings(soup) -> dict:
        imdb_rating = soup.find("a", href=lambda href: href and "imdb.com" in href).find("span")

        kinopoisk_rating = soup.find_all("a", href=lambda href: href and "kinopoisk.ru" in href)[1].find("span")
        return (dict(imdb=imdb_rating.text, kinopoisk=kinopoisk_rating.text)
                if imdb_rating and kinopoisk_rating else {})

    @staticmethod
    def _parse_torrent_details(soup) -> list[tuple]:
        video_details = []
        for b_tag in soup.find_all('b'):
            key = b_tag.get_text(strip=True).rstrip(':')
            value = b_tag.next_sibling.strip() if b_tag.next_sibling else None
            video_details.append((key, value))
        return video_details
