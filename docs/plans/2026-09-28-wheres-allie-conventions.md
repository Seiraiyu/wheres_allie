# wheres_allie: shared conventions (the contract for all plan files)

Every implementation plan follows this document. If a plan needs something this document doesn't define, it adds the new piece in an **"Interface additions"** section at the top of that plan. It never changes or contradicts what's here.

Design: `docs/plans/2026-09-28-wheres-allie-design.md` (approved). Repo: `github.com/Seiraiyu/wheres_allie`, default branch `main`.

## 1. Repo layout
```
box/                               # the home box: Python package + web GUI
  pyproject.toml                   # uv project "wheres-allie", Python 3.12, package wheres_allie
  src/wheres_allie/
    __init__.py
    config.py                      # Settings (pydantic-settings, env prefix WA_)
    db.py                          # connect(), migrate() (applies schema.sql), helpers
    schema.sql
    cli.py                         # typer app: serve | eval | export | replay | patch-bootloader
    retention.py
    ingest/{__init__,parse,mqtt}.py
    home/{__init__,model,geometry,graph,store}.py
    estimator/{__init__,window,emission,hmm,visits,runner,eval}.py
    calibration/{__init__,labels,fingerprints}.py
    brain/{__init__,rollups,baseline,anomalies}.py
    mcp/{__init__,server,tools,app_resource}.py
    api/{__init__,app,deps,ws}.py + api/routes/{home,nodes,pets,live,history,calibrate,data,pairing,flasher}.py
    relaylink/{__init__,client}.py
    replay/{__init__,bundle,replayer}.py
    nodes/{__init__,espresense_http}.py   # push settings to ESPresense nodes over HTTP
  tests/                           # pytest; mirrors src layout: tests/test_<module>.py or tests/<pkg>/test_*.py
  tests/fixtures/                  # tiny home.json, readings csv, etc.
  web/                             # Vite + React 18 + TypeScript, pnpm
    package.json, vite.config.ts, index.html
    src/main.tsx, src/App.tsx, src/lib/{api.ts,ws.ts,types.ts,units.ts}
    src/theme/tokens.css
    src/components/plan/…          # shared SVG plan renderer (used by GUI AND MCP App)
    src/pages/{Setup,Editor,Nodes,Live,History,Calibrate,Data}.tsx
    src/mcp-app/                   # separate Vite entry → single self-contained HTML
    public/firmware/               # flasher assets (built by `wheres-allie patch-bootloader`)
  Dockerfile                       # multi-stage: pnpm build web → python runtime; serves web/dist
relay/                             # AWS relay: separate uv project "wheres-allie-relay"
  pyproject.toml
  src/relay/{__init__,app,auth,pairing,boxes,store,config}.py
  tests/
  infra/                           # AWS CDK app in Python (app.py, stack.py), deploy via `npx aws-cdk@2`
  Dockerfile
deploy/
  compose.yml                      # mosquitto + box
  demo.yml                         # judge mode: mosquitto + box (WA_RELAY_URL empty) + replayer
  mosquitto/{mosquitto.conf,entrypoint.sh}
demo-data/                         # *.bundle (committed only when curated, <20 MB)
docs/
```
- Python tooling: `uv`, `pytest`, `pytest-asyncio` (mode=auto), `ruff` (line length 100). Run from `box/`: `uv run pytest -q`.
- Web tooling: `pnpm`, `vitest`, `@playwright/test`. Run from `box/web/`: `pnpm test`, `pnpm build`.
- Commits: conventional (`feat:`, `fix:`, `test:`, `chore:`, `docs:`), one per task. Every commit message ends with the line `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Push to `main` after each phase is green.

## 2. Dependencies (pin major versions)
box: `fastapi>=0.115`, `uvicorn[standard]`, `pydantic>=2`, `pydantic-settings`, `aiomqtt>=2`, `numpy>=2`, `shapely>=2` (polygons), `mcp>=2.2,<3` (official SDK 2.x: MCPServer + Apps extension, Streamable HTTP), `typer`, `httpx`, `websockets>=13`, `python-multipart`, `tzdata`. Dev: `pytest`, `pytest-asyncio`, `ruff`, `respx`.
web: `react`, `react-dom`, `react-router-dom`, `zustand` (state), `esptool-js` (flasher), `@modelcontextprotocol/ext-apps` (MCP App bridge, if available; otherwise plain `window.parent.postMessage`), `vitest`, `@testing-library/react`, `@playwright/test`. No UI kit. Hand-written CSS using `tokens.css`.
relay: `fastapi`, `uvicorn`, `websockets`, `httpx`, `boto3`, `pydantic-settings`, `aws-cdk-lib` (infra only).

## 3. Configuration (env, prefix `WA_`)
| Var | Default | Meaning |
|---|---|---|
| `WA_DATA_DIR` | `/data` | SQLite db, uploads, exports |
| `WA_MQTT_HOST` / `WA_MQTT_PORT` | `mosquitto` / `1883` | broker |
| `WA_MQTT_USER` / `WA_MQTT_PASS` | `wheres_allie` / (required) | broker creds (also given to nodes) |
| `WA_HTTP_PORT` | `8080` | API + GUI + `/mcp` |
| `WA_TZ` | `America/New_York` | fallback; the GUI setting in `settings.tz` wins |
| `WA_RELAY_URL` | `` (empty = relay disabled) | e.g. `wss://relay.wheres-allie.app/box` |
| `WA_LAN_TOKEN` | generated at first boot → `settings` | bearer token for `/mcp` on LAN |
| `WA_PUBLIC_HOST` | autodetect LAN IP | what nodes are told as their MQTT host |

