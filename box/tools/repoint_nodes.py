"""Point ESPresense nodes at another MQTT broker (reads current settings, resends all).

    set -a; . ../deploy/.env; set +a
    uv run python tools/repoint_nodes.py --host 192.168.5.254 --user wheres_allie
        --pass-env WA_MQTT_PASS --backup-dir ~/wheres-allie-node-backup
        office=192.168.5.232 --dry-run
"""

import argparse
import asyncio
import json
import os
from pathlib import Path

import httpx

from wheres_allie.nodes.espresense_http import get_main, push_settings, restart


async def run(args: argparse.Namespace) -> None:
    overrides = {"mqtt_host": args.host, "mqtt_port": args.port, "mqtt_user": args.user,
                 "mqtt_pass": os.environ[args.pass_env], "auto_update": False}
    async with httpx.AsyncClient() as client:
        for pair in args.nodes:
            room, ip = pair.split("=", 1)
            if args.backup_dir:
                backup = Path(args.backup_dir).expanduser()
                backup.mkdir(parents=True, exist_ok=True)
                current = await get_main(client, ip)
                (backup / f"{room}.json").write_text(json.dumps(current, indent=2))
            changes = await push_settings(client, ip, overrides, expect_room=room,
                                          dry_run=args.dry_run)
            for key, (old, new) in changes.items():
                print(f"{room}: {key}: {old!r} -> {new!r}")
            if args.dry_run:
                print(f"{room}: dry run, nothing saved")
            elif not args.no_restart:
                await restart(client, ip)
                print(f"{room}: saved, restarting")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("nodes", nargs="+", metavar="ROOM=IP")
    ap.add_argument("--host", required=True)
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--user", required=True)
    ap.add_argument("--pass-env", required=True, help="name of the env var holding the password")
    ap.add_argument("--backup-dir")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-restart", action="store_true")
    asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    main()
