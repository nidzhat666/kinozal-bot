class KinozalApiError(Exception):
    """Custom exception for search errors"""
    pass

class RutrackerApiError(Exception):
    """Custom exception for search errors"""
    pass

class KinopoiskApiError(Exception):
    """Custom exception for Kinopoisk API errors"""
    pass


class TmdbApiError(Exception):
    pass


class NoResultsFoundError(Exception):
    pass


__all__ = ["KinozalApiError", "RutrackerApiError", "KinopoiskApiError", "TmdbApiError", "NoResultsFoundError"]


