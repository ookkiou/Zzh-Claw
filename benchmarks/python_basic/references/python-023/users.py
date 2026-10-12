def normalize_email(email):
    return email.strip().lower()


def normalize_users(rows):
    return [
        {
            **row,
            "email": normalize_email(row["email"]),
            "name": row.get("name", "").strip(),
        }
        for row in rows
    ]
