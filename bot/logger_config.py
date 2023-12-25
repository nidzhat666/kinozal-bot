import logging
from logging.handlers import HTTPHandler

from pythonjsonlogger import jsonlogger

from config import LOGGLY_TOKEN


def setup_logging(tags="undefined"):
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)
    loggly_token = LOGGLY_TOKEN
    loggly_host = "logs-01.loggly.com"
    loggly_path = f"/inputs/{loggly_token}/tag/python"

    log_handler = HTTPHandler(
        host=loggly_host,
        url=loggly_path,
        method="POST",
    )
    formatter = jsonlogger.JsonFormatter()
    log_handler.setFormatter(formatter)
    logger.addHandler(log_handler)
    return logger
