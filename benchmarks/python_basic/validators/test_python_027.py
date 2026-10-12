from datetime import datetime, timedelta, timezone

import pytest
from timestamps import to_utc_iso


def test_conversion():
    value = datetime(2026, 1, 1, 2, 3, 4, 999999, tzinfo=timezone(timedelta(hours=8)))
    assert to_utc_iso(value) == "2025-12-31T18:03:04Z" and value.microsecond == 999999
    assert (
        to_utc_iso(datetime(1970, 1, 1, tzinfo=timezone.utc)) == "1970-01-01T00:00:00Z"
    )


def test_naive():
    with pytest.raises(ValueError):
        to_utc_iso(datetime(2026, 1, 1))
