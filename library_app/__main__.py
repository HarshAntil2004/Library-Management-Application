"""Command-line front end:  python -m library_app --help"""
import argparse
import sys
from datetime import date

from .clock import FixedClock, SystemClock
from .db import connect, migrate
from .exceptions import LibraryError
from .models import inr
from .repositories import Repositories
from .services import (CatalogService, LendingService, MemberService,
                       ReportService, ReservationService)


def build_parser():
    p = argparse.ArgumentParser(prog="library_app", description="Lucknow Public Library CLI")
    p.add_argument("--db", default="data/library.db", help="SQLite file (default: data/library.db)")
    p.add_argument("--today", help="pretend today is YYYY-MM-DD (handy for demos)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("migrate", help="create/upgrade the database and load sample data")

    s = sub.add_parser("search", help="find books")
    s.add_argument("--title"); s.add_argument("--author"); s.add_argument("--isbn")

    o = sub.add_parser("overdue", help="overdue report")
    o.add_argument("--branch", type=int, help="branch id (1-3); omit for all branches")

    for name, args in {
        "issue": ["member", "copy"], "return": ["copy"], "renew": ["loan"],
        "reserve": ["member", "book"], "cancel-reservation": ["reservation"],
        "pay": ["member"], "expire-holds": [],
    }.items():
        c = sub.add_parser(name)
        for a in args:
            c.add_argument(a, type=int)

    r = sub.add_parser("register", help="register a new member")
    r.add_argument("name"); r.add_argument("email")
    r.add_argument("--tier", default="Basic"); r.add_argument("--branch", type=int, default=1)
    return p


def main(argv=None) -> int:
    a = build_parser().parse_args(argv)
    conn = connect(a.db)
    clock = FixedClock(date.fromisoformat(a.today)) if a.today else SystemClock()

    if a.cmd == "migrate":
        done = migrate(conn)
        print("Applied:", ", ".join(done) if done else "nothing - already up to date")
        return 0

    repos = Repositories(conn)
    try:
        if a.cmd == "search":
            for b in CatalogService(repos, clock).search(a.title, a.author, a.isbn):
                print(f"[{b['id']:>4}] {b['title']} - {b['author']} (ISBN {b['isbn']}) "
                      f"{b['available_copies']}/{b['total_copies']} copies free")
        elif a.cmd == "overdue":
            rows = ReportService(repos, clock).overdue_report(a.branch)
            branch = None
            for r in rows:
                if r["branch"] != branch:
                    branch = r["branch"]; print(f"\n== {branch} ==")
                print(f"  loan {r['loan_id']:>5} | {r['title'][:32]:<32} | {r['member'][:20]:<20} | "
                      f"due {r['due_on']} | {r['days_overdue']:>3}d late | fine so far {inr(r['fine_so_far_paise'])}")
            print(f"\n{len(rows)} overdue item(s)")
        elif a.cmd == "issue":
            print("Issued, loan id", LendingService(repos, clock).issue(a.member, a.copy))
        elif a.cmd == "return":
            fine = LendingService(repos, clock).return_copy(a.copy)
            print("Returned." + (f" Fine charged: {inr(fine)}" if fine else " No fine."))
        elif a.cmd == "renew":
            print("Renewed, new due date", LendingService(repos, clock).renew(a.loan))
        elif a.cmd == "reserve":
            print("Reserved, queue position", ReservationService(repos, clock).reserve(a.member, a.book))
        elif a.cmd == "cancel-reservation":
            ReservationService(repos, clock).cancel(a.reservation); print("Cancelled.")
        elif a.cmd == "expire-holds":
            print(ReservationService(repos, clock).expire_holds(), "hold(s) expired")
        elif a.cmd == "pay":
            print("Paid", inr(LendingService(repos, clock).pay_fines(a.member)))
        elif a.cmd == "register":
            print("Registered, member id", MemberService(repos, clock).register(a.name, a.email, a.tier, a.branch))
    except LibraryError as e:
        print(f"Cannot do that: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