`deploy/compose.yml` maps host port 80 → 8080, and 1883 → 1883. mosquitto uses a password file generated by `entrypoint.sh` from `WA_MQTT_USER`/`WA_MQTT_PASS`, with `allow_anonymous false`.

## 4. Time and units
- Timestamps are `REAL` unix seconds UTC everywhere (db, API, bundles). The local day is computed with `zoneinfo` from `settings.tz`.
- Geometry is in **metres**. Plan coordinates are x right and **y down** (the same as SVG); the origin is arbitrary per home. Heights (`z`, `elevation_m`) are in metres above the basement floor.
- The GUI displays ft or m per `settings.units`. Conversion lives only in `web/src/lib/units.ts`.

## 5. Database (`box/src/wheres_allie/schema.sql`, SQLite WAL)
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
`db.connect(path) -> sqlite3.Connection` sets `journal_mode=WAL`, `foreign_keys=ON`, and `row_factory=sqlite3.Row`. `db.migrate(conn)` runs `schema.sql`, which must stay idempotent. Access is synchronous `sqlite3`; async code calls it through `asyncio.to_thread` when a query can take more than 10 ms.

## 6. Home model (`home/model.py`, pydantic v2; stored as JSON in the `home` table)
```python
class Underlay(BaseModel): image: str; scale_m_per_px: float; offset: tuple[float, float] = (0, 0); rotation_deg: float = 0; opacity: float = 0.4
class Floor(BaseModel): id: str; name: str; elevation_m: float; underlay: Underlay | None = None
class Wall(BaseModel): id: str; floor_id: str; a: tuple[float, float]; b: tuple[float, float]; thickness_m: float = 0.12; invisible: bool = False  # invisible = room divider
class RoomLabel(BaseModel): id: str; floor_id: str; name: str; seed: tuple[float, float]  # a point inside the room; names derived rooms
class Door(BaseModel): id: str; wall_id: str; t: float  # 0..1 along wall a→b; width_m: float = 0.9
class StairsEnd(BaseModel): floor_id: str; x: float; y: float
class Stairs(BaseModel): id: str; name: str = "Stairs"; a: StairsEnd; b: StairsEnd
LandmarkType = Literal["bed","food_bowl","water_bowl","couch","crate","door","custom"]
class Landmark(BaseModel): id: str; floor_id: str; x: float; y: float; type: LandmarkType; name: str; radius_m: float = 0.75
class NodePlacement(BaseModel): id: str; floor_id: str; x: float; y: float; z_m: float; name: str  # id = ESPresense room id
class Home(BaseModel):
    version: int = 0
    floors: list[Floor] = []; walls: list[Wall] = []; room_labels: list[RoomLabel] = []
    doors: list[Door] = []; stairs: list[Stairs] = []; landmarks: list[Landmark] = []; nodes: list[NodePlacement] = []
```
Ids are short random strings (`secrets.token_hex(4)`), except `NodePlacement.id`. `home/store.py`: `load_home(conn) -> Home` (latest version, or empty) and `save_home(conn, home) -> int` (inserts a row and returns the new version).

