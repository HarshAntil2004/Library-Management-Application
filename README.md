# Lucknow Public Library Management System

A transactional lending system for a fictional three-branch Lucknow library network
(Hazratganj, Aminabad, Gomti Nagar). It handles books and copies, membership tiers,
issue / return / renewal, reservation queues and fines that understand Sundays,
holidays, grace periods and caps.

Pure Python 3.10+ and SQLite. The only dependency is `pytest` for the tests.

## Quick start

```bash
git clone <your-repo-url> && cd lucknow-library
python -m venv .venv && source .venv/bin/activate     # optional
pip install -r requirements.txt

python -m library_app migrate            # builds data/library.db + loads sample data
python -m pytest -v                      # 64 tests, about a second
```

### Try it

```bash
python -m library_app search --title "Silent"
python -m library_app search --author "Sharma"
python -m library_app search --isbn 9789300000002
python -m library_app overdue                    # all branches
python -m library_app overdue --branch 2         # one branch
python -m library_app register "Asha Verma" asha@example.in --tier Premium --branch 1
python -m library_app issue <member_id> <copy_id>
python -m library_app return <copy_id>
python -m library_app renew <loan_id>
python -m library_app reserve <member_id> <book_id>
python -m library_app pay <member_id>
python -m library_app --today 2026-12-01 overdue   # time-travel for demos
```

Business-rule failures print `Cannot do that: <reason>` and exit with code 1.

## Sample data (loaded by migration 003)

| What | Count |
|---|---|
| Books | 2,000 |
| Physical copies | 4,744 |
| Members | 500 (Basic / Standard / Premium) |
| Raw loan-history rows (one year) | 7,079 |
| Loans loaded after cleaning | 6,907 |
| Rows rejected into quarantine | 172 |
| Rows repaired (missing due date) | 40 |

The raw history deliberately contains the sort of mistakes a paper register has:
returned-before-issued, missing due dates, unknown members/copies, future return dates,
duplicated entries and two open loans on one copy. Nothing is dropped silently:
every bad row is kept in `loan_quarantine` with a reason. Data is seeded
(`random.seed(2026)`), so every run produces identical data.

## Project layout

```
library_app/
  models.py        domain classes (Tier, Member, Book, Copy, Loan, Reservation)
  repositories.py  all SQL lives here
  services.py      business rules: Lending, Reservation, Member, Catalog, Report
  fines.py         calendar + fine policies (Strategy)
  db.py            connection, UnitOfWork, migration runner
  exceptions.py    one exception type per rule
  __main__.py      command-line interface
migrations/        001 schema, 002 reference data, 003 sample data
tests/             64 unit + integration tests
docs/              class diagram, ER diagram, test results (.dot sources included)
```

## Business rules and where they are tested

| Rule | Test file |
|---|---|
| Loan limit per tier (3 / 5 / 10) | test_lending.py |
| Unpaid fines block issue and renewal | test_lending.py, test_reservations_renewals.py |
| Reserved copies can only go to the reserver | test_reservations_renewals.py |
| Reservation queue is first-come-first-served; holds expire | test_reservations_renewals.py |
| Renewal limits, no renewing overdue or wanted books | test_reservations_renewals.py |
| Fines: grace, cap, Sundays, holidays, tier policies | test_fines.py |
| Atomic issue/return, rollback on failure | test_transactions.py |
| Member registration, validation, tier changes | test_catalog_members.py |
| Migrations, sample data, quarantine, CLI | test_migrations_integration.py |

Full output is in `docs/test_results.txt`.

## Design decisions and trade-offs

**Layering (domain / repository / service).** SQL appears only in repositories; rules
only in services. The cost is some boilerplate for simple lookups; the gain is that
rules can be tested against an in-memory database without any UI.

**Unit of Work for transactions.** Every service method is one `with uow:` block, so a
failure halfway rolls the whole operation back. It uses `BEGIN IMMEDIATE` so two desks
can't both see a copy as free. Trade-off: SQLite allows one writer at a time, which is
fine for three branches but would need row-level locking on PostgreSQL.

**Strategy pattern for fines.** The calendar decides *which days count*; a policy object
decides *what N days cost*. Basic uses an escalating rate, Standard/Premium a flat one.
A new tier rule is a new small class and the date logic stays untouched. A factory
(`policy_for`) turns a tier row into the right policy.

**Database as a second line of defence.** CHECK constraints plus partial unique indexes
("one open loan per copy", "one live reservation per member per book") mean a bug in the
service layer can't corrupt data. Trade-off: some rules are written twice.

**Holds are modelled as a copy status.** A returned copy with a queue becomes `held` for
3 days for the first member in line; `expire_holds()` passes it on. This makes "prevent
issuing reserved copies" a one-line check. Trade-off: the queue is per title across the
whole network, not per branch, so a member may collect from another branch.

**Fines:** Sundays and listed holidays are free days; a book due on a closed day is due
the next open day; the grace period is subtracted from chargeable days (not a
"forgive if under N" cliff); every tier has a cap. Money is stored as integer paise.
Holiday dates are approximate because lunar festivals shift.

**Dirty history is staged, not forced.** Raw rows go into an unconstrained table first,
then are validated into `loans`. Trade-off: extra tables and a longer migration, but
the legacy mess is auditable and not lost.

**SQLite + CLI.** Zero setup for a reviewer. A web UI was left out on purpose; the
service layer is UI-agnostic, so one could be added without touching the rules.

## Known limitations

- Fines are charged on return, not accrued nightly; there is no payment partial-settlement.
- No authentication or staff roles: the CLI trusts its operator.
- Lost-book charges and membership-fee billing are not implemented.
