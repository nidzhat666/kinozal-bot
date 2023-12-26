from config import KINOZAL_URL


def get_url(path: str) -> str:
    return KINOZAL_URL + path
