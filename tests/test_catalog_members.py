"""Registration, tiers, ISBN validation, search and the overdue report."""
import pytest

from library_app import isbn
from library_app.exceptions import BorrowLimitExceededError, DuplicateError, ValidationError


def test_register_member_with_tier(w):
    mid = w.members.register("Asha Verma", "Asha@Example.in", "premium", 2)
    m = w.repos.members.get(mid)
    assert m.email == "asha@example.in" and w.repos.tiers.get(m.tier_id).name == "Premium"


def test_duplicate_email_rejected(w):
    w.members.register("A", "a@example.in", "Basic", 1)
    with pytest.raises(DuplicateError):
        w.members.register("B", "a@example.in", "Basic", 1)


@pytest.mark.parametrize("name,email,tier", [("", "a@b.in", "Basic"), ("A", "not-an-email", "Basic"),
                                              ("A", "a@b.in", "Gold")])
def test_bad_registration_input(w, name, email, tier):
    with pytest.raises(ValidationError):
        w.members.register(name, email, tier, 1)


def test_cannot_downgrade_below_current_loans(w):
    m = w.member("Premium")
    for _ in range(5):
        _, (c,) = w.book(); w.lending.issue(m, c)
    with pytest.raises(BorrowLimitExceededError):
        w.members.change_tier(m, "Basic")


def test_upgrade_raises_limit(w):
    m = w.member("Basic")
    w.members.change_tier(m, "Premium")
    for _ in range(4):
        _, (c,) = w.book(); w.lending.issue(m, c)


def test_isbn_validation():
    assert isbn.validate("978-93-0000000-0"[:0] + "9789300000002") == "9789300000002"
    with pytest.raises(ValidationError):
        isbn.validate("9789300000003")                      # wrong check digit
    with pytest.raises(ValidationError):
        isbn.validate("12345")


def test_duplicate_isbn_rejected(w):
    w.catalog.add_book("9789300000002", "T", "A", "Fiction")
    with pytest.raises(DuplicateError):
        w.catalog.add_book("978-9300000002", "T2", "A2", "Fiction")


def test_search_by_title_author_and_isbn(w):
    w.catalog.add_book("9789300000002", "Monsoon Atlas", "Meera Khan", "Travel")
    assert len(w.catalog.search(title="monsoon")) == 1
    assert len(w.catalog.search(author="Meera")) == 1
    assert w.catalog.search(isbn="978-93-00000007"[:0] + "9789300000002")[0]["title"] == "Monsoon Atlas"
    assert w.catalog.search(title="nothing like this") == []


def test_search_reports_free_copies(w):
    bid, (c1, c2) = w.book(copies=2); m = w.member()
    w.lending.issue(m, c1)
    row = w.catalog.search(title=f"Book")[-1]
    assert (row["total_copies"], row["available_copies"]) == (2, 1)


def test_overdue_report_filters_by_branch(w):
    m1, m2 = w.member("Standard"), w.member("Standard")
    _, (c1,) = w.book()
    bid2 = w.catalog.add_book("9789300000019", "Other", "X", "Fiction"); c2 = w.catalog.add_copy(bid2, 2)
    w.lending.issue(m1, c1); w.lending.issue(m2, c2); w.clock.advance(40)
    assert len(w.reports.overdue_report()) == 2
    only_b2 = w.reports.overdue_report(branch_id=2)
    assert len(only_b2) == 1 and only_b2[0]["fine_so_far_paise"] > 0


def test_overdue_report_ignores_loans_still_in_time(w):
    m = w.member(); _, (c,) = w.book(); w.lending.issue(m, c); w.clock.advance(5)
    assert w.reports.overdue_report() == []
