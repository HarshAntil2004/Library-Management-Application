"""Service layer: every business rule lives here. Each public method is one
transaction, so a failure half-way never leaves half a loan behind."""
from __future__ import annotations

import re
from datetime import date, timedelta

from . import isbn as isbn_tools
from .db import UnitOfWork
from .exceptions import (BorrowLimitExceededError, CopyNotAvailableError, CopyReservedError,
                         DuplicateError, MembershipInactiveError, NotFoundError,
                         RenewalNotAllowedError, ReservationError, UnpaidFinesError,
                         ValidationError)
from .fines import FineCalculator, LibraryCalendar
from .models import to_date
from .repositories import Repositories

HOLD_DAYS = 3          # how long a reserved copy waits for its member
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class _Base:
    def __init__(self, repos: Repositories, clock):
        self.repos, self.clock = repos, clock
        self.uow = UnitOfWork(repos.conn)

    def _member(self, member_id):
        m = self.repos.members.get(member_id)
        if not m:
            raise NotFoundError(f"Member {member_id} not found")
        return m

    def _copy(self, copy_id):
        c = self.repos.copies.get(copy_id)
        if not c:
            raise NotFoundError(f"Copy {copy_id} not found")
        return c

    def _book(self, book_id):
        b = self.repos.books.get(book_id)
        if not b:
            raise NotFoundError(f"Book {book_id} not found")
        return b

    def _calculator(self):
        return FineCalculator(LibraryCalendar(self.repos.holidays.all_days()))


class ReservationService(_Base):
    def reserve(self, member_id: int, book_id: int) -> int:
        """Join the queue for a book. Returns the member's queue position."""
        with self.uow:
            member = self._member(member_id)
            self._book(book_id)
            self._require_good_standing(member)
            if self.repos.loans.member_has_book_open(member_id, book_id):
                raise ReservationError("Member already has this book on loan")
            if self.repos.reservations.live_for_member_and_book(member_id, book_id):
                raise DuplicateError("Member already has a reservation for this book")
            if self.repos.copies.available_for_book(book_id):
                raise ReservationError("A copy is available right now - just borrow it")
            rid = self.repos.reservations.add(member_id=member_id, book_id=book_id,
                                              created_at=self.clock.today().isoformat())
            return self.repos.reservations.position(self.repos.reservations.get(rid))

    def cancel(self, reservation_id: int) -> None:
        with self.uow:
            r = self.repos.reservations.get(reservation_id)
            if not r or r.status not in ("queued", "ready"):
                raise NotFoundError("No live reservation with that id")
            self.repos.reservations.set_status(r.id, "cancelled")
            if r.status == "ready":                      # free the held copy for the next person
                self._release_copy(r.held_copy_id, r.book_id)

    def expire_holds(self) -> int:
        """Housekeeping: holds not collected in time go to the next in line."""
        with self.uow:
            stale = self.repos.reservations.expired_ready(self.clock.today().isoformat())
            for r in stale:
                self.repos.reservations.set_status(r.id, "expired")
                self._release_copy(r.held_copy_id, r.book_id)
            return len(stale)

    # shared with LendingService.return_copy / CatalogService.add_copy
    def _release_copy(self, copy_id: int, book_id: int) -> None:
        """A copy just became free: hold it for the next queued member, else shelve it."""
        nxt = self.repos.reservations.next_in_queue(book_id)
        if nxt:
            expires = self.clock.today() + timedelta(days=HOLD_DAYS)
            self.repos.reservations.mark_ready(nxt.id, copy_id, expires.isoformat())
            self.repos.copies.set_status(copy_id, "held")
        else:
            self.repos.copies.set_status(copy_id, "available")

    def _require_good_standing(self, member):
        if not member.is_active:
            raise MembershipInactiveError(f"Membership is {member.status}")
        owed = self.repos.fines.unpaid_total(member.id)
        if owed > 0:
            raise UnpaidFinesError(f"Member owes {owed / 100:.2f} rupees in unpaid fines")


