import os

from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
BOT_SERVER_PORT = os.getenv("BOT_SERVER_PORT")
KINOZAL_CREDENTIALS = dict(username=os.getenv("KINOZAL_USERNAME"),
                           password=os.getenv("KINOZAL_PASSWORD"))
RUTRACKER_CREDENTIALS = dict(
    username=os.getenv("RUTRACKER_USERNAME"), password=os.getenv("RUTRACKER_PASSWORD")
)
KINOZAL_URL = "kinozal.tv"
RUTRACKER_URL = "rutracker.org"

QBT_CREDENTIALS = dict(username=os.getenv("QBT_USERNAME"),
                       password=os.getenv("QBT_PASSWORD"))
QBT_HOST = os.getenv("QBT_HOST")
QBT_PORT = os.getenv("QBT_PORT")
LOCAL_BUILD = os.getenv("LOCAL_BUILD", 0)

REDIS_HOST = os.getenv("REDIS_HOST")
REDIS_PORT = os.getenv("REDIS_PORT")
REDIS_DB = os.getenv("REDIS_DB")

PLEX_URL = os.getenv("PLEX_URL")
PLEX_TOKEN = os.getenv("PLEX_TOKEN")

GROQ_API_KEY = os.getenv("GROQ_API_KEY")

KINOPOISK_API_URL = os.getenv("KINOPOISK_API_URL", "https://api.poiskkino.dev/v1.4")
KINOPOISK_API_KEY = os.getenv("KINOPOISK_API_KEY")
KINOPOISK_SEARCH_LIMIT = int(os.getenv("KINOPOISK_SEARCH_LIMIT", 10))

TMDB_API_URL = os.getenv("TMDB_API_URL", "https://api.themoviedb.org/3")
TMDB_API_TOKEN = os.getenv("TMDB_API_TOKEN")

SEARCH_PROVIDER = os.getenv("SEARCH_PROVIDER", "tmdb").lower()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "..", "templates")