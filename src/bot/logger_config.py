import logging
import sys

import coloredlogs


def setup_logging():
    coloredlogs.install(logging.DEBUG)
    logging.basicConfig(level=logging.DEBUG, stream=sys.stdout)
