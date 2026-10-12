import csv
from io import StringIO


def parse_csv(text):
    rows = (row for row in csv.reader(StringIO(text, newline="")) if row)
    header = next(rows, None)
    if header is None:
        return []
    if len(set(header)) != len(header) or "" in header:
        raise ValueError("invalid header")
    result = []
    for row in rows:
        if len(row) != len(header):
            raise ValueError("column count")
        result.append(dict(zip(header, row)))
    return result
