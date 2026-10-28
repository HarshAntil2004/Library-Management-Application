"""Reservation queue, held copies and renewals."""
import pytest

from library_app.exceptions import (CopyReservedError, DuplicateError, RenewalNotAllowedError,
                                    ReservationError, UnpaidFinesError)


def test_cannot_reserve_when_a_copy_is_free(w):
    m = w.member(); bid, _ = w.book()
    with pytest.raises(ReservationError):
        w.reservations.reserve(m, bid)


def test_queue_positions_are_first_come_first_served(w):
    holder, a, b = w.member(), w.member(), w.member()
    bid, (c,) = w.book(); w.lending.issue(holder, c)
    assert w.reservations.reserve(a, bid) == 1
    assert w.reservations.reserve(b, bid) == 2


def test_duplicate_reservation_refused(w):
    holder, a = w.member(), w.member(); bid, (c,) = w.book(); w.lending.issue(holder, c)
    w.reservations.reserve(a, bid)
    with pytest.raises(DuplicateError):
        w.reservations.reserve(a, bid)


def test_returned_copy_is_held_for_queue_head(w):
    holder, a = w.member(), w.member(); bid, (c,) = w.book(); w.lending.issue(holder, c)
    w.reservations.reserve(a, bid)
    w.lending.return_copy(c)
    assert w.repos.copies.get(c).status == "held"


def test_reserved_copy_cannot_be_issued_to_someone_else(w):
    holder, a, stranger = w.member(), w.member(), w.member()
    bid, (c,) = w.book(); w.lending.issue(holder, c)
    w.reservations.reserve(a, bid); w.lending.return_copy(c)
    with pytest.raises(CopyReservedError):
        w.lending.issue(stranger, c)


def test_reserved_copy_can_be_issued_to_the_reserver(w):
    holder, a = w.member(), w.member(); bid, (c,) = w.book(); w.lending.issue(holder, c)
    rid_pos = w.reservations.reserve(a, bid); w.lending.return_copy(c)
    assert w.lending.issue(a, c)
    assert w.conn.execute("SELECT status FROM reservations").fetchone()[0] == "fulfilled"


def test_expired_hold_passes_to_next_member(w):
    holder, a, b = w.member(), w.member(), w.member()
    bid, (c,) = w.book(); w.lending.issue(holder, c)
    w.reservations.reserve(a, bid); w.reservations.reserve(b, bid)
    w.lending.return_copy(c)
    w.clock.advance(5)
    assert w.reservations.expire_holds() == 1
    assert w.repos.copies.get(c).status == "held"           # now held for b
    assert w.repos.reservations.ready_for_copy(c).member_id == b


def test_cancelled_hold_frees_copy(w):
    holder, a = w.member(), w.member(); bid, (c,) = w.book(); w.lending.issue(holder, c)
    w.reservations.reserve(a, bid); w.lending.return_copy(c)
    rid = w.conn.execute("SELECT id FROM reservations").fetchone()[0]
    w.reservations.cancel(rid)
    assert w.repos.copies.get(c).status == "available"


def test_new_copy_goes_straight_to_the_queue(w):
    holder, a = w.member(), w.member(); bid, (c,) = w.book(); w.lending.issue(holder, c)
    w.reservations.reserve(a, bid)
    new_copy = w.catalog.add_copy(bid, 2)
    assert w.repos.copies.get(new_copy).status == "held"


def test_renew_extends_by_tier_period(w):
    m = w.member("Standard"); _, (c,) = w.book()
    loan = w.lending.issue(m, c)
    old = w.repos.loans.get(loan).due_on
    assert w.lending.renew(loan) > old


def test_renewal_limit_per_tier(w):
    m = w.member("Basic"); _, (c,) = w.book()
    loan = w.lending.issue(m, c)
    w.lending.renew(loan)                                   # Basic allows exactly 1
    with pytest.raises(RenewalNotAllowedError):
        w.lending.renew(loan)


def test_cannot_renew_overdue_loan(w):
    m = w.member("Standard"); _, (c,) = w.book()
    loan = w.lending.issue(m, c); w.clock.advance(30)
    with pytest.raises(RenewalNotAllowedError):
        w.lending.renew(loan)


def test_cannot_renew_when_someone_is_waiting(w):
    holder, a = w.member("Premium"), w.member(); bid, (c,) = w.book()
    loan = w.lending.issue(holder, c); w.reservations.reserve(a, bid)
    with pytest.raises(RenewalNotAllowedError):
        w.lending.renew(loan)


def test_cannot_renew_with_unpaid_fines(w):
    m = w.member("Premium"); _, (c1,) = w.book(); _, (c2,) = w.book()
    old = w.lending.issue(m, c1); late = w.lending.issue(m, c2)
    w.clock.advance(70); w.lending.return_copy(c1)          # c1 returned very late -> fine
    w.repos.conn.execute("UPDATE loans SET due_on=date(?, '+60 day') WHERE id=?", (w.clock.today().isoformat(), late))
    with pytest.raises(UnpaidFinesError):
        w.lending.renew(late)
