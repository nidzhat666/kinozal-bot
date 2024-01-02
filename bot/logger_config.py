import json
import logging
import sys
from logging.handlers import HTTPHandler

import coloredlogs

from config import LOGGLY_TOKEN, LOCAL_BUILD


def setup_logging(tags="aiogram_bot"):
    if not LOCAL_BUILD:
        logger = logging.getLogger()
        logger.setLevel(logging.DEBUG)

        logger.handlers.clear()

        loggly_token = LOGGLY_TOKEN
        loggly_host = "logs-01.loggly.com"
        loggly_path = f"/inputs/{loggly_token}/tag/{tags}"
        log_handler = HTTPHandler(host=loggly_host, url=loggly_path, method="POST")
        logger.addHandler(log_handler)

        formatter = logging.Formatter(json.dumps({
            "timestamp": "%(asctime)s",
            "level": "%(levelname)s",
            "message": "%(message)s"
        }))
        log_handler.setFormatter(formatter)

        logger.propagate = False
    else:
        coloredlogs.install(logging.DEBUG)
        logging.basicConfig(level=logging.DEBUG, stream=sys.stdout)
