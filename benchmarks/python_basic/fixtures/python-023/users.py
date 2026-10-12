def normalize_users(rows):
    for row in rows:
        row["email"] = row["email"].lower()
        row["name"] = row.get("name", "").strip()
    return rows
