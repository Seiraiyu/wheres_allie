# wheres_allie Foundation (Phases 0–1) Implementation Plan

**Goal:** Retire the three biggest risks (Alexa+ MCP reachability, BC021 motion trigger, browser flashing), then stand up the box skeleton (broker + ingest + SQLite + API + GUI shell in `docker compose`) and move all 5 ESPresense nodes onto it so continuous data collection for Allie starts.

**Architecture:** One Python 3.12 package `wheres_allie` (FastAPI app factory, aiomqtt ingest task, retention task, in-process bus, SQLite WAL) serves `/api/*`, a WebSocket and the built Vite/React GUI; `mosquitto` runs beside it in `deploy/compose.yml`. Nodes keep the unmodified ESPresense v4.0.6 firmware and are repointed over HTTP by a script that reads every current setting and resends them all.

**Tech Stack:** Python 3.12, uv, FastAPI, pydantic-settings, aiomqtt 2, sqlite3, typer, httpx/respx, pytest(-asyncio); React 18 + TypeScript + Vite 8 + Vitest 5 (pnpm); eclipse-mosquitto 2; Docker multi-stage/multi-arch; esptool-js 0.7 (spike); Alexa AI CLI (`@alexa-ai/cli`, spike).

Contract: `docs/plans/2026-09-28-wheres-allie-conventions.md`. Design: `docs/plans/2026-09-28-wheres-allie-design.md`.

| Task | Description | Status | Tested | Pushed |
|------|-------------|--------|--------|--------|
| 1 | Spike A: Alexa+ MCP Toolkit hello-world (tunnel, simulator, device) | pending | no | no |
| 2 | Spike B: BC021 motion trigger switches minor id | pending | no | no |
| 3 | Spike C: esptool-js browser flash with dout/20m bootloader | pending | no | no |
| 4 | box/ uv project scaffold + .gitignore | pending | no | no |
| 5 | config.py Settings | pending | no | no |
| 6 | schema.sql + db.py | pending | no | no |
| 7 | bus.py | pending | no | no |
| 8 | ingest/parse.py: device messages | pending | no | no |
| 9 | ingest/parse.py: room status + telemetry | pending | no | no |
| 10 | ingest/mqtt.py: Ingestor (readings, motion, unknown devices, node health) | pending | no | no |
| 11 | ingest/mqtt.py: run_ingest + gaps | pending | no | no |
| 12 | retention.py | pending | no | no |
| 13 | replay/bundle.py writer + reader | pending | no | no |
| 14 | tools/import_raw_log.py | pending | no | no |
| 15 | nodes/espresense_http.py | pending | no | no |
| 16 | tools/repoint_nodes.py + runbook | pending | no | no |
| 17 | api/app.py factory + /api/health + deps | pending | no | no |
| 18 | GET/PUT /api/settings | pending | no | no |
| 19 | GET /api/nodes | pending | no | no |
| 20 | /api/pets, /api/pets/{id}/tags, /api/tags/candidates | pending | no | no |
| 21 | WS /api/ws | pending | no | no |
| 22 | Serve web/dist (SPA fallback) | pending | no | no |
| 23 | cli.py `serve` | pending | no | no |
| 24 | web/ scaffold: tokens, left rail, empty pages | pending | no | no |
| 25 | web/ lib (api, ws, types) + live Nodes page | pending | no | no |
| 26 | Dockerfile (multi-stage, multi-arch) | pending | no | no |
| 27 | deploy/compose.yml + mosquitto conf/entrypoint | pending | no | no |
| 28 | `docker compose up` smoke test + LAN reachability | pending | no | no |
| 29 | Register Allie; move the 5 nodes to the box broker (canary first) | pending | no | no |
| 30 | Verify continuous collection; stop raw logger; import raw log to bundle | pending | no | no |
| 31 | Friction log + spike results curation | pending | no | no |
| 32 | Phase exit + push | pending | no | no |

## Interface additions

These extend the conventions; none contradicts them. Later plans may rely on them.

1. **Dependency pin:** `mcp>=2.2,<3`, which locks to 2.2.0. Plan 05 is built on the 2.x API: `mcp.server.mcpserver.MCPServer`, MCP Apps and `mcp.Client`. In 2.x, `FastMCP` no longer exists.
2. **`config.Settings`** also has `web_dist: Path` (env `WA_WEB_DIST`, default `<box>/web/dist`) and a `db_path` property (`data_dir / "wheres_allie.db"`). `mqtt_pass` has no default (required), per §3.
3. **`db`:** `connect()` also uses `check_same_thread=False`, `isolation_level=None` (autocommit) and `synchronous=NORMAL`. Helpers `get_setting(conn, key, default=None) -> str | None` and `set_setting(conn, key, value)`. Settings keys used: `tz`, `units`, `home_name`.
4. **`bus`:** `Bus.subscribe(prefix="")` returns a `Subscription`, which is an `AsyncIterator[tuple[str, dict]]` plus a context manager and `.close()`. The subscription is registered as soon as `subscribe()` returns. `publish()` must be called on the event-loop thread. Each subscriber queue holds 1000 events; when it is full, new events are dropped.
5. **Bus payloads:** `reading` = `{ts, tag_id, node_id, rssi, distance}`. `node.health` = the `nodes` row as a dict, with `online` as a bool.
6. **`ingest.parse`:** `parse_device_message(topic, payload, ts: float | None = None)` (ts defaults to now; the importer and replayer pass explicit timestamps). `parse_room_status(topic, payload) -> NodeStatus(node_id, online) | None`. `parse_telemetry(topic, payload) -> NodeTelemetry(node_id, ip, wifi_rssi, uptime_s, version) | None`. All three are frozen dataclasses.
7. **`ingest.mqtt`:**
   - `class Ingestor(conn, bus)` with `handle(topic, payload, ts=None)`, `reload_tags()`, `nearby_devices(node_id, now=None) -> int` and `candidates(now=None) -> list[{ibeacon_id, node_id, rssi, last_seen}]` (unregistered `iBeacon:*` ids heard in the last 10 min, strongest first).
   - `run_ingest(settings, conn, bus, ingestor: Ingestor | None = None)` and `record_gap(conn, start, end)`, which writes `gaps.reason = 'mqtt_disconnect'`.
   - **Motion rule:** a motion-id message writes `motion(ts, tag, 1)` on the still→moving edge. A normal-id message writes `motion(ts, tag, 0)` only when the tag is moving **and** the last motion-id message is more than `MOTION_HOLD_S = 10` s old. This tolerates a beacon that keeps advertising both ids while moving.
