"""003: synthetic sample data.

Loads 2,000 books, ~4,500 copies, 500 members and a year of loan history.
The history is written into a raw staging table *with deliberate mistakes*
(like the paper registers would have), then validated row by row: good rows go
into `loans`, repairable rows are fixed and logged, and untrustworthy rows are
quarantined with a reason. Nothing is silently dropped.

Everything is seeded with random.seed(2026) so every run produces the same data.
"""
import random
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from library_app import isbn as isbn_tools                      # noqa: E402
from library_app.fines import FineCalculator, LibraryCalendar    # noqa: E402
from library_app.models import Tier, to_date                     # noqa: E402

TODAY = date(2026, 10, 27)
HISTORY_START = date(2025, 10, 28)

ADJ = ["Silent", "Golden", "Hidden", "Broken", "Midnight", "Crimson", "Forgotten", "Distant", "Burning",
       "Quiet", "Last", "First", "Lost", "Secret", "Endless", "Winter", "Monsoon", "Ivory", "Restless", "Hollow",
       "Wandering", "Fragile", "Bright", "Dark", "Ancient", "Gentle", "Wild", "Silver", "Scarlet", "Humble",
       "Painted", "Salted", "Weary", "Radiant", "Narrow", "Open", "Clay", "Paper", "Copper", "Marble"]
NOUN = ["River", "Garden", "Empire", "Letter", "Window", "Mirror", "Harvest", "Journey", "Kingdom", "Orchard",
        "Lantern", "Bridge", "Promise", "Shadow", "Compass", "Festival", "Archive", "Season", "Courtyard", "Voyage",
        "Tide", "Manuscript", "Bazaar", "Horizon", "Carriage", "Melody", "Citadel", "Monsoon", "Atlas", "Thread",
        "Fortress", "Echo", "Saffron", "Ledger", "Pilgrim", "Mosaic", "Almanac", "Ember", "Threshold", "Cartographer",
        "Nightingale", "Workshop", "Station", "Inheritance", "Clocktower", "Passage", "Reckoning", "Verandah",
        "Heirloom", "Wanderer"]
FIRST = ["Aarav", "Meera", "Rohan", "Ananya", "Vikram", "Priya", "Arjun", "Kavya", "Imran", "Sana", "Rahul",
         "Neha", "Siddharth", "Pooja", "Faisal", "Zoya", "Karan", "Ishita", "Manish", "Divya", "Anil", "Sunita",
         "Deepak", "Rekha", "Tarun", "Shweta", "Harsh", "Nidhi", "Yusuf", "Farah", "Amit", "Swati", "Rajesh", "Mona"]
LAST = ["Sharma", "Verma", "Mishra", "Srivastava", "Tiwari", "Khan", "Ansari", "Gupta", "Yadav", "Pandey",
        "Dubey", "Rizvi", "Naqvi", "Saxena", "Agarwal", "Trivedi", "Kapoor", "Shukla", "Bajpai", "Awasthi"]
GENRES = ["Fiction", "History", "Science", "Biography", "Poetry", "Children", "Mystery", "Self-Help",
          "Philosophy", "Technology", "Travel", "Civics"]


