import logging
import sys

import coloredlogs


def setup_logging() -> None:
    """Configures logging for the application with colored output."""
    # Define log format
    log_format = "%(asctime)s %(hostname)s %(name)s[%(process)d] %(levelname)s %(message)s"
    
    # Configure root logger
    logging.basicConfig(
        level=logging.INFO,  # Set default level to INFO
        stream=sys.stdout,
        format=log_format
    )

    # Apply colored logs
    coloredlogs.install(
        level="INFO",
        fmt=log_format,
        stream=sys.stdout,
        isatty=True
    )

    # Set specific log levels for third-party libraries to reduce noise
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)
    logging.getLogger("aiogram").setLevel(logging.INFO)
