# wheres_allie: design spec

**Status:** approved 2026-09-28 · **Date:** 2026-09-28 · **Deadline:** 2026-10-23 12:00 PDT (Alexa+ track)
**Name:** `wheres_allie` · **Demo pet:** Allie (dog)
**Related:** `docs/decisions/001-standalone-over-home-assistant.md`, `docs/friction-log.md`, candidate brief `docs/strategy/feature-funnel/01-candidates/006-pet-check-in.md`

---

## 1. Goal

Ask Alexa about your pet and get a rich, grounded answer. For example: *"Where's Allie?"*, *"What did Allie do today?"*, *"Did Allie do anything unusual?"*, *"When did she last go to her water bowl?"* The answers come from a BLE tag on the collar and ESP32 nodes in your home.

The owner also gets a polished local web app that:
- draws the home's floorplan (walls, rooms, doors, stairs, landmarks such as bed, bowls and couch);
- places the nodes;
- shows where the pet is right now, and the **path it actually took** drawn on the floorplan.

Setup has to be possible for a typical pet owner: a box on the home network, nodes flashed from the browser, no Home Assistant, and no router, DNS or tunnel configuration.

### Success criteria (by 2026-10-23)
1. **Localization quality.** On Allie's recorded data, the estimator names the correct room more often than the ESPresense-companion nearest-node baseline, measured against `data/ground-truth.md`. The under-master-bed case must be named correctly.
2. **Voice demo.** A real Alexa+ device answers all 6 tool intents end to end through the AWS relay, with no network configuration at home.
3. **Visual demo.** Path replay on the floorplan covers at least 1 day across all 3 floors, including stairs transitions.
4. **Judge mode.** `docker compose -f demo.yml up` on a clean machine shows Allie moving within 2 minutes, and the MCP tools answer from the replayed data.
5. **Submission package.** Public repo, a video under 3 minutes, product feedback, and the friction log.

### Non-goals (YAGNI; revisit only if time permits)
- Other sensors: bark detection, bowl scales, cameras (user: "circle back if time permits").
- Remote web GUI. Away from home, the owner uses Alexa (voice, plus the MCP App on a Show or phone).
- Stacked 3D multi-floor view (stretch goal, see phase 11).
- Custom firmware. ESPresense firmware v4.0.6 is used unmodified.
- Medical or health inference. Everything is framed as behaviour and routine only.
- Proactive push alerts. The Alexa+ MCP Toolkit is request/response only.

---

## 2. Constraints and facts established in the proof of concept (2026-09-27/28)

| Fact | Consequence |
|---|---|
| ESPresense firmware is reliable once running. It publishes `espresense/devices/<tag-id>/<room>` JSON (`rssi`, `distance`, `rssi@1m`, `rssiVar`, …) about every 2–5 s per node that hears the tag. | This is our only input; we consume it as-is. |
| AITRIP D1 mini ESP32 boards boot-loop at the default flash settings (DIO/40 MHz). A bootloader header patched to **dout/20 MHz** fixes them. | Our flasher ships a pre-patched bootloader. |
| ESPresense supports Improv over serial (`main/SerialImprov.cpp`), and settings via `POST /wifi` + `POST /restart`. The settings POST overwrites every field. | The flasher sets Wi-Fi via Improv, then pushes the full settings over HTTP. |
| The node's MQTT client id and topics come from its room name (`master_bedroom`). | Node identity in our model = ESPresense room id. We rename a node by pushing a new room name. |
| Under the master bed, the node in the room heard Allie at -89 dBm and the basement node below at -81 dBm. | Nearest-node fails for pets; learned fingerprints are needed. |
| A 14 s stretch of "loft" readings while Allie walked past the stairs. | Transit has to be modelled explicitly, not treated as a visit. |
| 3 floors: basement (office, moms_room), main (kitchen, master_bedroom), upstairs (loft). | Multi-floor support is required in v1. |
| Alexa+ MCP Toolkit: Streamable HTTP, spec 2025-11-25, US only, supports auth and **MCP Apps**, has a web simulator. | The MCP server targets that spec; the MCP App is the floorplan view. |
| Hackathon: "self-hosted MCP server"; the Open Source mini-challenge accepts unmerged PRs; the AWS Builder mini-challenge accepts documented AWS integrations; friction logs earn up to a 10% bonus. | The relay on AWS doubles as the AWS Builder entry. We keep the friction log. |