8. **API wiring:**
   - `api.app.create_app(settings: Settings | None = None, conn=None, start_background=True) -> FastAPI`. Plain `create_app()` reads `Settings()` from the `WA_*` env vars and opens `WA_DATA_DIR/wheres_allie.db`.
   - `app.state` holds `settings`, `conn`, `bus`, `ingestor` and `relay_status` (`"offline"` until plan 06's relaylink sets it). They are set when the app is created, so they are also available in the lifespan.
   - The `lifespan` in `create_app` starts `run_ingest` and `run_retention` with `asyncio.create_task` when `start_background` is true, and cancels them on shutdown. Later plans add their tasks to that list, or wrap `yield` (for example the MCP session manager).
   - `api/deps.py` exports `get_conn(request)`, `get_bus(request)`, `get_settings(request)` and `get_ingestor(request)`, plus the `Annotated` aliases `Conn`, `Cfg` and `Ing`.
   - Every `api/routes/<name>.py` exposes `router = APIRouter()` with paths **without** the `/api` prefix, and is registered as `app.include_router(<name>.router, prefix="/api")`. `api/ws.py` is registered the same way.
   - `/api/health` and `/api/settings` live in `api/app.py`.
   - The static GUI mount at `/` must stay the **last** statement in `create_app`. It serves `index.html` for every unknown path that doesn't start with `api` or `mcp`. Later plans add `/mcp` and their routers above it.
   - Test fixtures in `box/tests/conftest.py`: `conn` (a migrated in-memory db), `settings` (a `Settings` object using a temp data dir), and `client` (a `TestClient(create_app(start_background=False))` with `WA_DATA_DIR` pointing at a temp dir). API tests use `client.app.state.conn` for direct db access.
   - `cli.py` defines a typer `app` with `serve`, which runs `uvicorn.run(create_app(), …)`.
   - This plan does **not** create `WA_LAN_TOKEN` (plan 05 does, as settings key `lan_token`), `box_id`/`box_secret` (plan 06), `POST /api/nodes/{id}/configure` (plan 07), `POST /api/data/export` (plan 07), or an estimator on/off switch (plan 03).
9. **Response shapes:**
   - `GET /api/nodes` → `[{…nodes row, online: bool, placed: bool, nearby_devices: int}]`. `placed` is read from the latest `home.json["nodes"][].id`.
   - Pets → `{id, name, species, tags: [{id, pet_id, ibeacon_id, motion_ibeacon_id}]}`.
   - `POST /api/pets` returns 409 on a duplicate name. `POST /api/pets/{id}/tags` returns 404 for an unknown pet and 409 for a duplicate id.
   - `PUT /api/settings` returns 422 for an unknown tz or for units outside `ft|m`.
10. **`replay.bundle`:** `Bundle(manifest, home=EMPTY_HOME, readings=[], motion=[], labels=[], ground_truth=None)` dataclass, plus `write_bundle(path, bundle)`, `read_bundle(path) -> Bundle` (raises `ValueError` if `format != 1`), `COLUMNS` and `EMPTY_HOME`. Rows are tuples in §13 column order; empty cells are `None`, numeric columns are floats and `moving` is an int.
11. **`nodes.espresense_http`:** `get_main(client, ip) -> values`, `build_form(values, overrides)`, `push_settings(client, ip, overrides, expect_room=None, dry_run=False) -> {key: (old, new)}` (secrets are masked) and `restart(client, ip)`. It targets `GET/POST http://<ip>/wifi/main` (HeadlessWiFiSettings v1.1.4 in ESPresense v4.0.6).
12. **Tools:** `box/tools/repoint_nodes.py` (CLI) and `docs/runbooks/move-nodes-to-box.md`.
13. **Web:**
    - `src/theme/app.css` holds the layout; `tokens.css` holds only the variables.
    - `App.tsx` exports `PAGES`.
    - `lib/api.ts` exports `apiGet<T>(path)`, `apiPost<T>(path, body?)`, `apiPut<T>(path, body)`, `apiUpload<T>(path: string, file: File)` (multipart, field `"file"`) and `class ApiError extends Error { status: number }`. Each returns parsed JSON and throws `ApiError` on a non-2xx response. Pass full paths such as `"/api/nodes"`; a path without `/api` gets the prefix added.
    - `lib/ws.ts` exports `subscribe(topicPrefix: string, handler: (topic: string, data: any) => void): () => void` (two positional args; `data` is the bus payload). All subscribers share one WebSocket to `/api/ws`, which opens on the first subscribe, reconnects with backoff, and closes after the last unsubscribe.
    - `lib/types.ts` exports `Health`, `SiteSettings`, `Node`, `Pet`, `Tag`, `TagCandidate` and `BusEvent = {topic, data}`.
    - `App.tsx` routes `/setup /editor /nodes /live /history /calibrate /data` (each page is a default export in `src/pages/`), and `*` redirects to `/live`.
    - `vite.config.ts` proxies `/api` (including ws, which covers `/api/ws`) and `/mcp` to `http://localhost:8080`. Vitest uses jsdom and excludes `e2e/**`, which is kept for Playwright.
    - Tool versions: vite 8, vitest 5, TypeScript 7 and @vitejs/plugin-react 6. On 2026-09-29 I checked these against what plans 02, 04 and 07 add:
      - `zustand` 5, `esptool-js@^0.7.0`, `@modelcontextprotocol/ext-apps` 2.0.3, `vite-plugin-singlefile` 2.3.3 (its peer range includes vite 8), `@playwright/test` 1.63 and `@types/w3c-web-serial` all install without peer warnings.
      - A test in their style passes, and `pnpm exec tsc --noEmit` and `pnpm build` stay clean. That test used `// @vitest-environment jsdom`, `describe/it/vi`, `configDefaults` from `vitest/config`, @testing-library `fireEvent`/`cleanup`, and a zustand store.
    - This plan installs only `react`, `react-dom` and `react-router-dom`. Later plans add `zustand`, `esptool-js`, `@modelcontextprotocol/ext-apps` and `@playwright/test` when they need them.
14. **Deploy:** compose project `wheres-allie`, services `mosquitto` and `box`, local image `wheres-allie:dev`. `deploy/.env.example` is the template (the real `deploy/.env` is git-ignored). The mosquitto password file is `/mosquitto/data/passwd`.
15. **Spike results:** go in `docs/spikes/phase0.md`, which later plans read.

---

## Phase 0: Spikes (day 1–2; do all three before Task 29)

### Task 1: Spike A: Alexa+ MCP Toolkit hello-world

**Files:**
- Create: `spikes/alexa-hello/server.py`
- Create: `docs/spikes/phase0.md`

Your Amazon developer account must use the same Amazon login as the Echo device you will test on. The toolkit is US only.

1. **Prerequisites.** You need a free Alexa developer account (https://developer.amazon.com/alexa/), an AWS account, and, in the Alexa phone app, a completed profile with a phone number, an address and the US marketplace. Node 24 is already installed.
2. **Install and authenticate the CLI.** Run from anywhere:
   ```bash
   npm install -g @alexa-ai/cli
   alexa-ai --version
   alexa-ai configure            # opens LWA login; in WSL without a browser use: alexa-ai configure --no-browser
   ```
   Expected: a version is printed, and `~/.alexa-ai/credentials` exists afterwards. If access is gated (waitlist, "not enabled"), request it now and record the date in the friction log. Continue with steps 3–5 while you wait.
3. **Create the throwaway server** at `spikes/alexa-hello/server.py`:
   ```python
   """Phase 0 spike: smallest MCP server Alexa+ can call. Throwaway; not the product."""

   from mcp.server.mcpserver import MCPServer

   mcp = MCPServer("wheres-allie-hello")


   @mcp.tool()
   def where_is(pet: str = "Allie") -> str:
       """Say where the pet is right now. Spike: always the same canned answer."""
       return f"{pet} is on her bed in the master bedroom. This is spike data."


   if __name__ == "__main__":
       mcp.run("streamable-http", host="0.0.0.0", port=8765, stateless_http=True, json_response=True)
   ```
   Run it from the repo root, in terminal 1:
   ```bash
   uv run --with 'mcp>=2.2,<3' python spikes/alexa-hello/server.py
   ```
4. **Check it locally.** In terminal 2 (the Host header simulates the tunnel):
   ```bash
   curl -s -X POST http://localhost:8765/mcp -H 'Host: abc.trycloudflare.com' \
     -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
     -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"where_is","arguments":{}}}' \
     -w '\n%{http_code} %{time_total}\n'
   ```
   Expected: JSON containing `"Allie is on her bed in the master bedroom. This is spike data."`, then `200` and a time under 0.05 s. (This was verified on 2026-09-29 with mcp 2.2.0.)
5. **Start a temporary tunnel.** In terminal 3; run `docker info >/dev/null 2>&1 || sudo service docker start` first if Docker isn't running:
   ```bash
   docker run --rm --network host cloudflare/cloudflared:latest tunnel --no-autoupdate --url http://localhost:8765
   ```
   Expected: a `https://<random>.trycloudflare.com` URL in the log. Repeat the step 4 curl against `https://<random>.trycloudflare.com/mcp` without the `-H 'Host: …'` line. Record `time_total`: the toolkit requires a round-trip of **under 500 ms**.
6. **Create and deploy the add-on.** Do this outside the repo, because it is throwaway:
   ```bash
   mkdir -p ~/alexa-spike && cd ~/alexa-spike
   alexa-ai new mcp --name "Where's Allie Spike" --locale en-US --mcp-server-url "https://<random>.trycloudflare.com/mcp"
   ```
   Fill in the required fields in `addon-package/addon.json`: `shortDescription`, `fullDescription`, `examplePhrases` (use `"where is Allie"`), and the privacy and terms URLs (use `https://github.com/Seiraiyu/wheres_allie`). Add any media the CLI asks for; a 512×512 PNG of any dog emoji is fine. Then run:
   ```bash
   alexa-ai deploy
   ```
   Expected: the deploy succeeds. If there is a validation error, fix the fields it names and re-run.
7. **Test on the web simulator.** Follow https://developer.amazon.com/docs/alexaplus/add-ons/test-with-web-simulator.html and type "where is Allie". **Pass** means terminal 1 logs a `POST /mcp` and the simulator's reply mentions "master bedroom". Try at least 3 phrasings ("where's Allie", "ask Where's Allie Spike where Allie is", "is Allie in the bedroom") and record which ones route to the tool.
8. **Test on a real device.** Route the simulator session to your Echo, as described in "Test on a physical device" on the same docs page, or speak to the Echo directly. **Pass** means the Echo speaks the canned answer.
9. **Doc check.** Record each item as confirmed or different in `docs/spikes/phase0.md`:
   - Account linking must be OAuth 2.1 auth code + PKCE (S256), with a `resource` parameter equal to the MCP URL and the bearer token in the header only. Source: https://developer.amazon.com/docs/alexaplus/add-ons/mcp-toolkit-account-linking.html.
   - Unauthenticated calls must get a 401 **without** `WWW-Authenticate`.
   - MCP Apps are supported, which devices render them, and the resource MIME type and `_meta` key (see the MCP Apps section of the docs).
   - Any per-tool latency or timeout limit.
10. **Record the results.** Create `docs/spikes/phase0.md`:
    ```markdown
    # Phase 0 spike results

    ## A. Alexa+ MCP Toolkit hello-world (date: YYYY-MM-DD)
    | Check | Result | Notes |
    |---|---|---|
    | CLI install + configure | pass/fail | |
    | Tunnel round-trip time | ___ ms | limit 500 ms |
    | Deploy | pass/fail | |
    | Web simulator calls tool | pass/fail | phrases that worked: |
    | Real device speaks answer | pass/fail | device model: |
    | Account linking = OAuth 2.1 + PKCE + resource | confirmed/different | |
    | 401 without WWW-Authenticate | confirmed/different | |
    | MCP Apps: devices, mime type, _meta key | | |
    | Other limits (timeouts, payload size) | | |

    **Decision:**

    ## B. BC021 motion trigger (date: )

    ## C. esptool-js browser flash (date: )
    ```
    Write a friction-log entry in `docs/friction-log.md` for every surprise.
11. **Decision criteria:**
    - If the simulator passes and the device passes: no plan changes.
    - If the simulator passes and the device fails: the demo falls back to the web simulator, which the rules allow. Add a note to plan 06, Task "Alexa+ end to end", and keep retrying the device weekly.
    - If account linking differs from the relay design (§4.7, conventions §12): update `2026-09-28-wheres-allie-plan-06-relay.md` **before** plan 06 starts, and tell the team lead.
    - If MCP Apps are not rendered on any device: tell the plan 04 owner that phase 8 is simulator-only.
    - If the tunnel round-trip is over 400 ms: note in plan 06 that the relay must be in `us-east-1` and add a latency budget test.
12. **Tear down.** Stop the tunnel and the server with Ctrl-C in both terminals.
13. **Commit.** From the repo root:
    ```bash
    git add spikes/alexa-hello/server.py docs/spikes/phase0.md docs/friction-log.md
    git commit -m "docs: phase 0 spike A (Alexa+ MCP hello-world) results" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
    ```

### Task 2: Spike B: BC021 motion trigger

**Files:**
- Modify: `docs/spikes/phase0.md` (section B)

Allie's tag id today is `iBeacon:426c7565-4368-6172-6d42-6561636f6e73-3838-4949`: UUID `426c7565-4368-6172-6d42-6561636f6e73` (ASCII "BlueCharmBeacons"), major 3838, minor 4949. ESPresense prints major and minor as decimal. The target motion id is `iBeacon:426c7565-4368-6172-6d42-6561636f6e73-3838-4950`.

1. Install the Blue Charm configuration app named in the BC021 manual (KBeacon Pro) on a phone. Take the collar tag off Allie. Connect to the beacon; the default password is `0000000000000000` unless it was changed. Screenshot the current settings of every slot before you change anything.
2. Leave slot 0 exactly as it is: iBeacon, same UUID, major 3838, minor 4949.
3. Add a **motion trigger**: trigger type Motion, action "advertise", slot 1 = iBeacon with the **same UUID and major**, minor **4950**, advertising duration **10 s** after the last motion, and medium sensitivity. Save.
4. On the WSL box, subscribe to the current broker (the HA Mosquitto). Type the HA MQTT password when prompted; it is never written to disk:
   ```bash
   read -rsp 'HA MQTT password: ' HA_MQTT_PASS; echo
   mosquitto_sub -h 192.168.5.132 -u mqtt -P "$HA_MQTT_PASS" -v \
     -t 'espresense/devices/iBeacon:426c7565-4368-6172-6d42-6561636f6e73-3838-4950/#' \
     -t 'espresense/devices/iBeacon:426c7565-4368-6172-6d42-6561636f6e73-3838-4949/#' \
     | while IFS= read -r l; do echo "$(date +%T) $l"; done
   ```
5. Leave the tag still for 60 s, then shake it for 5 s, then leave it still for 60 s. Repeat 3 times.
6. **Pass** requires all of the following:
   - (a) `…-3838-4950` messages appear within 5 s of the shaking starting, every time;
   - (b) they stop within 20 s of stillness;
   - (c) no `…-3838-4950` messages appear during the still periods.

   Also record whether `…-3838-4949` keeps arriving **while** moving. Ingest's 10 s hold (Interface additions #7) handles both cases.
7. Record in `docs/spikes/phase0.md` section B: the pass/fail of (a)–(c), the observed latency, whether both ids advertise during motion, and the app settings used (as text, not screenshots).
8. **Decision criteria:**
   - If it passes: register the tag in Task 29 with `motion_ibeacon_id` = `…-3838-4950`.
   - If it fails: revert the trigger in the app and register the tag without a motion id (`motion_ibeacon_id` NULL, conventions §5). Tell the plan 03 owner that the estimator must use the movement-variance fallback (design §4.1). No plan file needs to change.
   - If it partially passes (latency over 10 s, say): register the motion id anyway, and note the latency for plan 03.
9. Put the tag back on Allie's collar. Commit from the repo root:
   ```bash
   git add docs/spikes/phase0.md docs/friction-log.md
   git commit -m "docs: phase 0 spike B (BC021 motion trigger) results" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
   ```

### Task 3: Spike C: esptool-js browser flash with a dout/20m bootloader

**Files:**
- Create: `spikes/flash/index.html`
- Modify: `.gitignore` (add `spikes/flash/fw/`)
- Modify: `docs/spikes/phase0.md` (section C)

This **erases** one node. Use `loft`, whose status is already the least stable. You re-provision it at the end.

1. Back up the loft settings and fetch the official v4.0.6 parts. Run from the repo root:
   ```bash
   mkdir -p ~/wheres-allie-node-backup spikes/flash/fw
   curl -s http://192.168.5.222/wifi/main > ~/wheres-allie-node-backup/loft-pre-spike.json
   grep -o '"room":"[^"]*"' ~/wheres-allie-node-backup/loft-pre-spike.json     # expect "room":"loft"
   curl -sLo spikes/flash/fw/bootloader.bin https://espresense.com/static/esp32/bootloader.bin
   curl -sLo spikes/flash/fw/partitions.bin https://espresense.com/static/esp32/partitions.bin
   curl -sLo spikes/flash/fw/boot_app0.bin  https://espresense.com/static/boot_app0.bin
   curl -sLo spikes/flash/fw/esp32.bin      https://github.com/ESPresense/ESPresense/releases/download/v4.0.6/esp32.bin
   echo 'spikes/flash/fw/' >> .gitignore
   ```
2. Patch the bootloader header to DOUT / 20 MHz. The stock image has an appended SHA-256 (byte 23 = 1), so the digest must be recomputed:
   ```bash
   python3 - <<'PY'
   import hashlib
   d = bytearray(open("spikes/flash/fw/bootloader.bin", "rb").read())
   assert d[0] == 0xE9, "not an ESP image"
   d[2] = 3                        # flash mode: DOUT
   d[3] = (d[3] & 0xF0) | 0x2      # flash freq: 20 MHz (keep the size nibble)
   if d[23] == 1:                  # SHA-256 appended: recompute over everything before it
       d[-32:] = hashlib.sha256(d[:-32]).digest()
   open("spikes/flash/fw/bootloader-dout20m.bin", "wb").write(d)
   PY
   uvx --from 'esptool>=4.8,<5' esptool.py image_info --version 2 spikes/flash/fw/bootloader-dout20m.bin | grep -E 'Flash (freq|mode)|valid'
   ```
   Expected (verified 2026-09-28):
   ```
   Flash freq: 20m
   Flash mode: DOUT
   Checksum: 0xab (valid)
   Validation hash: 8ce5…820a (valid)
   ```
3. Create `spikes/flash/index.html`:
   ```html
   <!doctype html>
   <html lang="en">
   <head><meta charset="utf-8"><title>Flash spike</title></head>
   <body>
     <h1>esptool-js flash spike: ESPresense v4.0.6</h1>
     <p>
       <label><input type="radio" name="bl" value="patched" checked> pre-patched bootloader (flashMode keep)</label><br>
       <label><input type="radio" name="bl" value="stock"> stock bootloader, esptool-js sets dout / 20m</label>
     </p>
     <button id="go">Connect + erase + flash</button>
     <p id="progress"></p>
     <pre id="log"></pre>
     <script type="module">
       import { ESPLoader, Transport } from "https://unpkg.com/esptool-js@0.7.0/bundle.js";
       const log = document.getElementById("log");
       const progress = document.getElementById("progress");
       const terminal = {
         clean: () => (log.textContent = ""),
         writeLine: (s) => (log.textContent += s + "\n"),
         write: (s) => (log.textContent += s),
       };
       const get = async (p) => new Uint8Array(await (await fetch(p)).arrayBuffer());
       document.getElementById("go").onclick = async () => {
         const patched = document.querySelector("input[name=bl]:checked").value === "patched";
         const port = await navigator.serial.requestPort();
         const transport = new Transport(port, true);
         const loader = new ESPLoader({ transport, baudrate: 460800, terminal });
         const t0 = performance.now();
         try {
           terminal.writeLine("chip: " + (await loader.main()));
           const fileArray = [
             { data: await get(patched ? "fw/bootloader-dout20m.bin" : "fw/bootloader.bin"), address: 0x1000 },
             { data: await get("fw/partitions.bin"), address: 0x8000 },
             { data: await get("fw/boot_app0.bin"), address: 0xe000 },
             { data: await get("fw/esp32.bin"), address: 0x10000 },
           ];
           await loader.writeFlash({
             fileArray,
             flashMode: patched ? "keep" : "dout",
             flashFreq: patched ? "keep" : "20m",
             flashSize: "keep",
             eraseAll: true,
             compress: true,
             reportProgress: (i, written, total) =>
               (progress.textContent = `file ${i + 1}/4: ${Math.round((100 * written) / total)}%`),
           });
           await loader.after("hard_reset");
           terminal.writeLine(`DONE in ${((performance.now() - t0) / 1000).toFixed(0)} s`);
         } catch (e) {
           terminal.writeLine("ERROR: " + e);
         } finally {
           await transport.disconnect();
         }
       };
     </script>
   </body>
   </html>
   ```
4. Serve it from the repo root with `python3 -m http.server 8000 -d spikes/flash`. Unplug loft from its wall power and plug it into the **Windows** PC over USB-C. In Chrome or Edge on Windows, open `http://localhost:8000` (WSL mirrored networking forwards localhost). Choose **pre-patched**, click the button and pick the CP210x COM port.
5. **Pass** requires all of the following:
   - (a) the log ends with `DONE in N s`;
   - (b) within 60 s of the reset, a Wi-Fi access point whose name starts with `espresense` appears (the unconfigured ESPresense captive portal), meaning the firmware booted and is not boot-looping;
   - (c) the whole thing is repeated once more with the same result.
6. Once, run the **stock** option too and record whether it also boots. That tells plan 07 whether esptool-js rewrites the header itself, in which case the patched bootloader would be optional.
7. **Re-provision loft.** Join the `espresense…` AP from a phone and open `http://192.168.4.1`. Set the Wi-Fi SSID and password, room `loft`, and the MQTT host, port, user and password copied from `~/wheres-allie-node-backup/loft-pre-spike.json` (the masked passwords come from your notes). Save, then Restart. Plug loft back into its wall power at its usual spot. Confirm `curl -s http://192.168.5.222/wifi/main | grep -o '"room":"loft"'`; if DHCP gave it a new IP, find it in the router or on the serial log. **Record the IP.**
8. Record in `docs/spikes/phase0.md` section C: pass/fail of (a)–(c), the flash time, the stock-bootloader result, and the Chrome version.
9. **Decision criteria:**
   - If it passes: plan 07 phase 9 goes ahead as designed.
   - If it fails after 3 tries: tell the plan 07 owner to make the documented CLI path the primary one:
     ```bash
     esptool.py --chip esp32 -b 460800 write_flash --erase-all --flash-mode dout --flash-freq 20m 0x1000 bootloader.bin 0x8000 partitions.bin 0xe000 boot_app0.bin 0x10000 esp32.bin
     ```
     Keep the browser flasher as experimental.
10. Commit from the repo root:
    ```bash
    git add .gitignore spikes/flash/index.html docs/spikes/phase0.md docs/friction-log.md
    git commit -m "docs: phase 0 spike C (esptool-js browser flash) results" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
    ```

---

## Phase 1: Box skeleton

All Python commands run from `box/` unless stated otherwise. All git commands run from the repo root.

### Task 4: box/ uv project scaffold

**Files:**
- Create: `box/pyproject.toml`, `box/src/wheres_allie/__init__.py`, the empty package `__init__.py` files, `box/tests/test_version.py`
- Modify: `.gitignore`

**Step 1: Write the failing test.** Create `box/tests/test_version.py`:
```python
import wheres_allie


def test_version():
    assert wheres_allie.__version__ == "0.1.0"
```

**Step 2: Run the test and verify it fails.** Create `box/pyproject.toml` first, because pytest needs the project:
```toml
[project]
name = "wheres-allie"
version = "0.1.0"
description = "Where's Allie: pet presence box (ESPresense + MCP)"
requires-python = ">=3.12,<3.13"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "pydantic>=2",
    "pydantic-settings>=2",
    "aiomqtt>=2",
    "numpy>=2",
    "shapely>=2",
    "mcp>=2.2,<3",
    "typer>=0.12",
    "httpx>=0.27",
    "websockets>=13",
    "python-multipart",
    "tzdata",
]

[project.scripts]
wheres-allie = "wheres_allie.cli:app"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/wheres_allie"]

[dependency-groups]
dev = ["pytest>=8", "pytest-asyncio>=0.24", "ruff>=0.6", "respx>=0.21"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
addopts = "--import-mode=importlib"

[tool.ruff]
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I"]

[tool.ruff.lint.per-file-ignores]
"tests/*" = ["E501"]
```
Then run: `mkdir -p src/wheres_allie && uv sync && uv run pytest -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'wheres_allie'`. If uv instead refuses to build because the package directory is empty, that counts as the same failure.

**Step 3: Implement.**
```bash
mkdir -p src/wheres_allie/{ingest,api/routes,replay,nodes} tests tools
touch src/wheres_allie/{ingest,api,api/routes,replay,nodes}/__init__.py
```
Create `box/src/wheres_allie/__init__.py`:
```python
"""wheres_allie: the home box."""

__version__ = "0.1.0"
```
Append to the repo-root `.gitignore`:
```
.venv/
.pytest_cache/
.ruff_cache/
box/.data/
box/web/dist/
data/*.bundle
```

**Step 4: Run the test and verify it passes.** `uv sync && uv run pytest -q && uv run ruff check .`
Expected: `1 passed`, `All checks passed!`

**Step 5: Commit.**
```bash
git add .gitignore box/pyproject.toml box/uv.lock box/src box/tests
git commit -m "chore: scaffold wheres_allie box package" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 5: config.py

**Files:**
- Create: `box/src/wheres_allie/config.py`
- Test: `box/tests/test_config.py`

**Step 1: Write the failing test.**
```python
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
```

**Step 2: Run the test and verify it fails.** `uv run pytest -q tests/test_config.py`
Expected: FAIL `ModuleNotFoundError: No module named 'wheres_allie.config'`

**Step 3: Implement** `box/src/wheres_allie/config.py`:
```python
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="WA_")

    data_dir: Path = Path("/data")
    mqtt_host: str = "mosquitto"
    mqtt_port: int = 1883
    mqtt_user: str = "wheres_allie"
    mqtt_pass: str
    http_port: int = 8080
    tz: str = "America/New_York"
    relay_url: str = ""
    lan_token: str = ""
    public_host: str = ""
    web_dist: Path = Path(__file__).resolve().parents[2] / "web" / "dist"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "wheres_allie.db"
```

**Step 4: Run the test and verify it passes.** `uv run pytest -q tests/test_config.py`
Expected: `2 passed`

**Step 5: Commit.**
```bash
git add box/src/wheres_allie/config.py box/tests/test_config.py
git commit -m "feat: WA_ settings via pydantic-settings" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 6: schema.sql + db.py

**Files:**
- Create: `box/src/wheres_allie/schema.sql`, `box/src/wheres_allie/db.py`, `box/tests/conftest.py`
- Test: `box/tests/test_db.py`

**Step 1: Write the failing test.** Create `box/tests/conftest.py`:
```python
import pytest

from wheres_allie import db


@pytest.fixture
def conn():
    c = db.connect(":memory:")
    db.migrate(c)
    yield c
    c.close()
```
Create `box/tests/test_db.py`:
```python
from wheres_allie import db

TABLES = {"settings", "home", "nodes", "pets", "tags", "readings", "motion", "positions",
          "visits", "labels", "gaps", "rollups"}


def test_migrate_creates_all_tables_and_is_idempotent(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    db.migrate(conn)
    db.migrate(conn)
    names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert TABLES <= names
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_settings_helpers(conn):
    assert db.get_setting(conn, "tz", "UTC") == "UTC"
    db.set_setting(conn, "tz", "America/Chicago")
    db.set_setting(conn, "tz", "America/Denver")
    assert db.get_setting(conn, "tz") == "America/Denver"
```

**Step 2: Run the test and verify it fails.** `uv run pytest -q tests/test_db.py`
Expected: FAIL `ImportError: cannot import name 'db' from 'wheres_allie'`

**Step 3: Implement.** Create `box/src/wheres_allie/schema.sql`, copied verbatim from conventions §5:
```sql
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS home (version INTEGER PRIMARY KEY AUTOINCREMENT, saved_at REAL NOT NULL, json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS nodes (
  id TEXT PRIMARY KEY,            -- ESPresense room id, e.g. 'master_bedroom'
  name TEXT, online INTEGER NOT NULL DEFAULT 0, last_seen REAL, ip TEXT,
  wifi_rssi INTEGER, uptime_s INTEGER, version TEXT, calib_json TEXT);
CREATE TABLE IF NOT EXISTS pets (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, species TEXT NOT NULL DEFAULT 'dog');
CREATE TABLE IF NOT EXISTS tags (
  id INTEGER PRIMARY KEY, pet_id INTEGER NOT NULL REFERENCES pets(id),
  ibeacon_id TEXT NOT NULL UNIQUE,         -- ESPresense id, e.g. 'iBeacon:426c…-3838-4949'
  motion_ibeacon_id TEXT UNIQUE);          -- id broadcast while moving (NULL if not configured)
CREATE TABLE IF NOT EXISTS readings (ts REAL NOT NULL, tag_id INTEGER NOT NULL, node_id TEXT NOT NULL,
  rssi REAL NOT NULL, distance REAL, rssi_var REAL);
CREATE INDEX IF NOT EXISTS readings_tag_ts ON readings(tag_id, ts);
CREATE TABLE IF NOT EXISTS motion (ts REAL NOT NULL, tag_id INTEGER NOT NULL, moving INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS motion_tag_ts ON motion(tag_id, ts);
CREATE TABLE IF NOT EXISTS positions (ts REAL NOT NULL, tag_id INTEGER NOT NULL, vertex_id TEXT NOT NULL,
  room_id TEXT, floor_id TEXT, confidence REAL NOT NULL, moving INTEGER);
CREATE INDEX IF NOT EXISTS positions_tag_ts ON positions(tag_id, ts);
CREATE TABLE IF NOT EXISTS visits (id INTEGER PRIMARY KEY, tag_id INTEGER NOT NULL, place_id TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('room','landmark','transit','away')), start REAL NOT NULL, "end" REAL);
CREATE INDEX IF NOT EXISTS visits_tag_start ON visits(tag_id, start);
CREATE TABLE IF NOT EXISTS labels (id INTEGER PRIMARY KEY, tag_id INTEGER NOT NULL, vertex_id TEXT NOT NULL,
  ts_start REAL NOT NULL, ts_end REAL NOT NULL, source TEXT NOT NULL CHECK (source IN ('walk','tap','voice','import')));
CREATE TABLE IF NOT EXISTS gaps (ts_start REAL NOT NULL, ts_end REAL, reason TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS rollups (tag_id INTEGER NOT NULL, date TEXT NOT NULL, json TEXT NOT NULL,
  PRIMARY KEY (tag_id, date));
```
Create `box/src/wheres_allie/db.py`:
```python
import sqlite3
from pathlib import Path

SCHEMA = Path(__file__).with_name("schema.sql")


def connect(path: str | Path) -> sqlite3.Connection:
    # Autocommit + check_same_thread=False: one shared connection used by the event loop,
    # FastAPI's threadpool and asyncio.to_thread.
    conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA.read_text())


def get_setting(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
```

**Step 4: Run the test and verify it passes.** `uv run pytest -q tests/test_db.py`
Expected: `2 passed`

**Step 5: Commit.**
```bash
git add box/src/wheres_allie/schema.sql box/src/wheres_allie/db.py box/tests/conftest.py box/tests/test_db.py
git commit -m "feat: SQLite schema, connect/migrate and settings helpers" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 7: bus.py

**Files:**
- Create: `box/src/wheres_allie/bus.py`
- Test: `box/tests/test_bus.py`

**Step 1: Write the failing test.**
```python
import asyncio

from wheres_allie.bus import Bus


async def test_prefix_filter_and_unsubscribe():
    bus = Bus()
    with bus.subscribe("node.") as sub:
        bus.publish("reading", {"rssi": -70})
        bus.publish("node.health", {"id": "office"})
        topic, data = await asyncio.wait_for(anext(sub), 1)
        assert (topic, data) == ("node.health", {"id": "office"})
        assert sub.queue.empty()
    bus.publish("node.health", {"id": "loft"})
    assert bus._subs == []
```

**Step 2: Run the test and verify it fails.** `uv run pytest -q tests/test_bus.py`
Expected: FAIL `ModuleNotFoundError: No module named 'wheres_allie.bus'`

**Step 3: Implement** `box/src/wheres_allie/bus.py`:
```python
import asyncio


class Subscription:
    """Async iterator of (topic, data) for one subscriber; a context manager unsubscribes."""

    def __init__(self, bus: "Bus", prefix: str):
        self.prefix = prefix
        self.queue: asyncio.Queue[tuple[str, dict]] = asyncio.Queue(maxsize=1000)
        self._bus = bus

    def __aiter__(self) -> "Subscription":
        return self

    async def __anext__(self) -> tuple[str, dict]:
        return await self.queue.get()

    def close(self) -> None:
        if self in self._bus._subs:
            self._bus._subs.remove(self)

    def __enter__(self) -> "Subscription":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


class Bus:
    """In-process pub/sub. publish() must be called from the event loop thread."""

    def __init__(self) -> None:
        self._subs: list[Subscription] = []

    def publish(self, topic: str, data: dict) -> None:
        for sub in list(self._subs):
            if topic.startswith(sub.prefix):
                try:
                    sub.queue.put_nowait((topic, data))
                except asyncio.QueueFull:
                    pass  # ponytail: a slow subscriber drops events; add backpressure if needed

    def subscribe(self, topic_prefix: str = "") -> Subscription:
        sub = Subscription(self, topic_prefix)
        self._subs.append(sub)
        return sub
```

**Step 4: Run the test and verify it passes.** `uv run pytest -q tests/test_bus.py`
Expected: `1 passed`

**Step 5: Commit.**
```bash
git add box/src/wheres_allie/bus.py box/tests/test_bus.py
git commit -m "feat: in-process event bus" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 8: ingest/parse.py: device messages

**Files:**
- Create: `box/src/wheres_allie/ingest/parse.py`
- Test: `box/tests/ingest/test_parse.py`

**Step 1: Write the failing test.** Run `mkdir -p tests/ingest`, then create `box/tests/ingest/test_parse.py`. The payload is copied from `data/allie-raw.log`.
```python
from wheres_allie.ingest.parse import parse_device_message

ALLIE = "iBeacon:426c7565-4368-6172-6d42-6561636f6e73-3838-4949"
# Copied from data/allie-raw.log (2026-09-28T22:34:11-04:00)
PAYLOAD = (
    b'{"mac":"dd8800003777","id":"iBeacon:426c7565-4368-6172-6d42-6561636f6e73-3838-4949",'
    b'"rssi@1m":-59,"rssi":-81.10,"rxAdj":0,"rssiVar":7.42,"distance":6.58,"var":4.00,"int":2028}'
)


def test_device_message():
    r = parse_device_message(f"espresense/devices/{ALLIE}/office", PAYLOAD, ts=100.0)
    assert r is not None
    assert (r.ts, r.ibeacon_id, r.node_id) == (100.0, ALLIE, "office")
    assert (r.rssi, r.distance, r.rssi_var) == (-81.10, 6.58, 7.42)


def test_device_message_defaults_ts_to_now():
    r = parse_device_message(f"espresense/devices/{ALLIE}/office", PAYLOAD)
    assert r is not None and r.ts > 1_700_000_000


def test_device_message_missing_optional_fields():
    r = parse_device_message(f"espresense/devices/{ALLIE}/loft", b'{"rssi":-90}', ts=1.0)
    assert r is not None and r.distance is None and r.rssi_var is None


def test_device_message_rejects_junk():
    assert parse_device_message(f"espresense/devices/{ALLIE}/office", b"not json") is None
    assert parse_device_message(f"espresense/devices/{ALLIE}/office", b'{"id":"x"}') is None
    assert parse_device_message(f"espresense/companion/{ALLIE}", PAYLOAD) is None
    assert parse_device_message("espresense/devices/x", PAYLOAD) is None
```

**Step 2: Run the test and verify it fails.** `uv run pytest -q tests/ingest/test_parse.py`
Expected: FAIL `ModuleNotFoundError: No module named 'wheres_allie.ingest.parse'`

**Step 3: Implement** `box/src/wheres_allie/ingest/parse.py`:
```python
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
```

**Step 4: Run the test and verify it passes.** `uv run pytest -q tests/ingest/test_parse.py`
Expected: `4 passed`

**Step 5: Commit.**
```bash
git add box/src/wheres_allie/ingest/parse.py box/tests/ingest/test_parse.py
git commit -m "feat: parse ESPresense device messages" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 9: ingest/parse.py: room status + telemetry

**Files:**
- Modify: `box/src/wheres_allie/ingest/parse.py`
- Test: `box/tests/ingest/test_parse.py`

**Step 1: Write the failing test.** In `tests/ingest/test_parse.py`, replace the first import line with:
```python
from wheres_allie.ingest.parse import (
    NodeStatus,
    parse_device_message,
    parse_room_status,
    parse_telemetry,
)
```
and append:
```python


def test_room_status():
    assert parse_room_status("espresense/rooms/loft/status", b"offline") == NodeStatus("loft", False)
    assert parse_room_status("espresense/rooms/loft/status", "online") == NodeStatus("loft", True)
    assert parse_room_status("espresense/rooms/loft/status", b"weird") is None
    assert parse_room_status("espresense/rooms/loft/telemetry", b"online") is None


def test_telemetry():
    t = parse_telemetry(
        "espresense/rooms/kitchen/telemetry",
        b'{"ip":"192.168.5.225","uptime":3605,"rssi":-61,"ver":"v4.0.6","adverts":12}',
    )
    assert t is not None
    assert (t.node_id, t.ip, t.wifi_rssi, t.uptime_s, t.version) == (
        "kitchen", "192.168.5.225", -61, 3605, "v4.0.6")
    assert parse_telemetry("espresense/rooms/kitchen/telemetry", b"[]") is None
    assert parse_telemetry("espresense/rooms/kitchen/max_distance", b"{}") is None
```

**Step 2: Run the test and verify it fails.** `uv run pytest -q tests/ingest/test_parse.py`
Expected: FAIL `ImportError: cannot import name 'NodeStatus'`

**Step 3: Implement.** In `parse.py`, add these dataclasses directly below `DeviceReading`:
```python


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
```
Add this helper directly below `_json`:
```python


def _room_topic(topic: str, leaf: str) -> str | None:
    parts = topic.split("/")
    if len(parts) == 4 and parts[0] == "espresense" and parts[1] == "rooms" and parts[3] == leaf:
        return parts[2]
    return None
```
Append at the end of the file:
```python


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
```

**Step 4: Run the test and verify it passes.** `uv run pytest -q tests/ingest/test_parse.py && uv run ruff check .`
Expected: `6 passed`, `All checks passed!`

**Step 5: Commit.**
```bash
git add box/src/wheres_allie/ingest/parse.py box/tests/ingest/test_parse.py
git commit -m "feat: parse ESPresense room status and telemetry" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 10: ingest/mqtt.py: Ingestor

**Files:**
- Create: `box/src/wheres_allie/ingest/mqtt.py`
- Test: `box/tests/ingest/test_mqtt.py`

**Step 1: Write the failing test.** Create `box/tests/ingest/test_mqtt.py`:
```python
from wheres_allie.bus import Bus
from wheres_allie.ingest.mqtt import Ingestor

ALLIE = "iBeacon:426c7565-4368-6172-6d42-6561636f6e73-3838-4949"
ALLIE_MOVING = "iBeacon:426c7565-4368-6172-6d42-6561636f6e73-3838-4950"
PHONE = "iBeacon:e2c56db5-dffb-48d2-b060-d0f5a71096e0-1-2"


def dev(ident, node):
    return f"espresense/devices/{ident}/{node}"


def make(conn, motion=True):
    conn.execute("INSERT INTO pets (id, name) VALUES (1, 'Allie')")
    conn.execute("INSERT INTO tags (id, pet_id, ibeacon_id, motion_ibeacon_id) VALUES (7, 1, ?, ?)",
                 (ALLIE, ALLIE_MOVING if motion else None))
    return Ingestor(conn, Bus())


def test_registered_tag_reading_is_stored(conn):
    ing = make(conn)
    ing.handle(dev(ALLIE, "office"), b'{"rssi":-81.1,"distance":6.58,"rssiVar":7.42}', ts=10.0)
    rows = [tuple(r) for r in conn.execute("SELECT * FROM readings")]
    assert rows == [(10.0, 7, "office", -81.1, 6.58, 7.42)]


def test_unknown_devices_counted_not_stored(conn):
    ing = make(conn)
    ing.handle(dev(PHONE, "office"), b'{"rssi":-60}', ts=100.0)
    ing.handle(dev("apple:1005:9-26", "office"), b'{"rssi":-70}', ts=100.0)
    ing.handle(dev(PHONE, "kitchen"), b'{"rssi":-75}', ts=100.0)
    assert conn.execute("SELECT count(*) FROM readings").fetchone()[0] == 0
    assert ing.nearby_devices("office", now=200.0) == 2
    assert ing.nearby_devices("office", now=100.0 + 601) == 0
    assert ing.candidates(now=200.0) == [
        {"ibeacon_id": PHONE, "node_id": "office", "rssi": -60.0, "last_seen": 100.0}]


def test_reload_tags_picks_up_new_tag(conn):
    ing = Ingestor(conn, Bus())
    conn.execute("INSERT INTO pets (id, name) VALUES (1, 'Allie')")
    conn.execute("INSERT INTO tags (pet_id, ibeacon_id) VALUES (1, ?)", (ALLIE,))
    ing.handle(dev(ALLIE, "office"), b'{"rssi":-80}', ts=1.0)
    ing.reload_tags()
    ing.handle(dev(ALLIE, "office"), b'{"rssi":-80}', ts=2.0)
    assert conn.execute("SELECT count(*) FROM readings").fetchone()[0] == 1


def test_motion_edges(conn):
    ing = make(conn)
    ing.handle(dev(ALLIE_MOVING, "office"), b'{"rssi":-80}', ts=100.0)  # -> moving
    ing.handle(dev(ALLIE_MOVING, "kitchen"), b'{"rssi":-85}', ts=101.0)  # no new edge
    ing.handle(dev(ALLIE, "office"), b'{"rssi":-80}', ts=105.0)  # within hold: still moving
    ing.handle(dev(ALLIE, "office"), b'{"rssi":-80}', ts=112.0)  # -> still
    ing.handle(dev(ALLIE, "office"), b'{"rssi":-80}', ts=120.0)  # no new edge
    assert [tuple(r) for r in conn.execute("SELECT ts, tag_id, moving FROM motion")] == [
        (100.0, 7, 1), (112.0, 7, 0)]
    assert conn.execute("SELECT count(*) FROM readings").fetchone()[0] == 5


async def test_reading_published_on_bus(conn):
    ing = make(conn)
    with ing.bus.subscribe("reading") as sub:
        ing.handle(dev(ALLIE, "loft"), b'{"rssi":-90}', ts=5.0)
        topic, data = sub.queue.get_nowait()
    assert topic == "reading" and data["node_id"] == "loft" and data["tag_id"] == 7


def test_node_status_and_telemetry(conn):
    ing = Ingestor(conn, Bus())
    with ing.bus.subscribe("node.health") as sub:
        ing.handle("espresense/rooms/loft/status", b"online", ts=1.0)
        ing.handle("espresense/rooms/loft/telemetry",
                   b'{"ip":"192.168.5.222","uptime":60,"rssi":-70,"ver":"v4.0.6"}', ts=2.0)
        ing.handle("espresense/rooms/loft/status", b"offline", ts=3.0)
        events = [sub.queue.get_nowait() for _ in range(3)]
    row = dict(conn.execute("SELECT * FROM nodes WHERE id = 'loft'").fetchone())
    assert row == {
        "id": "loft", "name": None, "online": 0, "last_seen": 3.0, "ip": "192.168.5.222",
        "wifi_rssi": -70, "uptime_s": 60, "version": "v4.0.6", "calib_json": None}
    assert [e[1]["online"] for e in events] == [True, True, False]
```

**Step 2: Run the test and verify it fails.** `uv run pytest -q tests/ingest/test_mqtt.py`
Expected: FAIL `ModuleNotFoundError: No module named 'wheres_allie.ingest.mqtt'`

**Step 3: Implement** `box/src/wheres_allie/ingest/mqtt.py`:
```python
"""MQTT ingest: ESPresense messages -> readings, motion edges, node health."""

import sqlite3
import time

from wheres_allie.bus import Bus
from wheres_allie.ingest.parse import (
    DeviceReading,
    NodeStatus,
    NodeTelemetry,
    parse_device_message,
    parse_room_status,
    parse_telemetry,
)

MOTION_HOLD_S = 10.0  # BC021 keeps the motion id up ~10 s; normal id within this is still "moving"
UNKNOWN_TTL_S = 600.0  # unregistered devices count as "nearby" for 10 min


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
```

**Step 4: Run the test and verify it passes.** `uv run pytest -q tests/ingest && uv run ruff check .`
Expected: `12 passed`, `All checks passed!`

**Step 5: Commit.**
```bash
git add box/src/wheres_allie/ingest/mqtt.py box/tests/ingest/test_mqtt.py
git commit -m "feat: Ingestor maps tags, motion edges, unknown devices and node health" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 11: ingest/mqtt.py: run_ingest + gaps

**Files:**
- Modify: `box/src/wheres_allie/ingest/mqtt.py`
- Test: `box/tests/ingest/test_mqtt.py`

**Step 1: Write the failing test.** Append to `tests/ingest/test_mqtt.py`:
```python


def test_record_gap_only_when_longer_than_10s(conn):
    from wheres_allie.ingest.mqtt import record_gap
    record_gap(conn, 100.0, 105.0)
    record_gap(conn, 200.0, 260.0)
    assert [tuple(r) for r in conn.execute("SELECT * FROM gaps")] == [
        (200.0, 260.0, "mqtt_disconnect")]
```

**Step 2: Run the test and verify it fails.** `uv run pytest -q tests/ingest/test_mqtt.py`
Expected: FAIL `ImportError: cannot import name 'record_gap'`

**Step 3: Implement.** In `mqtt.py`, replace the import block (everything above `MOTION_HOLD_S`) with:
```python
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
```
Add `GAP_MIN_S = 10.0` below `UNKNOWN_TTL_S`, then append at the end of the file:
```python


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
```
`run_ingest` against a real broker is exercised by the compose smoke test (Task 28).

**Step 4: Run the test and verify it passes.** `uv run pytest -q tests/ingest && uv run ruff check .`
Expected: `13 passed`, `All checks passed!`

**Step 5: Commit.**
```bash
git add box/src/wheres_allie/ingest/mqtt.py box/tests/ingest/test_mqtt.py
git commit -m "feat: run_ingest with reconnect backoff and gap recording" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 12: retention.py

**Files:**
- Create: `box/src/wheres_allie/retention.py`
- Test: `box/tests/test_retention.py`

**Step 1: Write the failing test.**
```python
from wheres_allie.retention import DAY, prune

NOW = 1_800_000_000.0


def test_prune_tiers(conn):
    for age_days in (1, 29, 31, 364, 366):
        ts = NOW - age_days * DAY
        conn.execute("INSERT INTO readings VALUES (?, 1, 'office', -70, NULL, NULL)", (ts,))
        conn.execute("INSERT INTO positions VALUES (?, 1, 'room:x', NULL, NULL, 0.9, NULL)", (ts,))
        conn.execute("INSERT INTO motion VALUES (?, 1, 1)", (ts,))
    assert prune(conn, now=NOW) == {"readings": 3, "positions": 1}
    assert conn.execute("SELECT count(*) FROM readings").fetchone()[0] == 2
    assert conn.execute("SELECT count(*) FROM positions").fetchone()[0] == 4
    assert conn.execute("SELECT count(*) FROM motion").fetchone()[0] == 5
```

**Step 2: Run the test and verify it fails.** `uv run pytest -q tests/test_retention.py`
Expected: FAIL `ModuleNotFoundError: No module named 'wheres_allie.retention'`

**Step 3: Implement** `box/src/wheres_allie/retention.py`:
```python
"""Tiered retention: raw readings 30 days, positions 1 year, everything else forever."""

import asyncio
import sqlite3
import time

DAY = 86400.0
READINGS_DAYS = 30
POSITIONS_DAYS = 365


def prune(conn: sqlite3.Connection, now: float | None = None) -> dict[str, int]:
    now = time.time() if now is None else now
    readings = conn.execute("DELETE FROM readings WHERE ts < ?",
                            (now - READINGS_DAYS * DAY,)).rowcount
    positions = conn.execute("DELETE FROM positions WHERE ts < ?",
                             (now - POSITIONS_DAYS * DAY,)).rowcount
    return {"readings": readings, "positions": positions}


async def run_retention(conn: sqlite3.Connection, every_s: float = 6 * 3600) -> None:
    # ponytail: fixed interval, not "nightly"; pin to 03:00 local if deletes ever stall ingest
    while True:
        await asyncio.to_thread(prune, conn)
        await asyncio.sleep(every_s)
```

**Step 4: Run the test and verify it passes.** `uv run pytest -q tests/test_retention.py`
Expected: `1 passed`

**Step 5: Commit.**
```bash
git add box/src/wheres_allie/retention.py box/tests/test_retention.py
git commit -m "feat: tiered retention (readings 30 d, positions 1 y)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 13: replay/bundle.py

**Files:**
- Create: `box/src/wheres_allie/replay/bundle.py`
- Test: `box/tests/replay/test_bundle.py`

**Step 1: Write the failing test.** Run `mkdir -p tests/replay`, then create `box/tests/replay/test_bundle.py`:
```python
import json
import zipfile

import pytest

from wheres_allie.replay.bundle import Bundle, read_bundle, write_bundle

ALLIE = "iBeacon:426c7565-4368-6172-6d42-6561636f6e73-3838-4949"
MANIFEST = {"format": 1, "created": 1.0, "tz": "America/New_York",
            "pets": [{"name": "Allie", "ibeacon_id": ALLIE, "motion_ibeacon_id": None}],
            "from": 10.0, "to": 11.5}


def test_round_trip(tmp_path):
    b = Bundle(
        manifest=MANIFEST,
        readings=[(10.0, ALLIE, "office", -81.1, 6.58, 7.42), (11.5, ALLIE, "loft", -90.0, None, None)],
        motion=[(10.0, ALLIE, 1)],
        labels=[(10.0, 11.0, ALLIE, "lm:bed", "walk")],
    )
    path = tmp_path / "a.bundle"
    write_bundle(path, b)
    names = set(zipfile.ZipFile(path).namelist())
    assert names == {"manifest.json", "home.json", "readings.csv", "motion.csv", "labels.csv"}
    back = read_bundle(path)
    assert back == b
    assert back.ground_truth is None


def test_rejects_unknown_format(tmp_path):
    path = tmp_path / "bad.bundle"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("manifest.json", json.dumps({"format": 99}))
    with pytest.raises(ValueError, match="format"):
        read_bundle(path)
```

**Step 2: Run the test and verify it fails.** `uv run pytest -q tests/replay`
Expected: FAIL `ModuleNotFoundError: No module named 'wheres_allie.replay.bundle'`

**Step 3: Implement** `box/src/wheres_allie/replay/bundle.py`:
```python
"""Replay bundle: a zip of manifest.json, home.json and CSVs (conventions §13)."""

import csv
import io
import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

FORMAT = 1
EMPTY_HOME = {"version": 0, "floors": [], "walls": [], "room_labels": [], "doors": [],
              "stairs": [], "landmarks": [], "nodes": []}
COLUMNS = {
    "readings.csv": ("ts", "ibeacon_id", "node_id", "rssi", "distance", "rssi_var"),
    "motion.csv": ("ts", "ibeacon_id", "moving"),
    "labels.csv": ("ts_start", "ts_end", "ibeacon_id", "vertex_id", "source"),
    "ground_truth.csv": ("ts_start", "ts_end", "ibeacon_id", "place"),
}
FLOATS = {"ts", "rssi", "distance", "rssi_var", "ts_start", "ts_end"}


@dataclass
class Bundle:
    manifest: dict
    home: dict = field(default_factory=lambda: dict(EMPTY_HOME))
    readings: list[tuple] = field(default_factory=list)
    motion: list[tuple] = field(default_factory=list)
    labels: list[tuple] = field(default_factory=list)
    ground_truth: list[tuple] | None = None


def _csv_text(name: str, rows: list[tuple]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(COLUMNS[name])
    w.writerows(rows)  # None -> empty cell
    return buf.getvalue()


def _cell(col: str, v: str):
    if v == "":
        return None
    if col in FLOATS:
        return float(v)
    return int(v) if col == "moving" else v


def _csv_rows(z: zipfile.ZipFile, name: str) -> list[tuple]:
    reader = csv.reader(io.StringIO(z.read(name).decode()))
    header = next(reader)
    return [tuple(_cell(c, v) for c, v in zip(header, row)) for row in reader]


def write_bundle(path: str | Path, b: Bundle) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(b.manifest, indent=2))
        z.writestr("home.json", json.dumps(b.home))
        z.writestr("readings.csv", _csv_text("readings.csv", b.readings))
        z.writestr("motion.csv", _csv_text("motion.csv", b.motion))
        z.writestr("labels.csv", _csv_text("labels.csv", b.labels))
        if b.ground_truth is not None:
            z.writestr("ground_truth.csv", _csv_text("ground_truth.csv", b.ground_truth))


def read_bundle(path: str | Path) -> Bundle:
    with zipfile.ZipFile(path) as z:
        manifest = json.loads(z.read("manifest.json"))
        if manifest.get("format") != FORMAT:
            raise ValueError(f"unsupported bundle format {manifest.get('format')!r}")
        names = set(z.namelist())
        return Bundle(
            manifest=manifest,
            home=json.loads(z.read("home.json")),
            readings=_csv_rows(z, "readings.csv"),
            motion=_csv_rows(z, "motion.csv"),
            labels=_csv_rows(z, "labels.csv"),
            ground_truth=_csv_rows(z, "ground_truth.csv") if "ground_truth.csv" in names else None,
        )
```

**Step 4: Run the test and verify it passes.** `uv run pytest -q tests/replay && uv run ruff check .`
Expected: `2 passed`, `All checks passed!`

**Step 5: Commit.**
```bash
git add box/src/wheres_allie/replay/bundle.py box/tests/replay/test_bundle.py
git commit -m "feat: replay bundle writer and reader" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 14: tools/import_raw_log.py

**Files:**
- Create: `box/tools/import_raw_log.py`
- Test: `box/tests/test_import_raw_log.py`

**Step 1: Write the failing test.**
```python
import subprocess
import sys
from pathlib import Path

from wheres_allie.replay.bundle import read_bundle

TOOL = Path(__file__).parents[1] / "tools" / "import_raw_log.py"
ALLIE = "iBeacon:426c7565-4368-6172-6d42-6561636f6e73-3838-4949"
LOG = f"""\
2026-09-28T22:34:08-04:00 espresense/companion/{ALLIE} Office
2026-09-28T22:34:08-04:00 espresense/rooms/office/status online
2026-09-28T22:34:11-04:00 espresense/devices/{ALLIE}/office {{"mac":"dd8800003777","id":"{ALLIE}","rssi@1m":-59,"rssi":-81.10,"rxAdj":0,"rssiVar":7.42,"distance":6.58,"var":4.00,"int":2028}}
garbage line
2026-09-28T22:34:16-04:00 espresense/devices/{ALLIE}/loft {{"rssi":-90.5}}
"""


def test_import_raw_log(tmp_path):
    log, out = tmp_path / "raw.log", tmp_path / "out.bundle"
    log.write_text(LOG)
    res = subprocess.run([sys.executable, str(TOOL), str(log), str(out)],
                         capture_output=True, text=True, check=True)
    assert "2 readings" in res.stdout
    b = read_bundle(out)
    assert b.readings == [
        (1790649251.0, ALLIE, "office", -81.1, 6.58, 7.42),
        (1790649256.0, ALLIE, "loft", -90.5, None, None),
    ]
    assert b.manifest["pets"][0]["name"] == "Allie"
    assert (b.manifest["from"], b.manifest["to"]) == (1790649251.0, 1790649256.0)
```

**Step 2: Run the test and verify it fails.** `uv run pytest -q tests/test_import_raw_log.py`
Expected: FAIL `CalledProcessError … can't open file '…/tools/import_raw_log.py'`

**Step 3: Implement** `box/tools/import_raw_log.py`:
```python
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
```

**Step 4: Run the test and verify it passes.** `uv run pytest -q tests/test_import_raw_log.py`
Expected: `1 passed`. Sanity check against the real log: `uv run python tools/import_raw_log.py ../data/allie-raw.log /tmp/check.bundle` prints `N readings -> /tmp/check.bundle`. N was 852 on 2026-09-28 at 23:35, and it grows while the logger runs.

**Step 5: Commit.**
```bash
git add box/tools/import_raw_log.py box/tests/test_import_raw_log.py
git commit -m "feat: import raw MQTT log into a replay bundle" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 15: nodes/espresense_http.py

**Files:**
- Create: `box/src/wheres_allie/nodes/espresense_http.py`
- Test: `box/tests/nodes/test_espresense_http.py`

Background (read in the v4.0.6 and HeadlessWiFiSettings v1.1.4 source):
- `GET /wifi/main` returns `{"values": {...}, "defaults": {...}}`. Password-type fields (`wifi-password`, `mqtt_user`, `mqtt_pass`) come back as `***###***`, and posting that mask back leaves them unchanged.
- `POST /wifi/main` is form-encoded and sets **every** field of the endpoint. An absent field is blanked, and a present checkbox counts as on.
- Saving does not reboot the node. `POST /restart` does.

**Step 1: Write the failing test.** Run `mkdir -p tests/nodes`, then create `box/tests/nodes/test_espresense_http.py`:
```python
from urllib.parse import parse_qs

import httpx
import pytest
import respx

from wheres_allie.nodes.espresense_http import MASK, build_form, push_settings, restart

IP = "192.168.5.232"
URL = f"http://{IP}/wifi/main"
CURRENT = {"room": "office", "wifi-ssid": "HomeNet", "wifi-password": MASK,
           "wifi_timeout": 30, "mqtt_host": "192.168.5.132", "mqtt_port": 1883,
           "mqtt_user": MASK, "mqtt_pass": MASK, "discovery": True, "pub_tele": True,
           "pub_devices": True, "auto_update": True, "prerelease": False, "arduino_ota": True}
NEW = {"mqtt_host": "192.168.5.254", "mqtt_user": "wheres_allie", "mqtt_pass": "pw",
       "auto_update": False}


def test_build_form_resends_everything():
    form = build_form(CURRENT, NEW)
    assert form["wifi-password"] == MASK  # unchanged on the node
    assert form["mqtt_host"] == "192.168.5.254" and form["mqtt_port"] == "1883"
    assert form["discovery"] == "1"
    assert "auto_update" not in form and "prerelease" not in form  # unchecked = absent


@respx.mock
async def test_push_settings_posts_full_form_and_verifies():
    after = CURRENT | {"mqtt_host": "192.168.5.254", "auto_update": False}
    respx.get(URL).mock(side_effect=[httpx.Response(200, json={"values": CURRENT, "defaults": {}}),
                                     httpx.Response(200, json={"values": after, "defaults": {}})])
    post = respx.post(URL).mock(return_value=httpx.Response(200))
    async with httpx.AsyncClient() as client:
        changes = await push_settings(client, IP, NEW, expect_room="office")
    sent = {k: v[0] for k, v in parse_qs(post.calls.last.request.content.decode()).items()}
    assert sent == build_form(CURRENT, NEW)
    assert changes["mqtt_pass"] == (MASK, MASK)  # never echo secrets
    assert changes["mqtt_host"] == ("192.168.5.132", "192.168.5.254")


@respx.mock
async def test_dry_run_does_not_post():
    respx.get(URL).mock(return_value=httpx.Response(200, json={"values": CURRENT}))
    post = respx.post(URL)
    async with httpx.AsyncClient() as client:
        changes = await push_settings(client, IP, NEW, dry_run=True)
    assert not post.called and "mqtt_host" in changes


@respx.mock
async def test_wrong_room_or_missing_wifi_aborts():
    respx.get(URL).mock(return_value=httpx.Response(200, json={"values": CURRENT}))
    async with httpx.AsyncClient() as client:
        with pytest.raises(ValueError, match="expected 'loft'"):
            await push_settings(client, IP, NEW, expect_room="loft")
    respx.get(URL).mock(return_value=httpx.Response(200, json={"values": {"room": "office"}}))
    async with httpx.AsyncClient() as client:
        with pytest.raises(ValueError, match="wifi-ssid"):
            await push_settings(client, IP, NEW)


@respx.mock
async def test_unexpected_change_after_save_raises():
    broken = CURRENT | {"wifi_timeout": 0}
    respx.get(URL).mock(side_effect=[httpx.Response(200, json={"values": CURRENT}),
                                     httpx.Response(200, json={"values": broken})])
    respx.post(URL).mock(return_value=httpx.Response(200))
    async with httpx.AsyncClient() as client:
        with pytest.raises(RuntimeError, match="wifi_timeout"):
            await push_settings(client, IP, NEW)


@respx.mock
async def test_restart_tolerates_dropped_connection():
    respx.post(f"http://{IP}/restart").mock(side_effect=httpx.ReadError("reset"))
    async with httpx.AsyncClient() as client:
        await restart(client, IP)
```

**Step 2: Run the test and verify it fails.** `uv run pytest -q tests/nodes`
Expected: FAIL `ModuleNotFoundError: No module named 'wheres_allie.nodes.espresense_http'`

**Step 3: Implement** `box/src/wheres_allie/nodes/espresense_http.py`:
```python
"""Push settings to ESPresense v4.0.6 nodes over HTTP (HeadlessWiFiSettings v1.1.4).

GET /wifi/main returns {"values": {...}, "defaults": {...}}; passwords come back as MASK.
POST /wifi/main (form-encoded) overwrites EVERY field of the endpoint: a missing field is
blanked, a present checkbox is on. So we always resend the full current values. Sending MASK
for a password leaves it unchanged. Saving does not reboot; POST /restart does.
"""

import httpx

MASK = "***###***"
SECRET_KEYS = {"wifi-password", "mqtt_user", "mqtt_pass"}


async def get_main(client: httpx.AsyncClient, ip: str) -> dict:
    r = await client.get(f"http://{ip}/wifi/main", timeout=10)
    r.raise_for_status()
    return r.json()["values"]


def build_form(values: dict, overrides: dict) -> dict[str, str]:
    form = {}
    for k, v in (values | overrides).items():
        if v is None or v is False:
            continue  # absent field = blank / unchecked
        form[k] = "1" if v is True else str(v)
    return form


async def push_settings(client: httpx.AsyncClient, ip: str, overrides: dict,
                        expect_room: str | None = None, dry_run: bool = False) -> dict:
    """Merge overrides into the node's current settings and save. Returns {key: (old, new)}."""
    values = await get_main(client, ip)
    if expect_room is not None and values.get("room") != expect_room:
        raise ValueError(f"{ip} is room {values.get('room')!r}, expected {expect_room!r}")
    if not values.get("wifi-ssid"):
        raise ValueError(f"{ip}: no wifi-ssid in current settings; refusing to overwrite")
    changes = {k: (values.get(k), MASK if k in SECRET_KEYS else v)
               for k, v in overrides.items() if values.get(k) != v}
    if dry_run:
        return changes
    r = await client.post(f"http://{ip}/wifi/main", data=build_form(values, overrides), timeout=10)
    r.raise_for_status()
    after = await get_main(client, ip)
    lost = sorted(k for k in values if k not in overrides and after.get(k) != values[k])
    if lost:
        raise RuntimeError(f"{ip}: fields changed unexpectedly after save: {lost}")
    return changes


async def restart(client: httpx.AsyncClient, ip: str) -> None:
    try:
        await client.post(f"http://{ip}/restart", timeout=5)
    except httpx.TransportError:
        pass  # the node may drop the connection while rebooting
```

**Step 4: Run the test and verify it passes.** `uv run pytest -q tests/nodes && uv run ruff check .`
Expected: `6 passed`, `All checks passed!`

**Step 5: Commit.**
```bash
git add box/src/wheres_allie/nodes/espresense_http.py box/tests/nodes/test_espresense_http.py
git commit -m "feat: safe full-form ESPresense settings push over HTTP" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 16: tools/repoint_nodes.py + runbook

**Files:**
- Create: `box/tools/repoint_nodes.py`
- Create: `docs/runbooks/move-nodes-to-box.md`

All the logic is tested in Task 15. This script only parses arguments and loops over nodes.

**Step 1: Write a failing check.** `uv run python tools/repoint_nodes.py --help`
Expected: FAIL `can't open file '…/tools/repoint_nodes.py'`

**Step 2: Implement** `box/tools/repoint_nodes.py`:
```python
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
```

**Step 3: Write the runbook** `docs/runbooks/move-nodes-to-box.md`:
```markdown
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
```

**Step 4: Verify.** `uv run python tools/repoint_nodes.py --help && uv run ruff check .`
Expected: usage text beginning `usage: repoint_nodes.py [-h] --host HOST`, and `All checks passed!`

**Step 5: Commit.**
```bash
git add box/tools/repoint_nodes.py docs/runbooks/move-nodes-to-box.md
git commit -m "feat: repoint_nodes tool and runbook for moving nodes to the box broker" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 17: api/app.py factory + /api/health + deps

**Files:**
- Create: `box/src/wheres_allie/api/app.py`, `box/src/wheres_allie/api/deps.py`
- Modify: `box/tests/conftest.py`
- Test: `box/tests/api/test_health.py`

**Step 1: Write the failing test.** Append these fixtures to `box/tests/conftest.py`:
```python


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
```
Run `mkdir -p tests/api`, then create `box/tests/api/test_health.py`:
```python
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
```

**Step 2: Run the test and verify it fails.** `uv run pytest -q tests/api`
Expected: FAIL `ModuleNotFoundError: No module named 'wheres_allie.api.app'`

**Step 3: Implement.** Create `box/src/wheres_allie/api/deps.py`:
```python
import sqlite3
from typing import Annotated

from fastapi import Depends, Request

from wheres_allie.bus import Bus
from wheres_allie.config import Settings
from wheres_allie.ingest.mqtt import Ingestor


def get_conn(request: Request) -> sqlite3.Connection:
    return request.app.state.conn


def get_bus(request: Request) -> Bus:
    return request.app.state.bus


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_ingestor(request: Request) -> Ingestor:
    return request.app.state.ingestor


Conn = Annotated[sqlite3.Connection, Depends(get_conn)]
Cfg = Annotated[Settings, Depends(get_settings)]
Ing = Annotated[Ingestor, Depends(get_ingestor)]
```
Create `box/src/wheres_allie/api/app.py`:
```python
import asyncio
import sqlite3
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from wheres_allie import __version__, db
from wheres_allie.bus import Bus
from wheres_allie.config import Settings
from wheres_allie.ingest.mqtt import Ingestor, run_ingest
from wheres_allie.retention import run_retention


def create_app(settings: Settings | None = None, conn: sqlite3.Connection | None = None,
               start_background: bool = True) -> FastAPI:
    settings = settings or Settings()
    if conn is None:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        conn = db.connect(settings.db_path)
    db.migrate(conn)
    bus = Bus()
    ingestor = Ingestor(conn, bus)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        tasks = []
        if start_background:  # later plans append their background tasks here
            tasks = [asyncio.create_task(run_ingest(settings, conn, bus, ingestor)),
                     asyncio.create_task(run_retention(conn))]
        yield
        for t in tasks:
            t.cancel()

    app = FastAPI(title="wheres_allie", version=__version__, lifespan=lifespan)
    app.state.settings, app.state.conn, app.state.bus = settings, conn, bus
    app.state.ingestor = ingestor
    app.state.relay_status = "offline"  # set by relaylink (plan 06)

    @app.get("/api/health")
    def health(request: Request) -> dict:
        relay = request.app.state.relay_status if settings.relay_url else "disabled"
        return {"ok": True, "version": __version__, "relay": relay}

    return app
```

**Step 4: Run the test and verify it passes.** `uv run pytest -q && uv run ruff check .`
Expected: all pass (`32 passed`), `All checks passed!`

**Step 5: Commit.**
```bash
git add box/src/wheres_allie/api/app.py box/src/wheres_allie/api/deps.py box/tests/conftest.py box/tests/api/test_health.py
git commit -m "feat: FastAPI app factory with background ingest/retention and /api/health" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 18: GET/PUT /api/settings

**Files:**
- Modify: `box/src/wheres_allie/api/app.py`
- Test: `box/tests/api/test_settings_api.py`

**Step 1: Write the failing test.**
```python
def test_defaults(client):
    assert client.get("/api/settings").json() == {
        "tz": "America/New_York", "units": "ft", "home_name": "Home"}


def test_put_then_get(client):
    body = {"tz": "America/Chicago", "units": "m", "home_name": "Stonely house"}
    assert client.put("/api/settings", json=body).json() == body
    assert client.get("/api/settings").json() == body


def test_rejects_bad_values(client):
    assert client.put("/api/settings", json={"tz": "Mars/Base", "units": "m",
                                             "home_name": "x"}).status_code == 422
    assert client.put("/api/settings", json={"tz": "UTC", "units": "yards",
                                             "home_name": "x"}).status_code == 422
```

**Step 2: Run the test and verify it fails.** `uv run pytest -q tests/api/test_settings_api.py`
Expected: FAIL `AssertionError` (the response is `{'detail': 'Not Found'}`)

**Step 3: Implement.** In `api/app.py`:
- Add these imports: `from typing import Literal`, `from zoneinfo import ZoneInfo, ZoneInfoNotFoundError`, `from pydantic import BaseModel, Field` and `from wheres_allie.api.deps import Cfg, Conn`.
- Change the fastapi import to `from fastapi import FastAPI, HTTPException, Request`.

Add these above `create_app`:
```python
class SiteSettings(BaseModel):
    tz: str
    units: Literal["ft", "m"]
    home_name: str = Field(min_length=1, max_length=60)


def read_site_settings(conn: sqlite3.Connection, settings: Settings) -> SiteSettings:
    return SiteSettings(tz=db.get_setting(conn, "tz", settings.tz),
                        units=db.get_setting(conn, "units", "ft"),
                        home_name=db.get_setting(conn, "home_name", "Home"))
```
Add these directly after the `health` route, inside `create_app`:
```python

    @app.get("/api/settings")
    def get_settings(conn: Conn, cfg: Cfg) -> SiteSettings:
        return read_site_settings(conn, cfg)

    @app.put("/api/settings")
    def put_settings(body: SiteSettings, conn: Conn, cfg: Cfg) -> SiteSettings:
        try:
            ZoneInfo(body.tz)
        except (ZoneInfoNotFoundError, ValueError):
            raise HTTPException(422, f"unknown time zone {body.tz!r}") from None
        for key, value in body.model_dump().items():
            db.set_setting(conn, key, value)
        return read_site_settings(conn, cfg)
```

**Step 4: Run the test and verify it passes.** `uv run ruff check --fix . && uv run pytest -q tests/api`
Expected: `6 passed`

**Step 5: Commit.**
```bash
git add box/src/wheres_allie/api/app.py box/tests/api/test_settings_api.py
git commit -m "feat: GET/PUT /api/settings (tz, units, home_name)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 19: GET /api/nodes

**Files:**
- Create: `box/src/wheres_allie/api/routes/nodes.py`
- Modify: `box/src/wheres_allie/api/app.py`
- Test: `box/tests/api/test_nodes_api.py`

**Step 1: Write the failing test.**
```python
import json
import time


def test_nodes_with_health_placed_and_nearby(client):
    conn, ing = client.app.state.conn, client.app.state.ingestor
    ing.handle("espresense/rooms/office/telemetry",
               b'{"ip":"192.168.5.232","uptime":5,"rssi":-60,"ver":"v4.0.6"}')
    ing.handle("espresense/rooms/loft/status", b"offline")
    ing.handle("espresense/devices/apple:1005:9-26/office", b'{"rssi":-70}', ts=time.time())
    conn.execute("INSERT INTO home (saved_at, json) VALUES (0, ?)",
                 (json.dumps({"nodes": [{"id": "office"}]}),))
    nodes = client.get("/api/nodes").json()
    assert [(n["id"], n["online"], n["placed"], n["nearby_devices"]) for n in nodes] == [
        ("loft", False, False, 0), ("office", True, True, 1)]
    assert nodes[1]["ip"] == "192.168.5.232"
```

**Step 2: Run the test and verify it fails.** `uv run pytest -q tests/api/test_nodes_api.py`
Expected: FAIL `TypeError: string indices must be integers` (the 404 body is a dict)

**Step 3: Implement** `box/src/wheres_allie/api/routes/nodes.py`:
```python
import json

from fastapi import APIRouter

from wheres_allie.api.deps import Conn, Ing

router = APIRouter()


@router.get("/nodes")
def list_nodes(conn: Conn, ing: Ing) -> list[dict]:
    home = conn.execute("SELECT json FROM home ORDER BY version DESC LIMIT 1").fetchone()
    placed = {n["id"] for n in json.loads(home["json"]).get("nodes", [])} if home else set()
    return [dict(r) | {"online": bool(r["online"]), "placed": r["id"] in placed,
                       "nearby_devices": ing.nearby_devices(r["id"])}
            for r in conn.execute("SELECT * FROM nodes ORDER BY id")]
```
In `api/app.py`, add `from wheres_allie.api.routes import nodes`, and add `app.include_router(nodes.router, prefix="/api")` on the line after `app.state.relay_status = …`.

**Step 4: Run the test and verify it passes.** `uv run ruff check --fix . && uv run pytest -q tests/api`
Expected: `7 passed`

**Step 5: Commit.**
```bash
git add box/src/wheres_allie/api/routes/nodes.py box/src/wheres_allie/api/app.py box/tests/api/test_nodes_api.py
git commit -m "feat: GET /api/nodes with health, placed and nearby device count" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 20: pets, tags, tag candidates

**Files:**
- Create: `box/src/wheres_allie/api/routes/pets.py`
- Modify: `box/src/wheres_allie/api/app.py`
- Test: `box/tests/api/test_pets_api.py`

**Step 1: Write the failing test.**
```python
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
```

**Step 2: Run the test and verify it fails.** `uv run pytest -q tests/api/test_pets_api.py`
Expected: FAIL `AssertionError` (the body is `{'detail': 'Not Found'}`)

**Step 3: Implement** `box/src/wheres_allie/api/routes/pets.py`:
```python
import sqlite3

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from wheres_allie.api.deps import Conn, Ing

router = APIRouter()


class PetIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    species: str = "dog"


class TagIn(BaseModel):
    ibeacon_id: str = Field(min_length=3)
    motion_ibeacon_id: str | None = None


def _pets(conn: sqlite3.Connection) -> list[dict]:
    pets = {r["id"]: dict(r) | {"tags": []} for r in conn.execute("SELECT * FROM pets ORDER BY id")}
    for t in conn.execute("SELECT * FROM tags ORDER BY id"):
        pets[t["pet_id"]]["tags"].append(dict(t))
    return list(pets.values())


def _pet(conn: sqlite3.Connection, pet_id: int) -> dict:
    for p in _pets(conn):
        if p["id"] == pet_id:
            return p
    raise HTTPException(404, "pet not found")


@router.get("/pets")
def list_pets(conn: Conn) -> list[dict]:
    return _pets(conn)


@router.post("/pets")
def create_pet(body: PetIn, conn: Conn) -> dict:
    try:
        cur = conn.execute("INSERT INTO pets (name, species) VALUES (?, ?)",
                           (body.name, body.species))
    except sqlite3.IntegrityError:
        raise HTTPException(409, f"a pet named {body.name!r} already exists") from None
    return _pet(conn, cur.lastrowid)


@router.post("/pets/{pet_id}/tags")
def add_tag(pet_id: int, body: TagIn, conn: Conn, ing: Ing) -> dict:
    _pet(conn, pet_id)
    try:
        conn.execute("INSERT INTO tags (pet_id, ibeacon_id, motion_ibeacon_id) VALUES (?, ?, ?)",
                     (pet_id, body.ibeacon_id, body.motion_ibeacon_id))
    except sqlite3.IntegrityError:
        raise HTTPException(409, "that iBeacon id is already registered") from None
    ing.reload_tags()
    return _pet(conn, pet_id)


@router.get("/tags/candidates")
def tag_candidates(ing: Ing) -> list[dict]:
    return ing.candidates()
```
In `api/app.py`, change the routes import to `from wheres_allie.api.routes import nodes, pets`, and add `app.include_router(pets.router, prefix="/api")` after the nodes router line.

**Step 4: Run the test and verify it passes.** `uv run ruff check --fix . && uv run pytest -q tests/api`
Expected: `10 passed`

**Step 5: Commit.**
```bash
git add box/src/wheres_allie/api/routes/pets.py box/src/wheres_allie/api/app.py box/tests/api/test_pets_api.py
git commit -m "feat: pets, tag registration and tag candidates API" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 21: WS /api/ws

**Files:**
- Create: `box/src/wheres_allie/api/ws.py`
- Modify: `box/src/wheres_allie/api/app.py`
- Test: `box/tests/api/test_ws.py`

**Step 1: Write the failing test.**
```python
def test_ws_forwards_bus_events(client):
    bus = client.app.state.bus
    with client.websocket_connect("/api/ws") as ws:
        client.portal.call(bus.publish, "node.health", {"id": "office", "online": True})
        assert ws.receive_json() == {"topic": "node.health",
                                     "data": {"id": "office", "online": True}}
    assert bus._subs == []
```

**Step 2: Run the test and verify it fails.** `uv run pytest -q tests/api/test_ws.py`
Expected: FAIL `starlette.websockets.WebSocketDisconnect` (no route)

**Step 3: Implement** `box/src/wheres_allie/api/ws.py`:
```python
import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


@router.websocket("/ws")
async def events(websocket: WebSocket) -> None:
    """Forward every bus event to the GUI as {topic, data}."""
    with websocket.app.state.bus.subscribe("") as sub:  # subscribe before accept: no lost events
        await websocket.accept()

        async def pump() -> None:
            async for topic, data in sub:
                await websocket.send_json({"topic": topic, "data": data})

        task = asyncio.create_task(pump())
        try:
            while True:
                await websocket.receive_text()  # raises on disconnect; client messages ignored
        except WebSocketDisconnect:
            pass
        finally:
            task.cancel()
```
In `api/app.py`, add `from wheres_allie.api import ws`, and add `app.include_router(ws.router, prefix="/api")` after the pets router line.

**Step 4: Run the test and verify it passes.** `uv run ruff check --fix . && for i in 1 2 3; do uv run pytest -q tests/api/test_ws.py; done`
Expected: `1 passed`, three times; this confirms the test is not flaky.

**Step 5: Commit.**
```bash
git add box/src/wheres_allie/api/ws.py box/src/wheres_allie/api/app.py box/tests/api/test_ws.py
git commit -m "feat: /api/ws forwards bus events to the GUI" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 22: Serve web/dist with SPA fallback

**Files:**
- Modify: `box/src/wheres_allie/api/app.py`
- Test: `box/tests/api/test_static.py`

**Step 1: Write the failing test.**
```python
from fastapi.testclient import TestClient

from wheres_allie.api.app import create_app


def test_serves_spa_with_client_side_routes(settings, conn, tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<div id=root></div>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    settings.web_dist = dist
    with TestClient(create_app(settings, conn=conn, start_background=False)) as c:
        assert c.get("/").text == "<div id=root></div>"
        assert c.get("/nodes").text == "<div id=root></div>"
        assert c.get("/assets/app.js").text == "console.log(1)"
        assert c.get("/api/health").json()["ok"] is True
        assert c.get("/api/nope").status_code == 404
        assert c.get("/mcp/nope").status_code == 404


def test_no_dist_means_api_only(client):
    assert client.get("/").status_code == 404
```

**Step 2: Run the test and verify it fails.** `uv run pytest -q tests/api/test_static.py`
Expected: FAIL on `assert c.get("/").text == …` (the response is `{"detail":"Not Found"}`)

**Step 3: Implement.** In `api/app.py`, add `from fastapi.staticfiles import StaticFiles` and `from starlette.exceptions import HTTPException as StarletteHTTPException`. StaticFiles raises Starlette's base class, not FastAPI's subclass. Add this class above `SiteSettings`:
```python
class SPAStaticFiles(StaticFiles):
    """Serves web/dist; unknown non-/api, non-/mcp paths get index.html (client-side routes)."""

    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as e:
            if e.status_code != 404 or path.startswith(("api", "mcp")):
                raise
            return await super().get_response("index.html", scope)
```
Replace the final `return app` of `create_app` with:
```python
    # Keep this mount LAST: it matches every path not claimed above (plans add /mcp before it).
    if settings.web_dist.is_dir():
        app.mount("/", SPAStaticFiles(directory=settings.web_dist, html=True), name="web")
    return app
```

**Step 4: Run the test and verify it passes.** `uv run ruff check --fix . && uv run pytest -q && uv run ruff check .`
Expected: `42 passed`, `All checks passed!`

**Step 5: Commit.**
```bash
git add box/src/wheres_allie/api/app.py box/tests/api/test_static.py
git commit -m "feat: serve the built GUI with SPA fallback" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 23: cli.py `serve`

**Files:**
- Create: `box/src/wheres_allie/cli.py`
- Test: `box/tests/test_cli.py`

**Step 1: Write the failing test.**
```python
from typer.testing import CliRunner

from wheres_allie.cli import app


def test_help_lists_serve():
    res = CliRunner().invoke(app, ["--help"])
    assert res.exit_code == 0
    assert "serve" in res.output
```

**Step 2: Run the test and verify it fails.** `uv run pytest -q tests/test_cli.py`
Expected: FAIL `ModuleNotFoundError: No module named 'wheres_allie.cli'`

**Step 3: Implement** `box/src/wheres_allie/cli.py`. The `@app.callback()` keeps `serve` a real subcommand, so later plans can add `eval`, `export`, `replay` and `patch-bootloader`.
```python
import typer
import uvicorn

from wheres_allie.api.app import create_app
from wheres_allie.config import Settings

app = typer.Typer(no_args_is_help=True, help="wheres_allie home box")


@app.callback()
def main() -> None:
    """wheres_allie home box."""


@app.command()
def serve() -> None:
    """Run the API + GUI + MQTT ingest + retention (config from WA_* env vars)."""
    uvicorn.run(create_app(), host="0.0.0.0", port=Settings().http_port)
```

**Step 4: Run the test and verify it passes.** `uv run pytest -q tests/test_cli.py && uv run wheres-allie --help`
Expected: `1 passed`, and the help output lists `serve`. Optional local run:
```bash
WA_DATA_DIR=.data WA_MQTT_PASS=x WA_MQTT_HOST=localhost uv run wheres-allie serve
```
With that running, `curl localhost:8080/api/health` returns `{"ok":true,…}`. The log shows `mqtt: … retrying` because there is no local broker, which is expected. Stop it with Ctrl-C.

**Step 5: Commit.**
```bash
git add box/src/wheres_allie/cli.py box/tests/test_cli.py
git commit -m "feat: wheres-allie serve CLI" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 24: web/ scaffold (tokens, left rail, empty pages)

**Files:**
- Create: `box/web/package.json`, `box/web/tsconfig.json`, `box/web/vite.config.ts`, `box/web/index.html`, `box/web/src/main.tsx`, `box/web/src/App.tsx`, `box/web/src/theme/tokens.css`, `box/web/src/theme/app.css`, `box/web/src/pages/{Setup,Editor,Nodes,Live,History,Calibrate,Data}.tsx`
- Test: `box/web/src/App.test.tsx`

Run all commands from `box/web/`.

**Step 1: Write the failing test.** Create the tooling files first.

`package.json`:
```json
{
  "name": "wheres-allie-web",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc && vite build",
    "test": "vitest run"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "react-router-dom": "^6.30.6"
  },
  "devDependencies": {
    "@testing-library/dom": "^10.4.2",
    "@testing-library/react": "^16.3.3",
    "@types/react": "^18.3.31",
    "@types/react-dom": "^18.3.7",
    "@vitejs/plugin-react": "^6.1.1",
    "jsdom": "^30.1.1",
    "typescript": "^7.0.2",
    "vite": "^8.3.1",
    "vitest": "^5.0.2"
  }
}
```
`tsconfig.json`:
```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "bundler",
    "jsx": "react-jsx",
    "strict": true,
    "noEmit": true,
    "skipLibCheck": true,
    "types": ["vite/client"]
  },
  "include": ["src"]
}
```
`vite.config.ts`:
```ts
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": { target: "http://localhost:8080", ws: true },
      "/mcp": { target: "http://localhost:8080" },
    },
  },
  test: { environment: "jsdom", exclude: ["e2e/**", "node_modules/**"] },
});
```
`src/App.test.tsx`:
```tsx
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, test } from "vitest";
import App from "./App";

test("left rail links every page and / redirects to Live", () => {
  render(
    <MemoryRouter initialEntries={["/"]}>
      <App />
    </MemoryRouter>,
  );
  const nav = screen.getByRole("navigation", { name: "Pages" });
  const labels = Array.from(nav.querySelectorAll("a")).map((a) => a.getAttribute("title"));
  expect(labels).toEqual(["Live", "History", "Plan", "Nodes", "Calibrate", "Data", "Setup"]);
  expect(screen.getByRole("heading", { name: "Live" })).toBeTruthy();
});
```

**Step 2: Run the test and verify it fails.** `pnpm install && pnpm test`
Expected: FAIL `Failed to resolve import "./App"`

**Step 3: Implement.**

`index.html`:
```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Where's Allie</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```
`src/theme/tokens.css` (conventions §14):
```css
:root {
  --bg: #f6f7f9;
  --panel: #ffffff;
  --line: #d9dde3;
  --text: #1b1f24;
  --muted: #6b7480;
  --accent: #006fff;
  --accent-2: #19b36b;
  --warn: #f5a524;
  --danger: #e5484d;
  --wall: #2b313a;
  --room-fill: rgba(0, 111, 255, 0.04);
  --radius: 8px;
  --font: "Inter", system-ui, sans-serif;
}

[data-theme="dark"] {
  --bg: #111418;
  --panel: #1a1e24;
  --line: #2c323b;
  --text: #e6e9ee;
  --muted: #8b94a1;
  --wall: #c9d1dc;
  --room-fill: rgba(0, 111, 255, 0.08);
}
```
`src/theme/app.css`:
```css
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text); font: 14px/1.4 var(--font); }
.shell { display: flex; min-height: 100vh; }
.rail {
  width: 64px; flex: none; display: flex; flex-direction: column; gap: 4px; padding: 8px 6px;
  background: var(--panel); border-right: 1px solid var(--line);
}
.rail a {
  display: flex; flex-direction: column; align-items: center; gap: 2px; padding: 8px 0;
  border-radius: var(--radius); color: var(--muted); text-decoration: none; font-size: 11px;
}
.rail a .icon { font-size: 16px; font-weight: 600; }
.rail a:hover { background: var(--bg); }
.rail a.active { color: var(--accent); background: var(--room-fill); }
.page { flex: 1; padding: 24px; min-width: 0; }
.panel { background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius); }
table { width: 100%; border-collapse: collapse; }
th, td { text-align: left; padding: 8px 12px; border-bottom: 1px solid var(--line); }
th { color: var(--muted); font-weight: 500; }
.dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; }
.dot.ok { background: var(--accent-2); }
.dot.down { background: var(--danger); }
```
Empty pages. This loop creates `Setup`, `Editor`, `Nodes`, `Live`, `History`, `Calibrate` and `Data`, each returning `<h1>Name</h1>`:
```bash
for p in Setup Editor Nodes Live History Calibrate Data; do
  printf 'export default function %s() {\n  return <h1>%s</h1>;\n}\n' $p $p > src/pages/$p.tsx
done
```
`src/App.tsx`:
```tsx
import { Navigate, NavLink, Route, Routes } from "react-router-dom";
import Calibrate from "./pages/Calibrate";
import Data from "./pages/Data";
import Editor from "./pages/Editor";
import History from "./pages/History";
import Live from "./pages/Live";
import Nodes from "./pages/Nodes";
import Setup from "./pages/Setup";

export const PAGES = [
  { path: "live", label: "Live", icon: "◉", element: <Live /> },
  { path: "history", label: "History", icon: "↺", element: <History /> },
  { path: "editor", label: "Plan", icon: "▦", element: <Editor /> },
  { path: "nodes", label: "Nodes", icon: "⌖", element: <Nodes /> },
  { path: "calibrate", label: "Calibrate", icon: "◎", element: <Calibrate /> },
  { path: "data", label: "Data", icon: "⇩", element: <Data /> },
  { path: "setup", label: "Setup", icon: "⚙", element: <Setup /> },
];

export default function App() {
  return (
    <div className="shell">
      <nav className="rail" aria-label="Pages">
        {PAGES.map((p) => (
          <NavLink key={p.path} to={`/${p.path}`} title={p.label}>
            <span className="icon" aria-hidden="true">{p.icon}</span>
            {p.label}
          </NavLink>
        ))}
      </nav>
      <main className="page">
        <Routes>
          {PAGES.map((p) => (
            <Route key={p.path} path={`/${p.path}`} element={p.element} />
          ))}
          <Route path="*" element={<Navigate to="/live" replace />} />
        </Routes>
      </main>
    </div>
  );
}
```
`src/main.tsx`:
```tsx
import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import "./theme/tokens.css";
import "./theme/app.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>,
);
```

**Step 4: Run the test and verify it passes.** `pnpm test && pnpm build`
Expected: `Tests 1 passed`, and `dist/index.html` plus `dist/assets/index-*.js` are built. (Both were verified with these exact versions on 2026-09-28.)

**Step 5: Commit.**
```bash
git add box/web/package.json box/web/pnpm-lock.yaml box/web/tsconfig.json box/web/vite.config.ts box/web/index.html box/web/src
git commit -m "feat: web GUI skeleton with tokens, left rail and empty pages" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 25: web lib (api, ws, types) + live Nodes page

**Files:**
- Create: `box/web/src/lib/api.ts`, `box/web/src/lib/ws.ts`, `box/web/src/lib/types.ts`
- Modify: `box/web/src/pages/Nodes.tsx`
- Test: `box/web/src/lib/ws.test.ts`, `box/web/src/pages/Nodes.test.tsx`

**Step 1: Write the failing tests.** Create `src/lib/ws.test.ts`:
```ts
import { afterEach, expect, test, vi } from "vitest";

class FakeWs {
  static last: FakeWs | null = null;
  onopen: (() => void) | null = null;
  onmessage: ((m: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  closed = false;
  url: string;
  constructor(url: string) {
    this.url = url;
    FakeWs.last = this;
  }
  close() {
    this.closed = true;
    this.onclose?.();
  }
  emit(topic: string, data: object) {
    this.onmessage?.({ data: JSON.stringify({ topic, data }) });
  }
}

afterEach(() => vi.unstubAllGlobals());

test("one shared socket, prefix routing, closes after last unsubscribe", async () => {
  vi.stubGlobal("WebSocket", FakeWs);
  const { subscribe } = await import("./ws");
  const nodes: string[] = [];
  const all: string[] = [];
  const offNodes = subscribe("node.", (topic, data) => nodes.push(`${topic}:${data.id}`));
  const offAll = subscribe("", (topic) => all.push(topic));
  const sock = FakeWs.last!;
  expect(sock.url).toMatch(/\/api\/ws$/);
  sock.emit("node.health", { id: "office" });
  sock.emit("reading", { rssi: -70 });
  expect(nodes).toEqual(["node.health:office"]);
  expect(all).toEqual(["node.health", "reading"]);
  offNodes();
  expect(sock.closed).toBe(false);
  offAll();
  expect(sock.closed).toBe(true);
});
```
Create `src/pages/Nodes.test.tsx`:
```tsx
import { render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import Nodes from "./Nodes";

vi.mock("../lib/ws", () => ({ subscribe: () => () => {} }));

afterEach(() => vi.unstubAllGlobals());

test("lists nodes from /api/nodes with health", async () => {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(
      JSON.stringify([
        { id: "loft", name: null, online: false, last_seen: null, ip: null, wifi_rssi: null,
          uptime_s: null, version: null, calib_json: null, placed: false, nearby_devices: 0 },
        { id: "office", name: null, online: true, last_seen: Date.now() / 1000, ip: "192.168.5.232",
          wifi_rssi: -60, uptime_s: 5, version: "v4.0.6", calib_json: null, placed: false,
          nearby_devices: 3 },
      ]),
    ),
  );
  vi.stubGlobal("fetch", fetchMock);
  render(<Nodes />);
  expect(await screen.findByText("192.168.5.232")).toBeTruthy();
  expect(screen.getByText("loft")).toBeTruthy();
  expect(screen.getByText("never")).toBeTruthy();
  expect(fetchMock).toHaveBeenCalledWith("/api/nodes", expect.anything());
});

test("apiGet throws ApiError with status", async () => {
  const { apiGet, ApiError } = await import("../lib/api");
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ detail: "pet not found" }), { status: 404 })));
  const err = await apiGet("/pets/9").then(() => null, (e: InstanceType<typeof ApiError>) => e);
  expect(err).toBeInstanceOf(ApiError);
  expect(err?.status).toBe(404);
  expect(err?.message).toContain("pet not found");
});
```

**Step 2: Run the tests and verify they fail.** `pnpm test`
Expected: FAIL `Failed to resolve import "./ws"` and `"../lib/api"`, and `Unable to find an element with the text: 192.168.5.232`.

**Step 3: Implement.**

`src/lib/types.ts`:
```ts
// Hand-written mirrors of the box API (conventions §10). Keep in sync with the pydantic models.
export type Health = { ok: boolean; version: string; relay: "connected" | "disabled" | "offline" };

