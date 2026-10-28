"""Plain domain classes. They carry the data plus the little bits of behaviour
that belong to them; anything that touches the database or crosses several
objects lives in the service layer instead."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date


def to_date(value: str | date | None) -> date | None:
    if value is None or isinstance(value, date):
        return value
    return date.fromisoformat(value)


def inr(paise: int) -> str:
    """Format paise as a rupee string, e.g. 15050 -> 'Rs 150.50'."""
    return f"Rs {paise / 100:,.2f}"


@dataclass(frozen=True)
class Tier:
    id: int
    name: str
    max_loans: int
    loan_days: int
    max_renewals: int
    annual_fee_paise: int
    fine_policy: str
    fine_rate_paise: int
    grace_days: int
    fine_cap_paise: int


@dataclass
class Member:
    id: int
    name: str
    email: str
    phone: str | None
    tier_id: int
    home_branch_id: int
    joined_on: str
    status: str

    @property
    def is_active(self) -> bool:
        return self.status == "active"


@dataclass(frozen=True)
class Book:
    id: int
    isbn: str
    title: str
    author: str
    genre: str
    published_year: int | None


@dataclass
class Copy:
    id: int
    book_id: int
    branch_id: int
    barcode: str
    status: str

    @property
    def is_available(self) -> bool:
        return self.status == "available"


@dataclass
class Loan:
    id: int
    copy_id: int
    member_id: int
    issued_on: str
    due_on: str
    returned_on: str | None
    renewals: int

    @property
    def is_open(self) -> bool:
        return self.returned_on is None


@dataclass
class Reservation:
    id: int
    book_id: int
    member_id: int
    created_at: str
    status: str
    held_copy_id: int | None
    expires_on: str | None
