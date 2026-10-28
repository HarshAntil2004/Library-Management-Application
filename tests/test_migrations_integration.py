"""Integration: run the real migrations (incl. 2,000 books of sample data)."""
import subprocess
import sys
from pathlib import Path

import pytest

from library_app.db import connect, migrate

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def seeded():
    conn = connect(":memory:")
    applied = migrate(conn)
    return conn, applied


def scalar(conn, sql):
    return conn.execute(sql).fetchone()[0]


def test_all_migrations_apply_with_zero_errors(seeded):
    _, applied = seeded
    assert applied == ["001_schema.sql", "002_reference_data.sql", "003_seed_sample_data.py"]


def test_sample_data_volumes(seeded):
    conn, _ = seeded
    assert scalar(conn, "SELECT COUNT(*) FROM books") == 2000
    assert scalar(conn, "SELECT COUNT(*) FROM members") == 500
    assert scalar(conn, "SELECT COUNT(*) FROM copies") >= 2000
    assert scalar(conn, "SELECT COUNT(*) FROM loans") > 5000


def test_messy_history_was_quarantined_not_lost(seeded):
    conn, _ = seeded
    raw = scalar(conn, "SELECT COUNT(*) FROM loan_history_raw")
    loaded = scalar(conn, "SELECT COUNT(*) FROM loans")
    rejected = scalar(conn, "SELECT COUNT(*) FROM loan_quarantine WHERE action='rejected'")
    assert loaded + rejected == raw
    assert scalar(conn, "SELECT COUNT(*) FROM loan_quarantine WHERE action='repaired'") > 0


def test_loaded_data_is_consistent(seeded):
    conn, _ = seeded
    assert scalar(conn, "SELECT COUNT(*) FROM loans WHERE returned_on < issued_on") == 0
    assert scalar(conn, "SELECT COUNT(*) FROM (SELECT copy_id FROM loans WHERE returned_on IS NULL "
                        "GROUP BY copy_id HAVING COUNT(*)>1)") == 0
    assert scalar(conn, "SELECT COUNT(*) FROM copies c JOIN loans l ON l.copy_id=c.id "
                        "WHERE l.returned_on IS NULL AND c.status!='on_loan'") == 0
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_migrations_are_idempotent(seeded):
    conn, _ = seeded
    assert migrate(conn) == []


def test_failed_migration_rolls_back(tmp_path, monkeypatch):
    from library_app import db
    bad = tmp_path / "migs"; bad.mkdir()
    (bad / "001_ok.sql").write_text("CREATE TABLE a (x INTEGER);")
    (bad / "002_bad.sql").write_text("CREATE TABLE b (x INTEGER);\nINSERT INTO nope VALUES (1);")
    monkeypatch.setattr(db, "MIGRATIONS_DIR", bad)
    conn = connect(":memory:")
    with pytest.raises(Exception):
        migrate(conn)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "a" in tables and "b" not in tables               # 002 left no half-built table


def test_cli_end_to_end(tmp_path):
    db = str(tmp_path / "cli.db")
    run = lambda *a: subprocess.run([sys.executable, "-m", "library_app", "--db", db, "--today", "2026-10-27", *a],
                                    cwd=ROOT, capture_output=True, text=True)
    assert run("migrate").returncode == 0
    out = run("search", "--title", "Silent")
    assert out.returncode == 0 and "copies free" in out.stdout
    assert "overdue item(s)" in run("overdue", "--branch", "1").stdout
    bad = run("issue", "99999", "1")
    assert bad.returncode == 1 and "Cannot do that" in bad.stderr