export type SiteSettings = { tz: string; units: "ft" | "m"; home_name: string };

export type Node = {
  id: string;
  name: string | null;
  online: boolean;
  last_seen: number | null;
  ip: string | null;
  wifi_rssi: number | null;
  uptime_s: number | null;
  version: string | null;
  calib_json: string | null;
  placed: boolean;
  nearby_devices: number;
};

export type Tag = { id: number; pet_id: number; ibeacon_id: string; motion_ibeacon_id: string | null };
export type Pet = { id: number; name: string; species: string; tags: Tag[] };
export type TagCandidate = { ibeacon_id: string; node_id: string; rssi: number; last_seen: number };

export type BusEvent = { topic: string; data: Record<string, unknown> };
```
`src/lib/api.ts`:
```ts
export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(method: string, path: string, body?: BodyInit, json = true): Promise<T> {
  const url = path.startsWith("/api/") ? path : `/api${path}`;
  const headers = json && body !== undefined ? { "Content-Type": "application/json" } : undefined;
  const res = await fetch(url, { method, body, headers });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      if (j?.detail) detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {
      // non-JSON error body: keep statusText
    }
    throw new ApiError(res.status, `${method} ${url} failed (${res.status}): ${detail}`);
  }
  return (await res.json()) as T;
}

export const apiGet = <T>(path: string) => request<T>("GET", path);

