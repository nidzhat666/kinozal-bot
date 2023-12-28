def extract_text_without_command(message_text, command):
    """
    Extracts the text from a message without the command.
    :param message_text: The full text of the message.
    :param command: The command to remove from the message.
    :return: The text without the command.
    """
    command_length = len(command) + 1  # +1 for the '/' in the command
    return message_text[command_length:].strip()
