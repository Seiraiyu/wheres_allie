"""Convert a raw MQTT log (`<iso-ts> <topic> <payload>` per line) into a replay bundle.

    uv run python tools/import_raw_log.py ../data/allie-raw.log ../data/allie-2026-09-28.bundle
"""

import argparse
import time
from datetime import datetime

from wheres_allie.ingest.parse import parse_device_message
from wheres_allie.replay.bundle import Bundle, write_bundle

ALLIE = "iBeacon:426c7565-4368-6172-6d42-6561636f6e73-3838-4949"


def parse_log(lines, ibeacon_id: str) -> list[tuple]:
    rows = []
    for line in lines:
        parts = line.rstrip("\n").split(" ", 2)
        if len(parts) != 3:
            continue
        try:
            ts = datetime.fromisoformat(parts[0]).timestamp()
        except ValueError:
            continue
        r = parse_device_message(parts[1], parts[2], ts)
        if r and r.ibeacon_id == ibeacon_id:
            rows.append((r.ts, r.ibeacon_id, r.node_id, r.rssi, r.distance, r.rssi_var))
    return rows


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("log")
    ap.add_argument("out")
    ap.add_argument("--pet", default="Allie")
    ap.add_argument("--ibeacon-id", default=ALLIE)
    ap.add_argument("--tz", default="America/New_York")
    args = ap.parse_args(argv)
    with open(args.log, encoding="utf-8", errors="replace") as f:
        readings = parse_log(f, args.ibeacon_id)
    if not readings:
        raise SystemExit(f"no readings for {args.ibeacon_id} in {args.log}")
    manifest = {
        "format": 1, "created": time.time(), "tz": args.tz,
        "pets": [{"name": args.pet, "ibeacon_id": args.ibeacon_id, "motion_ibeacon_id": None}],
        "from": readings[0][0], "to": readings[-1][0],
    }
    write_bundle(args.out, Bundle(manifest=manifest, readings=readings))
    print(f"{len(readings)} readings -> {args.out}")


if __name__ == "__main__":
    main()
