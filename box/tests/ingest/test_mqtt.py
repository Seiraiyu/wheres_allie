from wheres_allie.bus import Bus
from wheres_allie.ingest.mqtt import Ingestor

ALLIE = "iBeacon:426c7565-4368-6172-6d42-6561636f6e73-3838-4949"
ALLIE_MOVING = "iBeacon:426c7565-4368-6172-6d42-6561636f6e73-3838-4950"
PHONE = "iBeacon:e2c56db5-dffb-48d2-b060-d0f5a71096e0-1-2"


def dev(ident, node):
    return f"espresense/devices/{ident}/{node}"


def make(conn, motion=True):
    conn.execute("INSERT INTO pets (id, name) VALUES (1, 'Allie')")
    conn.execute("INSERT INTO tags (id, pet_id, ibeacon_id, motion_ibeacon_id) VALUES (7, 1, ?, ?)",
                 (ALLIE, ALLIE_MOVING if motion else None))
    return Ingestor(conn, Bus())


def test_registered_tag_reading_is_stored(conn):
    ing = make(conn)
    ing.handle(dev(ALLIE, "office"), b'{"rssi":-81.1,"distance":6.58,"rssiVar":7.42}', ts=10.0)
    rows = [tuple(r) for r in conn.execute("SELECT * FROM readings")]
    assert rows == [(10.0, 7, "office", -81.1, 6.58, 7.42)]


def test_unknown_devices_counted_not_stored(conn):
    ing = make(conn)
    ing.handle(dev(PHONE, "office"), b'{"rssi":-60}', ts=100.0)
    ing.handle(dev("apple:1005:9-26", "office"), b'{"rssi":-70}', ts=100.0)
    ing.handle(dev(PHONE, "kitchen"), b'{"rssi":-75}', ts=100.0)
    assert conn.execute("SELECT count(*) FROM readings").fetchone()[0] == 0
    assert ing.nearby_devices("office", now=200.0) == 2
    assert ing.nearby_devices("office", now=100.0 + 601) == 0
    assert ing.candidates(now=200.0) == [
        {"ibeacon_id": PHONE, "node_id": "office", "rssi": -60.0, "last_seen": 100.0}]


def test_reload_tags_picks_up_new_tag(conn):
    ing = Ingestor(conn, Bus())
    conn.execute("INSERT INTO pets (id, name) VALUES (1, 'Allie')")
    conn.execute("INSERT INTO tags (pet_id, ibeacon_id) VALUES (1, ?)", (ALLIE,))
    ing.handle(dev(ALLIE, "office"), b'{"rssi":-80}', ts=1.0)
    ing.reload_tags()
    ing.handle(dev(ALLIE, "office"), b'{"rssi":-80}', ts=2.0)
    assert conn.execute("SELECT count(*) FROM readings").fetchone()[0] == 1


def test_motion_edges(conn):
    ing = make(conn)
    ing.handle(dev(ALLIE_MOVING, "office"), b'{"rssi":-80}', ts=100.0)  # -> moving
    ing.handle(dev(ALLIE_MOVING, "kitchen"), b'{"rssi":-85}', ts=101.0)  # no new edge
    ing.handle(dev(ALLIE, "office"), b'{"rssi":-80}', ts=105.0)  # within hold: still moving
    ing.handle(dev(ALLIE, "office"), b'{"rssi":-80}', ts=112.0)  # -> still
    ing.handle(dev(ALLIE, "office"), b'{"rssi":-80}', ts=120.0)  # no new edge
    assert [tuple(r) for r in conn.execute("SELECT ts, tag_id, moving FROM motion")] == [
        (100.0, 7, 1), (112.0, 7, 0)]
    assert conn.execute("SELECT count(*) FROM readings").fetchone()[0] == 5


async def test_reading_published_on_bus(conn):
    ing = make(conn)
    with ing.bus.subscribe("reading") as sub:
        ing.handle(dev(ALLIE, "loft"), b'{"rssi":-90}', ts=5.0)
        topic, data = sub.queue.get_nowait()
    assert topic == "reading" and data["node_id"] == "loft" and data["tag_id"] == 7


def test_node_status_and_telemetry(conn):
    ing = Ingestor(conn, Bus())
    with ing.bus.subscribe("node.health") as sub:
        ing.handle("espresense/rooms/loft/status", b"online", ts=1.0)
        ing.handle("espresense/rooms/loft/telemetry",
                   b'{"ip":"192.168.5.222","uptime":60,"rssi":-70,"ver":"v4.0.6"}', ts=2.0)
        ing.handle("espresense/rooms/loft/status", b"offline", ts=3.0)
        events = [sub.queue.get_nowait() for _ in range(3)]
    row = dict(conn.execute("SELECT * FROM nodes WHERE id = 'loft'").fetchone())
    assert row == {
        "id": "loft", "name": None, "online": 0, "last_seen": 3.0, "ip": "192.168.5.222",
        "wifi_rssi": -70, "uptime_s": 60, "version": "v4.0.6", "calib_json": None}
    assert [e[1]["online"] for e in events] == [True, True, False]
