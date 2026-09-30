from fastapi.testclient import TestClient

from wheres_allie.api.app import create_app


def test_health(client, tmp_path):
    assert client.get("/api/health").json() == {"ok": True, "version": "0.1.0", "relay": "disabled"}
    assert (tmp_path / "wheres_allie.db").exists()  # create_app() used WA_DATA_DIR


def test_health_relay_configured_but_not_connected(settings, conn):
    settings.relay_url = "wss://relay.example/box"
    with TestClient(create_app(settings, conn=conn, start_background=False)) as c:
        assert c.get("/api/health").json()["relay"] == "offline"


def test_create_app_opens_db_in_data_dir(settings):
    create_app(settings, start_background=False)
    assert settings.db_path.exists()
