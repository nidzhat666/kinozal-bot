class KinozalApiError(Exception):
    """Custom exception for search errors"""


class RutrackerApiError(Exception):
    """Custom exception for search errors"""


class TmdbApiError(Exception):
    pass


class NoResultsFoundError(Exception):
    pass


__all__ = [
    "KinozalApiError",
    "NoResultsFoundError",
    "RutrackerApiError",
    "TmdbApiError",
]
