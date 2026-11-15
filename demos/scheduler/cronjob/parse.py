def parse_interval(text):
    text = text.strip().lower()
    if "h" in text:
        hours = text.split("h")[0]
        return int(hours) * 60
    if text.endswith("m"):
        return int(text[:-1])
    return int(text)
