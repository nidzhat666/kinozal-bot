import logging
import sys

import structlog
from structlog.processors import JSONRenderer, TimeStamper
from structlog.stdlib import LoggerFactory

from bot.config import LOG_FORMAT, LOG_LEVEL, LOG_DEV_MODE


def setup_logging() -> None:
    """Configures structured logging for the application with JSON output for Grafana."""
    # Convert string log level to logging constant
    log_level = getattr(logging, LOG_LEVEL, logging.INFO)
    
    # Configure standard library logging
    logging.basicConfig(
        level=log_level,
        stream=sys.stdout,
        format="%(message)s",  # structlog will handle formatting
    )
    
    # Configure structlog processors
    processors: list = [
        structlog.contextvars.merge_contextvars,  # Merge context variables
        structlog.stdlib.add_log_level,  # Add log level
        structlog.stdlib.add_logger_name,  # Add logger name
        structlog.stdlib.ExtraAdder(),  # Add extra fields
        TimeStamper(fmt="iso"),  # ISO 8601 timestamp
    ]
    
    # Choose renderer based on format
    if LOG_FORMAT == "json" or not LOG_DEV_MODE:
        # JSON format for production/Grafana
        processors.append(JSONRenderer())
    else:
        # Console format for development
        processors.append(structlog.dev.ConsoleRenderer())
    
    # Configure structlog
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    
    # Set specific log levels for third-party libraries to reduce noise
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)
    logging.getLogger("aiogram").setLevel(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)  # Reduce HTTP noise