export const apiPost = <T>(path: string, body?: unknown) =>
  request<T>("POST", path, body === undefined ? undefined : JSON.stringify(body));

export const apiPut = <T>(path: string, body: unknown) =>
  request<T>("PUT", path, JSON.stringify(body));

export function apiUpload<T>(path: string, file: File): Promise<T> {
  const form = new FormData();
  form.append("file", file);
  return request<T>("POST", path, form, false);
}
```
`src/lib/ws.ts`:
```ts
import type { BusEvent } from "./types";

// data is `any`: its shape depends on the topic (see Interface additions #5)
export type Handler = (topic: string, data: any) => void;
type Sub = { prefix: string; handler: Handler };

const subs = new Set<Sub>();
let ws: WebSocket | null = null;
let timer: ReturnType<typeof setTimeout> | undefined;
let delay = 1000;

function open() {
  timer = undefined;
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const sock = new WebSocket(`${proto}://${location.host}/api/ws`);
  ws = sock;
  sock.onopen = () => (delay = 1000);
  sock.onmessage = (m) => {
    const e = JSON.parse(m.data) as BusEvent;
    for (const s of subs) if (e.topic.startsWith(s.prefix)) s.handler(e.topic, e.data);
  };
  sock.onclose = () => {
    if (ws === sock) ws = null;
    if (subs.size === 0 || timer !== undefined) return;
    timer = setTimeout(open, delay);
    delay = Math.min(delay * 2, 30000);
  };
}

