import re
from datetime import datetime
from typing import Optional

# Formats seen across the CSV sources, the seeded demo cases and generated data.
_DATETIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%d",
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y %H:%M",
    "%m/%d/%Y",
    "%d/%m/%Y",
    "%d-%b-%Y",
    # Seeded case style: "Jun 22, 2026, 21:06:49" / "Jun 04, 2026, 12:57 PM"
    "%b %d, %Y, %H:%M:%S",
    "%b %d, %Y, %I:%M:%S %p",
    "%b %d, %Y, %I:%M %p",
    "%b %d, %Y %H:%M:%S",
    "%b %d, %Y",
)

# Trailing timezone abbreviation, e.g. "Jun 04, 2026, 12:57 PM PDT".
_TZ_SUFFIX = re.compile(r"\s+(?:UTC|GMT|[PMCE][SD]T|Z)$", re.IGNORECASE)

OUTPUT_FORMAT = "%Y-%m-%d %H:%M:%S"


def safe_float(value, default: float = 0.0) -> float:
    """Coerce a value to float, tolerating currency formatting and blanks."""
    if value is None:
        return default
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = str(value).strip().replace(",", "").replace("$", "")
    if not text:
        return default
    try:
        return float(text)
    except (TypeError, ValueError):
        return default


def parse_any_datetime(value) -> Optional[datetime]:
    """Parse a datetime from any of the formats used in the data sources.

    Returns None when the value is blank or unparseable, so callers can fall
    back with `or datetime.min`.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None

    for candidate in (text, _TZ_SUFFIX.sub("", text).strip()):
        for fmt in _DATETIME_FORMATS:
            try:
                return datetime.strptime(candidate, fmt)
            except ValueError:
                continue

    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00").replace("z", "+00:00"))
        return dt.replace(tzinfo=None) if dt.tzinfo else dt
    except ValueError:
        return None


def fmt_datetime(value, fallback: str = "") -> str:
    """Format a datetime (or parseable string) as 'YYYY-MM-DD HH:MM:SS'."""
    dt = value if isinstance(value, datetime) else parse_any_datetime(value)
    if dt is None:
        return fallback
    return dt.strftime(OUTPUT_FORMAT)
