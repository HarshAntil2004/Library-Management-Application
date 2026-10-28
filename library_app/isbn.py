"""ISBN-13 helpers. Strict enough to catch typos, no more."""
from .exceptions import ValidationError


def check_digit(first12: str) -> str:
    total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(first12))
    return str((10 - total % 10) % 10)


def normalise(isbn: str) -> str:
    return isbn.replace("-", "").replace(" ", "")


def validate(isbn: str) -> str:
    """Return the cleaned ISBN-13 or raise ValidationError."""
    clean = normalise(isbn)
    if len(clean) != 13 or not clean.isdigit():
        raise ValidationError(f"ISBN must be 13 digits, got '{isbn}'")
    if check_digit(clean[:12]) != clean[12]:
        raise ValidationError(f"ISBN '{isbn}' has a bad check digit")
    return clean
