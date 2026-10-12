from urllib.parse import parse_qs


def parse_query(query):
    if query.startswith("?"):
        query = query[1:]
    return parse_qs(query, keep_blank_values=True)
