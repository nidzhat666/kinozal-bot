import logging
import sys

import structlog
from structlog.processors import JSONRenderer, TimeStamper
from structlog.stdlib import LoggerFactory, ProcessorFormatter

from bot.config import LOG_DEV_MODE, LOG_FORMAT, LOG_LEVEL


def setup_logging() -> None:
    """Configures structured logging for the application with JSON output for Grafana."""
    # Convert string log level to logging constant
    log_level = getattr(logging, LOG_LEVEL, logging.INFO)

    # Configure structlog processors
    shared_processors: list = [
        structlog.contextvars.merge_contextvars,  # Merge context variables
        structlog.stdlib.add_log_level,  # Add log level
        structlog.stdlib.add_logger_name,  # Add logger name
        structlog.stdlib.ExtraAdder(),  # Add extra fields
        TimeStamper(fmt="iso"),  # ISO 8601 timestamp
    ]

    # Choose renderer based on format
    if LOG_FORMAT == "json" or not LOG_DEV_MODE:
        # JSON format for production/Grafana
        renderer = JSONRenderer()
    else:
        # Console format for development
        renderer = structlog.dev.ConsoleRenderer()

    # Configure structlog
    structlog.configure(
        processors=[
            *shared_processors,
            # Prepare for formatting by logging module
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        cache_logger_on_first_use=True,
    )

    # Configure standard library logging to use structlog's ProcessorFormatter
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        ProcessorFormatter(
            # These run on all logs (structlog and stdlib)
            processor=renderer,
            # These run ONLY on stdlib logs (to add context)
            foreign_pre_chain=shared_processors,
        )
    )

    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(log_level)

    # Set specific log levels for third-party libraries to reduce noise
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)
    logging.getLogger("aiogram").setLevel(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)  # Reduce HTTP noise
    # Suppress verbose httpcore logs
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("httpcore.http11").setLevel(logging.WARNING)
    logging.getLogger("httpcore.http2").setLevel(logging.WARNING)
    logging.getLogger("httpcore.connection").setLevel(logging.WARNING)