---

## 3. Architecture

```
 ┌── Home ─────────────────────────────────────────────────────────────┐
 │  ESP32 nodes (ESPresense fw) ──MQTT──┐                              │
 │   BLE tag on collar ◀─ scanned by ───┘                              │
 │                                      ▼                              │
 │  ┌──────── docker compose (Pi / x86 / VM) ────────────────────────┐ │
 │  │ mosquitto  ◀──────────────▶  wheres_allie (FastAPI, Python 3.12)     │ │
 │  │                               ├─ ingest      (aiomqtt)         │ │
 │  │                               ├─ estimator   (HMM on graph)    │ │
 │  │                               ├─ brain       (visits, baseline)│ │
 │  │                               ├─ mcp         (Streamable HTTP) │ │
 │  │                               ├─ api + GUI   (REST/WS + React) │ │
 │  │                               ├─ relay-link  (outbound WSS)    │ │
 │  │                               └─ store       (SQLite, WAL)     │ │
 │  └────────────────────────────────────────────────────────────────┘ │
 │   Browser on LAN ── http://wheres-allie.local ── GUI (+ Web Serial flasher)│
 └─────────────────────────────────────┬───────────────────────────────┘
                                       │ outbound WSS (box dials out)
 ┌── AWS ──────────────────────────────▼───────────────────────────────┐
 │  relay (Fargate, Python): LWA OAuth, pairing, MCP proxy             │
 │  DynamoDB: pairings (amazon_user_id ↔ box_id), no pet data          │
 └─────────────────────────────────────▲───────────────────────────────┘
                                       │ HTTPS MCP (Streamable HTTP)
                               Alexa+ (MCP Toolkit)
```

**Deliverables**
- `compose.yml`: `mosquitto` + `wheres_allie`. Images are multi-arch (amd64, arm64), with a named volume `/data`.
- `demo.yml`: the same plus `replayer`, loading `demo-data/allie-*.bundle`. It never connects to the relay.
- `relay/`: the AWS service, deployed with CDK (a single stack).

---

## 4. Components

