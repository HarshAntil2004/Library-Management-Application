"""A tiny clock abstraction so tests (and the CLI demo) can control 'today'."""
from datetime import date


class SystemClock:
    def today(self) -> date:
        return date.today()


class FixedClock:
    def __init__(self, day: date):
        self.day = day

    def today(self) -> date:
        return self.day

    def advance(self, days: int) -> None:
        from datetime import timedelta
        self.day += timedelta(days=days)
