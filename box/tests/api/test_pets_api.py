import time

ALLIE = "iBeacon:426c7565-4368-6172-6d42-6561636f6e73-3838-4949"
MOVING = "iBeacon:426c7565-4368-6172-6d42-6561636f6e73-3838-4950"


def test_create_pet_and_tag(client):
    conn = client.app.state.conn
    pet = client.post("/api/pets", json={"name": "Allie"}).json()
    assert pet == {"id": 1, "name": "Allie", "species": "dog", "tags": []}
    r = client.post("/api/pets/1/tags", json={"ibeacon_id": ALLIE, "motion_ibeacon_id": MOVING})
    assert r.json()["tags"] == [
        {"id": 1, "pet_id": 1, "ibeacon_id": ALLIE, "motion_ibeacon_id": MOVING}]
    assert client.get("/api/pets").json() == [r.json()]
    # the ingestor picked the tag up without a restart
    client.app.state.ingestor.handle(f"espresense/devices/{ALLIE}/office", b'{"rssi":-70}')
    assert conn.execute("SELECT count(*) FROM readings").fetchone()[0] == 1


def test_conflicts_and_missing(client):
    client.post("/api/pets", json={"name": "Allie"})
    assert client.post("/api/pets", json={"name": "Allie"}).status_code == 409
    assert client.post("/api/pets/1/tags", json={"ibeacon_id": ALLIE}).status_code == 200
    assert client.post("/api/pets/1/tags", json={"ibeacon_id": ALLIE}).status_code == 409
    assert client.post("/api/pets/9/tags", json={"ibeacon_id": MOVING}).status_code == 404
    assert client.post("/api/pets", json={"name": ""}).status_code == 422


def test_candidates(client):
    client.app.state.ingestor.handle(f"espresense/devices/{ALLIE}/kitchen", b'{"rssi":-55}',
                                     ts=time.time())
    cands = client.get("/api/tags/candidates").json()
    assert [(c["ibeacon_id"], c["node_id"], c["rssi"]) for c in cands] == [(ALLIE, "kitchen", -55)]
