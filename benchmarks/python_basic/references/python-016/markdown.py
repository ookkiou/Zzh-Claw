import re


def headings(text):
    result = []
    fence = None
    for line in text.splitlines():
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if fence:
            if (
                marker
                and marker[1][0] == fence[0]
                and len(marker[1]) >= fence[1]
                and not marker[2].strip()
            ):
                fence = None
            continue
        if marker:
            fence = (marker[1][0], len(marker[1]))
            continue
        match = re.match(r"^ {0,3}(#{1,6})(?:[ \t]+(.*)|$)", line)
        if match:
            title = match[2] or ""
            title = re.sub(r"[ \t]+#+[ \t]*$", "", title).strip()
            result.append((len(match[1]), title))
    return result