/** Receive box bus events whose topic starts with topicPrefix ("" = all). Returns unsubscribe. */
export function subscribe(topicPrefix: string, handler: Handler): () => void {
  const sub = { prefix: topicPrefix, handler };
  subs.add(sub);
  if (!ws && timer === undefined) open();
  return () => {
    subs.delete(sub);
    if (subs.size > 0) return;
    clearTimeout(timer);
    timer = undefined;
    ws?.close();
    ws = null;
  };
}
```
Replace `src/pages/Nodes.tsx` with:
```tsx
import { useEffect, useState } from "react";
import { apiGet } from "../lib/api";
import type { Node } from "../lib/types";
import { subscribe } from "../lib/ws";

function ago(ts: number | null): string {
  if (ts == null) return "never";
  const s = Math.max(0, Math.round(Date.now() / 1000 - ts));
  return s < 90 ? `${s}s ago` : `${Math.round(s / 60)}m ago`;
}

export default function Nodes() {
  const [nodes, setNodes] = useState<Node[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const load = () => apiGet<Node[]>("/api/nodes").then(setNodes, (e: Error) => setError(e.message));
    load();
    return subscribe("node.health", load);
  }, []);

  if (error) return <p role="alert">Could not load nodes: {error}</p>;
  if (!nodes) return <p>Loading…</p>;
  return (
    <>
      <h1>Nodes</h1>
      {nodes.length === 0 ? (
        <p>No nodes have reported yet. Point your ESPresense nodes at this box's MQTT broker.</p>
      ) : (
        <table className="panel">
          <thead>
            <tr><th>Node</th><th>IP</th><th>Wi-Fi</th><th>Last seen</th><th>Nearby devices</th><th>Version</th></tr>
          </thead>
          <tbody>
            {nodes.map((n) => (
              <tr key={n.id}>
                <td><span className={`dot ${n.online ? "ok" : "down"}`} />{n.name ?? n.id}</td>
                <td>{n.ip ?? "–"}</td>
                <td>{n.wifi_rssi != null ? `${n.wifi_rssi} dBm` : "–"}</td>
                <td>{ago(n.last_seen)}</td>
                <td>{n.nearby_devices}</td>
                <td>{n.version ?? "–"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
```

**Step 4: Run the tests and verify they pass.** `pnpm test && pnpm build`
Expected: `Test Files 3 passed`, `Tests 4 passed`, and the build succeeds.

**Step 5: Commit.**
```bash
git add box/web/src
git commit -m "feat: web api/ws/types libs and live Nodes health page" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 26: Dockerfile (multi-stage, multi-arch)

**Files:**
- Create: `box/Dockerfile`, `box/.dockerignore`

Run from the repo root. First make sure the Docker daemon is running: `docker info >/dev/null 2>&1 || sudo service docker start`.

**Step 1: Write the failing check.** `docker build -t wheres-allie:dev box/`
Expected: FAIL `failed to read dockerfile: open Dockerfile: no such file or directory`

**Step 2: Implement.**

`box/Dockerfile`:
```dockerfile
# syntax=docker/dockerfile:1
# Web build runs on the build platform only: dist/ is architecture independent.
FROM --platform=$BUILDPLATFORM node:24-slim AS web
RUN npm install -g pnpm@10
WORKDIR /web
COPY web/package.json web/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY web/ ./
RUN pnpm build

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev
COPY --from=web /web/dist ./web/dist
ENV PATH="/app/.venv/bin:$PATH" WA_WEB_DIST=/app/web/dist WA_DATA_DIR=/data
VOLUME /data
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/api/health')"
CMD ["wheres-allie", "serve"]
```
`box/.dockerignore`:
```
.venv
.data
.pytest_cache
.ruff_cache
**/__pycache__
web/node_modules
web/dist
tests
tools
```

**Step 3: Build and run it.**
```bash
docker build -t wheres-allie:dev box/
docker run --rm -d --name wa-test -p 18080:8080 -e WA_MQTT_PASS=x wheres-allie:dev
sleep 5
curl -s localhost:18080/api/health
curl -s localhost:18080/nodes | grep -o "<title>.*</title>"
docker rm -f wa-test
```
Expected:
- the build succeeds;
- health returns `{"ok":true,"version":"0.1.0","relay":"disabled"}`;
- `/nodes` shows `<title>Where's Allie</title>`, which proves the SPA fallback works inside the image.

The container log shows `mqtt: … retrying`; that is expected, because there is no broker.

**Step 4: Check the multi-arch build.** Run the binfmt install once per machine; the arm64 build is slow under QEMU.
```bash
docker run --privileged --rm tonistiigi/binfmt --install arm64
docker buildx build --platform linux/arm64 -t wheres-allie:arm64-check box/
```
Expected: the build finishes. The numpy and shapely wheels exist for aarch64, so nothing compiles. If it fails, record it in the friction log and continue; arm64 is only needed for Pi users (plan 07 publishes images).

**Step 5: Commit.**
```bash
git add box/Dockerfile box/.dockerignore
git commit -m "feat: multi-stage multi-arch box image serving API + GUI" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 27: deploy/compose.yml + mosquitto

**Files:**
- Create: `deploy/compose.yml`, `deploy/mosquitto/mosquitto.conf`, `deploy/mosquitto/entrypoint.sh`, `deploy/.env.example`

**Step 1: Write the failing check.** From the repo root: `docker compose -f deploy/compose.yml config`
Expected: FAIL `open …/deploy/compose.yml: no such file or directory`

**Step 2: Implement.**

`deploy/mosquitto/mosquitto.conf`:
```
listener 1883 0.0.0.0
allow_anonymous false
password_file /mosquitto/data/passwd
persistence false
log_dest stdout
```
`deploy/mosquitto/entrypoint.sh`:
```sh
#!/bin/sh
# Generates the broker password file from WA_MQTT_USER / WA_MQTT_PASS on every start.
set -eu
: "${WA_MQTT_PASS:?WA_MQTT_PASS is required}"
mosquitto_passwd -c -b /mosquitto/data/passwd "${WA_MQTT_USER:-wheres_allie}" "$WA_MQTT_PASS"
chown mosquitto:mosquitto /mosquitto/data/passwd
chmod 0600 /mosquitto/data/passwd
exec mosquitto -c /mosquitto/config/mosquitto.conf
```
`deploy/.env.example`:
```
# Copy to deploy/.env (git-ignored) and fill in. Never commit the real file.
WA_MQTT_USER=wheres_allie
WA_MQTT_PASS=change-me
WA_TZ=America/New_York
# LAN IP of this box, told to nodes as their MQTT host
WA_PUBLIC_HOST=
# Empty = relay disabled
WA_RELAY_URL=
```
`deploy/compose.yml`:
```yaml
name: wheres-allie

services:
  mosquitto:
    image: eclipse-mosquitto:2
    restart: unless-stopped
    entrypoint: ["/bin/sh", "/mosquitto/entrypoint.sh"]
    environment:
      WA_MQTT_USER: ${WA_MQTT_USER:-wheres_allie}
      WA_MQTT_PASS: ${WA_MQTT_PASS:?set WA_MQTT_PASS in deploy/.env}
    volumes:
      - ./mosquitto/mosquitto.conf:/mosquitto/config/mosquitto.conf:ro
      - ./mosquitto/entrypoint.sh:/mosquitto/entrypoint.sh:ro
    ports:
      - "1883:1883"

  box:
    build: ../box
    image: wheres-allie:dev
    restart: unless-stopped
    depends_on: [mosquitto]
    environment:
      WA_MQTT_HOST: mosquitto
      WA_MQTT_USER: ${WA_MQTT_USER:-wheres_allie}
      WA_MQTT_PASS: ${WA_MQTT_PASS:?set WA_MQTT_PASS in deploy/.env}
      WA_TZ: ${WA_TZ:-America/New_York}
      WA_PUBLIC_HOST: ${WA_PUBLIC_HOST:-}
      WA_RELAY_URL: ${WA_RELAY_URL:-}
    volumes:
      - wa-data:/data
    ports:
      - "80:8080"

volumes:
  wa-data:
```

**Step 3: Verify the config renders.** `WA_MQTT_PASS=x docker compose -f deploy/compose.yml config --quiet && echo OK`
Expected: `OK`. Without the variable set, compose must fail with `set WA_MQTT_PASS in deploy/.env`.

**Step 4: Confirm `.env` is ignored.** `git check-ignore deploy/.env`
Expected: `deploy/.env` (the existing `.env` rule covers it).

**Step 5: Commit.**
```bash
git add deploy/compose.yml deploy/mosquitto/mosquitto.conf deploy/mosquitto/entrypoint.sh deploy/.env.example
git commit -m "feat: compose stack with authenticated mosquitto and the box" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 28: `docker compose up` smoke test + LAN reachability

**Files:** none; this task writes only local `deploy/.env`, which is git-ignored.

The box host is the WSL2 dev machine at `192.168.5.254` (mirrored networking). Run from `deploy/`.

1. Create the env file with a fresh password:
   ```bash
   cp .env.example .env
   sed -i "s/^WA_MQTT_PASS=.*/WA_MQTT_PASS=$(python3 -c 'import secrets; print(secrets.token_urlsafe(18))')/" .env
   sed -i 's/^WA_PUBLIC_HOST=.*/WA_PUBLIC_HOST=192.168.5.254/' .env
   ```
   Copy the password into your password manager as "wheres_allie MQTT".
2. Start the stack: `docker compose up -d --build && sleep 20 && docker compose ps`
   Expected: `mosquitto` is running and `box` is running (healthy). If port 80 or 1883 is already taken, find the owner with `sudo ss -ltnp | grep -E ':(80|1883) '` and stop it (the old WSL mosquitto must stay disabled).
3. Check the API and GUI:
   ```bash
   curl -s localhost/api/health                      # {"ok":true,"version":"0.1.0","relay":"disabled"}
   curl -s localhost/ | grep -o "<title>.*</title>"  # <title>Where's Allie</title>
   docker compose logs box | grep "mqtt connected"   # mqtt connected to mosquitto:1883
   ```
4. Check that the broker rejects anonymous clients:
   ```bash
   docker compose exec mosquitto mosquitto_sub -t '#' -C 1 -W 3; echo "exit=$?"
   ```
   Expected: `Connection error: Connection Refused: not authorised.` and a non-zero exit.
5. Check end-to-end ingest with fake ESPresense messages:
   ```bash
   set -a; . ./.env; set +a
   docker compose exec mosquitto mosquitto_pub -u "$WA_MQTT_USER" -P "$WA_MQTT_PASS" -t espresense/rooms/smoke/status -m online
   docker compose exec mosquitto mosquitto_pub -u "$WA_MQTT_USER" -P "$WA_MQTT_PASS" -t 'espresense/devices/iBeacon:smoke-1-2/smoke' -m '{"rssi":-60}'
   curl -s localhost/api/nodes            # [{"id":"smoke",…,"online":true,…,"nearby_devices":1}]
   curl -s localhost/api/tags/candidates  # [{"ibeacon_id":"iBeacon:smoke-1-2","node_id":"smoke","rssi":-60.0,…}]
   ```
   Open `http://localhost/nodes` in the Windows browser: `smoke` shows with a green dot. Then clean up:
   ```bash
   docker compose exec box python -c "import sqlite3; sqlite3.connect('/data/wheres_allie.db').execute(\"DELETE FROM nodes WHERE id='smoke'\").connection.commit()"
   ```
6. Check LAN reachability: this decides where the box runs. From another LAN machine (for example the Proxmox host `pve5`), run `nc -zv 192.168.5.254 1883 && nc -zv 192.168.5.254 80`. Expected: both `succeeded`/`open`.
   - If this fails, first allow inbound traffic through the WSL Hyper-V firewall by running this in an **admin PowerShell** on Windows:
     ```powershell
     New-NetFirewallHyperVRule -Name WA-Box -DisplayName "wheres_allie box" -Direction Inbound -VMCreatorId '{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}' -Protocol TCP -LocalPorts 80,1883
     ```
     Then retry.
   - **If it still fails:** run the same compose stack on a small Proxmox LXC/VM instead, use its IP everywhere `192.168.5.254` appears below, and log the WSL/Docker networking friction.
7. Log what you did in the friction log, then commit it:
   ```bash
   git add docs/friction-log.md
   git commit -m "docs: friction notes from first compose bring-up" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
   ```
   (Skip the commit if you have nothing to note.)

### Task 29: Register Allie; move the 5 nodes to the box broker

**Files:** none; the procedure is in `docs/runbooks/move-nodes-to-box.md`.

Node map: office `192.168.5.232`, moms_room `.186`, kitchen `.225`, master_bedroom `.172`, loft `.222`. Loft may have a new IP after Task 3; use the one recorded there.

1. **Register Allie first**, so her readings are stored from the first minute. Run from anywhere:
   ```bash
   curl -s -X POST localhost/api/pets -H 'content-type: application/json' -d '{"name":"Allie","species":"dog"}'
   # if spike B passed:
   curl -s -X POST localhost/api/pets/1/tags -H 'content-type: application/json' \
     -d '{"ibeacon_id":"iBeacon:426c7565-4368-6172-6d42-6561636f6e73-3838-4949","motion_ibeacon_id":"iBeacon:426c7565-4368-6172-6d42-6561636f6e73-3838-4950"}'
   # if spike B failed, instead:
   curl -s -X POST localhost/api/pets/1/tags -H 'content-type: application/json' \
     -d '{"ibeacon_id":"iBeacon:426c7565-4368-6172-6d42-6561636f6e73-3838-4949"}'
   ```
   Expected: `{"id":1,"name":"Allie",…,"tags":[{…"ibeacon_id":"iBeacon:426c…-3838-4949"…}]}`.
2. **Dry-run the canary (office)** from `box/`:
   ```bash
   set -a; . ../deploy/.env; set +a
   uv run python tools/repoint_nodes.py --host 192.168.5.254 --user "$WA_MQTT_USER" --pass-env WA_MQTT_PASS \
     --backup-dir ~/wheres-allie-node-backup office=192.168.5.232 --dry-run
   ```
   Expected: only these lines, followed by `office: dry run, nothing saved`:
   ```
   office: mqtt_host: '192.168.5.132' -> '192.168.5.254'
   office: mqtt_user: '***###***' -> '***###***'
   office: mqtt_pass: '***###***' -> '***###***'
   ```
   There may also be an `auto_update: True -> False` line. `~/wheres-allie-node-backup/office.json` must contain `"wifi-ssid"`. **Stop** if any other key is listed, or if it reports `expected 'office'`, which means the wrong IP.
3. **Apply it to the canary.** Run the same command without `--dry-run`, then watch:
   ```bash
   docker compose -f ../deploy/compose.yml exec mosquitto mosquitto_sub -u "$WA_MQTT_USER" -P "$WA_MQTT_PASS" -v -t 'espresense/rooms/office/#' -W 90
   ```
   **Pass** means that within 60 s you see `espresense/rooms/office/status online` and a `…/telemetry` message, and `curl -s localhost/api/nodes` lists `office` with `"online":true`.
   **Rollback** if nothing arrives within 2 minutes:
   ```bash
   read -rsp 'HA MQTT password: ' HA_MQTT_PASS; echo; export HA_MQTT_PASS
   uv run python tools/repoint_nodes.py --host 192.168.5.132 --user mqtt --pass-env HA_MQTT_PASS office=192.168.5.232
   ```
   If the node is unreachable over HTTP, use its `espresense…` captive-portal AP at http://192.168.4.1 (see the runbook). Fix the cause (usually LAN reachability, Task 28 step 6) before continuing.
4. **Move the remaining 4 nodes.** Dry-run them first, check the same rule as step 2, then run for real:
   ```bash
   uv run python tools/repoint_nodes.py --host 192.168.5.254 --user "$WA_MQTT_USER" --pass-env WA_MQTT_PASS \
     --backup-dir ~/wheres-allie-node-backup moms_room=192.168.5.186 kitchen=192.168.5.225 \
     master_bedroom=192.168.5.172 loft=192.168.5.222 --dry-run
   ```
5. **Verify.** Within 2 minutes, `http://localhost/nodes` shows all 5 nodes with green dots, a Wi-Fi RSSI and version `v4.0.6`. The HA companion now shows them unavailable, which is expected. Log this in the friction log.

### Task 30: Verify continuous collection; stop the raw logger; import the raw log

**Files:** none committed; the bundle is personal data and is git-ignored.

1. Take the first sample now and a second one 10 minutes later. Run from the repo root:
   ```bash
   docker compose -f deploy/compose.yml exec box python -c "import sqlite3,time; c=sqlite3.connect('/data/wheres_allie.db'); print(c.execute('SELECT node_id, count(*), round(? - max(ts)) FROM readings GROUP BY node_id', (time.time(),)).fetchall()); print('gaps', c.execute('SELECT count(*) FROM gaps').fetchone())"
   ```
   **Pass** requires all of the following:
   - (a) the total count grows between the two samples, by about 150 or more per 10 min when Allie is near any node;
   - (b) at least one node has an age under 30 s;
   - (c) `gaps (0,)`.

   If Allie is away from every node, walk the tag past a node and re-sample.
2. **Only after that passes**, stop the ad-hoc logger:
   ```bash
   pkill -f allie-raw; sleep 1; pgrep -fa allie-raw || echo "raw logger stopped"
   ```
   Expected: `raw logger stopped`.
3. Preserve the raw data as a bundle. Run from `box/`:
   ```bash
   uv run python tools/import_raw_log.py ../data/allie-raw.log ../data/allie-2026-09-28.bundle
   uv run python -c "from wheres_allie.replay.bundle import read_bundle; b = read_bundle('../data/allie-2026-09-28.bundle'); print(len(b.readings), sorted({r[2] for r in b.readings}))"
   ```
   Expected: `N readings -> ../data/allie-2026-09-28.bundle` with N ≥ 852, and the node list includes `office`, `kitchen`, `master_bedroom`, `loft` and `moms_room` (whichever heard Allie). `git status --short data/` shows nothing, because the bundle is git-ignored. Copy the bundle to backup storage outside the repo.
4. Leave the stack running. From now on the box is the data collector: do **not** `docker compose down -v`, which would delete the `wa-data` volume.

### Task 31: Friction log + spike results curation

**Files:**
- Modify: `docs/friction-log.md`
- Modify: `docs/spikes/phase0.md`

1. Make sure `docs/spikes/phase0.md` has a **Decision:** line filled in for A, B and C, and that each "tell plan N owner" action from Tasks 1–3 has been sent to the team lead. Add a line per action: `Sent to: <who>, <date>`.
2. Add a dated `## 2026-MM-DD: Phase 1 box bring-up` section to `docs/friction-log.md`. Include anything surprising from Tasks 26–30: Docker in WSL, the Hyper-V firewall, mosquitto password-file permissions, ESPresense node repointing, and whether the HA companion noticed.
3. Commit:
   ```bash
   git add docs/friction-log.md docs/spikes/phase0.md
   git commit -m "docs: phase 0-1 friction log and spike decisions" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
   ```

### Task 32: Phase exit + push

1. Run the full checks:
   ```bash
   (cd box && uv run pytest -q && uv run ruff check .)
   (cd box/web && pnpm test && pnpm build)
   ```
   Web tool versions are vite 8, vitest 5 and TS 7; see Interface additions #13 for the compatibility check against plans 02, 04 and 07. If a later plan's vitest run fails on a vitest or vite API difference, pin that plan's package with `pnpm add -D vitest@<major>` rather than editing its tests, and note it in the friction log.
   Expected: `43 passed`, `All checks passed!`, `Test Files 3 passed`, and a successful build.
2. Update the status table at the top of this file: every task goes to `done | yes | no`, or `skipped` with a reason (spikes that failed are still `done`, and their decision is recorded).
3. Commit and push:
   ```bash
   git add docs/plans/2026-09-28-wheres-allie-plan-01-foundation.md
   git commit -m "docs: mark plan 01 foundation complete" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
   git push origin main
   ```
4. Set the `Pushed` column to `yes`, then commit and push again with `git commit -am "docs: plan 01 pushed" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" && git push origin main`.

## Phase exit criteria

- [ ] `docs/spikes/phase0.md` has results and a decision for spikes A, B and C, and the affected plan owners have been told.
- [ ] `cd box && uv run pytest -q` → 43 passed; `uv run ruff check .` is clean.
- [ ] `cd box/web && pnpm test && pnpm build` → 3 test files pass; `dist/` builds.
- [ ] `docker compose -f deploy/compose.yml ps` shows `mosquitto` and a healthy `box`. `http://<box-ip>/` serves the GUI, and `/nodes` lists all 5 nodes online with v4.0.6.
- [ ] Anonymous MQTT is refused, and the LAN can reach ports 1883 and 80.
- [ ] Allie is registered (with a motion id if spike B passed), and `readings` grows continuously with `gaps` at 0 over a 10 min check.
- [ ] The ad-hoc `allie-raw` logger is stopped **after** ingest was verified, and `data/allie-2026-09-28.bundle` exists (git-ignored) and round-trips through `read_bundle`.
- [ ] No secrets in git: `git grep -nE 'WA_MQTT_PASS=[^c]|-P .[A-Za-z0-9]{12}'` returns nothing (only `change-me` in `.env.example`).
- [ ] Everything is pushed to `origin/main`.
