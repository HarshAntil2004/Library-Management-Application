-- 001: core schema for the Lucknow Public Library network.
-- Money is stored as integer paise so we never fight float rounding.

CREATE TABLE branches (
    id    INTEGER PRIMARY KEY,
    name  TEXT NOT NULL UNIQUE,
    area  TEXT NOT NULL
);

CREATE TABLE membership_tiers (
    id               INTEGER PRIMARY KEY,
    name             TEXT NOT NULL UNIQUE,
    max_loans        INTEGER NOT NULL CHECK (max_loans > 0),
    loan_days        INTEGER NOT NULL CHECK (loan_days > 0),
    max_renewals     INTEGER NOT NULL CHECK (max_renewals >= 0),
    annual_fee_paise INTEGER NOT NULL CHECK (annual_fee_paise >= 0),
    fine_policy      TEXT NOT NULL CHECK (fine_policy IN ('flat', 'escalating')),
    fine_rate_paise  INTEGER NOT NULL CHECK (fine_rate_paise >= 0),
    grace_days       INTEGER NOT NULL CHECK (grace_days >= 0),
    fine_cap_paise   INTEGER NOT NULL CHECK (fine_cap_paise >= 0)
);

CREATE TABLE members (
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL,
    email           TEXT NOT NULL UNIQUE,
    phone           TEXT,
    tier_id         INTEGER NOT NULL REFERENCES membership_tiers(id),
    home_branch_id  INTEGER NOT NULL REFERENCES branches(id),
    joined_on       TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'suspended', 'expired'))
);

CREATE TABLE books (
    id              INTEGER PRIMARY KEY,
    isbn            TEXT NOT NULL UNIQUE,
    title           TEXT NOT NULL,
    author          TEXT NOT NULL,
    genre           TEXT NOT NULL,
    published_year  INTEGER
);
CREATE INDEX idx_books_title  ON books(title);
CREATE INDEX idx_books_author ON books(author);

CREATE TABLE copies (
    id         INTEGER PRIMARY KEY,
    book_id    INTEGER NOT NULL REFERENCES books(id),
    branch_id  INTEGER NOT NULL REFERENCES branches(id),
    barcode    TEXT NOT NULL UNIQUE,
    status     TEXT NOT NULL DEFAULT 'available'
               CHECK (status IN ('available', 'on_loan', 'held', 'lost'))
);
CREATE INDEX idx_copies_book ON copies(book_id);

CREATE TABLE loans (
    id           INTEGER PRIMARY KEY,
    copy_id      INTEGER NOT NULL REFERENCES copies(id),
    member_id    INTEGER NOT NULL REFERENCES members(id),
    issued_on    TEXT NOT NULL,
    due_on       TEXT NOT NULL,
    returned_on  TEXT,
    renewals     INTEGER NOT NULL DEFAULT 0,
    CHECK (due_on >= issued_on),
    CHECK (returned_on IS NULL OR returned_on >= issued_on)
);
-- The database itself refuses two open loans on one physical copy.
CREATE UNIQUE INDEX one_open_loan_per_copy ON loans(copy_id) WHERE returned_on IS NULL;
CREATE INDEX idx_loans_member ON loans(member_id);

CREATE TABLE reservations (
    id            INTEGER PRIMARY KEY,
    book_id       INTEGER NOT NULL REFERENCES books(id),
    member_id     INTEGER NOT NULL REFERENCES members(id),
    created_at    TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'queued'
                  CHECK (status IN ('queued', 'ready', 'fulfilled', 'cancelled', 'expired')),
    held_copy_id  INTEGER REFERENCES copies(id),
    expires_on    TEXT
);
CREATE UNIQUE INDEX one_live_reservation
    ON reservations(book_id, member_id) WHERE status IN ('queued', 'ready');

CREATE TABLE fines (
    id            INTEGER PRIMARY KEY,
    loan_id       INTEGER NOT NULL UNIQUE REFERENCES loans(id),
    member_id     INTEGER NOT NULL REFERENCES members(id),
    amount_paise  INTEGER NOT NULL CHECK (amount_paise > 0),
    created_on    TEXT NOT NULL,
    paid_on       TEXT
);
CREATE INDEX idx_fines_member ON fines(member_id);

CREATE TABLE holidays (
    day   TEXT PRIMARY KEY,
    name  TEXT NOT NULL
);

-- Staging area for the legacy register data. Deliberately untyped and
-- unconstrained: this is where the messy rows land before we clean them.
CREATE TABLE loan_history_raw (
    id          INTEGER PRIMARY KEY,
    copy_id     INTEGER,
    member_id   INTEGER,
    issued_on   TEXT,
    due_on      TEXT,
    returned_on TEXT
);

-- Rows we could not trust (or had to repair) end up here with the reason.
CREATE TABLE loan_quarantine (
    id        INTEGER PRIMARY KEY,
    raw_id    INTEGER NOT NULL,
    reason    TEXT NOT NULL,
    action    TEXT NOT NULL CHECK (action IN ('rejected', 'repaired'))
);
