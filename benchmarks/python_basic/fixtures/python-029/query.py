def parse_query(query):
    return dict(part.split("=") for part in query.split("&"))