class LendingService(_Base):
    def __init__(self, repos, clock):
        super().__init__(repos, clock)
        self.reservations = ReservationService(repos, clock)
        self.reservations.uow = self.uow          # share one transaction scope

    # ------------------------------------------------------------- issue
    def issue(self, member_id: int, copy_id: int) -> int:
        with self.uow:
            member = self._member(member_id)
            copy = self._copy(copy_id)
            tier = self.repos.tiers.get(member.tier_id)

            self.reservations._require_good_standing(member)

            if self.repos.loans.count_open_for_member(member_id) >= tier.max_loans:
                raise BorrowLimitExceededError(
                    f"{tier.name} members can hold {tier.max_loans} books at a time")
            if self.repos.loans.member_has_book_open(member_id, copy.book_id):
                raise DuplicateError("Member already has a copy of this title")

            held_for = None
            if copy.status == "held":
                held_for = self.repos.reservations.ready_for_copy(copy_id)
                if not held_for or held_for.member_id != member_id:
                    raise CopyReservedError("This copy is being held for another member")
            elif copy.status != "available":
                raise CopyNotAvailableError(f"Copy is {copy.status.replace('_', ' ')}")

            today = self.clock.today()
            due = today + timedelta(days=tier.loan_days)
            # order matters for the rollback tests: status first, loan row second
            self.repos.copies.set_status(copy_id, "on_loan")
            loan_id = self.repos.loans.create(copy_id, member_id, today.isoformat(), due.isoformat())
            if held_for:
                self.repos.reservations.set_status(held_for.id, "fulfilled")
            return loan_id

    # ------------------------------------------------------------ return
    def return_copy(self, copy_id: int) -> int:
        """Close the loan, charge any fine, pass the copy to the queue. Returns fine in paise."""
        with self.uow:
            copy = self._copy(copy_id)
            loan = self.repos.loans.open_for_copy(copy_id)
            if not loan:
                raise NotFoundError("That copy is not currently on loan")
            member = self._member(loan.member_id)
            tier = self.repos.tiers.get(member.tier_id)
            today = self.clock.today()

            fine = self._calculator().fine(tier, to_date(loan.due_on), today)
            self.repos.loans.close(loan.id, today.isoformat())
            if fine > 0:
                self.repos.fines.add(loan.id, member.id, fine, today.isoformat())
            self.reservations._release_copy(copy.id, copy.book_id)
            return fine

    # ------------------------------------------------------------- renew
    def renew(self, loan_id: int) -> str:
        """Extend a loan by the tier's loan period. Returns the new due date."""
        with self.uow:
            loan = self.repos.loans.get(loan_id)
            if not loan or not loan.is_open:
                raise NotFoundError("No open loan with that id")
            member = self._member(loan.member_id)
            tier = self.repos.tiers.get(member.tier_id)
            copy = self._copy(loan.copy_id)
            today = self.clock.today()
            cal = LibraryCalendar(self.repos.holidays.all_days())

            if not member.is_active:
                raise MembershipInactiveError(f"Membership is {member.status}")
            if self.repos.fines.unpaid_total(member.id) > 0:
                raise UnpaidFinesError("Clear your fines before renewing")
            if today > cal.effective_due(to_date(loan.due_on)):
                raise RenewalNotAllowedError("Overdue books can't be renewed - return it first")
            if loan.renewals >= tier.max_renewals:
                raise RenewalNotAllowedError(
                    f"{tier.name} members can renew {tier.max_renewals} time(s)")
            if self.repos.reservations.queued_count(copy.book_id) > 0:
                raise RenewalNotAllowedError("Someone is waiting for this book")

            new_due = (to_date(loan.due_on) + timedelta(days=tier.loan_days)).isoformat()
            self.repos.loans.extend(loan.id, new_due)
            return new_due

    # --------------------------------------------------------- pay fines
    def pay_fines(self, member_id: int) -> int:
        with self.uow:
            self._member(member_id)
            return self.repos.fines.pay_all(member_id, self.clock.today().isoformat())


class MemberService(_Base):
    def register(self, name: str, email: str, tier_name: str, branch_id: int, phone: str | None = None) -> int:
        name, email = name.strip(), email.strip().lower()
        if not name:
            raise ValidationError("Name is required")
        if not EMAIL_RE.match(email):
            raise ValidationError(f"'{email}' doesn't look like an email address")
        with self.uow:
            tier = self.repos.tiers.by_name(tier_name)
            if not tier:
                raise ValidationError(f"Unknown membership tier '{tier_name}'")
            if self.repos.members.by_email(email):
                raise DuplicateError(f"{email} is already registered")
            return self.repos.members.add(name, email, phone, tier.id, branch_id,
                                          self.clock.today().isoformat())

    def change_tier(self, member_id: int, tier_name: str) -> None:
        with self.uow:
            member = self._member(member_id)
            new = self.repos.tiers.by_name(tier_name)
            if not new:
                raise ValidationError(f"Unknown membership tier '{tier_name}'")
            # Downgrading below what they already hold would break the limit rule.
            if self.repos.loans.count_open_for_member(member.id) > new.max_loans:
                raise BorrowLimitExceededError("Member holds more books than the new tier allows")
            self.repos.members.set_tier(member.id, new.id)


class CatalogService(_Base):
    def add_book(self, isbn: str, title: str, author: str, genre: str, year: int | None = None) -> int:
        clean = isbn_tools.validate(isbn)
        if not title.strip() or not author.strip():
            raise ValidationError("Title and author are required")
        with self.uow:
            if self.repos.books.by_isbn(clean):
                raise DuplicateError(f"ISBN {clean} is already in the catalogue")
            return self.repos.books.add(clean, title.strip(), author.strip(), genre, year)

    def add_copy(self, book_id: int, branch_id: int) -> int:
        with self.uow:
            self._book(book_id)
            cid = self.repos.copies.add(book_id, branch_id, f"TMP-{book_id}-{branch_id}-{self.clock.today().toordinal()}")
            # give it a proper barcode now that we have the id
            self.repos.conn.execute("UPDATE copies SET barcode=? WHERE id=?", (f"LKO-{cid:06d}", cid))
            # a brand-new copy might satisfy someone waiting in the queue
            ReservationService(self.repos, self.clock)._release_copy(cid, book_id)
            return cid

    def search(self, title=None, author=None, isbn=None, limit=25):
        return self.repos.books.search(title, author, isbn, limit)


class ReportService(_Base):
    def overdue_report(self, branch_id: int | None = None) -> list[dict]:
        """Open loans past their (holiday-adjusted) due date, with fine so far."""
        today = self.clock.today()
        cal = LibraryCalendar(self.repos.holidays.all_days())
        calc = FineCalculator(cal)
        rows = []
        for r in self.repos.loans.overdue_rows(today.isoformat(), branch_id):
            due = to_date(r["due_on"])
            if today <= cal.effective_due(due):
                continue                      # due date fell on a closed day, still in time
            tier = self.repos.tiers.get(r["tier_id"])
            r["days_overdue"] = cal.chargeable_days(due, today)
            r["fine_so_far_paise"] = calc.fine(tier, due, today)
            rows.append(r)
        return rows
