from config import KINOZAL_URL


def get_url(path: str) -> str:
    return "https://" + KINOZAL_URL + path