**Derived geometry** (`home/geometry.py`):
```python
@dataclass(frozen=True) class Room: id: str; floor_id: str; name: str; polygon: list[tuple[float,float]]
def detect_rooms(home: Home) -> list[Room]   # faces of the planar wall graph per floor (incl. invisible walls);
                                             # a face gets id/name from the RoomLabel whose seed is inside it,
                                             # else id f"room-{floor_id}-{n}" and name "Unnamed room"
def room_at(rooms, floor_id, x, y) -> Room | None
```
**Walkable graph** (`home/graph.py`):
```python
@dataclass(frozen=True) class Vertex: id: str; kind: Literal["room","landmark","door","stairs"]; floor_id: str; x: float; y: float; room_id: str | None; name: str
@dataclass class Graph:
    vertices: dict[str, Vertex]; edges: list[tuple[str, str, float]]   # (a, b, length_m), undirected
    def neighbors(self, vid: str) -> list[tuple[str, float]]
def build_graph(home: Home, rooms: list[Room]) -> Graph
```
Vertex ids: `room:<room_id>`, `lm:<landmark_id>`, `door:<door_id>`, `stairs:<stairs_id>:a|b`. Within a room, every pair of vertices is connected by the straight-line distance. A door vertex connects to both rooms it joins. The two ends of a stairs are connected with length = horizontal distance + 3 m. The special state `away` is not a graph vertex: the estimator adds it.

## 7. Estimator interfaces
```python
# estimator/window.py
@dataclass class Window:
    tag_id: int; t_end: float                      # windows are 2.0 s: [t_end-2, t_end)
    rssi: dict[str, list[float]]                   # node_id -> readings in window
    online_nodes: set[str]; moving: bool | None    # None = unknown
# estimator/emission.py
class EmissionModel(Protocol):
    def log_likelihood(self, w: Window, states: list[str]) -> np.ndarray   # len(states), incl. "away"
class PhysicsEmission: ...    # path-loss from node positions; per-floor attenuation (default 10 dB)
class BlendedEmission: ...    # fingerprints (calibration.fingerprints) blended with physics by sample count
# estimator/hmm.py
class HmmFilter:
    def __init__(self, graph: Graph, emission: EmissionModel, max_speed_mps: float = 3.0, dt: float = 2.0)
    def step(self, w: Window) -> Estimate          # forward filter
    def smoothed(self) -> list[Estimate]           # Viterbi over the last 60 s (30 windows)
@dataclass class Estimate: ts: float; vertex_id: str; confidence: float; moving: bool | None
# estimator/visits.py
class VisitTracker:                                # min dwell 30 s → room/landmark visit; shorter → transit
    def update(self, e: Estimate, v: Vertex | None) -> list[VisitEvent]
# estimator/runner.py — asyncio task: every 2 s builds Windows from readings, steps each tag's filter,
#   writes positions + visits, publishes to the in-process event bus (§9)
# estimator/eval.py — eval(bundle_path, truth_csv) -> dict(room_acc, landmark_acc, transit_false_visit_rate, baseline_room_acc)
```

## 8. Ingest (`ingest/`)
- `parse.py`: `parse_device_message(topic: str, payload: bytes) -> DeviceReading | None` returns `DeviceReading(ts, ibeacon_id, node_id, rssi, distance, rssi_var)`. The topic is `espresense/devices/<ibeacon_id>/<node_id>`. `parse_room_status` / `parse_telemetry` cover `espresense/rooms/<node>/status|telemetry`.
- `mqtt.py`: `async run_ingest(settings, conn, bus)` subscribes to `espresense/devices/+/+` and `espresense/rooms/+/+`. It maps `ibeacon_id` to a tag through the `tags` table (both `ibeacon_id` and `motion_ibeacon_id`). A message on a motion id writes `motion(ts, tag, 1)`, and a message on the normal id after motion inserts `motion(ts, tag, 0)`. Readings from both ids go to `readings`. Unknown ids are counted per node in memory (`nearby_devices`) and are never stored. It reconnects with backoff, and a disconnect longer than 10 s writes a `gaps` row.

