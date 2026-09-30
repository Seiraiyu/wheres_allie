"""MQTT ingest: ESPresense messages -> readings, motion edges, node health."""

import asyncio
import logging
import os
import sqlite3
import time

import aiomqtt

from wheres_allie.bus import Bus
from wheres_allie.config import Settings
from wheres_allie.ingest.parse import (
    DeviceReading,
    NodeStatus,
    NodeTelemetry,
    parse_device_message,
    parse_room_status,
    parse_telemetry,
)

log = logging.getLogger(__name__)

MOTION_HOLD_S = 10.0  # BC021 keeps the motion id up ~10 s; normal id within this is still "moving"
UNKNOWN_TTL_S = 600.0  # unregistered devices count as "nearby" for 10 min
GAP_MIN_S = 10.0


class Ingestor:
    def __init__(self, conn: sqlite3.Connection, bus: Bus):
        self.conn, self.bus = conn, bus
        self.tags: dict[str, tuple[int, bool]] = {}  # ibeacon id -> (tag_id, is_motion_id)
        self.moving: dict[int, bool] = {}
        self.last_motion: dict[int, float] = {}
        self.unknown: dict[tuple[str, str], tuple[float, float]] = {}  # (node, id) -> (ts, rssi)
        self.reload_tags()

    def reload_tags(self) -> None:
        tags: dict[str, tuple[int, bool]] = {}
        for r in self.conn.execute("SELECT id, ibeacon_id, motion_ibeacon_id FROM tags"):
            tags[r["ibeacon_id"]] = (r["id"], False)
            if r["motion_ibeacon_id"]:
                tags[r["motion_ibeacon_id"]] = (r["id"], True)
        self.tags = tags

    def handle(self, topic: str, payload: bytes | str, ts: float | None = None) -> None:
        ts = time.time() if ts is None else ts
        if topic.startswith("espresense/devices/"):
            if r := parse_device_message(topic, payload, ts):
                self._reading(r)
        elif topic.endswith("/status"):
            if s := parse_room_status(topic, payload):
                self._status(s, ts)
        elif topic.endswith("/telemetry"):
            if t := parse_telemetry(topic, payload):
                self._telemetry(t, ts)

    def _reading(self, r: DeviceReading) -> None:
        hit = self.tags.get(r.ibeacon_id)
        if hit is None:
            self.unknown[(r.node_id, r.ibeacon_id)] = (r.ts, r.rssi)
            if len(self.unknown) > 5000:  # phones rotate MACs; keep the dict bounded
                self._prune(r.ts)
            return
        tag_id, is_motion_id = hit
        self.conn.execute(
            "INSERT INTO readings (ts, tag_id, node_id, rssi, distance, rssi_var) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (r.ts, tag_id, r.node_id, r.rssi, r.distance, r.rssi_var),
        )
        if is_motion_id:
            self.last_motion[tag_id] = r.ts
            if not self.moving.get(tag_id):
                self._motion(r.ts, tag_id, True)
        elif self.moving.get(tag_id) and r.ts - self.last_motion[tag_id] > MOTION_HOLD_S:
            self._motion(r.ts, tag_id, False)
        self.bus.publish("reading", {"ts": r.ts, "tag_id": tag_id, "node_id": r.node_id,
                                     "rssi": r.rssi, "distance": r.distance})

    def _motion(self, ts: float, tag_id: int, moving: bool) -> None:
        self.moving[tag_id] = moving
        self.conn.execute("INSERT INTO motion (ts, tag_id, moving) VALUES (?, ?, ?)",
                          (ts, tag_id, int(moving)))

    def _status(self, s: NodeStatus, ts: float) -> None:
        self.conn.execute(
            "INSERT INTO nodes (id, online, last_seen) VALUES (?, ?, ?) ON CONFLICT(id) DO UPDATE "
            "SET online = excluded.online, last_seen = excluded.last_seen",
            (s.node_id, int(s.online), ts),
        )
        self._publish_node(s.node_id)

    def _telemetry(self, t: NodeTelemetry, ts: float) -> None:
        self.conn.execute(
            "INSERT INTO nodes (id, online, last_seen, ip, wifi_rssi, uptime_s, version) "
            "VALUES (?, 1, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET online = 1, "
            "last_seen = excluded.last_seen, ip = excluded.ip, wifi_rssi = excluded.wifi_rssi, "
            "uptime_s = excluded.uptime_s, version = excluded.version",
            (t.node_id, ts, t.ip, t.wifi_rssi, t.uptime_s, t.version),
        )
        self._publish_node(t.node_id)

    def _publish_node(self, node_id: str) -> None:
        row = self.conn.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
        self.bus.publish("node.health", dict(row) | {"online": bool(row["online"])})

    def _prune(self, now: float) -> None:
        self.unknown = {k: v for k, v in self.unknown.items() if now - v[0] <= UNKNOWN_TTL_S}

    def nearby_devices(self, node_id: str, now: float | None = None) -> int:
        now = time.time() if now is None else now
        return sum(1 for (n, _), (ts, _) in self.unknown.items()
                   if n == node_id and now - ts <= UNKNOWN_TTL_S)

    def candidates(self, now: float | None = None) -> list[dict]:
        """Unregistered iBeacons heard in the last 10 min, strongest first (for tag setup)."""
        now = time.time() if now is None else now
        best: dict[str, dict] = {}
        for (node, dev), (ts, rssi) in self.unknown.items():
            if not dev.startswith("iBeacon:") or now - ts > UNKNOWN_TTL_S:
                continue
            if dev not in best or rssi > best[dev]["rssi"]:
                best[dev] = {"ibeacon_id": dev, "node_id": node, "rssi": rssi, "last_seen": ts}
        return sorted(best.values(), key=lambda c: -c["rssi"])


def record_gap(conn: sqlite3.Connection, start: float, end: float) -> None:
    if end - start > GAP_MIN_S:
        conn.execute("INSERT INTO gaps (ts_start, ts_end, reason) VALUES (?, ?, 'mqtt_disconnect')",
                     (start, end))


async def run_ingest(settings: Settings, conn: sqlite3.Connection, bus: Bus,
                     ingestor: Ingestor | None = None) -> None:
    ingestor = ingestor or Ingestor(conn, bus)
    backoff, down_since = 1.0, time.time()
    while True:
        try:
            async with aiomqtt.Client(
                settings.mqtt_host, settings.mqtt_port, username=settings.mqtt_user,
                password=settings.mqtt_pass, identifier=f"wheres-allie-{os.getpid()}",
            ) as client:
                await client.subscribe("espresense/devices/+/+")
                await client.subscribe("espresense/rooms/+/+")
                log.info("mqtt connected to %s:%s", settings.mqtt_host, settings.mqtt_port)
                record_gap(conn, down_since, time.time())
                backoff = 1.0
                async for msg in client.messages:
                    ingestor.handle(str(msg.topic), msg.payload)
        except aiomqtt.MqttError as e:
            down_since = time.time()
            log.warning("mqtt: %s; retrying in %.0f s", e, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)
