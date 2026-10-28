"""If any step of issue/return fails, nothing at all is saved."""
import pytest


def test_issue_rolls_back_if_loan_insert_fails(w, monkeypatch):
    m = w.member(); _, (c,) = w.book()

    def boom(*a, **k):
        raise RuntimeError("disk on fire")
    monkeypatch.setattr(w.repos.loans, "create", boom)
    with pytest.raises(RuntimeError):
        w.lending.issue(m, c)
    # the copy status change happened *before* the failure - it must be undone
    assert w.repos.copies.get(c).status == "available"
    assert w.conn.execute("SELECT COUNT(*) FROM loans").fetchone()[0] == 0


def test_return_rolls_back_if_queue_handoff_fails(w, monkeypatch):
    holder, a = w.member(), w.member(); bid, (c,) = w.book()
    loan = w.lending.issue(holder, c); w.reservations.reserve(a, bid)
    w.clock.advance(40)

    def boom(*a, **k):
        raise RuntimeError("queue exploded")
    monkeypatch.setattr(w.repos.reservations, "mark_ready", boom)
    with pytest.raises(RuntimeError):
        w.lending.return_copy(c)
    assert w.repos.loans.get(loan).is_open                  # still on loan
    assert w.repos.fines.unpaid_total(holder) == 0           # fine not recorded
    assert w.repos.copies.get(c).status == "on_loan"


def test_failed_business_rule_leaves_no_trace(w):
    from library_app.exceptions import BorrowLimitExceededError
    m = w.member("Basic")
    for _ in range(3):
        _, (c,) = w.book(); w.lending.issue(m, c)
    _, (extra,) = w.book()
    with pytest.raises(BorrowLimitExceededError):
        w.lending.issue(m, extra)
    assert w.conn.execute("SELECT COUNT(*) FROM loans").fetchone()[0] == 3


def test_unit_of_work_nests(w):
    with w.lending.uow:
        with w.lending.uow:
            w.conn.execute("INSERT INTO holidays VALUES ('2030-01-01','x')")
        # inner exit must not have committed yet
        assert w.conn.in_transaction
    assert not w.conn.in_transaction


def test_database_blocks_double_open_loan(w):
    import sqlite3
    a, b = w.member(), w.member(); _, (c,) = w.book()
    w.lending.issue(a, c)
    with pytest.raises(sqlite3.IntegrityError):              # safety net below the service layer
        w.conn.execute("INSERT INTO loans (copy_id,member_id,issued_on,due_on) VALUES (?,?,?,?)",
                       (c, b, "2026-06-01", "2026-06-15"))