## 9. In-process event bus
`wheres_allie/bus.py`: `class Bus` with `publish(topic: str, data: dict)` and `subscribe(topic_prefix) -> AsyncIterator[tuple[str, dict]]`. Topics: `node.health`, `reading`, `position`, `visit`, `label`, `home.saved`. The WebSocket (§10) forwards them to the GUI.

## 10. HTTP API (FastAPI; all under `/api`; JSON; the GUI is served at `/`; MCP at `/mcp`)
| Method + path | Body / query | Returns |
|---|---|---|
| GET `/api/health` | – | `{ok, version, relay: "connected"\|"disabled"\|"offline"}` |
| GET/PUT `/api/settings` | `{tz, units:"ft"\|"m", home_name}` | settings |
| GET `/api/home` | – | `{home: Home, rooms: Room[], graph: {vertices, edges}}` |
| PUT `/api/home` | `Home` | same as GET (after save + rebuild) |
| POST `/api/home/underlay` | multipart image | `{image: "uploads/<file>"}` |
| GET `/api/nodes` | – | `Node[]` (db row + `placed: bool` + `nearby_devices: int`) |
| POST `/api/nodes/{id}/configure` | `{ip, room_id, name}` | pushes ESPresense settings via `nodes/espresense_http.py` |
| GET/POST `/api/pets` · POST `/api/pets/{id}/tags` | `{name, species}` · `{ibeacon_id, motion_ibeacon_id?}` | pets with tags |
| GET `/api/tags/candidates` | – | iBeacons heard recently that aren't registered (for setup) |
| GET `/api/live` | – | per pet: latest `Estimate` + vertex + room + floor |
| GET `/api/history/path` | `pet, from, to` | `{points:[{ts,vertex_id,floor_id,x,y,moving}], raw?:[…]}` |
| GET `/api/history/visits` | `pet, from, to` | visits |
| POST `/api/calibrate/label` | `{pet, vertex_id, ts_start?, ts_end?, source}` | label |
| GET `/api/calibrate/stats` | `pet` | samples per vertex, eval if ground truth exists |
| POST `/api/data/export` | `{from, to}` | bundle download |
| POST `/api/pairing/code` | – | `{code, expires_at}` (via relay) |
| WS `/api/ws` | – | server → client `{topic, data}` for bus topics |

The GUI's type definitions for these live in `web/src/lib/types.ts`, and they mirror the pydantic models by hand.

## 11. MCP (`mcp/`)
- Mounted at `/mcp` (Streamable HTTP, stateless, spec 2025-11-25) on the same FastAPI app. On the LAN it needs `Authorization: Bearer <WA_LAN_TOKEN>`. Requests forwarded by the relay arrive over `relaylink` and skip the LAN token (trust is established by the relay link, §12).
- Tools and their result shapes (JSON `structuredContent` plus a text `speech` hint):
  - `where_is(pet?: str)` → `{pet, place, place_kind, room, floor, since, moving, confidence, speech}`
  - `day_summary(pet?, date?: "YYYY-MM-DD")` → `{pet, date, rooms:[{room, minutes}], landmarks:[{name, visits, last}], active_minutes, notable:[str], speech}`
  - `timeline(pet?, date?, from?: "HH:MM", to?: "HH:MM")` → `{pet, date, items:[{start, end, kind, place}], speech}`
  - `last_visit(pet?, place: str)` → `{pet, place, last_start, last_end, minutes, speech}` (fuzzy-matches the place name)
  - `anything_unusual(pet?, date?)` → `{pet, date, status:"normal"|"unusual"|"learning", reasons:[{kind, …}], days_of_data, speech}`
  - `mark_location(pet?, place: str)` → `{pet, place, vertex_id, speech}`
- MCP App resource: `ui://wheres-allie/floorplan`, a single HTML file built from `web/src/mcp-app/`. `where_is`, `day_summary` and `timeline` declare it in their tool `_meta` per the MCP Apps extension. Its data comes from the tool result.

