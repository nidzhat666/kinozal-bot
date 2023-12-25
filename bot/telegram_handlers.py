from bot.commands.search_command import handle_search_command


async def process_update(update: dict):
    if 'message' in update and 'text' in update['message']:
        message = update['message']
        chat_id = message['chat']['id']
        text = message['text']

        if text.startswith('/search'):
            query = text[len('/search '):]
            response_text = await handle_search_command(chat_id, query)
            await send_message(chat_id, response_text)


async def send_message(chat_id: int, text: str):
    pass
