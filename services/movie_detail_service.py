import asyncio
import logging
from typing import List

import aiohttp
from bs4 import BeautifulSoup

from services.exceptions import KinozalApiError
from utilities.kinozal_utils import get_url

logger = logging.getLogger(__name__)


class MovieDetailService:
    url = get_url("/details.php")

    def __init__(self, auth_cookies):
        self.auth_cookies = auth_cookies

    async def get_movie_detail(self, movie_id: [int, str]) -> dict:
        params = {"id": movie_id}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.url, params=params,
                                       cookies=self.auth_cookies) as response:
                    if response.status != 200:
                        error_message = f"Movie retrieve request failed with status code: {response.status}"
                        logger.error(error_message)
                        raise KinozalApiError(error_message)
                    return self.parse_search_results(await response.text())
        except aiohttp.ClientError as e:
            error_message = f"HTTP client error during movie retrieve: {e}"
            logger.error(error_message)
            raise KinozalApiError(error_message)
        except Exception as e:
            error_message = f"Unexpected error during movie retrieve: {e}"
            logger.error(error_message)
            raise KinozalApiError(error_message)

    @staticmethod
    def parse_search_results(text) -> dict:
        try:
            soup = BeautifulSoup(text, features="html.parser")
            name = soup.find("h1").find("a").text

            year_tag = soup.find(lambda tag: tag.name == "b" and "Год выпуска:" in tag.text)
            year = ""
            if year_tag:
                year = year_tag.next_sibling

            # Finding and extracting genres
            genre_tag = soup.find(lambda tag: tag.name == "b" and "Жанр:" in tag.text)
            genres = [a.text for a in genre_tag.find_next_siblings('span')[0].find_all('a')] if genre_tag else "Жанры не найдены"

            # Finding and extracting director
            director_tag = soup.find(lambda tag: tag.name == "b" and "Режиссер:" in tag.text)
            director = director_tag.find_next_sibling('span').get_text(strip=True) if director_tag else "Режиссер не найден"

            # Finding and extracting actors
            actors_tag = soup.find(lambda tag: tag.name == "b" and "В ролях:" in tag.text)
            actors = [a.text for a in actors_tag.find_next_siblings('span')[0].find_all('a')] if actors_tag else "Актеры не найдены"

            description_tag = soup.find('div', class_='bx1 justify', recursive=True)
            description = description_tag.find("p").get_text(strip=True) if description_tag else "Описание не найдено"

            image_url = soup.find("img", class_="p200")["src"]

            result = dict(name=name, year=year.strip(), image_url=get_url(image_url),
                          size="", id="", genres=genres, director=director, actors=actors,
                          description=description)
            logger.info(result)
            logger.debug(f"Found results: {result}")
            return result
        except Exception as e:
            error_message = f"Error parsing movie detail results: {e}"
            logger.error(error_message)
            raise KinozalApiError(error_message)