def upgrade(conn):
    rnd = random.Random(2026)

    tiers = {r["id"]: Tier(**dict(r)) for r in conn.execute("SELECT * FROM membership_tiers")}
    calc = FineCalculator(LibraryCalendar({to_date(r["day"]) for r in conn.execute("SELECT day FROM holidays")}))

    # ---- authors and books (2,000)
    authors = [f"{rnd.choice(FIRST)} {rnd.choice(LAST)}" for _ in range(220)]
    books = []
    for i in range(2000):
        title = f"The {rnd.choice(ADJ)} {rnd.choice(NOUN)}"
        if rnd.random() < 0.35:
            title += f" of {rnd.choice(NOUN)}s"
        base = f"97893{i:07d}"
        books.append((i + 1, base + isbn_tools.check_digit(base), title, rnd.choice(authors),
                      rnd.choice(GENRES), rnd.randint(1950, 2025)))
    conn.executemany("INSERT INTO books VALUES (?,?,?,?,?,?)", books)

    # ---- copies (1-4 per title, spread over the 3 branches)
    copies = []
    cid = 0
    for b in books:
        for _ in range(rnd.choice([1, 2, 2, 3, 4])):
            cid += 1
            copies.append((cid, b[0], rnd.randint(1, 3), f"LKO-{cid:06d}", "available"))
    conn.executemany("INSERT INTO copies VALUES (?,?,?,?,?)", copies)

    # ---- members (500)
    members = []
    for i in range(500):
        name = f"{rnd.choice(FIRST)} {rnd.choice(LAST)}"
        status = rnd.choices(["active", "suspended", "expired"], [94, 3, 3])[0]
        joined = date(2024, 1, 1) + timedelta(days=rnd.randint(0, 640))
        members.append((i + 1, name, f"{name.lower().replace(' ', '.')}.{i + 1}@example.in",
                        f"+91 9{rnd.randint(100000000, 999999999)}",
                        rnd.choices([1, 2, 3], [50, 35, 15])[0], rnd.randint(1, 3),
                        joined.isoformat(), status))
    conn.executemany("INSERT INTO members VALUES (?,?,?,?,?,?,?,?)", members)
    member_tier = {m[0]: m[4] for m in members}
    active_ids = [m[0] for m in members if m[7] == "active"]

    # ---- a year of loan history, written to the raw staging table
    raw = []
    for c in copies:
        if rnd.random() > 0.25:
            continue
        cursor = HISTORY_START + timedelta(days=rnd.randint(0, 60))
        while cursor < TODAY:
            mid = rnd.choice(active_ids)
            period = tiers[member_tier[mid]].loan_days
            due = cursor + timedelta(days=period)
            actual = rnd.choices([rnd.randint(2, period), period + rnd.randint(1, 12), period + rnd.randint(13, 40)],
                                 [70, 22, 8])[0]
            returned = cursor + timedelta(days=actual)
            if returned >= TODAY:
                raw.append([c[0], mid, cursor.isoformat(), due.isoformat(), None])
                break
            raw.append([c[0], mid, cursor.isoformat(), due.isoformat(), returned.isoformat()])
            cursor = returned + timedelta(days=rnd.randint(2, 90))

    clean_count = len(raw)
    # ---- inject the kind of mess a paper register has
    def pick(n):
        return rnd.sample(range(len(raw)), n)

    for i in pick(60):                                   # returned before issued
        raw[i][4] = (to_date(raw[i][2]) - timedelta(days=rnd.randint(1, 10))).isoformat()
    for i in pick(40):                                   # due date never written down
        raw[i][3] = None
    for i in pick(25):                                   # member id that doesn't exist
        raw[i][1] = rnd.randint(900, 999)
    for i in pick(20):                                   # copy id that doesn't exist
        raw[i][0] = rnd.randint(90000, 99999)
    for i in pick(25):                                   # "returned" in the future
        raw[i][4] = (TODAY + timedelta(days=rnd.randint(3, 60))).isoformat()
    for i in pick(30):                                   # same entry copied twice
        raw.append(list(raw[i]))
    for i in pick(20):                                   # second open loan on the same copy
        raw.append([raw[i][0], rnd.choice(active_ids), (TODAY - timedelta(days=rnd.randint(1, 20))).isoformat(),
                    TODAY.isoformat(), None])
    rnd.shuffle(raw)
    conn.executemany(
        "INSERT INTO loan_history_raw (copy_id, member_id, issued_on, due_on, returned_on) VALUES (?,?,?,?,?)", raw)

    # ---- validate + load
    copy_ids = {c[0] for c in copies}
    member_ids = set(member_tier)
    rows = conn.execute("SELECT * FROM loan_history_raw ORDER BY copy_id, issued_on, id").fetchall()
    seen, last_end, open_copies = set(), {}, set()
    for r in rows:
        key = (r["copy_id"], r["member_id"], r["issued_on"], r["returned_on"])
        reason = None
        if key in seen:
            reason = "duplicate of an earlier row"
        elif r["copy_id"] not in copy_ids:
            reason = "unknown copy id"
        elif r["member_id"] not in member_ids:
            reason = "unknown member id"
        elif r["returned_on"] and r["returned_on"] < r["issued_on"]:
            reason = "returned before it was issued"
        elif r["returned_on"] and to_date(r["returned_on"]) > TODAY:
            reason = "return date is in the future"
        elif r["returned_on"] is None and r["copy_id"] in open_copies:
            reason = "copy already has an open loan"
        elif last_end.get(r["copy_id"]) and r["issued_on"] < last_end[r["copy_id"]]:
            reason = "overlaps the previous loan of this copy"
        seen.add(key)
        if reason:
            conn.execute("INSERT INTO loan_quarantine (raw_id, reason, action) VALUES (?,?,'rejected')",
                         (r["id"], reason))
            continue

        due = r["due_on"]
        if due is None:                                  # repairable: apply the member's loan period
            due = (to_date(r["issued_on"]) + timedelta(days=tiers[member_tier[r["member_id"]]].loan_days)).isoformat()
            conn.execute("INSERT INTO loan_quarantine (raw_id, reason, action) VALUES (?,?,'repaired')",
                         (r["id"], "missing due date, recomputed from tier loan period"))
        cur = conn.execute(
            "INSERT INTO loans (copy_id, member_id, issued_on, due_on, returned_on) VALUES (?,?,?,?,?)",
            (r["copy_id"], r["member_id"], r["issued_on"], due, r["returned_on"]))
        if r["returned_on"] is None:
            open_copies.add(r["copy_id"])
            conn.execute("UPDATE copies SET status='on_loan' WHERE id=?", (r["copy_id"],))
        else:
            last_end[r["copy_id"]] = r["returned_on"]
            fine = calc.fine(tiers[member_tier[r["member_id"]]], to_date(due), to_date(r["returned_on"]))
            if fine > 0:
                paid = None if rnd.random() < 0.04 else r["returned_on"]
                conn.execute("INSERT INTO fines (loan_id, member_id, amount_paise, created_on, paid_on) "
                             "VALUES (?,?,?,?,?)", (cur.lastrowid, r["member_id"], fine, r["returned_on"], paid))

    # ---- a few live reservations on titles where every copy is out
    stuck = conn.execute("""
        SELECT book_id FROM copies GROUP BY book_id
        HAVING SUM(status='available') = 0 ORDER BY RANDOM() LIMIT 25""").fetchall()
    for s in stuck:
        for m in rnd.sample(active_ids, rnd.randint(1, 3)):
            have = conn.execute("""SELECT 1 FROM loans l JOIN copies c ON c.id=l.copy_id
                WHERE l.member_id=? AND c.book_id=? AND l.returned_on IS NULL""", (m, s["book_id"])).fetchone()
            if not have:
                conn.execute("INSERT OR IGNORE INTO reservations (book_id, member_id, created_at) VALUES (?,?,?)",
                             (s["book_id"], m, (TODAY - timedelta(days=rnd.randint(0, 15))).isoformat()))
