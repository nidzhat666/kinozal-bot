import os

from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
BOT_SERVER_PORT = os.getenv("BOT_SERVER_PORT")
LOGGLY_TOKEN = os.getenv("LOGGLY_TOKEN")
KINOZAL_CREDENTIALS = dict(username=os.getenv("KINOZAL_USERNAME"),
                           password=os.getenv("KINOZAL_PASSWORD"))
KINOZAL_URL = "kinozal.tv"
