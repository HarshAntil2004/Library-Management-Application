"""Fine calculation: grace periods, caps, Sundays and holidays."""
from datetime import date

from library_app.fines import EscalatingPolicy, FlatRatePolicy, FineCalculator, LibraryCalendar
from library_app.models import Tier

BASIC = Tier(1, "Basic", 3, 14, 1, 0, "escalating", 200, 2, 20000)
STANDARD = Tier(2, "Standard", 5, 21, 2, 0, "flat", 200, 3, 20000)
PREMIUM = Tier(3, "Premium", 10, 28, 3, 0, "flat", 150, 5, 10000)
CAL = LibraryCalendar({date(2026, 6, 4)})          # pretend Thursday 4 June is a holiday
CALC = FineCalculator(CAL)


def test_returned_on_time_is_free():
    assert CALC.fine(STANDARD, date(2026, 6, 10), date(2026, 6, 10)) == 0


def test_inside_grace_period_is_free():
    # Wed 3 June due, back Fri 5 June... 2 chargeable days but Standard grace is 3
    assert CALC.fine(STANDARD, date(2026, 6, 3), date(2026, 6, 5)) == 0


def test_fine_starts_after_grace():
    # due Mon 8 Jun, back Sat 13 Jun = 5 open days late, minus 3 grace = 2 x Rs2
    assert CALC.fine(STANDARD, date(2026, 6, 8), date(2026, 6, 13)) == 400


def test_sundays_are_not_charged():
    # due Sat 6 Jun, back Mon 15 Jun: Sun 7 and Sun 14 skipped -> 7 open days
    assert CAL.chargeable_days(date(2026, 6, 6), date(2026, 6, 15)) == 7


def test_holidays_are_not_charged():
    # due Wed 3 Jun, back Fri 5 Jun; Thu 4 Jun is a holiday -> only Fri counts
    assert CAL.chargeable_days(date(2026, 6, 3), date(2026, 6, 5)) == 1


def test_due_on_sunday_slides_to_monday():
    # due Sun 7 Jun -> effective due Mon 8 Jun; returning Mon 8 is on time
    assert CAL.effective_due(date(2026, 6, 7)) == date(2026, 6, 8)
    assert CAL.chargeable_days(date(2026, 6, 7), date(2026, 6, 8)) == 0


def test_due_on_holiday_then_sunday_chain():
    cal = LibraryCalendar({date(2026, 6, 6)})        # Saturday holiday, then Sunday
    assert cal.effective_due(date(2026, 6, 6)) == date(2026, 6, 8)


def test_standard_fine_is_capped():
    assert CALC.fine(STANDARD, date(2026, 1, 5), date(2026, 6, 1)) == 20000


def test_premium_has_longer_grace_and_lower_cap():
    assert CALC.fine(PREMIUM, date(2026, 6, 8), date(2026, 6, 12)) == 0      # 4 days <= grace 5
    assert CALC.fine(PREMIUM, date(2026, 1, 5), date(2026, 6, 1)) == 10000   # capped at Rs100


def test_escalating_rate_doubles_after_two_weeks():
    p = EscalatingPolicy(200, 0, 10**9, step=14)
    assert p.amount_for(14) == 14 * 200
    assert p.amount_for(16) == 14 * 200 + 2 * 400


def test_flat_policy_never_negative():
    assert FlatRatePolicy(200, 5, 1000).amount_for(0) == 0
