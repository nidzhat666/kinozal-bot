"""Utilities for structured logging with context."""
from __future__ import annotations

import contextlib
import inspect
import time
from typing import Any, Callable, TypeVar

import structlog

F = TypeVar("F", bound=Callable[..., Any])


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Get a structured logger instance.
    
    Args:
        name: Logger name (usually __name__). If None, uses calling module.
    
    Returns:
        Bound logger instance with structlog.
    """
    if name is None:
        # Get the calling module name
        frame = inspect.currentframe()
        if frame and frame.f_back:
            name = frame.f_back.f_globals.get("__name__", "unknown")
    return structlog.get_logger(name)


def get_provider_logger(provider_name: str) -> structlog.stdlib.BoundLogger:
    """Get a logger for torrent providers with pre-configured context.
    
    Args:
        provider_name: Name of the provider (e.g., "kinozal", "rutracker").
    
    Returns:
        Bound logger with component="torrent_provider" and provider set.
    """
    # Get the calling module name for proper logger name
    frame = inspect.currentframe()
    caller_name = "torrents.providers.unknown"
    if frame and frame.f_back:
        caller_name = frame.f_back.f_globals.get("__name__", caller_name)
    
    return structlog.get_logger(caller_name).bind(
        component="torrent_provider",
        provider=provider_name,
    )


def get_handler_logger(handler_name: str) -> structlog.stdlib.BoundLogger:
    """Get a logger for handlers with pre-configured context.
    
    Args:
        handler_name: Name of the handler.
    
    Returns:
        Bound logger with component="handler" and operation set.
    """
    # Get the calling module name for proper logger name
    frame = inspect.currentframe()
    caller_name = "handlers.unknown"
    if frame and frame.f_back:
        caller_name = frame.f_back.f_globals.get("__name__", caller_name)
    
    return structlog.get_logger(caller_name).bind(
        component="handler",
        operation=handler_name,
    )


def get_service_logger(service_name: str) -> structlog.stdlib.BoundLogger:
    """Get a logger for services with pre-configured context.
    
    Args:
        service_name: Name of the service (e.g., "qbt", "plex").
    
    Returns:
        Bound logger with component="service" and service_name set.
    """
    # Get the calling module name for proper logger name
    frame = inspect.currentframe()
    caller_name = "services.unknown"
    if frame and frame.f_back:
        caller_name = frame.f_back.f_globals.get("__name__", caller_name)
    
    return structlog.get_logger(caller_name).bind(
        component="service",
        service_name=service_name,
    )


@contextlib.contextmanager
def log_operation(
    logger: structlog.stdlib.BoundLogger,
    operation: str,
    **context: Any,
):
    """Context manager for logging operation start and completion with duration.
    
    Usage:
        with log_operation(logger, "search", query="test"):
            # operation code
            result = do_search()
    
    Args:
        logger: Structlog logger instance.
        operation: Operation name.
        **context: Additional context fields to include.
    """
    start_time = time.perf_counter()
    op_logger = logger.bind(operation=operation, **context)
    op_logger.info(f"{operation}_start")
    
    try:
        yield op_logger
        duration_ms = int((time.perf_counter() - start_time) * 1000)
        op_logger.info(
            f"{operation}_completed",
            duration_ms=duration_ms,
        )
    except Exception as exc:
        duration_ms = int((time.perf_counter() - start_time) * 1000)
        error_type = type(exc).__name__
        op_logger.error(
            f"{operation}_failed",
            duration_ms=duration_ms,
            error_type=error_type,
            error_message=str(exc),
            exc_info=True,
        )
        raise


def log_duration(func: F) -> F:
    """Decorator to automatically log function duration.
    
    Usage:
        @log_duration
        def my_function():
            # function code
    """
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        logger = structlog.get_logger(func.__module__)
        func_name = func.__name__
        start_time = time.perf_counter()
        
        logger = logger.bind(operation=func_name)
        logger.debug(f"{func_name}_start")
        
        try:
            result = func(*args, **kwargs)
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            logger.debug(
                f"{func_name}_completed",
                duration_ms=duration_ms,
            )
            return result
        except Exception as exc:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            error_type = type(exc).__name__
            logger.error(
                f"{func_name}_failed",
                duration_ms=duration_ms,
                error_type=error_type,
                error_message=str(exc),
                exc_info=True,
            )
            raise
    
    return wrapper  # type: ignore[return-value]

