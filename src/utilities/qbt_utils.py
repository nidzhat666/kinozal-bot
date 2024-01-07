from bot.config import QBT_HOST, QBT_PORT


def get_url(path: str = "") -> str:
    return f"{QBT_HOST}:{QBT_PORT}{path}"
