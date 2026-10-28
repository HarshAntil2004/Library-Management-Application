import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from library_app.clock import FixedClock          # noqa: E402
from library_app.db import connect, migrate       # noqa: E402
from library_app.repositories import Repositories  # noqa: E402
from library_app.services import (CatalogService, LendingService, MemberService,  # noqa: E402
                                  ReportService, ReservationService)

# A Monday, well away from any seeded holiday.
START = date(2026, 6, 1)


class World:
    """A tiny hand-built library: three tiers from migration 002, no sample data."""

    def __init__(self):
        self.conn = connect(":memory:")
        migrate(self.conn, upto=2)
        self.clock = FixedClock(START)
        self.repos = Repositories(self.conn)
        self.lending = LendingService(self.repos, self.clock)
        self.reservations = self.lending.reservations
        self.members = MemberService(self.repos, self.clock)
        self.catalog = CatalogService(self.repos, self.clock)
        self.reports = ReportService(self.repos, self.clock)

    def member(self, tier="Basic", n=[0]):
        n[0] += 1
        return self.members.register(f"Test {n[0]}", f"t{n[0]}@example.in", tier, 1)

    def book(self, copies=1, n=[0]):
        n[0] += 1
        base = f"97893{n[0]:07d}"
        from library_app.isbn import check_digit
        bid = self.catalog.add_book(base + check_digit(base), f"Book {n[0]}", "Some Author", "Fiction")
        cids = [self.catalog.add_copy(bid, 1) for _ in range(copies)]
        return bid, cids


@pytest.fixture
def w():
    return World()
