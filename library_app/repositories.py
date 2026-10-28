"""Repository layer: the only place that writes SQL. Services ask for domain
objects and never see a cursor."""
from __future__ import annotations

import sqlite3

from .models import Book, Copy, Loan, Member, Reservation, Tier


def _one(cls, row):
    return cls(**dict(row)) if row else None


class TierRepository:
    def __init__(self, conn): self.conn = conn

    def get(self, tier_id: int) -> Tier | None:
        return _one(Tier, self.conn.execute("SELECT * FROM membership_tiers WHERE id=?", (tier_id,)).fetchone())

    def by_name(self, name: str) -> Tier | None:
        return _one(Tier, self.conn.execute(
            "SELECT * FROM membership_tiers WHERE lower(name)=lower(?)", (name,)).fetchone())


class MemberRepository:
    def __init__(self, conn): self.conn = conn

    def get(self, member_id: int) -> Member | None:
        return _one(Member, self.conn.execute("SELECT * FROM members WHERE id=?", (member_id,)).fetchone())

    def by_email(self, email: str) -> Member | None:
        return _one(Member, self.conn.execute("SELECT * FROM members WHERE email=?", (email,)).fetchone())

    def add(self, name, email, phone, tier_id, branch_id, joined_on) -> int:
        cur = self.conn.execute(
            "INSERT INTO members (name,email,phone,tier_id,home_branch_id,joined_on) VALUES (?,?,?,?,?,?)",
            (name, email, phone, tier_id, branch_id, joined_on))
        return cur.lastrowid

    def set_tier(self, member_id, tier_id):
        self.conn.execute("UPDATE members SET tier_id=? WHERE id=?", (tier_id, member_id))

    def set_status(self, member_id, status):
        self.conn.execute("UPDATE members SET status=? WHERE id=?", (status, member_id))


class BookRepository:
    def __init__(self, conn): self.conn = conn

    def get(self, book_id: int) -> Book | None:
        return _one(Book, self.conn.execute("SELECT * FROM books WHERE id=?", (book_id,)).fetchone())

    def by_isbn(self, isbn: str) -> Book | None:
        return _one(Book, self.conn.execute("SELECT * FROM books WHERE isbn=?", (isbn,)).fetchone())

    def add(self, isbn, title, author, genre, year) -> int:
        cur = self.conn.execute(
            "INSERT INTO books (isbn,title,author,genre,published_year) VALUES (?,?,?,?,?)",
            (isbn, title, author, genre, year))
        return cur.lastrowid

    def search(self, title=None, author=None, isbn=None, limit=25) -> list[dict]:
        """Returns book rows plus how many copies are free right now."""
        where, args = [], []
        if title:
            where.append("b.title LIKE ?"); args.append(f"%{title}%")
        if author:
            where.append("b.author LIKE ?"); args.append(f"%{author}%")
        if isbn:
            where.append("b.isbn = ?"); args.append(isbn.replace("-", ""))
        clause = ("WHERE " + " AND ".join(where)) if where else ""
        sql = f"""
            SELECT b.*, COUNT(c.id) AS total_copies,
                   COALESCE(SUM(c.status='available'),0) AS available_copies
            FROM books b LEFT JOIN copies c ON c.book_id=b.id
            {clause} GROUP BY b.id ORDER BY b.title LIMIT ?"""
        return [dict(r) for r in self.conn.execute(sql, (*args, limit))]


class CopyRepository:
    def __init__(self, conn): self.conn = conn

    def get(self, copy_id: int) -> Copy | None:
        return _one(Copy, self.conn.execute("SELECT * FROM copies WHERE id=?", (copy_id,)).fetchone())

    def add(self, book_id, branch_id, barcode) -> int:
        cur = self.conn.execute(
            "INSERT INTO copies (book_id,branch_id,barcode) VALUES (?,?,?)", (book_id, branch_id, barcode))
        return cur.lastrowid

    def set_status(self, copy_id, status):
        self.conn.execute("UPDATE copies SET status=? WHERE id=?", (status, copy_id))

    def available_for_book(self, book_id) -> list[Copy]:
        rows = self.conn.execute(
            "SELECT * FROM copies WHERE book_id=? AND status='available' ORDER BY id", (book_id,))
        return [Copy(**dict(r)) for r in rows]


