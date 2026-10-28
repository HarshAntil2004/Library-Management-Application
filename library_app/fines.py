"""Fine calculation.

Two ideas live here:
  * the *calendar* decides which days count (Sundays and listed holidays are
    closed, so nobody is charged for them), and
  * a *policy* (Strategy pattern) decides how many rupees N chargeable days cost.
Keeping them apart means a new tier rule never touches the date logic.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Protocol

from .models import Tier


class FinePolicy(Protocol):
    def amount_for(self, chargeable_days: int) -> int: ...


class FlatRatePolicy:
    """Same rate every day after the grace period, up to a cap."""

    def __init__(self, rate_paise: int, grace_days: int, cap_paise: int):
        self.rate, self.grace, self.cap = rate_paise, grace_days, cap_paise

    def amount_for(self, chargeable_days: int) -> int:
        billable = max(0, chargeable_days - self.grace)
        return min(billable * self.rate, self.cap)


class EscalatingPolicy:
    """Rate doubles once a book is more than `step` billable days late."""

    def __init__(self, rate_paise: int, grace_days: int, cap_paise: int, step: int = 14):
        self.rate, self.grace, self.cap, self.step = rate_paise, grace_days, cap_paise, step

    def amount_for(self, chargeable_days: int) -> int:
        billable = max(0, chargeable_days - self.grace)
        normal = min(billable, self.step)
        extra = billable - normal
        return min(normal * self.rate + extra * self.rate * 2, self.cap)


def policy_for(tier: Tier) -> FinePolicy:
    """Small factory: tier row -> the right strategy object."""
    if tier.fine_policy == "escalating":
        return EscalatingPolicy(tier.fine_rate_paise, tier.grace_days, tier.fine_cap_paise)
    return FlatRatePolicy(tier.fine_rate_paise, tier.grace_days, tier.fine_cap_paise)


class LibraryCalendar:
    """Knows which days the branches are shut."""

    def __init__(self, holidays: set[date]):
        self.holidays = holidays

    def is_closed(self, day: date) -> bool:
        return day.weekday() == 6 or day in self.holidays   # 6 = Sunday

    def effective_due(self, due: date) -> date:
        """A book due on a closed day can't be returned that day, so the
        deadline slides to the next day we're open."""
        while self.is_closed(due):
            due += timedelta(days=1)
        return due

    def chargeable_days(self, due: date, returned: date) -> int:
        """Open days strictly after the (adjusted) due date up to and including return."""
        day = self.effective_due(due) + timedelta(days=1)
        count = 0
        while day <= returned:
            if not self.is_closed(day):
                count += 1
            day += timedelta(days=1)
        return count


class FineCalculator:
    def __init__(self, calendar: LibraryCalendar):
        self.calendar = calendar

    def fine(self, tier: Tier, due: date, returned: date) -> int:
        days = self.calendar.chargeable_days(due, returned)
        return policy_for(tier).amount_for(days)
