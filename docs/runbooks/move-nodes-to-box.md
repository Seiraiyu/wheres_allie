# Move ESPresense nodes to the wheres_allie broker

ESPresense's settings save overwrites every field, so never hand-edit a partial form.
`box/tools/repoint_nodes.py` reads the node's current settings, changes only the MQTT
fields (and turns auto-update off so firmware stays on v4.0.6), resends everything, re-reads
and fails loudly if any other field changed. Passwords are passed by env var name and
never printed.

1. The box is up (`docker compose -f deploy/compose.yml ps` shows `box` healthy) and the
   LAN can reach port 1883 on it.
2. From `box/`: `set -a; . ../deploy/.env; set +a`
3. Dry run the canary: `uv run python tools/repoint_nodes.py --host <box-ip> --user "$WA_MQTT_USER" --pass-env WA_MQTT_PASS --backup-dir ~/wheres-allie-node-backup office=<ip> --dry-run`
   Only `mqtt_*` and `auto_update` may appear as changes.
4. Run it without `--dry-run`. Within 60 s: `espresense/rooms/office/status online` on the box broker,
   and the node shows online on the GUI Nodes page.
5. Repeat for the other nodes (several `room=ip` pairs in one command is fine).
6. Rollback: same command with the old broker's host/user and `--pass-env` pointing at a variable
   holding the old password. If a node is unreachable over HTTP, it opens its `espresense…`
   captive-portal AP after its Wi-Fi timeout; fix it at http://192.168.4.1.
