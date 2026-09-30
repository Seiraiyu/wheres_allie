from pathlib import Path

import pytest
from pydantic import ValidationError

from wheres_allie.config import Settings


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("WA_MQTT_PASS", "s3cret")
    monkeypatch.setenv("WA_MQTT_PORT", "1884")
    monkeypatch.setenv("WA_DATA_DIR", "/tmp/wa")
    s = Settings()
    assert s.mqtt_pass == "s3cret"
    assert s.mqtt_port == 1884
    assert s.mqtt_host == "mosquitto"
    assert s.relay_url == ""
    assert s.db_path == Path("/tmp/wa/wheres_allie.db")


def test_mqtt_pass_required(monkeypatch):
    monkeypatch.delenv("WA_MQTT_PASS", raising=False)
    with pytest.raises(ValidationError):
        Settings()
