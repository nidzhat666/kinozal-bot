import aiohttp
from bs4 import BeautifulSoup
from services.exceptions import KinozalApiError
from utilities.kinozal_utils import get_url
import logging

logger = logging.getLogger(__name__)


class MovieSearchService:

    async def search(self, query: str, quality: str | int) -> list[dict]:
        """
        Search for movies based on a query string.

        Args:
            query (str): The search query.

        Returns:
            list[dict]: A list of dictionaries containing movie search results.

        Raises:
            KinozalApiError: If the search request or parsing fails.
            :param query: Movie search query.
            :param quality: Quality of the movie.
        """
        url = get_url("/browse.php")
        params = {"s": query, "v": quality, "t": 1, "g": 3}
        logger.debug(f"Initiating search for query: {query}")

        try:
            async with aiohttp.ClientSession() as session:
                return await self._fetch_and_parse(session, url, params)
        except aiohttp.ClientError as e:
            error_message = f"HTTP client error during search: {e}"
            logger.error(error_message)
            raise KinozalApiError(error_message)
        except Exception as e:
            error_message = f"Unexpected error during search: {e}"
            logger.error(error_message)
            raise KinozalApiError(error_message)

    async def _fetch_and_parse(self, session, url, params) -> list[dict]:
        """
        Fetch search results from the URL and parse them.

        Args:
            session (aiohttp.ClientSession): The HTTP session.
            url (str): The URL to fetch.
            params (dict): The query parameters.

        Returns:
            list[dict]: Parsed search results.

        Raises:
            KinozalApiError: If the response status is not 200.
        """
        async with session.get(url, params=params) as response:
            logger.debug(f"Request URL: {response.url}")
            if response.status != 200:
                error_message = f"Search request failed with status code: {response.status}"
                logger.error(error_message)
                raise KinozalApiError(error_message)

            response_text = await response.text()
            return self._parse_search_results(response_text)

    @staticmethod
    def _parse_search_results(text) -> list[dict]:
        """
        Parse the HTML search results into a list of dictionaries.

        Args:
            text (str): The HTML text to parse.

        Returns:
            list[dict]: The parsed search results.

        Raises:
            KinozalApiError: If there is an error during parsing.
        """
        try:
            soup = BeautifulSoup(text, features="html.parser")
            results_list = soup.find_all("tr", class_="bg")
            result = []

            for el in results_list:
                name = el.find("td", class_="nam")
                if name is None:
                    continue
                size = el.find_all("td", class_="s")[1]
                id_ = name.find("a").get("href").split("=")[-1]
                result.append(dict(name=name.find("a").text, size=size.text, id=id_))

            logger.debug(f"Found results: {len(result)} items")
            return result
        except Exception as e:
            error_message = f"Error parsing search results: {e}"
            logger.error(error_message)
            raise KinozalApiError(error_message)
