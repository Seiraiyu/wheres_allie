"""Parse ESPresense v4 MQTT messages."""

import json
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class DeviceReading:
    ts: float
    ibeacon_id: str
    node_id: str
    rssi: float
    distance: float | None
    rssi_var: float | None


def _num(v) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _json(payload: bytes | str) -> dict | None:
    try:
        msg = json.loads(payload)
    except ValueError:
        return None
    return msg if isinstance(msg, dict) else None


def parse_device_message(
    topic: str, payload: bytes | str, ts: float | None = None
) -> DeviceReading | None:
    """`espresense/devices/<ibeacon_id>/<node_id>` JSON -> DeviceReading (ts defaults to now)."""
    parts = topic.split("/")
    if len(parts) != 4 or parts[0] != "espresense" or parts[1] != "devices":
        return None
    msg = _json(payload)
    if msg is None or _num(msg.get("rssi")) is None:
        return None
    return DeviceReading(
        ts=time.time() if ts is None else ts,
        ibeacon_id=parts[2],
        node_id=parts[3],
        rssi=float(msg["rssi"]),
        distance=_num(msg.get("distance")),
        rssi_var=_num(msg.get("rssiVar")),
    )
