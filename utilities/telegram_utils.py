import re


def escape_special_characters(text):
    """
    Escapes special characters in a given string with a preceding backslash.

    Args:
    text (str): The string in which to escape special characters.

    Returns:
    str: The string with special characters escaped.
    """
    pattern = r"([_\*\[\]\(\)~`>#\+\-\=\|{}\.\!])"
    return re.sub(pattern, r"\\\1", text)
