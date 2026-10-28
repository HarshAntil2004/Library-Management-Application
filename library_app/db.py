"""Connection handling, the Unit of Work and the migration runner."""
from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def connect(path: str = ":memory:") -> sqlite3.Connection:
    if path != ":memory:":
        Path(path).resolve().parent.mkdir(parents=True, exist_ok=True)   # first run: make data/ if missing
    # isolation_level=None means Python won't open transactions behind our back;
    # the UnitOfWork below decides exactly when BEGIN/COMMIT happen.
    conn = sqlite3.connect(path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


class UnitOfWork:
    """One business operation = one transaction.

    Services wrap their work in `with uow:`. If anything raises, everything
    done inside rolls back. Blocks can nest (issue() calling a helper that also
    uses the uow); only the outermost one really commits or rolls back.
    """

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self._depth = 0

    def __enter__(self):
        if self._depth == 0:
            # IMMEDIATE grabs the write lock up front so two desks can't
            # both read "copy available" and then both issue it.
            self.conn.execute("BEGIN IMMEDIATE")
        self._depth += 1
        return self

    def __exit__(self, exc_type, exc, tb):
        self._depth -= 1
        if self._depth == 0:
            self.conn.execute("ROLLBACK" if exc_type else "COMMIT")
        return False  # never swallow the exception


# ---------------------------------------------------------------- migrations

def _discover(upto: int | None):
    for f in sorted(MIGRATIONS_DIR.iterdir()):
        if f.suffix not in (".sql", ".py") or not f.name[:3].isdigit():
            continue
        version = int(f.name[:3])
        if upto is None or version <= upto:
            yield version, f


def migrate(conn: sqlite3.Connection, upto: int | None = None) -> list[str]:
    """Apply any migrations that haven't run yet. Returns the file names applied.

    Each migration runs inside its own transaction, so a failure leaves the
    database exactly as it was before that file started.
    """
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations "
        "(version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL "
        "DEFAULT CURRENT_TIMESTAMP)"
    )
    done = {r["version"] for r in conn.execute("SELECT version FROM schema_migrations")}
    applied = []
    for version, path in _discover(upto):
        if version in done:
            continue
        conn.execute("BEGIN")
        try:
            if path.suffix == ".sql":
                # executescript can't be driven inside our BEGIN, so run the
                # statements one at a time.
                for stmt in _split_sql(path.read_text(encoding="utf-8")):
                    conn.execute(stmt)
            else:
                spec = importlib.util.spec_from_file_location(f"mig_{version}", path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                module.upgrade(conn)
            conn.execute(
                "INSERT INTO schema_migrations (version, name) VALUES (?, ?)",
                (version, path.name),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        applied.append(path.name)
    return applied


def _split_sql(text: str) -> list[str]:
    """Split a .sql file into statements using sqlite's own completeness check."""
    statements, buf = [], ""
    for line in text.splitlines(keepends=True):
        buf += line
        if sqlite3.complete_statement(buf):
            if buf.strip():
                statements.append(buf.strip())
            buf = ""
    if buf.strip() and not all(l.strip().startswith("--") or not l.strip() for l in buf.splitlines()):
        statements.append(buf.strip())
    return statements
