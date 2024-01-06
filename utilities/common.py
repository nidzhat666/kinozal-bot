def truncate_string(input_string: str, max_length: int) -> str:
    if len(input_string) > max_length:
        return input_string[:max_length]
    else:
        return input_string
