from contextlib import asynccontextmanager

from fastapi import FastAPI, Response, status
import uvicorn

from bot.logger_config import setup_logging
from bot.telegram_bot import setup_telegram_bot
from bot.telegram_handlers import process_update
from config import BOT_SERVER_PORT

logger = setup_logging()


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    setup_telegram_bot()
    yield


app = FastAPI(lifespan=app_lifespan)


@app.post("/webhook")
async def handle_webhook(update: dict):
    await process_update(update)
    return Response(status_code=status.HTTP_200_OK)


if __name__ == "__main__":
    uvicorn.run(app, host="localhost", port=BOT_SERVER_PORT)
