import json
import uuid

from services.redis_services.client import redis_client
from utilities.logger_utils import get_logger

logger = get_logger(__name__)


def extract_text_without_command(message_text, command):
    """
    Extracts the text from a message without the command.
    :param message_text: The full text of the message.
    :param command: The command to remove from the message.
    :return: The text without the command.
    """
    command_length = len(command) + 1  # +1 for the '/' in the command
    return message_text[command_length:].strip()


def redis_callback_save(callback_data: dict) -> str:
    op_logger = logger.bind(component="utility", operation="redis_save")
    op_logger.debug("Saving callback data", callback_data=callback_data)
    query_key = str(uuid.uuid4())
    serialized_data = json.dumps(callback_data)

    redis_client.set(query_key, serialized_data, ex=3600)
    return query_key


def redis_callback_get(callback_key: str):
    op_logger = logger.bind(component="utility", operation="redis_get")
    op_logger.debug("Retrieving callback data", callback_key=callback_key)
    serialized_data = redis_client.get(callback_key)
    if serialized_data:
        return json.loads(serialized_data)
    return None


def check_action(callback_data: str, action: str) -> bool:
    callback_data = redis_callback_get(callback_data)
    return callback_data and callback_data.get("action") == action
