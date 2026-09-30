from wheres_allie.retention import DAY, prune

NOW = 1_800_000_000.0


def test_prune_tiers(conn):
    for age_days in (1, 29, 31, 364, 366):
        ts = NOW - age_days * DAY
        conn.execute("INSERT INTO readings VALUES (?, 1, 'office', -70, NULL, NULL)", (ts,))
        conn.execute("INSERT INTO positions VALUES (?, 1, 'room:x', NULL, NULL, 0.9, NULL)", (ts,))
        conn.execute("INSERT INTO motion VALUES (?, 1, 1)", (ts,))
    assert prune(conn, now=NOW) == {"readings": 3, "positions": 1}
    assert conn.execute("SELECT count(*) FROM readings").fetchone()[0] == 2
    assert conn.execute("SELECT count(*) FROM positions").fetchone()[0] == 4
    assert conn.execute("SELECT count(*) FROM motion").fetchone()[0] == 5
