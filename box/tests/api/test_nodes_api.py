import json
import time


def test_nodes_with_health_placed_and_nearby(client):
    conn, ing = client.app.state.conn, client.app.state.ingestor
    ing.handle("espresense/rooms/office/telemetry",
               b'{"ip":"192.168.5.232","uptime":5,"rssi":-60,"ver":"v4.0.6"}')
    ing.handle("espresense/rooms/loft/status", b"offline")
    ing.handle("espresense/devices/apple:1005:9-26/office", b'{"rssi":-70}', ts=time.time())
    conn.execute("INSERT INTO home (saved_at, json) VALUES (0, ?)",
                 (json.dumps({"nodes": [{"id": "office"}]}),))
    nodes = client.get("/api/nodes").json()
    assert [(n["id"], n["online"], n["placed"], n["nearby_devices"]) for n in nodes] == [
        ("loft", False, False, 0), ("office", True, True, 1)]
    assert nodes[1]["ip"] == "192.168.5.232"
