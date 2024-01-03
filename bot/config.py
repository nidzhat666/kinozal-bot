import os

from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
BOT_SERVER_PORT = os.getenv("BOT_SERVER_PORT")
LOGGLY_TOKEN = os.getenv("LOGGLY_TOKEN")
KINOZAL_CREDENTIALS = dict(username=os.getenv("KINOZAL_USERNAME"),
                           password=os.getenv("KINOZAL_PASSWORD"))
KINOZAL_URL = "kinozal.tv"
QBT_CREDENTIALS = dict(username=os.getenv("QBT_USERNAME"),
                       password=os.getenv("QBT_PASSWORD"))
QBT_HOST = os.getenv("QBT_HOST")
QBT_PORT = os.getenv("QBT_PORT")
LOCAL_BUILD = os.getenv("LOCAL_BUILD", 0)