### 4.1 Ingest
- Subscribes to `espresense/devices/+/+`, `espresense/rooms/+/status` and `espresense/rooms/+/telemetry`.
- Keeps only registered tags. Unregistered devices (phones, Sonos, the KICKR) are counted per node for a "nearby devices" diagnostic and are never stored.
- Writes each reading to `readings(ts, tag_id, node_id, rssi, distance, rssi_var)`.
- Reads node health (online/offline, uptime, Wi-Fi RSSI) into `nodes`.
- **Tag motion:** the BC021 is configured so that movement switches its minor id for about 10 s (it's the same iBeacon UUID with a different minor). Ingest maps both ids to one tag and emits a `motion(ts, tag_id, moving)` edge. A tag without a motion id falls back to "unknown", and the estimator uses movement variance instead.
- Node discovery: a node that appears on MQTT but isn't in the model shows up in the GUI as "unplaced".

### 4.2 Home model (edited in the GUI, stored as one JSON document with a version number)
- **Floor:** id, name, elevation, optional underlay image (with scale plus offset and rotation).
- **Wall:** a polyline segment with thickness. The editor snaps to endpoints, 0/45/90°, and a grid, with lengths shown in ft or m.
- **Room:** derived automatically from closed wall loops (a planar-face detection on the wall graph), then named by the user. Open-plan areas can be split with an invisible "divider" wall.
- **Door/opening:** placed on a wall, becomes a graph edge between the two rooms it connects.
- **Stairs:** a linked pair of objects on 2 floors; a cross-floor graph edge.
- **Landmark:** a point with a type (bed, food bowl, water bowl, couch, crate, door, custom), a name and a radius.
- **Node:** position (x, y, height above floor) and the ESPresense room id.
- **Walkable graph:** generated, not hand-drawn. Its vertices are room centroids, landmarks and doorway midpoints, plus stairs endpoints. Edges connect vertices within a room (direct line) and through doors and stairs. Each edge stores its length, so walking time can be estimated.

### 4.3 Estimator (the core IP)
It runs once per **2 s window** per tag, as an online HMM with forward filtering, and does Viterbi smoothing over the last 60 s to produce the stable path.

- **States:** the walkable-graph vertices, plus `away` (no node hears the tag).
- **Transitions:** stay or move to an adjacent vertex. The probability depends on the edge length and a maximum dog speed (default 3 m/s, tunable). While the tag reports still, the probability of staying rises to about 1.
- **Emission** P(readings | state):
  1. **Learned fingerprint.** If the state has at least 20 labelled samples, use a per-node Gaussian over RSSI (mean and std), plus a per-node "not heard" probability. This handles under-the-bed and floor bleed.
  2. **Fallback physics model.** Log-distance path loss from the node position to the state position, plus a per-floor-crossing attenuation (default 10 dB, learned from labels when available), plus the probability of not being heard as a function of expected RSSI.
  3. The two are blended by sample count, so learned data gradually takes over.
- **Outputs**
  - `positions(ts, tag_id, vertex_id, room_id, floor_id, confidence)` from the smoothed path.
  - `visits(tag_id, place_id, kind, start, end)`: room and landmark visits, where kind is room/landmark. A visit needs a dwell of at least 30 s. Shorter stays are recorded as `transit`, so "passed the loft stairs" is kept but never called a visit.
  - `activity(tag_id, minute, moving_s)` from motion edges.
- **Calibration data:** `labels(ts_start, ts_end, tag_id, vertex_id, source)`, where source is the guided walk, a GUI tap, or `mark_location` via voice. Each label pulls in the readings from its time window as training samples.
- **Evaluation harness:** `wheres-allie eval --bundle X --truth ground-truth.csv` reports room accuracy, landmark accuracy and transit false-visit rate, for both our estimator and a nearest-node baseline. This tests success criterion 1 and runs in CI on the recorded bundle.

### 4.4 Brain (history → answers)
- **Daily rollups,** in local time (time zone set in the GUI at setup): time per room, landmark visit counts and times, first and last activity, active minutes, restlessness (room changes per hour), and night activity.
- **Baseline:** for each tag, feature, and hour-of-day bucket (with weekday and weekend split), the median plus an inter-quartile range over the last 14–28 days. It is only used once there are at least 5 days of data; before that, `anything_unusual` says "still learning Allie's routine (N/5 days)".
- **Anomaly rules:** only explainable deviations, each producing a structured reason:
  - a feature outside its normal range, for example: `{"kind":"no_visit","place":"water bowl","since":"09:10","typical_interval":"~3h"}`;
  - an unusual location for the time of day;
  - a restless night (activity between 00:00 and 05:00 above the 90th percentile);
  - a long "away" (the tag is unheard for longer than any recent absence).
- Behaviour only, never medical wording. Tool descriptions tell the model the same.

### 4.5 MCP server (inside `wheres_allie`, mounted at `/mcp`)
- Streamable HTTP, spec 2025-11-25, official Python SDK. Stateless.
- Tools. Every tool takes an optional `pet` (default: the only pet, or "all") and returns structured JSON plus a short `speech` hint.

| Tool | Returns |
|---|---|
| `where_is(pet?)` | Current place (room, and landmark if within its radius), floor, since when, confidence, moving or still. |
| `day_summary(pet?, date?)` | The rollup plus the 3 most notable facts. |
| `timeline(pet?, date?, from?, to?)` | Ordered visits and transits. |
| `last_visit(pet?, place)` | Last time at a landmark or room, and its duration. |
| `anything_unusual(pet?, date?)` | Anomaly reasons, or "normal day", or "still learning". |
| `mark_location(pet?, place)` | Records a label for now, e.g. "Allie is on her bed". Confirms the place name. |

- **MCP App:** one UI resource, `ui://wheres-allie/floorplan`. It renders the current floor with the pet's position, or the path replay for a requested time range. `where_is`, `day_summary` and `timeline` reference it. It is a self-contained HTML bundle built from the same React components as the GUI.
- **Auth:** on the LAN, the MCP endpoint needs a box token (for testing with MCP Inspector). Through the relay, the relay authenticates Alexa and the box authenticates the relay (§4.7).

### 4.6 GUI (React + TypeScript, served by FastAPI, LAN only)
- **Visual direction:** inspired by UniFi Design Center (clean light theme with a dark variant, thin lines, blueprint-like plan, floating tool palette, right-hand inspector). No UniFi assets, names or pixel copies.
- **Screens**
  1. **Setup wizard:** name, time zone, units, first pet and its tag (auto-detected as "a new tag heard nearby"), then pairing with Alexa (shows a 6-digit code).
  2. **Plan editor:** floor tabs; wall tool; door and opening tool; stairs tool; landmark palette; underlay upload with a 2-point scale; undo/redo; each node's coverage ring (last 10 min average RSSI heat-dots).
  3. **Nodes:** list with health, an "Add node" flasher wizard (§4.8), drag onto the plan, rename, and per-node calibration values.
  4. **Live:** the plan with the pet's live marker (confidence halo), current place card, and moving/still.
  5. **History:** a date picker; the path replay animates along the snapped path with a time scrubber and 1–120× speed; the floor switches automatically at stairs; visit list; a floor strip showing which floor over time; toggle raw evidence dots.
  6. **Calibrate:** a guided walk ("Take the tag to *Water bowl* and wait 30 s": a progress ring, then next). Also "Allie is here now" on any landmark or room. Before/after accuracy is shown when ground truth exists.
  7. **Data:** export a bundle for a date range (raw readings, home model, labels, as `.bundle` = zip). Retention settings.
- **Live updates:** a WebSocket from the API pushes position, node health and readings (the latter throttled).

### 4.7 AWS relay (`relay/`, CDK)
- **Service:** a small Python service (FastAPI + websockets) on ECS Fargate, 1 task, behind an ALB with TLS on a Route 53 domain.
- **Box link:** the box dials `wss://relay/.../box` using its `box_id` and `box_secret` (generated at first boot, registered with the relay on first connect). Keepalive pings; reconnects with backoff.
- **Pairing:** the GUI requests a code from the box, and the box requests it from the relay. The 6-digit code expires after 10 minutes and is stored in DynamoDB as `code → box_id`.
- **Alexa account linking:** OAuth 2.0 authorization-code flow. The authorize page is **Login with Amazon** followed by "enter your pairing code". After that, DynamoDB holds `amazon_user_id ↔ box_id`, and the relay issues its own access and refresh tokens to Alexa.
- **MCP proxy:** Alexa+ → `POST https://relay/mcp` with a bearer token → the relay looks up the box → forwards the MCP request frame over the box's WebSocket → waits (with a timeout, default 8 s) → returns the response. Streamable HTTP responses are passed straight through. If the box is offline, the tool result says *"Allie's home hub is offline"* rather than returning an HTTP error, so Alexa says something sensible.
- **Data:** the relay stores only pairings and tokens. Requests and responses are not logged beyond metadata (timestamp, box_id, tool name, latency, status).
- **Cost:** 1 Fargate task + ALB, about $20–25/month. It's destroyed after judging, or the ALB is swapped for API Gateway later.

### 4.8 Node flasher (in the GUI, Chrome/Edge Web Serial)
1. The user plugs the node into the computer running the browser and clicks "Add node".
2. The wizard flashes using `esptool-js`: `bootloader-dout20m.bin` (ESPresense's bootloader with its header patched, done in our build) + `partitions.bin` + `boot_app0.bin` + ESPresense `esp32.bin` (pinned to v4.0.6), with a full erase.
3. **Improv over serial:** the user picks a Wi-Fi network (the SSID list comes from Improv's scan) and enters the password. The node replies with its URL (IP).
4. The box `POST`s the full settings to `http://<ip>/wifi`: MQTT host = the box's LAN IP, credentials, room id (the user's chosen name, slugified), auto-update off. Then it `POST`s `/restart`.
5. The wizard waits for `espresense/rooms/<id>/status = online`, then asks the user to place the node on the plan.
6. **Failure reporting:** each step shows a plain-English error, and the serial log is kept for "copy diagnostics".

---

## 5. Data model (SQLite, WAL, `/data/wheres_allie.db`)
`home(version, json)` · `nodes(id, name, floor_id, x, y, z, calib_json, last_seen, online)` · `pets(id, name, species)` · `tags(id, pet_id, ibeacon_id, motion_ibeacon_id)` · `readings(ts, tag_id, node_id, rssi, distance, rssi_var)` · `motion(ts, tag_id, moving)` · `positions(ts, tag_id, vertex_id, room_id, floor_id, confidence)` · `visits(id, tag_id, place_id, kind, start, end)` · `labels(id, tag_id, vertex_id, ts_start, ts_end, source)` · `rollups(tag_id, date, json)` · `settings(key, value)`.

Retention runs nightly: readings 30 days, positions 1 year, everything else forever.

---

## 6. Data flow examples
- **"Alexa, where's Allie?"** Alexa+ → relay → box `where_is` → latest smoothed position `{place:"Allie's bed", room:"Master Bedroom", floor:"Main", since:"21:58", moving:false, confidence:0.86}` → Alexa: *"Allie's been on her bed in the master bedroom since about ten, resting."* On a Show, the MCP App shows the plan with her dot on the bed.
- **"What did she do today?"** `day_summary` → rollup → *"Mostly the office with you this morning, 3 trips to her water bowl, a long nap on her bed from 1 to 4, a quick trip upstairs around 5."*

---

## 7. Error handling
| Failure | Behaviour |
|---|---|
| Node offline | Health turns red in the GUI; the estimator drops that node from the emission model (treating it as unknown, not as "not heard"); tools mention reduced confidence if it affects the answer. |
| Tag unheard | State `away` after 120 s; the answer is "I haven't heard Allie's tag since 14:05; she may be outside or her tag battery may be low." |
| MQTT broker down | Ingest reconnects with backoff; the gap is recorded as `data_gap` so baselines aren't polluted. |
| Relay unreachable | The box keeps working locally and the GUI shows "Alexa link offline". |
| Box offline (from Alexa) | The relay returns a tool result with a spoken explanation, not an HTTP error. |
| Home model edited | The graph and emission model are rebuilt. Past positions are kept; past visits are not recomputed. |
| Too little data for the baseline | Explicit "still learning" responses. |
| Flash, Improv or config step fails | Step-level error plus diagnostics; nothing is left half-configured. Re-running the wizard erases the node first. |

---

## 8. Testing approach
- **Estimator:** the recorded bundle plus `ground-truth` labels are the regression test, via `wheres-allie eval` in CI with accuracy thresholds (success criterion 1). Unit tests cover the emission models and the transition matrix built from a small synthetic graph.
- **Geometry:** unit tests for room detection from wall loops (including a wall with a gap and an open-plan divider), for door-to-edge generation, and for cross-floor stairs.
- **Brain:** fixtures of synthetic visit sequences produce the expected rollups and anomaly reasons (for example, a "no water-bowl visit" day).
- **MCP:** contract tests call every tool through the SDK client against a replayed bundle, and the MCP App resource must render (a Playwright snapshot).
- **Relay:** integration test with a fake box over WebSocket, the pairing flow with LWA mocked, and a timeout path.
- **GUI:** Playwright scripts for draw walls → auto room appears → place a node and landmark → live marker moves during replay.
- **Flasher:** manual checklist on 2 board types (AITRIP, plus another if acquired). Web Serial can't be tested in CI.
- **End to end:** Alexa+ simulator, then a real device, weekly from phase 6 onwards.

---

## 9. Risks and mitigations
| Risk | Mitigation |
|---|---|
| Alexa+ MCP Toolkit access, account linking or MCP Apps behave differently than the docs say. | Phase 0 spike on day 1–2: a hello-world tool through a temporary tunnel on a real device, then through the relay. Fallback: the web simulator, which the rules allow. |
| The BC021 motion trigger doesn't work as hoped. | Phase 0 PoC. Fallback: activity from movement variance. |
| HMM accuracy isn't clearly better than nearest-node. | The eval harness shows it early (phase 3); tune the emission and floor attenuation; learned spots from the guided walk. |
| The wall editor eats the schedule. | Hard cap: phase 2 is timeboxed to 5 days. Cut order: underlay rotation, 45° snapping, then divider walls. |
| esptool-js flashing with a patched bootloader fails in the browser. | Keep the proven CLI esptool command in docs as the fallback path. |
| Not enough days of baseline data before the demo. | Collect data continuously from now (a raw logger is already running). Phase 1 moves the logger into wheres_allie. |

---

## 10. Phases

Order: the risky spikes first, then the data path, because the brain and demo need days of accumulated real data.

| Phase | Description | Status | Tested | Pushed |
|-------|-------------|--------|--------|--------|
| 0 | Spikes: Alexa+ MCP Toolkit hello-world on a real device (temporary tunnel); BC021 motion-trigger PoC; esptool-js flash with the patched bootloader | pending | no | no |
| 1 | Box skeleton: compose (mosquitto + wheres_allie), move nodes to our broker, ingest + SQLite + retention, node health API; continuous data collection starts | pending | no | no |
| 2 | Home model + plan editor: walls/snapping, auto-rooms, doors, stairs, floors, landmarks, nodes, underlay (timeboxed to 5 days) | pending | no | no |
| 3 | Estimator: walkable graph, HMM (physics emission), visits/transit, `wheres-allie eval` vs nearest-node on recorded data | pending | no | no |
| 4 | Calibration: labels, guided walk, "here now", fingerprint emission + blending; eval shows the gain | pending | no | no |
| 5 | Live + History GUI: live marker, path replay with scrubber, floor auto-switch, visits list | pending | no | no |
| 6 | Brain + MCP: rollups, baseline, anomaly reasons, 6 tools, LAN token auth, contract tests | pending | no | no |
| 7 | AWS relay: CDK stack, box link, LWA + pairing, MCP proxy; Alexa+ end to end on a real device | pending | no | no |
| 8 | MCP App: floorplan/path UI resource on Echo Show and the Alexa app | pending | no | no |
| 9 | In-GUI node flasher: esptool-js + Improv + HTTP config wizard | pending | no | no |
| 10 | Judge mode + submission: bundle export, `demo.yml` replayer, README, video, product feedback, friction log curation | pending | no | no |
| 11 | Stretch: stacked 3D path view; extra sensors; companion availability-topic upstream PR | pending | no | no |

**Milestones:** phases 0–1 by 10/01 · phases 2–4 by 10/09 · phases 5–7 by 10/15 · phases 8–10 by 10/21 · 10/22–23 buffer for the video and submission.

---

## 11. Decisions log (from the interview, 2026-09-28)
- Scope: presence only; more sensors only if time permits.
- Path: snapped to the walkable graph (plausible routes), with raw evidence toggleable.
- Calibration: guided walk plus ongoing hints (GUI tap or voice `mark_location`).
- Floorplan: draw walls from scratch with auto-detected rooms, plus an optional underlay for tracing.
- Floors: tabs plus stairs portals; stacked 3D is a stretch goal.
- Alexa: voice-first for a typical user; the MCP App floorplan is an enhancement for Show and phone.
- Reachability: our outbound relay on AWS (no user network config), which is also the AWS Builder mini-challenge entry.
- Linking: pairing code plus Login with Amazon.
- GUI: LAN only; away from home = Alexa.
- Onboarding: in-GUI flasher (patched bootloader + Improv + HTTP config); browser flashing is fine if it's reliable.
- Stack: Python (FastAPI, MCP SDK, aiomqtt, SQLite, numpy) + React/TS; multi-arch images.
- Judges: replay of real recorded Allie data.
- Unusual: an explainable per-dog routine baseline; behaviour only.
- Pets: N in the model, 1 in the demo.
- Motion: the BC021 motion trigger is a first-class signal (after a PoC).
- Retention: tiered (raw 30 days, positions 1 year, events forever) plus dataset export.
- Home Assistant and companion PRs: considered, probably not; the companion availability fix is listed under stretch.
