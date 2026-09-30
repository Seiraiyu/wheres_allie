import pytest

from wheres_allie import db


@pytest.fixture
def conn():
    c = db.connect(":memory:")
    db.migrate(c)
    yield c
    c.close()


@pytest.fixture
def settings(tmp_path):
    from wheres_allie.config import Settings
    return Settings(data_dir=tmp_path, mqtt_pass="test", web_dist=tmp_path / "no-dist")


@pytest.fixture
def client(tmp_path, monkeypatch):
    """TestClient on create_app() configured purely from env, with a temp WA_DATA_DIR."""
    from fastapi.testclient import TestClient

    from wheres_allie.api.app import create_app
    monkeypatch.setenv("WA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("WA_MQTT_PASS", "test")
    monkeypatch.setenv("WA_WEB_DIST", str(tmp_path / "no-dist"))
    with TestClient(create_app(start_background=False)) as c:
        yield c
