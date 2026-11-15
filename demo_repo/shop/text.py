def slugify(title):
    cleaned = "".join(c.lower() if c.isalnum() else "-" for c in title)
    return "-".join(part for part in cleaned.split("-") if part)


def truncate(text, limit):
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."
