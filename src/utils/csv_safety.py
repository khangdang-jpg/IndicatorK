"""Symbol validation and CSV injection prevention."""

import re

_SYMBOL_RE = re.compile(r"^[A-Z0-9]{1,10}$")
_CSV_INJECTION_CHARS = {"=", "+", "-", "@", "\t", "\r"}


def validate_symbol(s: str) -> str:
    """Validate and normalize a stock symbol.

    Rules: uppercase, alphanumeric only, 1-10 chars.
    Raises ValueError if invalid.
    """
    s = s.strip().upper()
    if not _SYMBOL_RE.match(s):
        raise ValueError(
            f"Invalid symbol '{s}': must be 1-10 alphanumeric characters"
        )
    return s


def sanitize_csv_field(s: str) -> str:
    """Sanitize a string for safe CSV writing.

    Strips leading characters that could trigger formula injection
    in spreadsheet applications (=, +, -, @, tab, CR).
    """
    s = str(s)
    while s and s[0] in _CSV_INJECTION_CHARS:
        s = s[1:]
    return s


def parse_number(s: str) -> float:
    """Parse a string to float safely.

    Raises ValueError if the string is not a valid number.
    """
    s = s.strip()
    try:
        val = float(s)
    except (ValueError, TypeError):
        raise ValueError(f"Invalid number: '{s}'")
    if not isinstance(val, float) or val != val:  # NaN check
        raise ValueError(f"Invalid number: '{s}'")
    return val