## 12. Relay protocol (box ↔ relay WebSocket, JSON text frames)
```
box → relay  {"type":"hello","box_id":"<uuid>","box_secret":"<hex32>","version":"x.y.z"}
relay → box  {"type":"welcome"} | {"type":"error","reason":"…"}
box → relay  {"type":"pair_request","req_id":"…"}      relay → box {"type":"pair_code","req_id":"…","code":"123456","expires_at":<ts>}
relay → box  {"type":"mcp_request","id":"…","method":"POST","path":"/mcp","headers":{…},"body_b64":"…"}
box → relay  {"type":"mcp_response","id":"…","status":200,"headers":{…},"body_b64":"…"}
both         {"type":"ping"} / {"type":"pong"} every 20 s
```
- The box keeps `box_id` and `box_secret` in `settings`, generated at first boot. The relay registers them on the first `hello` (trust on first use).
- Relay HTTP: `POST /mcp` (Alexa, bearer = relay access token); OAuth `GET /oauth/authorize` (LWA login → pairing-code form), `POST /oauth/token`; `GET /healthz`. DynamoDB tables: `boxes(box_id, secret_hash, last_seen)`, `pair_codes(code, box_id, expires_at TTL)`, `links(amazon_user_id, box_id)`, `tokens(token_hash, amazon_user_id, kind, expires_at TTL)`.

## 13. Replay bundle (`replay/bundle.py`)
A zip containing `manifest.json` (`{format:1, created, tz, pets:[{name, ibeacon_id, motion_ibeacon_id}], from, to}`), `home.json`, `readings.csv` (`ts,ibeacon_id,node_id,rssi,distance,rssi_var`), `motion.csv` (`ts,ibeacon_id,moving`), `labels.csv` (`ts_start,ts_end,ibeacon_id,vertex_id,source`) and optionally `ground_truth.csv` (`ts_start,ts_end,ibeacon_id,place`, where place is a vertex id or room id). The replayer publishes readings to MQTT as real ESPresense messages (`espresense/devices/<ibeacon_id>/<node_id>` with JSON `{"id":…,"rssi":…,"distance":…,"rssiVar":…}`) at `--speed N`, with timestamps shifted so the data appears to happen now.

`box/tools/import_raw_log.py` converts `data/allie-raw.log` (the format from 2026-09-28: `<iso-ts> <topic> <payload>`) into a bundle.

## 14. Visual design tokens (`web/src/theme/tokens.css`)
UniFi-inspired, not copied. Light theme by default, dark via `[data-theme=dark]`.
`--bg #f6f7f9 · --panel #ffffff · --line #d9dde3 · --text #1b1f24 · --muted #6b7480 · --accent #006fff · --accent-2 #19b36b (live/ok) · --warn #f5a524 · --danger #e5484d · --wall #2b313a · --room-fill rgba(0,111,255,.04) · --radius 8px · --font "Inter", system-ui`.
Layout: a left icon rail (pages), a floating bottom tool palette (editor), a right inspector panel (320 px), and floor tabs top-left. The plan is SVG with a thin blueprint grid (0.5 m minor, 1 m major lines).

## 15. Plan-file index (all phases)
| Plan file | Phases |
|---|---|
| `2026-09-28-wheres-allie-plan-01-foundation.md` | 0 spikes, 1 box skeleton (compose, broker migration, db, ingest, retention, bus, API skeleton, web skeleton) |
| `2026-09-28-wheres-allie-plan-02-home-editor.md` | 2 home model, geometry, graph, plan editor GUI |
| `2026-09-28-wheres-allie-plan-03-estimator.md` | 3 estimator + eval, 4 calibration |
| `2026-09-28-wheres-allie-plan-04-live-history-mcpapp.md` | 5 live + history GUI, 8 MCP App |
| `2026-09-28-wheres-allie-plan-05-brain-mcp.md` | 6 rollups, baseline, anomalies, MCP tools |
| `2026-09-28-wheres-allie-plan-06-relay.md` | 7 AWS relay + relaylink + pairing |
| `2026-09-28-wheres-allie-plan-07-flasher-judge.md` | 9 in-GUI flasher, 10 judge mode + submission, 11 stretch notes |

Dependency order for execution: 01 → 02 → 03 → (04, 05 in parallel) → 06 → 07. Exception: plan 05 Task 6 needs plan 04 Task 4 (`home/pathing.py` `home_context`) done first. A plan may rely only on artifacts created by plans before it in this order, plus this document and each plan's "Interface additions" section (the resolved contracts between plans).
