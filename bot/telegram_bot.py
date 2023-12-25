import httpx

from config import TELEGRAM_BOT_TOKEN

TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/"


def setup_telegram_bot():
    pass


async def send_message(chat_id: int, text: str):
    async with httpx.AsyncClient() as client:
        payload = {"chat_id": chat_id, "text": text}
        await client.post(TELEGRAM_API_URL + "sendMessage", json=payload)


async def handle_command(update):
    message = update.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "")

    if text.startswith("/search"):
        await search_movies(chat_id, text)


async def search_movies(chat_id: int, query: str):
    pass
