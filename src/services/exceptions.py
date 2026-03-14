class KinozalApiError(Exception):
    """Custom exception for search errors"""

    pass


class RutrackerApiError(Exception):
    """Custom exception for search errors"""

    pass


class TmdbApiError(Exception):
    pass


class NoResultsFoundError(Exception):
    pass


__all__ = [
    "KinozalApiError",
    "RutrackerApiError",
    "TmdbApiError",
    "NoResultsFoundError",
]
