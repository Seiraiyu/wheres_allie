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


@dataclass(frozen=True)
class NodeStatus:
    node_id: str
    online: bool


@dataclass(frozen=True)
class NodeTelemetry:
    node_id: str
    ip: str | None
    wifi_rssi: int | None
    uptime_s: int | None
    version: str | None


def _num(v) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _json(payload: bytes | str) -> dict | None:
    try:
        msg = json.loads(payload)
    except ValueError:
        return None
    return msg if isinstance(msg, dict) else None


def _room_topic(topic: str, leaf: str) -> str | None:
    parts = topic.split("/")
    if len(parts) == 4 and parts[0] == "espresense" and parts[1] == "rooms" and parts[3] == leaf:
        return parts[2]
    return None


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


def parse_room_status(topic: str, payload: bytes | str) -> NodeStatus | None:
    """`espresense/rooms/<node>/status` = online|offline (offline is the MQTT last will)."""
    node = _room_topic(topic, "status")
    text = payload.decode(errors="replace") if isinstance(payload, bytes) else payload
    if node is None or text not in ("online", "offline"):
        return None
    return NodeStatus(node, text == "online")


def parse_telemetry(topic: str, payload: bytes | str) -> NodeTelemetry | None:
    """`espresense/rooms/<node>/telemetry` JSON ({ip, uptime, rssi, ver, ...})."""
    node = _room_topic(topic, "telemetry")
    msg = _json(payload) if node else None
    if msg is None:
        return None
    rssi, uptime = _num(msg.get("rssi")), _num(msg.get("uptime"))
    return NodeTelemetry(
        node_id=node,
        ip=msg.get("ip") if isinstance(msg.get("ip"), str) else None,
        wifi_rssi=int(rssi) if rssi is not None else None,
        uptime_s=int(uptime) if uptime is not None else None,
        version=str(msg["ver"]) if "ver" in msg else None,
    )
