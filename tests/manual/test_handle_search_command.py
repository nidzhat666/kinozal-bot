import logging
from unittest import IsolatedAsyncioTestCase

from bot.commands.search_command import handle_search_command

logging.basicConfig(level=logging.INFO, handlers=[logging.StreamHandler()])


class SearchCommandHandlerTestCase(IsolatedAsyncioTestCase):

    async def test_handle_search_command(self):
        result = await handle_search_command(None, "Во все тяжкие")
        pass