class LoanRepository:
    def __init__(self, conn): self.conn = conn

    def get(self, loan_id) -> Loan | None:
        return _one(Loan, self.conn.execute("SELECT * FROM loans WHERE id=?", (loan_id,)).fetchone())

    def open_for_copy(self, copy_id) -> Loan | None:
        return _one(Loan, self.conn.execute(
            "SELECT * FROM loans WHERE copy_id=? AND returned_on IS NULL", (copy_id,)).fetchone())

    def count_open_for_member(self, member_id) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) FROM loans WHERE member_id=? AND returned_on IS NULL", (member_id,)).fetchone()[0]

    def member_has_book_open(self, member_id, book_id) -> bool:
        return self.conn.execute(
            """SELECT 1 FROM loans l JOIN copies c ON c.id=l.copy_id
               WHERE l.member_id=? AND c.book_id=? AND l.returned_on IS NULL""",
            (member_id, book_id)).fetchone() is not None

    def create(self, copy_id, member_id, issued_on, due_on) -> int:
        cur = self.conn.execute(
            "INSERT INTO loans (copy_id,member_id,issued_on,due_on) VALUES (?,?,?,?)",
            (copy_id, member_id, issued_on, due_on))
        return cur.lastrowid

    def close(self, loan_id, returned_on):
        self.conn.execute("UPDATE loans SET returned_on=? WHERE id=?", (returned_on, loan_id))

    def extend(self, loan_id, new_due):
        self.conn.execute("UPDATE loans SET due_on=?, renewals=renewals+1 WHERE id=?", (new_due, loan_id))

    def overdue_rows(self, today: str, branch_id=None) -> list[dict]:
        sql = """
            SELECT l.id AS loan_id, l.due_on, l.renewals, c.id AS copy_id, c.barcode,
                   br.id AS branch_id, br.name AS branch, b.title, b.author,
                   m.id AS member_id, m.name AS member, m.phone, m.tier_id
            FROM loans l
            JOIN copies c ON c.id=l.copy_id
            JOIN branches br ON br.id=c.branch_id
            JOIN books b ON b.id=c.book_id
            JOIN members m ON m.id=l.member_id
            WHERE l.returned_on IS NULL AND l.due_on < ?"""
        args = [today]
        if branch_id:
            sql += " AND br.id=?"; args.append(branch_id)
        sql += " ORDER BY br.id, l.due_on"
        return [dict(r) for r in self.conn.execute(sql, args)]


class ReservationRepository:
    def __init__(self, conn): self.conn = conn

    def get(self, rid) -> Reservation | None:
        return _one(Reservation, self.conn.execute("SELECT * FROM reservations WHERE id=?", (rid,)).fetchone())

    def add(self, book_id, member_id, created_at) -> int:
        cur = self.conn.execute(
            "INSERT INTO reservations (book_id,member_id,created_at) VALUES (?,?,?)",
            (book_id, member_id, created_at))
        return cur.lastrowid

    def live_for_member_and_book(self, member_id, book_id) -> Reservation | None:
        return _one(Reservation, self.conn.execute(
            "SELECT * FROM reservations WHERE member_id=? AND book_id=? AND status IN ('queued','ready')",
            (member_id, book_id)).fetchone())

    def ready_for_copy(self, copy_id) -> Reservation | None:
        return _one(Reservation, self.conn.execute(
            "SELECT * FROM reservations WHERE held_copy_id=? AND status='ready'", (copy_id,)).fetchone())

    def next_in_queue(self, book_id) -> Reservation | None:
        # created_at then id keeps the queue strictly first-come-first-served
        return _one(Reservation, self.conn.execute(
            "SELECT * FROM reservations WHERE book_id=? AND status='queued' ORDER BY created_at, id LIMIT 1",
            (book_id,)).fetchone())

    def queued_count(self, book_id) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) FROM reservations WHERE book_id=? AND status='queued'", (book_id,)).fetchone()[0]

    def position(self, reservation: Reservation) -> int:
        return self.conn.execute(
            """SELECT COUNT(*) FROM reservations WHERE book_id=? AND status='queued'
               AND (created_at < ? OR (created_at = ? AND id <= ?))""",
            (reservation.book_id, reservation.created_at, reservation.created_at, reservation.id)).fetchone()[0]

    def mark_ready(self, rid, copy_id, expires_on):
        self.conn.execute(
            "UPDATE reservations SET status='ready', held_copy_id=?, expires_on=? WHERE id=?",
            (copy_id, expires_on, rid))

    def set_status(self, rid, status):
        self.conn.execute("UPDATE reservations SET status=? WHERE id=?", (status, rid))

    def expired_ready(self, today: str) -> list[Reservation]:
        rows = self.conn.execute(
            "SELECT * FROM reservations WHERE status='ready' AND expires_on < ?", (today,))
        return [Reservation(**dict(r)) for r in rows]


class FineRepository:
    def __init__(self, conn): self.conn = conn

    def add(self, loan_id, member_id, amount_paise, created_on) -> int:
        cur = self.conn.execute(
            "INSERT INTO fines (loan_id,member_id,amount_paise,created_on) VALUES (?,?,?,?)",
            (loan_id, member_id, amount_paise, created_on))
        return cur.lastrowid

    def unpaid_total(self, member_id) -> int:
        return self.conn.execute(
            "SELECT COALESCE(SUM(amount_paise),0) FROM fines WHERE member_id=? AND paid_on IS NULL",
            (member_id,)).fetchone()[0]

    def pay_all(self, member_id, paid_on) -> int:
        total = self.unpaid_total(member_id)
        self.conn.execute("UPDATE fines SET paid_on=? WHERE member_id=? AND paid_on IS NULL", (paid_on, member_id))
        return total


class HolidayRepository:
    def __init__(self, conn): self.conn = conn

    def all_days(self) -> set:
        from .models import to_date
        return {to_date(r["day"]) for r in self.conn.execute("SELECT day FROM holidays")}


class Repositories:
    """Bundle so services get everything with one constructor argument."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.tiers = TierRepository(conn)
        self.members = MemberRepository(conn)
        self.books = BookRepository(conn)
        self.copies = CopyRepository(conn)
        self.loans = LoanRepository(conn)
        self.reservations = ReservationRepository(conn)
        self.fines = FineRepository(conn)
        self.holidays = HolidayRepository(conn)
