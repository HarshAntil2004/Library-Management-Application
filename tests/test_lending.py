"""Issue and return: every borrowing rule has a test here."""
from datetime import timedelta

import pytest

from library_app.exceptions import (BorrowLimitExceededError, CopyNotAvailableError, CopyReservedError,
                                    DuplicateError, MembershipInactiveError, NotFoundError,
                                    UnpaidFinesError)


def test_issue_sets_due_date_from_tier(w):
    m = w.member("Premium"); _, (c,) = w.book()
    loan_id = w.lending.issue(m, c)
    loan = w.repos.loans.get(loan_id)
    assert loan.due_on == (w.clock.today() + timedelta(days=28)).isoformat()
    assert w.repos.copies.get(c).status == "on_loan"


@pytest.mark.parametrize("tier,limit", [("Basic", 3), ("Standard", 5), ("Premium", 10)])
def test_borrowing_limit_per_tier(w, tier, limit):
    m = w.member(tier)
    for _ in range(limit):
        _, (c,) = w.book()
        w.lending.issue(m, c)
    _, (extra,) = w.book()
    with pytest.raises(BorrowLimitExceededError):
        w.lending.issue(m, extra)
    assert w.repos.copies.get(extra).status == "available"      # nothing leaked


def test_unpaid_fines_block_issue(w):
    m = w.member("Standard"); _, (c,) = w.book(); _, (c2,) = w.book()
    w.lending.issue(m, c)
    w.clock.advance(60)
    assert w.lending.return_copy(c) > 0
    with pytest.raises(UnpaidFinesError):
        w.lending.issue(m, c2)


def test_paying_fines_unblocks_member(w):
    m = w.member("Standard"); _, (c,) = w.book(); _, (c2,) = w.book()
    w.lending.issue(m, c); w.clock.advance(60); w.lending.return_copy(c)
    assert w.lending.pay_fines(m) > 0
    assert w.lending.issue(m, c2)


def test_cannot_issue_a_copy_already_on_loan(w):
    a, b = w.member(), w.member(); _, (c,) = w.book()
    w.lending.issue(a, c)
    with pytest.raises(CopyNotAvailableError):
        w.lending.issue(b, c)


def test_cannot_issue_a_lost_copy(w):
    m = w.member(); _, (c,) = w.book()
    w.repos.copies.set_status(c, "lost")
    with pytest.raises(CopyNotAvailableError):
        w.lending.issue(m, c)


def test_inactive_member_cannot_borrow(w):
    m = w.member(); _, (c,) = w.book()
    w.repos.members.set_status(m, "suspended")
    with pytest.raises(MembershipInactiveError):
        w.lending.issue(m, c)


def test_same_title_twice_is_refused(w):
    m = w.member("Premium"); _, (c1, c2) = w.book(copies=2)
    w.lending.issue(m, c1)
    with pytest.raises(DuplicateError):
        w.lending.issue(m, c2)


def test_unknown_member_or_copy(w):
    m = w.member(); _, (c,) = w.book()
    with pytest.raises(NotFoundError):
        w.lending.issue(9999, c)
    with pytest.raises(NotFoundError):
        w.lending.issue(m, 9999)


def test_on_time_return_has_no_fine_and_shelves_copy(w):
    m = w.member(); _, (c,) = w.book()
    w.lending.issue(m, c); w.clock.advance(10)
    assert w.lending.return_copy(c) == 0
    assert w.repos.copies.get(c).status == "available"


def test_late_return_records_fine(w):
    m = w.member("Standard"); _, (c,) = w.book()
    w.lending.issue(m, c); w.clock.advance(21 + 10)        # 10 days late (Sundays free)
    fine = w.lending.return_copy(c)
    assert fine > 0
    assert w.repos.fines.unpaid_total(m) == fine


def test_returning_a_shelved_copy_fails(w):
    _, (c,) = w.book()
    with pytest.raises(NotFoundError):
        w.lending.return_copy(c)
