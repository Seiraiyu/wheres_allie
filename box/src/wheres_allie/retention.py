"""Tiered retention: raw readings 30 days, positions 1 year, everything else forever."""

import asyncio
import sqlite3
import time

DAY = 86400.0
READINGS_DAYS = 30
POSITIONS_DAYS = 365


def prune(conn: sqlite3.Connection, now: float | None = None) -> dict[str, int]:
    now = time.time() if now is None else now
    readings = conn.execute("DELETE FROM readings WHERE ts < ?",
                            (now - READINGS_DAYS * DAY,)).rowcount
    positions = conn.execute("DELETE FROM positions WHERE ts < ?",
                             (now - POSITIONS_DAYS * DAY,)).rowcount
    return {"readings": readings, "positions": positions}


async def run_retention(conn: sqlite3.Connection, every_s: float = 6 * 3600) -> None:
    # ponytail: fixed interval, not "nightly"; pin to 03:00 local if deletes ever stall ingest
    while True:
        await asyncio.to_thread(prune, conn)
        await asyncio.sleep(every_s)
