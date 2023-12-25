from unittest import TestCase

from bot.logger_config import setup_logging


class LoggingTestCase(TestCase):
    def test_logging(self):
        logger = setup_logging()
        logger.info("Hello world")
        self.assertTrue(logger)
