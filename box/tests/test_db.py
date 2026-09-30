from wheres_allie import db

TABLES = {"settings", "home", "nodes", "pets", "tags", "readings", "motion", "positions",
          "visits", "labels", "gaps", "rollups"}


def test_migrate_creates_all_tables_and_is_idempotent(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    db.migrate(conn)
    db.migrate(conn)
    names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert TABLES <= names
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_settings_helpers(conn):
    assert db.get_setting(conn, "tz", "UTC") == "UTC"
    db.set_setting(conn, "tz", "America/Chicago")
    db.set_setting(conn, "tz", "America/Denver")
    assert db.get_setting(conn, "tz") == "America/Denver"
