import re


def slugify(text, separator="-"):
    if separator not in {"-", "_"}:
        raise ValueError("separator")
    return separator.join(re.findall("[a-z0-9]+", text.lower()))
