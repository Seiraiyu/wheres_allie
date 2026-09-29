# wheres_allie: Brain + MCP Tools Implementation Plan

**Goal:** Turn visits and motion into daily rollups, a per-dog routine baseline and explainable "unusual" reasons, and serve them as the six MCP tools (conventions §11) at `/mcp`: Streamable HTTP, stateless, LAN bearer token, plus an in-process entry point for relay-forwarded requests. This is design phase 6.

**Architecture:** `brain/` is pure Python over SQLite. `rollups.py` computes one local day per tag (cached in `rollups` once the day is over; today is recomputed on every call). `baseline.py` turns the previous 28 days of rollups into medians, IQRs and per-hour room shares, and needs at least 5 days. `anomalies.py` compares a rollup against the baseline and returns structured reasons. `mcp/tools.py` holds the tool logic as plain functions `(ctx, pet, **args) -> dict`: pet and place resolution and spoken hints. It attaches plan 04's MCP App view (`app`) to `where_is`, `day_summary` and `timeline`. `mcp/server.py` wraps them with the official `mcp` SDK (v2 `MCPServer` plus the built-in MCP Apps extension), mounts `/mcp` on the plan-01 FastAPI app behind a token guard, and exposes `handle_mcp_request()` for plan 06's relaylink.

**Tech Stack:** Python 3.12, `sqlite3`, `zoneinfo`, `statistics`, `difflib`, `mcp>=2.2,<3` (`MCPServer`, `mcp.server.apps.Apps`, `mcp.Client`), FastAPI/Starlette, httpx, pytest + pytest-asyncio (auto mode), MCP Inspector (`npx @modelcontextprotocol/inspector`) for the manual check.

Design: `docs/plans/2026-09-28-wheres-allie-design.md` §4.4, §4.5, §6, §7. Contract: `docs/plans/2026-09-28-wheres-allie-conventions.md` §3, §5, §11. This plan needs plans 01, 02 and 03 executed, plus plan 04 Task 4 (`home/pathing.py` `home_context`), which Task 6 imports. Apart from that it runs in parallel with plan 04. Plan 04's `mcp/app_resource.py` is optional here: the tools and the server fall back when it is missing, and plan 04's Task 22 checks the link once both plans are done.

| Task | Description | Status | Tested | Pushed |
|------|-------------|--------|--------|--------|
| 1 | Check the `mcp` 2.x pin and the names this plan relies on | pending | no | no |
| 2 | `brain/rollups.py`: `day_bounds`, `minus_gaps` | pending | no | no |
| 3 | `tests/synth.py` synthetic days + `compute_rollup` / `get_rollup` | pending | no | no |
| 4 | `brain/baseline.py`: median/IQR/p90, hour-room shares, bowl intervals | pending | no | no |
| 5 | `brain/anomalies.py`: no_visit, unusual_location_for_time, restless_night, long_away | pending | no | no |
| 6 | `mcp/tools.py` core: pets, fuzzy places, speech helpers, MCP App view hook | pending | no | no |
| 7 | `where_is` + `mcp/server.py` `build_mcp` + floorplan UI resource | pending | no | no |
| 8 | `day_summary` + `timeline` (with the `from` argument) | pending | no | no |
| 9 | `last_visit` + `mark_location` | pending | no | no |
| 10 | `anything_unusual` + full contract (6 tools, guidance, spoken errors) | pending | no | no |
| 11 | `/mcp` mount, LAN token guard, `handle_mcp_request` for relaylink | pending | no | no |
| 12 | Wire `/mcp` into the plan-01 app (LAN token, session manager in lifespan) | pending | no | no |
| 13 | Manual check with MCP Inspector | pending | no | no |
| 14 | Phase 6 exit: full suite, lint, push | pending | no | no |

## Interface additions

These add to conventions §5 and §11. None of them replaces anything there.

**A. Dependency.** `mcp>=2.2,<3` (locked 2.2.0) narrows conventions §2's `mcp>=1.20`. Plan 01 already pins it, and Task 1 only checks the pin. The plan uses `mcp.server.mcpserver.MCPServer`, `mcp.server.apps.Apps` (the MCP Apps extension, `io.modelcontextprotocol/ui`), `mcp.server.streamable_http_manager.StreamableHTTPASGIApp`, `mcp.server.transport_security.TransportSecuritySettings`, `mcp.types.CallToolResult/TextContent/ToolAnnotations` and, in tests, `mcp.Client(server)` (in-memory).

**B. `brain/rollups.py`**
```python
NIGHT_END_HOUR = 5
def day_bounds(day: date, tz: ZoneInfo) -> tuple[float, float]          # local midnight..midnight, unix s
def minus_gaps(a, b, gaps: list[tuple[float, float]]) -> list[tuple[float, float]]
def compute_rollup(conn, tag_id, day, tz, lm_room: dict[str, str | None], now=None) -> dict
def get_rollup(conn, tag_id, day, tz, lm_room, now=None) -> dict       # cached when complete
def visit_end(conn, tag_id, start, end) -> float | None                # NULL end on a stale row -> next visit's start
def load_visits(conn, tag_id, t0, t1, now) -> list[(place_id, kind, start, end)]   # overlapping [t0, t1)
```
A visit left open by a box restart (`"end"` NULL but not the tag's latest visit) ends at the next visit's start, as plan 03 specifies.
The rollup JSON (stored in `rollups.json`):
`{date, complete, rooms:{room_id: minutes}, landmarks:{landmark_vertex_id:[visit_start_ts…]}, hours:[24 × {room, room_minutes, active_minutes}], first_activity, last_activity, active_minutes, night_active_minutes, room_changes, restlessness, observed_minutes, away_minutes, longest_away_minutes}`.
- Rooms get the landmark visits inside them, through `lm_room`. Its keys are landmark vertex ids (`lm:<id>`, which is what plan 03 stores in `visits.place_id`) and its values are room ids, from the graph.
- Anything inside a `gaps` row is excluded.
- `active_minutes` comes from `motion` rows. Each `moving=1` row counts until the next `moving=0` row, or at most 120 s after the last `moving=1` row.
- `restlessness` = room changes per observed hour.

**C. `brain/baseline.py`**
- `MIN_DAYS = 5`, `WINDOW_DAYS = 28`. A day counts only if `observed_minutes >= 60`.
- `Baseline(days, stats, hour_rooms, hour_days, landmark_interval_h)` with `.learning`, `.room_share(weekend, hour, room) -> (share, n)` and `.usual_room(weekend, hour)`.
- `stats[feature] = {median, q1, q3, p90, max}`. The features are `active_minutes`, `night_active_minutes`, `restlessness`, `longest_away_minutes`, and `visits:<landmark vertex id>`.
- The weekday/weekend hour bucket falls back to the pooled bucket when it has fewer than 5 days.
- `build_baseline(rollups) -> Baseline` is pure. `load_baseline(conn, tag_id, day, tz, lm_room, now=None)` uses the 28 days before `day`.

**D. `brain/anomalies.py`:** `find_anomalies(rollup, base, tz, names, now) -> list[dict]`. It returns `[]` while learning. The reason shapes are:
- `{"kind":"no_visit","place","place_id","since":"HH:MM"|None,"typical_interval":"~3h"}`, where `place_id` is the landmark vertex id: only for landmarks with a median of 2 or more visits per day. It fires when the time since the last visit (or since the first activity) is more than `max(2×interval, interval+1h)`.
- `{"kind":"unusual_location_for_time","room","hour":"HH:00","usual_room"}`: at least 20 min in a room that held that hour on fewer than 10 % of at least 5 baseline days.
- `{"kind":"restless_night","active_minutes","usual_max_minutes"}`: more than p90 of night activity, and at least 10 min.
- `{"kind":"long_away","minutes","longest_recent_minutes"}`: longer than any baseline day's longest absence, and at least 30 min.

**E. `mcp/tools.py`**
- The MCP App payload is **plan 04's**. `where_is`, `day_summary` and `timeline` add one key, `app: AppView | None`:
  - `where_is` → `app_view_for_position(conn, [tag_id])`.
  - `day_summary` → `app_view_for_range(conn, [tag_id], day_t0, min(day_t1, now))`.
  - `timeline` → `app_view_for_range(conn, [tag_id], from_ts, to_ts)`.
  - Both functions come from `wheres_allie.mcp.app_resource`. If that module isn't there yet, `tools.py` falls back to stubs that return `None`.
  - `tools.py` has no floorplan or path code of its own.
- `Ctx(conn, tz, now)` loads `(home, rooms, graph)` through plan 04's `home.pathing.home_context(conn)`.
- Every result has `speech`. Every time in a result is a **local ISO-8601 string with offset** (`2026-09-28T09:10:00-04:00`), except inside `app` (plan 04's view: unix seconds) and anomaly `since`/`hour` (`HH:MM`, as design §4.4).
- `pet` defaults: none given → the only pet, or every pet; `"all"` → every pet. With more than one pet, the result is `{"pets":[<per-pet result>…], "speech":"<joined>"}`.
- Place matching uses exact normalised names or types, then substring, then `difflib` (cutoff 0.6), over room names, landmark names and landmark types (`"water bowl"`, `"bed"`…).
- `Answer(speech)` ends a tool with a spoken message: unknown pet or place, no tag, a future date, a bad time.
- `run(conn, tz, now, fn, pet, **kw) -> dict`.
- `where_is` reports `place:"away"` when the latest position is older than 120 s, or its vertex isn't in the graph (design §7).
- `mark_location` calls plan 03's `create_label(conn, tag_id, vertex_id, "voice", ts_start=now-30, ts_end=now)`. The vertex id is `room:<room_id>` or `lm:<landmark_id>`.

**F. `mcp/server.py`**
- `FLOORPLAN_URI = "ui://wheres-allie/floorplan"`.
- `build_mcp(connect: Callable[[], sqlite3.Connection], tz_default="America/New_York", clock=time.time) -> MCPServer`. `connect()` is called once per tool call and returns the connection to use, which is never closed by the tool. Sync tools run in worker threads, so the connection must allow that. The app passes `lambda: app.state.conn` (plan 01's connection is `check_same_thread=False`, autocommit). Tests pass `lambda: connect(db_path)`.
- The tz is `db.get_setting(conn, "tz")`, falling back to `tz_default` (`settings.tz` / `WA_TZ`).
- Each tool result is `CallToolResult(content=[TextContent(text=speech)], structuredContent=<dict>)`. On `Answer` it is `isError=true` and `structuredContent={"speech"}`.
- `where_is`, `day_summary` and `timeline` are registered with `Apps.tool(resource_uri=FLOORPLAN_URI)`, so their tool `_meta` is `{"ui":{"resourceUri":"ui://wheres-allie/floorplan"}}`. The resource is served as `text/html;profile=mcp-app` from plan 04's `wheres_allie.mcp.app_resource.floorplan_html()`, with a placeholder page when that module is missing.
- **SDK check:** `mcp.server.apps.Apps` must exist (Task 1 checks this; it exists in 2.2). If it doesn't, register the resource with `srv.resource(FLOORPLAN_URI, mime_type="text/html;profile=mcp-app")(floorplan_html)` and the three tools with `srv.tool(meta={"ui": {"resourceUri": FLOORPLAN_URI}}, ...)`. The wire result is the same.
- Every read tool's description, and the server `instructions`, say "Never make medical or health claims…".
- `timeline` publishes the argument name `from` (a Python keyword) through an explicit `__signature__`.
- `mount_mcp(app, srv, lan_token: Callable[[], str]) -> None` adds `GET|POST|DELETE /mcp`. It builds the transport as stateless with **JSON responses (no SSE)**, so the relay forwards exactly one body. DNS-rebinding protection is off, because the bearer token guards the endpoint. It returns 401 JSON with `WWW-Authenticate: Bearer` without the right token. **The caller must enter `srv.session_manager.run()` in the app lifespan.**
- `mount_mcp` inserts the route at index 0, so plan 01's GUI mount at `/` can't shadow it.
- `ensure_lan_token(conn, configured=None) -> str` returns `configured` (`Settings.lan_token`, from `WA_LAN_TOKEN`, default `""`) when set, otherwise the saved token, otherwise a new `secrets.token_urlsafe(24)`. The result is saved with `db.set_setting(conn, "lan_token", …)` (conventions §3); plan 01 leaves token generation to this plan. `create_app` stores it as `app.state.lan_token`.
- `async handle_mcp_request(method, path, headers, body) -> (status, headers, body)` is for plan 06's relaylink. It runs the request against the mounted MCP ASGI app in-process and skips the token. It drops `host`, `content-length`, `authorization`, `connection` and `transfer-encoding`. Paths other than `/mcp` get 404. It is a module-level function bound to the last `mount_mcp` call (one app per process).

**G. Test helpers:** `box/tests/synth.py`, with `TZ`, `at(day, "HH:MM")` and `add_day(conn, tag_id, day, segments, water, moving, until, water_id)`. It writes exclusive visits, a position at each visit start, and motion rows (a `moving=1` row every 60 s). `box/tests/mcp/conftest.py` provides `seed(path, history_days)`, `db_path`, `mcp_server`, `NOW` = 2026-09-28 15:30 America/New_York, and the fixture names. `box/pyproject.toml` gets `pythonpath = ["src", "tests"]` if it doesn't have it.

**H. Names from earlier plans.** Task 1 checks each one with grep. If a name differs, use the real one everywhere in this plan.
- **Plan 01** (confirmed by plan-01):
  - `db.connect(path)`, `migrate(conn)`, `get_setting(conn, key, default=None)` and `set_setting(conn, key, value)`. The settings keys are `tz`, `units`, `home_name` and, from this plan, `lan_token`.
  - `config.Settings`, with `data_dir`, `mqtt_pass`, `web_dist`, `tz` (`WA_TZ`) and `lan_token` (`WA_LAN_TOKEN`, default `""`).
  - `api.app.create_app(settings: Settings | None = None, conn=None, start_background=True)`. It sets `app.state.settings`, `app.state.conn`, `app.state.bus`, and so on when the app is created. Its `@asynccontextmanager` lifespan starts the `tasks` and cancels them after `yield`.
  - The final line is `if settings.web_dist.is_dir(): app.mount("/", SPAStaticFiles…)`, and it must stay last. The SPA fallback already skips `mcp…` paths.
- **Plan 02:**
  - `home.store.load_home/save_home`, `home.model.Home`, `home.geometry.detect_rooms/Room`, `home.graph.build_graph/Graph`. Landmark vertices carry `room_id`.
  - The fixture `tests/fixtures/home_allie.json`, with rooms "Office" and "Mom's room" (floor "Basement"), "Kitchen" and "Master bedroom" (floor "Main"), and "Loft" (floor "Upstairs").
  - Its landmarks are "Allie's bed" (`bed_master`, in the master bedroom), "Water bowl" and "Food bowl" (kitchen), and "Couch" (loft).
- **Plan 04** (runs in parallel):
  - `home.pathing.home_context(conn) -> (Home, list[Room], Graph)` is plan 04 Task 4, which must be done before this plan's Task 6.
  - `mcp.app_resource`: `FLOORPLAN_URI`, `floorplan_html()`, `app_view_for_position(conn, tag_ids)` and `app_view_for_range(conn, tag_ids, t0, t1)`. They are optional here (import fallbacks).
  - Plan 04's Task 22 builds the server with `build_mcp(lambda: None)`.
  - The MCP App reads `pet`, `place` and `app` from structuredContent.
- **Plan 03:**
  - `calibration.labels.create_label(conn, tag_id, vertex_id, source, ts_start=None, ts_end=None) -> dict`.
  - `visits.place_id` is the room id for `kind='room'`, the landmark **vertex id** `lm:<id>` for `kind='landmark'`, the vertex id for `transit`, and `'away'` for `away`.
  - A visit opens with `"end" NULL` once the dwell reaches 30 s.
  - Visits are exclusive in time, because a landmark and its room are separate HMM states.
  - While the pet is away, `positions.vertex_id='away'`.

---

### Task 1: Check the `mcp` 2.x pin and the names this plan relies on

**Files:**
- Modify: `box/pyproject.toml` (only if the pytest options below are missing)

**Step 1: Write failing test**
There's no unit test. The check is two commands:
```bash
cd box && grep -n '"mcp>=2.2,<3"' pyproject.toml
cd box && uv run python -c "from mcp.server.apps import Apps; from mcp.server.mcpserver import MCPServer; from mcp import Client; print('ok')"
```

**Step 2: Run test, verify failure**
Run both commands.
Expected: the grep prints plan 01's `"mcp>=2.2,<3"` dependency line, and the import prints `ok`. If the grep prints nothing, plan 01 is not done: stop and finish plan 01 first. Don't change the pin here.

**Step 3: Implement**
Make sure `[tool.pytest.ini_options]` in `box/pyproject.toml` has these two lines. Add any that are missing and keep the rest:
```toml
pythonpath = ["src", "tests"]
asyncio_mode = "auto"
```
Check the names from Interface additions H. Every grep must print at least one line:
```bash
cd box
grep -n "def connect\|def migrate\|def get_setting\|def set_setting" src/wheres_allie/db.py
grep -n "def create_app\|lifespan\|yield\|app.state.conn\|web_dist\|mount(" src/wheres_allie/api/app.py
grep -n "lan_token\|tz" src/wheres_allie/config.py
grep -n "def load_home\|def save_home" src/wheres_allie/home/store.py
grep -n "def detect_rooms\|class Room" src/wheres_allie/home/geometry.py
grep -n "def build_graph\|class Graph\|room_id" src/wheres_allie/home/graph.py
grep -n "def create_label" -A2 src/wheres_allie/calibration/labels.py
grep -n "Master bedroom\|Water bowl\|Allie's bed\|\"Loft\"\|\"Basement\"" tests/fixtures/home_allie.json
grep -n "def home_context" src/wheres_allie/home/pathing.py   # plan 04 Task 4
uv run python -c "from mcp.server.apps import Apps; a = Apps(); print(a.tool, a.add_html_resource)"
```
If the last command fails, the pinned SDK has no MCP Apps helper. In that case use the fallback from Interface additions F in Tasks 7 and 8: `srv.resource(FLOORPLAN_URI, mime_type="text/html;profile=mcp-app")(floorplan_html)`, and `srv.tool(meta={"ui": {"resourceUri": FLOORPLAN_URI}}, ...)` in place of `apps.tool(resource_uri=FLOORPLAN_URI, ...)`. If `home_context` is missing, do plan 04 Task 4 first.

**Step 4: Run test, verify pass**
Run the Step 1 commands again. Expected: the pin line and `ok`.

**Step 5: Commit** (only if `pyproject.toml` changed)
```bash
git add box/pyproject.toml
git commit -m "chore: pytest pythonpath for shared test helpers" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: `brain/rollups.py`: `day_bounds`, `minus_gaps`

**Files:**
- Create: `box/src/wheres_allie/brain/__init__.py` (empty, if missing)
- Create: `box/src/wheres_allie/brain/rollups.py`
- Test: `box/tests/brain/test_rollups.py`

**Step 1: Write failing test**
```python
# box/tests/brain/test_rollups.py
from datetime import date
from zoneinfo import ZoneInfo

from wheres_allie.brain.rollups import day_bounds, minus_gaps


def test_minus_gaps_cuts_out_overlap():
    assert minus_gaps(0, 10, [(2, 4), (8, 20)]) == [(0, 2), (4, 8)]
    assert minus_gaps(0, 10, []) == [(0, 10)]
    assert minus_gaps(3, 5, [(0, 10)]) == []


def test_day_bounds_is_local_midnight_to_midnight():
    t0, t1 = day_bounds(date(2026, 9, 28), ZoneInfo("America/New_York"))
    assert t1 - t0 == 86400
    assert t0 == 1790568000  # 2026-09-28T00:00:00-04:00
```

**Step 2: Run test, verify failure**
Run: `cd box && uv run pytest tests/brain/test_rollups.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'wheres_allie.brain'` (or `...brain.rollups`)

**Step 3: Implement**
Create an empty `box/src/wheres_allie/brain/__init__.py` if it doesn't exist. Then:
```python
# box/src/wheres_allie/brain/rollups.py
"""Local-day rollups built from visits + motion, cached in the `rollups` table."""

from datetime import date, datetime, timedelta
from datetime import time as dtime
from zoneinfo import ZoneInfo


def day_bounds(day: date, tz: ZoneInfo) -> tuple[float, float]:
    start = datetime.combine(day, dtime(), tz)
    return start.timestamp(), datetime.combine(day + timedelta(days=1), dtime(), tz).timestamp()


def minus_gaps(a: float, b: float, gaps: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """[a, b) with every data gap cut out."""
    parts = [(a, b)]
    for g0, g1 in gaps:
        parts = [p for x, y in parts for p in ((x, min(y, g0)), (max(x, g1), y)) if p[1] > p[0]]
    return parts
```

**Step 4: Run test, verify pass**
Run: `cd box && uv run pytest tests/brain/test_rollups.py -q`
Expected: `2 passed`

**Step 5: Commit**
```bash
git add box/src/wheres_allie/brain/__init__.py box/src/wheres_allie/brain/rollups.py box/tests/brain/test_rollups.py
git commit -m "feat: rollup day bounds and gap subtraction" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: `tests/synth.py` synthetic days + `compute_rollup` / `get_rollup`

**Files:**
- Create: `box/tests/synth.py`
- Modify: `box/src/wheres_allie/brain/rollups.py`
- Test: `box/tests/brain/test_rollups.py`

**Step 1: Write failing test**
First create the shared synthetic-data helper. The brain and MCP tests use it, and it needs no estimator:
```python
# box/tests/synth.py
"""Synthetic visit/motion days for brain + MCP tests (no estimator needed)."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/New_York")
WATER_TIMES = ("07:30", "10:30", "13:30", "16:30", "19:30")
# (start, place_id, kind): each segment runs until the next one; the last until midnight
ROUTINE = [
    ("00:00", "bed", "landmark"),
    ("07:00", "office", "room"),
    ("12:00", "kitchen", "room"),
    ("13:00", "office", "room"),
    ("18:00", "living", "room"),
    ("22:00", "bed", "landmark"),
]


def at(day: date, hhmm: str) -> float:
    if hhmm == "24:00":
        return datetime.combine(day + timedelta(days=1), time(), TZ).timestamp()
    return datetime.combine(day, time.fromisoformat(hhmm), TZ).timestamp()


def add_day(
    conn,
    tag_id: int,
    day: date,
    segments=ROUTINE,
    water=WATER_TIMES,
    moving=(("07:00", "07:10"), ("12:00", "12:15"), ("18:00", "18:30")),
    until=None,
    water_id="water",
):
    """Write exclusive visits for `day`: the routine with 3-minute water-bowl trips spliced in,
    a position at the start of each visit and motion edges. Landmark place ids are used as the
    position vertex id as is (plan 03 stores "lm:<id>"). `until` (ts) truncates the day and
    leaves the last visit open."""
    points = [(at(day, s), p, k) for s, p, k in segments]
    for w in water:
        t = at(day, w)
        back = max((pt for pt in points if pt[0] <= t), key=lambda pt: pt[0])
        points += [(t, water_id, "landmark"), (t + 180, back[1], back[2])]
    points.sort(key=lambda pt: pt[0])
    ends = [pt[0] for pt in points[1:]] + [at(day, "24:00")]
    for (start, place, kind), end in zip(points, ends):
        if until is not None and start >= until:
            break
        open_ = until is not None and end > until
        conn.execute(
            'INSERT INTO visits (tag_id, place_id, kind, start, "end") VALUES (?,?,?,?,?)',
            (tag_id, place, kind, start, None if open_ else end),
        )
        conn.execute(
            "INSERT INTO positions (ts, tag_id, vertex_id, confidence, moving) "
            "VALUES (?,?,?,0.9,0)",
            (start, tag_id, place if kind == "landmark" else f"room:{place}"),
        )
    for a, b in moving:
        if until is None or at(day, a) < until:
            for t in range(int(at(day, a)), int(at(day, b)), 60):  # the tag repeats its motion id
                conn.execute("INSERT INTO motion VALUES (?,?,1)", (t, tag_id))
            conn.execute("INSERT INTO motion VALUES (?,?,0)", (at(day, b), tag_id))
    conn.commit()


LM_ROOM = {"water": "kitchen", "bed": "bedroom"}
NAMES = {
    "water": "Water bowl",
    "bed": "Allie's bed",
    "office": "Office",
    "kitchen": "Kitchen",
    "living": "Living room",
    "bedroom": "Master bedroom",
    "basement": "Basement",
}
```
Then replace `box/tests/brain/test_rollups.py` with:
```python
# box/tests/brain/test_rollups.py
from datetime import date
from zoneinfo import ZoneInfo

import pytest
from synth import LM_ROOM, TZ, add_day, at

from wheres_allie.brain.rollups import day_bounds, get_rollup, minus_gaps
from wheres_allie.db import connect, migrate

DAY = date(2026, 9, 21)  # a Monday


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "t.db")
    migrate(c)
    return c


def test_minus_gaps_cuts_out_overlap():
    assert minus_gaps(0, 10, [(2, 4), (8, 20)]) == [(0, 2), (4, 8)]
    assert minus_gaps(0, 10, []) == [(0, 10)]
    assert minus_gaps(3, 5, [(0, 10)]) == []


def test_day_bounds_is_local_midnight_to_midnight():
    t0, t1 = day_bounds(date(2026, 9, 28), ZoneInfo("America/New_York"))
    assert t1 - t0 == 86400
    assert t0 == 1790568000  # 2026-09-28T00:00:00-04:00


def test_routine_day_rollup(conn):
    add_day(conn, 1, DAY)
    r = get_rollup(conn, 1, DAY, TZ, LM_ROOM, now=at(DAY, "24:00") + 60)
    assert r["complete"] is True
    assert r["rooms"]["office"] == pytest.approx(10 * 60 - 4 * 3, abs=0.1)  # 4 trips from office
    assert r["rooms"]["kitchen"] == pytest.approx(60 + 5 * 3, abs=0.1)  # bowl is in the kitchen
    water = [round(at(DAY, w)) for w in ("07:30", "10:30", "13:30", "16:30", "19:30")]
    assert [round(t) for t in r["landmarks"]["water"]] == water
    assert r["active_minutes"] == pytest.approx(55)
    assert r["night_active_minutes"] == 0
    assert r["first_activity"] == at(DAY, "07:00")
    assert r["hours"][3]["room"] == "bedroom"
    assert r["hours"][9]["room"] == "office"
    assert r["room_changes"] > 0 and r["restlessness"] > 0


def test_gaps_are_excluded(conn):
    add_day(conn, 1, DAY)
    conn.execute("INSERT INTO gaps VALUES (?, ?, 'mqtt')", (at(DAY, "08:00"), at(DAY, "09:00")))
    r = get_rollup(conn, 1, DAY, TZ, LM_ROOM, now=at(DAY, "24:00") + 60)
    assert r["rooms"]["office"] == pytest.approx(9 * 60 - 4 * 3, abs=0.1)


def test_night_activity_and_away(conn):
    add_day(conn, 1, DAY, moving=(("01:00", "01:05"), ("02:00", "02:05")))
    conn.execute(
        'INSERT INTO visits (tag_id, place_id, kind, start, "end") VALUES (1,?,?,?,?)',
        ("away", "away", at(DAY, "20:00"), at(DAY, "21:30")),
    )
    r = get_rollup(conn, 1, DAY, TZ, LM_ROOM, now=at(DAY, "24:00") + 60)
    assert r["night_active_minutes"] == pytest.approx(10)
    assert r["longest_away_minutes"] == pytest.approx(90)


def test_open_visit_left_by_a_restart_ends_at_the_next_visit(conn):
    rows = [("office", "room", at(DAY, "08:00"), None), ("kitchen", "room", at(DAY, "09:00"), None)]
    conn.executemany(
        'INSERT INTO visits (tag_id, place_id, kind, start, "end") VALUES (1,?,?,?,?)', rows
    )
    r = get_rollup(conn, 1, DAY, TZ, LM_ROOM, now=at(DAY, "10:00"))
    assert r["rooms"] == {"office": 60.0, "kitchen": 60.0}


def test_complete_day_cached_today_recomputed(conn):
    add_day(conn, 1, DAY, until=at(DAY, "12:10"))
    r1 = get_rollup(conn, 1, DAY, TZ, LM_ROOM, now=at(DAY, "12:10"))
    assert r1["complete"] is False
    r2 = get_rollup(conn, 1, DAY, TZ, LM_ROOM, now=at(DAY, "12:30"))  # open visit grows
    assert r2["rooms"]["kitchen"] > r1["rooms"]["kitchen"]
    done = get_rollup(conn, 1, DAY, TZ, LM_ROOM, now=at(DAY, "24:00") + 1)
    conn.execute("DELETE FROM visits")
    assert get_rollup(conn, 1, DAY, TZ, LM_ROOM, now=at(DAY, "24:00") + 99) == done
```

**Step 2: Run test, verify failure**
Run: `cd box && uv run pytest tests/brain/test_rollups.py -q`
Expected: FAIL with `ImportError: cannot import name 'get_rollup' from 'wheres_allie.brain.rollups'`

**Step 3: Implement**
Replace `box/src/wheres_allie/brain/rollups.py` with:
```python
# box/src/wheres_allie/brain/rollups.py
"""Local-day rollups built from visits + motion, cached in the `rollups` table."""

import json
import sqlite3
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from datetime import time as dtime
from zoneinfo import ZoneInfo

NIGHT_END_HOUR = 5  # "night" = 00:00-05:00 local
MOTION_CAP_S = 120  # a moving row counts for at most 2 min unless another row follows sooner


def day_bounds(day: date, tz: ZoneInfo) -> tuple[float, float]:
    start = datetime.combine(day, dtime(), tz)
    return start.timestamp(), datetime.combine(day + timedelta(days=1), dtime(), tz).timestamp()


def minus_gaps(a: float, b: float, gaps: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """[a, b) with every data gap cut out."""
    parts = [(a, b)]
    for g0, g1 in gaps:
        parts = [p for x, y in parts for p in ((x, min(y, g0)), (max(x, g1), y)) if p[1] > p[0]]
    return parts


def _add_by_hour(parts, tz: ZoneInfo, hours: list[dict], key: str, room: str | None = None) -> None:
    # ponytail: splits on UTC hour boundaries, so it assumes a whole-hour tz offset
    for a, b in parts:
        while a < b:
            nxt = min(b, (a // 3600 + 1) * 3600)
            h = hours[datetime.fromtimestamp(a, tz).hour]
            if room is None:
                h[key] += nxt - a
            else:
                h[key][room] += nxt - a
            a = nxt


def _motion_intervals(conn, tag_id: int, t0: float, t1: float) -> list[tuple[float, float]]:
    rows = conn.execute(
        "SELECT ts, moving FROM motion WHERE tag_id = ? AND ts >= ? AND ts < ? ORDER BY ts",
        (tag_id, t0 - MOTION_CAP_S, t1),
    ).fetchall()
    out, start, last = [], None, None
    for ts, moving in rows:
        if start is not None and (not moving or ts - last > MOTION_CAP_S):
            out.append((start, min(ts, last + MOTION_CAP_S)))
            start = None
        if moving:
            start = ts if start is None else start
            last = ts
    if start is not None:
        out.append((start, min(t1, last + MOTION_CAP_S)))
    return [(max(a, t0), min(b, t1)) for a, b in out if min(b, t1) > max(a, t0)]


def visit_end(conn: sqlite3.Connection, tag_id: int, start: float, end: float | None):
    """A visit left open by a box restart ends where the next visit starts (plan 03)."""
    if end is not None:
        return end
    return conn.execute(
        "SELECT min(start) FROM visits WHERE tag_id = ? AND start > ?", (tag_id, start)
    ).fetchone()[0]


def load_visits(
    conn: sqlite3.Connection, tag_id: int, t0: float, t1: float, now: float
) -> list[tuple[str, str, float, float | None]]:
    """(place_id, kind, start, end) overlapping [t0, t1), by start; end None = still there."""
    rows = conn.execute(
        'SELECT place_id, kind, start, "end" FROM visits '
        'WHERE tag_id = ? AND start < ? AND coalesce("end", ?) > ? ORDER BY start',
        (tag_id, t1, now, t0),
    ).fetchall()
    out = [(p, k, s, visit_end(conn, tag_id, s, e)) for p, k, s, e in rows]
    return [v for v in out if v[3] is None or v[3] > t0]


def compute_rollup(
    conn: sqlite3.Connection,
    tag_id: int,
    day: date,
    tz: ZoneInfo,
    lm_room: dict[str, str | None],
    now: float | None = None,
) -> dict:
    now = time.time() if now is None else now
    t0, t_day_end = day_bounds(day, tz)
    t1 = min(t_day_end, now)
    gaps = [
        (g0, now if g1 is None else g1)
        for g0, g1 in conn.execute(
            "SELECT ts_start, ts_end FROM gaps WHERE ts_start < ? AND coalesce(ts_end, ?) > ?",
            (t1, now, t0),
        )
    ]
    visits = load_visits(conn, tag_id, t0, t1, now)

    hours = [{"rooms": defaultdict(float), "active": 0.0} for _ in range(24)]
    rooms: dict[str, float] = defaultdict(float)
    landmarks: dict[str, list[float]] = defaultdict(list)
    observed = away = longest_away = 0.0
    changes, prev_room, first_seen, last_seen = 0, None, None, None
    for place_id, kind, start, end in visits:
        parts = minus_gaps(max(start, t0), min(end or now, t1), gaps)
        secs = sum(b - a for a, b in parts)
        if not parts:
            continue
        if kind == "away":
            away += secs
            longest_away = max(longest_away, secs)
            continue
        observed += secs
        first_seen = parts[0][0] if first_seen is None else first_seen
        last_seen = parts[-1][1]
        if kind == "transit":
            continue
        room = lm_room.get(place_id) if kind == "landmark" else place_id
        if kind == "landmark" and start >= t0:
            landmarks[place_id].append(start)
        if room is None:
            continue
        rooms[room] += secs
        _add_by_hour(parts, tz, hours, "rooms", room)
        if prev_room is not None and room != prev_room:
            changes += 1
        prev_room = room

    moving = [p for a, b in _motion_intervals(conn, tag_id, t0, t1) for p in minus_gaps(a, b, gaps)]
    _add_by_hour(moving, tz, hours, "active")
    active = sum(b - a for a, b in moving)
    hour_rows = []
    for h in hours:
        top = max(h["rooms"].items(), key=lambda kv: kv[1], default=(None, 0.0))
        hour_rows.append(
            {
                "room": top[0],
                "room_minutes": round(top[1] / 60, 1),
                "active_minutes": round(h["active"] / 60, 1),
            }
        )
    return {
        "date": day.isoformat(),
        "complete": now >= t_day_end,
        "rooms": {k: round(v / 60, 1) for k, v in sorted(rooms.items(), key=lambda kv: -kv[1])},
        "landmarks": dict(landmarks),
        "hours": hour_rows,
        "first_activity": moving[0][0] if moving else first_seen,
        "last_activity": moving[-1][1] if moving else last_seen,
        "active_minutes": round(active / 60, 1),
        "night_active_minutes": round(
            sum(r["active_minutes"] for r in hour_rows[:NIGHT_END_HOUR]), 1
        ),
        "room_changes": changes,
        "restlessness": round(changes / (observed / 3600), 2) if observed >= 600 else 0.0,
        "observed_minutes": round(observed / 60, 1),
        "away_minutes": round(away / 60, 1),
        "longest_away_minutes": round(longest_away / 60, 1),
    }


def get_rollup(
    conn: sqlite3.Connection,
    tag_id: int,
    day: date,
    tz: ZoneInfo,
    lm_room: dict[str, str | None],
    now: float | None = None,
) -> dict:
    """Cached rollup for finished days; today (or any unfinished day) is recomputed every call."""
    row = conn.execute(
        "SELECT json FROM rollups WHERE tag_id = ? AND date = ?", (tag_id, day.isoformat())
    ).fetchone()
    if row:
        cached = json.loads(row[0])
        if cached["complete"]:
            return cached
    r = compute_rollup(conn, tag_id, day, tz, lm_room, now)
    conn.execute(
        "INSERT OR REPLACE INTO rollups (tag_id, date, json) VALUES (?, ?, ?)",
        (tag_id, day.isoformat(), json.dumps(r)),
    )
    conn.commit()
    return r
```

**Step 4: Run test, verify pass**
Run: `cd box && uv run pytest tests/brain/test_rollups.py -q`
Expected: `7 passed`

**Step 5: Commit**
```bash
git add box/tests/synth.py box/src/wheres_allie/brain/rollups.py box/tests/brain/test_rollups.py
git commit -m "feat: daily rollups from visits and motion, cached per finished day" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: `brain/baseline.py`: median/IQR/p90, hour-room shares, bowl intervals

**Files:**
- Create: `box/src/wheres_allie/brain/baseline.py`
- Test: `box/tests/brain/test_baseline_anomalies.py`

**Step 1: Write failing test**
```python
# box/tests/brain/test_baseline_anomalies.py
from datetime import date, timedelta

import pytest
from synth import LM_ROOM, NAMES, ROUTINE, TZ, add_day, at

from wheres_allie.brain.baseline import load_baseline
from wheres_allie.brain.rollups import get_rollup
from wheres_allie.db import connect, migrate

TODAY = date(2026, 9, 28)


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "t.db")
    migrate(c)
    return c


def seed_history(conn, days: int):
    for d in range(1, days + 1):
        add_day(conn, 1, TODAY - timedelta(days=d))


def test_learning_with_4_days(conn):
    seed_history(conn, 4)
    base = load_baseline(conn, 1, TODAY, TZ, LM_ROOM, at(TODAY, "20:00"))
    assert base.learning and base.days == 4 and base.stats == {}


def test_baseline_stats(conn):
    seed_history(conn, 14)
    base = load_baseline(conn, 1, TODAY, TZ, LM_ROOM, at(TODAY, "12:00"))
    assert base.days == 14 and not base.learning
    assert base.landmark_interval_h["water"] == pytest.approx(3)
    assert base.stats["visits:water"]["median"] == 5
    assert base.stats["active_minutes"]["median"] == pytest.approx(55)
    assert base.usual_room(False, 9) == "office"
    assert base.room_share(True, 9, "office") == (1.0, 14)  # 4 weekend days -> pooled bucket
```

**Step 2: Run test, verify failure**
Run: `cd box && uv run pytest tests/brain/test_baseline_anomalies.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'wheres_allie.brain.baseline'`

**Step 3: Implement**
```python
# box/src/wheres_allie/brain/baseline.py
"""Per-tag routine baseline: median + IQR per feature over the last 28 days of rollups."""

import sqlite3
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from wheres_allie.brain.rollups import get_rollup

MIN_DAYS = 5
WINDOW_DAYS = 28
MIN_OBSERVED_MINUTES = 60  # a day with less data than this doesn't count toward the baseline
DAILY_FEATURES = ("active_minutes", "night_active_minutes", "restlessness", "longest_away_minutes")


@dataclass
class Baseline:
    days: int
    # feature -> {median, q1, q3, p90, max}; landmark visit counts are "visits:<landmark_id>"
    stats: dict[str, dict[str, float]] = field(default_factory=dict)
    # (weekend: bool | None, hour) -> {room_id: share of days that hour was spent mostly there};
    # None = weekday and weekend pooled
    hour_rooms: dict[tuple[bool | None, int], dict[str, float]] = field(default_factory=dict)
    hour_days: dict[tuple[bool | None, int], int] = field(default_factory=dict)
    # landmark_id -> median hours between consecutive visits on the same day
    landmark_interval_h: dict[str, float] = field(default_factory=dict)

    @property
    def learning(self) -> bool:
        return self.days < MIN_DAYS

    def _key(self, weekend: bool, hour: int) -> tuple[bool | None, int]:
        """The weekday/weekend bucket, or the pooled one if that bucket is thin."""
        return (
            (weekend, hour) if self.hour_days.get((weekend, hour), 0) >= MIN_DAYS else (None, hour)
        )

    def room_share(self, weekend: bool, hour: int, room: str) -> tuple[float, int]:
        """(share of days spent mostly in `room` that hour, sample days)."""
        key = self._key(weekend, hour)
        return self.hour_rooms.get(key, {}).get(room, 0.0), self.hour_days.get(key, 0)

    def usual_room(self, weekend: bool, hour: int) -> str | None:
        shares = self.hour_rooms.get(self._key(weekend, hour))
        return max(shares, key=shares.get) if shares else None


def _summary(values: list[float]) -> dict[str, float]:
    q = statistics.quantiles(values, n=20, method="inclusive")  # 5 % steps
    return {
        "median": statistics.median(values),
        "q1": q[4],
        "q3": q[14],
        "p90": q[17],
        "max": max(values),
    }


def build_baseline(rollups: list[dict]) -> Baseline:
    days = [r for r in rollups if r["observed_minutes"] >= MIN_OBSERVED_MINUTES]
    base = Baseline(days=len(days))
    if base.learning:
        return base
    for f in DAILY_FEATURES:
        base.stats[f] = _summary([r[f] for r in days])
    for lm in {lm for r in days for lm in r["landmarks"]}:
        per_day = [sorted(r["landmarks"].get(lm, [])) for r in days]
        base.stats[f"visits:{lm}"] = _summary([len(v) for v in per_day])
        gaps = [b - a for v in per_day for a, b in zip(v, v[1:])]
        if gaps:
            base.landmark_interval_h[lm] = statistics.median(gaps) / 3600
    counts: dict[tuple, Counter] = defaultdict(Counter)
    for r in days:
        weekend = date.fromisoformat(r["date"]).weekday() >= 5
        for hour, h in enumerate(r["hours"]):
            if h["room"]:
                counts[(weekend, hour)][h["room"]] += 1
                counts[(None, hour)][h["room"]] += 1
    for key, c in counts.items():
        n = sum(c.values())
        base.hour_days[key] = n
        base.hour_rooms[key] = {room: k / n for room, k in c.items()}
    return base


def load_baseline(
    conn: sqlite3.Connection,
    tag_id: int,
    day: date,
    tz: ZoneInfo,
    lm_room: dict[str, str | None],
    now: float | None = None,
) -> Baseline:
    """Baseline from the WINDOW_DAYS days before `day` (rollups computed and cached on demand)."""
    return build_baseline(
        [
            get_rollup(conn, tag_id, day - timedelta(days=d), tz, lm_room, now)
            for d in range(1, WINDOW_DAYS + 1)
        ]
    )
```

**Step 4: Run test, verify pass**
Run: `cd box && uv run pytest tests/brain/test_baseline_anomalies.py -q`
Expected: `2 passed`

**Step 5: Commit**
```bash
git add box/src/wheres_allie/brain/baseline.py box/tests/brain/test_baseline_anomalies.py
git commit -m "feat: per-tag routine baseline (median/IQR over 28 days, min 5)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: `brain/anomalies.py`: no_visit, unusual_location_for_time, restless_night, long_away

**Files:**
- Create: `box/src/wheres_allie/brain/anomalies.py`
- Test: `box/tests/brain/test_baseline_anomalies.py`

**Step 1: Write failing test**
Replace `box/tests/brain/test_baseline_anomalies.py` with (Task 4's tests plus the anomaly tests):
```python
# box/tests/brain/test_baseline_anomalies.py
from datetime import date, timedelta

import pytest
from synth import LM_ROOM, NAMES, ROUTINE, TZ, add_day, at

from wheres_allie.brain.anomalies import find_anomalies
from wheres_allie.brain.baseline import load_baseline
from wheres_allie.brain.rollups import get_rollup
from wheres_allie.db import connect, migrate

TODAY = date(2026, 9, 28)


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "t.db")
    migrate(c)
    return c


def seed_history(conn, days: int):
    for d in range(1, days + 1):
        add_day(conn, 1, TODAY - timedelta(days=d))


def check(conn, now):
    base = load_baseline(conn, 1, TODAY, TZ, LM_ROOM, now)
    r = get_rollup(conn, 1, TODAY, TZ, LM_ROOM, now)
    return base, find_anomalies(r, base, TZ, NAMES, now)


def test_learning_with_4_days(conn):
    seed_history(conn, 4)
    base = load_baseline(conn, 1, TODAY, TZ, LM_ROOM, at(TODAY, "20:00"))
    assert base.learning and base.days == 4 and base.stats == {}


def test_baseline_stats(conn):
    seed_history(conn, 14)
    base = load_baseline(conn, 1, TODAY, TZ, LM_ROOM, at(TODAY, "12:00"))
    assert base.days == 14 and not base.learning
    assert base.landmark_interval_h["water"] == pytest.approx(3)
    assert base.stats["visits:water"]["median"] == 5
    assert base.stats["active_minutes"]["median"] == pytest.approx(55)
    assert base.usual_room(False, 9) == "office"
    assert base.room_share(True, 9, "office") == (1.0, 14)  # 4 weekend days -> pooled bucket


def test_learning_gives_no_reasons(conn):
    seed_history(conn, 4)
    add_day(conn, 1, TODAY, water=("07:30",), until=at(TODAY, "20:00"))
    assert check(conn, at(TODAY, "20:00"))[1] == []


def test_normal_day_has_no_reasons(conn):
    seed_history(conn, 14)
    add_day(conn, 1, TODAY, until=at(TODAY, "20:00"))
    assert check(conn, at(TODAY, "20:00"))[1] == []


def test_no_water_bowl_since_0910(conn):
    seed_history(conn, 14)
    add_day(conn, 1, TODAY, water=("07:30", "09:10"), until=at(TODAY, "15:30"))
    _, reasons = check(conn, at(TODAY, "15:30"))
    assert reasons == [
        {
            "kind": "no_visit",
            "place": "Water bowl",
            "place_id": "water",
            "since": "09:10",
            "typical_interval": "~3h",
        }
    ]


def test_unusual_location_restless_night_long_away(conn):
    seed_history(conn, 14)
    segs = ROUTINE[:3] + [("13:00", "basement", "room"), ("16:00", "office", "room")] + ROUTINE[4:]
    add_day(conn, 1, TODAY, segments=segs, moving=(("01:00", "01:30"), ("03:00", "03:20")))
    conn.execute(
        'INSERT INTO visits (tag_id, place_id, kind, start, "end") VALUES (1,?,?,?,?)',
        ("away", "away", at(TODAY, "22:30"), at(TODAY, "23:59")),
    )
    _, reasons = check(conn, at(TODAY, "24:00") + 60)
    kinds = {r["kind"]: r for r in reasons}
    assert kinds["unusual_location_for_time"] == {
        "kind": "unusual_location_for_time",
        "room": "Basement",
        "hour": "13:00",
        "usual_room": "Office",
    }
    assert kinds["restless_night"] == {
        "kind": "restless_night",
        "active_minutes": 50,
        "usual_max_minutes": 0,
    }
    assert kinds["long_away"]["minutes"] == 89
```

**Step 2: Run test, verify failure**
Run: `cd box && uv run pytest tests/brain/test_baseline_anomalies.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'wheres_allie.brain.anomalies'`

**Step 3: Implement**
```python
# box/src/wheres_allie/brain/anomalies.py
"""Explainable routine deviations. Behaviour only: reasons never carry health or medical wording."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from wheres_allie.brain.baseline import MIN_DAYS, Baseline
from wheres_allie.brain.rollups import day_bounds

UNUSUAL_SHARE = 0.1  # a room seen in that hour on < 10 % of baseline days is unusual
MIN_ROOM_MINUTES = 20  # ...if the pet spent at least this long there in that hour
MIN_NIGHT_ACTIVE = 10
MIN_AWAY_MINUTES = 30


def _hhmm(ts: float, tz: ZoneInfo) -> str:
    return datetime.fromtimestamp(ts, tz).strftime("%H:%M")


def _interval(hours: float) -> str:
    return f"~{round(hours)}h" if hours >= 1 else f"~{round(hours * 60)}m"


def find_anomalies(
    r: dict, base: Baseline, tz: ZoneInfo, names: dict[str, str], now: float
) -> list[dict]:
    """Reasons why rollup `r` departs from `base`. `names`: room/landmark id -> display name."""
    if base.learning:
        return []
    day = date.fromisoformat(r["date"])
    _, t_end = day_bounds(day, tz)
    until = min(now, t_end)
    reasons: list[dict] = []

    for lm, interval_h in base.landmark_interval_h.items():
        if base.stats[f"visits:{lm}"]["median"] < 2:
            continue
        today = r["landmarks"].get(lm, [])
        ref = max(today) if today else r["first_activity"]
        if ref is not None and until - ref > max(2 * interval_h, interval_h + 1) * 3600:
            reasons.append(
                {
                    "kind": "no_visit",
                    "place": names.get(lm, lm),
                    "place_id": lm,
                    "since": _hhmm(max(today), tz) if today else None,
                    "typical_interval": _interval(interval_h),
                }
            )

    weekend = day.weekday() >= 5
    prev_room = None
    for hour, h in enumerate(r["hours"]):
        room = h["room"]
        if room and room != prev_room and h["room_minutes"] >= MIN_ROOM_MINUTES:
            share, n = base.room_share(weekend, hour, room)
            usual = base.usual_room(weekend, hour)
            if n >= MIN_DAYS and share < UNUSUAL_SHARE and usual:
                reasons.append(
                    {
                        "kind": "unusual_location_for_time",
                        "room": names.get(room, room),
                        "hour": f"{hour:02d}:00",
                        "usual_room": names.get(usual, usual),
                    }
                )
        prev_room = room

    night, p90 = r["night_active_minutes"], base.stats["night_active_minutes"]["p90"]
    if night >= MIN_NIGHT_ACTIVE and night > p90:
        reasons.append(
            {
                "kind": "restless_night",
                "active_minutes": round(night),
                "usual_max_minutes": round(p90),
            }
        )

    away, longest = r["longest_away_minutes"], base.stats["longest_away_minutes"]["max"]
    if away >= MIN_AWAY_MINUTES and away > longest:
        reasons.append(
            {"kind": "long_away", "minutes": round(away), "longest_recent_minutes": round(longest)}
        )
    return reasons
```

**Step 4: Run test, verify pass**
Run: `cd box && uv run pytest tests/brain -q`
Expected: `13 passed`

**Step 5: Commit**
```bash
git add box/src/wheres_allie/brain/anomalies.py box/tests/brain/test_baseline_anomalies.py
git commit -m "feat: explainable routine anomalies (no visit, odd room, restless night, long away)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: `mcp/tools.py` core: pets, fuzzy places, speech helpers, MCP App view hook

**Files:**
- Create: `box/src/wheres_allie/mcp/__init__.py` (empty, if missing)
- Create: `box/src/wheres_allie/mcp/tools.py`
- Create: `box/tests/mcp/conftest.py`
- Test: `box/tests/mcp/test_tools_helpers.py`

**Step 1: Write failing test**
The seeded database used by every MCP test:
```python
# box/tests/mcp/conftest.py
"""Seeded db for MCP tests: the plan-02 fixture home, 14 routine days, and a today with water-bowl
visits only at 07:30 and 09:10 ("no water bowl since 09:10")."""

from datetime import date, timedelta
from pathlib import Path

import pytest
from synth import add_day, at

from wheres_allie.db import connect, migrate
from wheres_allie.home.geometry import detect_rooms
from wheres_allie.home.model import Home
from wheres_allie.home.store import save_home

FIXTURE = Path(__file__).parent.parent / "fixtures" / "home_allie.json"
HOME = Home.model_validate_json(FIXTURE.read_text())
# display names in home_allie.json (plan 02); ids are looked up from the names
OFFICE, KITCHEN, BEDROOM, LOFT = "Office", "Kitchen", "Master bedroom", "Loft"
WATER, BED, BASEMENT = "Water bowl", "Allie's bed", "Basement"
# room name -> room id; landmark name -> landmark vertex id (what visits.place_id holds, plan 03)
ID = {r.name: r.id for r in detect_rooms(HOME)} | {lm.name: f"lm:{lm.id}" for lm in HOME.landmarks}
TODAY = date(2026, 9, 28)  # a Monday
NOW = at(TODAY, "15:30")
ROUTINE = [
    ("00:00", ID[BED], "landmark"),
    ("07:00", ID[OFFICE], "room"),
    ("12:00", ID[KITCHEN], "room"),
    ("13:00", ID[OFFICE], "room"),
    ("18:00", ID[LOFT], "room"),
    ("22:00", ID[BED], "landmark"),
]


def seed(path: Path, history_days: int) -> None:
    conn = connect(path)
    migrate(conn)
    save_home(conn, HOME)
    conn.execute("INSERT OR REPLACE INTO settings VALUES ('tz', 'America/New_York')")
    conn.execute("INSERT INTO pets (id, name) VALUES (1, 'Allie')")
    conn.execute("INSERT INTO tags (id, pet_id, ibeacon_id) VALUES (1, 1, 'iBeacon:allie')")
    for d in range(1, history_days + 1):
        add_day(conn, 1, TODAY - timedelta(days=d), segments=ROUTINE, water_id=ID[WATER])
    add_day(conn, 1, TODAY, ROUTINE, water=("07:30", "09:10"), until=NOW, water_id=ID[WATER])
    # heard 4 s ago, still in the office
    conn.execute(
        "INSERT INTO positions (ts, tag_id, vertex_id, confidence, moving) "
        "VALUES (?, 1, ?, 0.86, 0)",
        (NOW - 4, f"room:{ID[OFFICE]}"),
    )
    conn.commit()
    conn.close()


@pytest.fixture
def db_path(tmp_path) -> Path:
    path = tmp_path / "wa.db"
    seed(path, history_days=14)
    return path


@pytest.fixture
def mcp_server(db_path):
    from wheres_allie.mcp.server import build_mcp

    return build_mcp(lambda: connect(db_path), clock=lambda: NOW)
```
Then create the helper tests:
```python
# box/tests/mcp/test_tools_helpers.py
from datetime import date
from zoneinfo import ZoneInfo

import pytest
from conftest import BED, KITCHEN, NOW, TODAY, WATER
from synth import at

from wheres_allie.db import connect
from wheres_allie.mcp import tools

TZ = ZoneInfo("America/New_York")


@pytest.fixture
def ctx(db_path):
    return tools.Ctx(connect(db_path), TZ, NOW)


def test_say_time(ctx):
    assert tools.say_time(ctx, at(TODAY, "21:58")) == "about 10"
    assert tools.say_time(ctx, at(TODAY, "15:24")) == "3:25"
    assert tools.say_time(ctx, at(TODAY, "09:10"), at=True) == "at 9:10"
    assert tools.say_time(ctx, at(date(2026, 9, 27), "09:00")) == "yesterday at about 9"
    assert tools.say_time(ctx, at(date(2026, 9, 24), "07:40")) == "Thursday at 7:40"


def test_say_minutes_and_the():
    assert [tools.say_minutes(m) for m in (0.5, 1, 25, 60, 250, 270)] == [
        "less than a minute",
        "1 minute",
        "25 minutes",
        "1 hour",
        "4 hours",
        "4.5 hours",
    ]
    assert tools.the("Water bowl") == "the water bowl"
    assert tools.the("Allie's bed") == "Allie's bed"


def test_resolve_pets(ctx):
    assert [p.name for p in tools.resolve_pets(ctx.conn, None)] == ["Allie"]
    assert tools.resolve_pets(ctx.conn, "ALLIE")[0].tag_id == 1
    assert tools.resolve_pets(ctx.conn, "alli")[0].name == "Allie"
    with pytest.raises(tools.Answer, match="I don't know a pet called Rex. I know Allie."):
        tools.resolve_pets(ctx.conn, "Rex")
    ctx.conn.execute("INSERT INTO pets (id, name) VALUES (2, 'Rex')")
    assert [p.name for p in tools.resolve_pets(ctx.conn, "all")] == ["Allie", "Rex"]
    assert [p.name for p in tools.resolve_pets(ctx.conn, None)] == ["Allie", "Rex"]
    assert tools.resolve_pets(ctx.conn, "rex")[0].tag_id is None


@pytest.mark.parametrize(
    "said,name",
    [
        ("her water", WATER),
        ("water bowl", WATER),
        ("bed", BED),
        ("Kitchen", KITCHEN),
        ("the kitchn", KITCHEN),
    ],
)
def test_match_place(ctx, said, name):
    assert tools.match_place(ctx, said).name == name


def test_match_place_unknown(ctx):
    with pytest.raises(tools.Answer, match="I don't know a place called garage"):
        tools.match_place(ctx, "garage")
```

**Step 2: Run test, verify failure**
Run: `cd box && uv run pytest tests/mcp/test_tools_helpers.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'wheres_allie.mcp'` (or `...mcp.tools`)

**Step 3: Implement**
Create an empty `box/src/wheres_allie/mcp/__init__.py` if it doesn't exist. Then create `box/src/wheres_allie/mcp/tools.py` (the tool functions are appended in Tasks 7–10):
```python
"""MCP tool logic (conventions §11): plain functions over a sqlite connection.

`mcp/server.py` wraps these as MCP tools. Every result is a dict with a `speech` hint; every time
in a result is a local ISO-8601 string (inside `app`, plan 04's view, times are unix seconds).
Behaviour and routine only, never health claims.
"""

import difflib
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, time
from functools import cached_property
from zoneinfo import ZoneInfo

from wheres_allie.brain.anomalies import find_anomalies
from wheres_allie.brain.baseline import MIN_DAYS, load_baseline
from wheres_allie.brain.rollups import day_bounds, get_rollup, load_visits, visit_end
from wheres_allie.calibration.labels import create_label
from wheres_allie.db import get_setting
from wheres_allie.home.geometry import Room
from wheres_allie.home.graph import Graph
from wheres_allie.home.model import Home
from wheres_allie.home.pathing import home_context

try:  # the MCP App view payload (plan 04)
    from wheres_allie.mcp.app_resource import app_view_for_position, app_view_for_range
except ImportError:  # plan 04 not merged yet: no floorplan view, voice answers still work

    def app_view_for_position(conn, tag_ids):
        return None

    def app_view_for_range(conn, tag_ids, t0, t1):
        return None


AWAY_AFTER_S = 120  # design §7: tag unheard this long = away
LOW_CONFIDENCE = 0.5
ALL_PETS = {"all", "everyone", "both", "all pets"}


class Answer(Exception):
    """A spoken reply that ends a tool early (unknown pet or place, no tag, ...)."""

    def __init__(self, speech: str):
        super().__init__(speech)
        self.speech = speech


@dataclass
class Pet:
    id: int
    name: str
    tag_id: int | None


@dataclass
class Place:
    kind: str  # "room" | "landmark"
    id: str
    name: str
    vertex_id: str


@dataclass
class Ctx:
    conn: sqlite3.Connection
    tz: ZoneInfo
    now: float
    home: Home = field(init=False)
    rooms: list[Room] = field(init=False)
    graph: Graph = field(init=False)

    def __post_init__(self):
        self.home, self.rooms, self.graph = home_context(self.conn)

    @cached_property
    def lm_room(self) -> dict[str, str | None]:
        """landmark vertex id ("lm:<id>", the visits.place_id of a landmark) -> room id."""
        return {vid: v.room_id for vid, v in self.graph.vertices.items() if v.kind == "landmark"}

    @cached_property
    def names(self) -> dict[str, str]:
        """room id / landmark id / vertex id / floor id -> display name."""
        out = {f.id: f.name for f in self.home.floors}
        out |= {r.id: r.name for r in self.rooms} | {lm.id: lm.name for lm in self.home.landmarks}
        return out | {vid: v.name for vid, v in self.graph.vertices.items()}

    def today(self) -> date:
        return datetime.fromtimestamp(self.now, self.tz).date()


def load_tz(conn: sqlite3.Connection, default: str) -> ZoneInfo:
    return ZoneInfo(get_setting(conn, "tz") or default)


# ---------- speech helpers ----------


def iso(ctx: Ctx, ts: float | None) -> str | None:
    return None if ts is None else datetime.fromtimestamp(ts, ctx.tz).isoformat(timespec="seconds")


def say_time(ctx: Ctx, ts: float, at: bool = False) -> str:
    """'about 10', '3:25', 'yesterday at about 9', 'Monday at 7:40' (5-minute rounding).
    `at=True` prefixes today's times with 'at'."""
    t = datetime.fromtimestamp(round(ts / 300) * 300, ctx.tz)
    clock = f"about {t.hour % 12 or 12}" if t.minute == 0 else f"{t.hour % 12 or 12}:{t.minute:02d}"
    days_ago = (ctx.today() - datetime.fromtimestamp(ts, ctx.tz).date()).days
    if days_ago <= 0:
        return f"at {clock}" if at else clock
    return f"{'yesterday' if days_ago == 1 else t.strftime('%A')} at {clock}"


def say_minutes(m: float) -> str:
    if m < 1:
        return "less than a minute"
    if m < 60:
        return f"{round(m)} minute{'s' if round(m) != 1 else ''}"
    h = round(m / 30) / 2
    return f"{h:g} hour{'s' if h != 1 else ''}"


def the(name: str) -> str:
    """'Water bowl' -> 'the water bowl'; "Allie's bed" stays as is."""
    return name if "'" in name else f"the {name.lower()}"


def say_day(ctx: Ctx, day: date) -> str:
    return "today" if day == ctx.today() else f"on {day.strftime('%A')}"


# ---------- resolution ----------


def resolve_pets(conn: sqlite3.Connection, pet: str | None) -> list[Pet]:
    """None = the only pet (or all of them); 'all' = every pet; else a fuzzy name match."""
    pets = [
        Pet(*r)
        for r in conn.execute(
            "SELECT p.id, p.name, min(t.id) FROM pets p LEFT JOIN tags t ON t.pet_id = p.id "
            "GROUP BY p.id ORDER BY p.id"
        )
    ]  # ponytail: first tag per pet; one collar tag each
    if not pets:
        raise Answer("No pets are set up yet. Add one in the Where's Allie app.")
    if pet is None or not pet.strip() or pet.strip().lower() in ALL_PETS:
        return pets
    by_name = {p.name.lower(): p for p in pets}
    hit = difflib.get_close_matches(pet.strip().lower(), by_name, n=1, cutoff=0.6)
    if not hit:
        raise Answer(
            f"I don't know a pet called {pet}. I know {' and '.join(p.name for p in pets)}."
        )
    return [by_name[hit[0]]]


def _norm(s: str) -> str:
    s = re.sub(r"'s\b", "", s.lower().replace("_", " "))
    words = re.sub(r"[^a-z0-9 ]", " ", s).split()
    while words and words[0] in {"the", "her", "his", "its", "my", "their"}:
        words = words[1:]
    return " ".join(words)


def match_place(ctx: Ctx, query: str) -> Place:
    """Fuzzy-match a spoken place against landmark names/types and room names."""
    keys: dict[str, Place] = {}
    for r in ctx.rooms:
        if r.name != "Unnamed room":
            keys.setdefault(_norm(r.name), Place("room", r.id, r.name, f"room:{r.id}"))
    for lm in ctx.home.landmarks:
        p = Place("landmark", lm.id, lm.name, f"lm:{lm.id}")
        keys[_norm(lm.name)] = p
        keys.setdefault(_norm(lm.type), p)
    q = _norm(query)
    if q in keys:
        return keys[q]
    partial = sorted((k for k in keys if q and (q in k or k in q)), key=len)
    close = difflib.get_close_matches(q, keys, n=1, cutoff=0.6)
    if partial or close:
        return keys[(partial or close)[0]]
    known = ", ".join(sorted({p.name for p in keys.values()})[:8])
    raise Answer(f"I don't know a place called {query}. I know: {known}.")


def parse_day(ctx: Ctx, day: str | None) -> date:
    if not day:
        return ctx.today()
    try:
        d = date.fromisoformat(day)
    except ValueError:
        raise Answer(f"I didn't understand the date {day}. Use a date like 2026-09-28.") from None
    if d > ctx.today():
        raise Answer("That day hasn't happened yet.")
    return d

def run(conn: sqlite3.Connection, tz: ZoneInfo, now: float, fn, pet: str | None, **kw) -> dict:
    """Resolve `pet` and call a tool once per pet; several pets -> {"pets": [...], "speech"}."""
    ctx = Ctx(conn, tz, now)
    results = [fn(ctx, p, **kw) for p in resolve_pets(conn, pet)]
    if len(results) == 1:
        return results[0]
    return {"pets": results, "speech": " ".join(r["speech"] for r in results)}
```

**Step 4: Run test, verify pass**
Run: `cd box && uv run pytest tests/mcp/test_tools_helpers.py -q`
Expected: `9 passed`

**Step 5: Commit**
```bash
git add box/src/wheres_allie/mcp/__init__.py box/src/wheres_allie/mcp/tools.py box/tests/mcp/conftest.py box/tests/mcp/test_tools_helpers.py
git commit -m "feat: MCP tool core (pet/place resolution, speech, MCP App view hook)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: `where_is` + `mcp/server.py` `build_mcp` + floorplan UI resource

**Files:**
- Modify: `box/src/wheres_allie/mcp/tools.py`
- Create: `box/src/wheres_allie/mcp/server.py`
- Test: `box/tests/mcp/test_contract.py`

**Step 1: Write failing test**
The contract tests call every tool through the SDK's in-memory client (`mcp.Client(server)`):
```python
import pytest
from conftest import BASEMENT, BED, BEDROOM, ID, KITCHEN, NOW, OFFICE, WATER, seed
from mcp import Client

from wheres_allie.db import connect
from wheres_allie.mcp.server import FLOORPLAN_URI, build_mcp
from wheres_allie.mcp.tools import the

TOOLS = {"where_is", "day_summary", "timeline", "last_visit", "anything_unusual", "mark_location"}


async def call(server, name: str, args: dict | None = None) -> dict:
    async with Client(server) as c:
        r = await c.call_tool(name, args or {})
    assert not r.is_error, r.content
    assert r.content[0].text == r.structured_content["speech"]
    return r.structured_content


def assert_app_view(r: dict) -> None:
    """Plan 04's MCP App view: None until mcp/app_resource.py exists."""
    assert r["app"] is None or r["app"]["view"] in {"position", "path"}


# ---- where_is (Task 7)


async def test_where_is(mcp_server):
    r = await call(mcp_server, "where_is")
    assert (r["pet"], r["place"], r["place_kind"]) == ("Allie", OFFICE, "room")
    assert (r["room"], r["floor"], r["moving"], r["confidence"]) == (OFFICE, BASEMENT, False, 0.86)
    assert r["since"] == "2026-09-28T13:00:00-04:00"
    assert r["speech"] == f"Allie has been in {the(OFFICE)} since about 1, resting."
    assert_app_view(r)


async def test_where_is_away_after_120s(tmp_path):
    seed(tmp_path / "a.db", history_days=0)
    srv = build_mcp(lambda: connect(tmp_path / "a.db"), clock=lambda: NOW + 3600)
    r = await call(srv, "where_is")
    assert (r["place"], r["place_kind"], r["room"]) == ("away", "away", None)
    assert r["speech"] == (
        "I haven't heard Allie's tag since 3:30. "
        "Allie may be outside, or the tag battery may be low."
    )


async def test_floorplan_ui_resource(mcp_server):
    async with Client(mcp_server) as c:
        res = await c.read_resource(FLOORPLAN_URI)
    assert res.contents[0].mime_type == "text/html;profile=mcp-app"
```

**Step 2: Run test, verify failure**
Run: `cd box && uv run pytest tests/mcp/test_contract.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'wheres_allie.mcp.server'`

**Step 3: Implement**
Append to `box/src/wheres_allie/mcp/tools.py`:
```python
# ---------- tools ----------


def _tag(pet: Pet) -> int:
    if pet.tag_id is None:
        raise Answer(f"{pet.name} doesn't have a tag set up yet.")
    return pet.tag_id


def where_is(ctx: Ctx, pet: Pet) -> dict:
    tag = _tag(pet)
    row = ctx.conn.execute(
        "SELECT ts, vertex_id, confidence, moving FROM positions WHERE tag_id = ? "
        "ORDER BY ts DESC LIMIT 1",
        (tag,),
    ).fetchone()
    if row is None:
        raise Answer(f"I haven't heard {pet.name}'s tag yet.")
    ts, vid, confidence, moving = row
    v = ctx.graph.vertices.get(vid)
    if v is None or ctx.now - ts > AWAY_AFTER_S:
        heard = (
            ctx.conn.execute(
                "SELECT max(ts) FROM positions WHERE tag_id = ? AND vertex_id != 'away'", (tag,)
            ).fetchone()[0]
            or ts
        )
        return {
            "pet": pet.name,
            "place": "away",
            "place_kind": "away",
            "room": None,
            "floor": None,
            "since": iso(ctx, heard),
            "moving": None,
            "confidence": confidence,
            "app": app_view_for_position(ctx.conn, [tag]),
            "speech": f"I haven't heard {pet.name}'s tag since {say_time(ctx, heard)}. "
            f"{pet.name} may be outside, or the tag battery may be low.",
        }
    last = ctx.conn.execute(
        'SELECT kind, start, "end" FROM visits WHERE tag_id = ? ORDER BY start DESC LIMIT 1',
        (tag,),
    ).fetchone()
    since = last[1] if last and last[2] is None and last[0] != "away" else ts
    room = ctx.names.get(v.room_id) if v.room_id else None
    floor = ctx.names.get(v.floor_id)
    state = {None: "", 0: ", resting", 1: ", moving around"}[moving]
    if v.kind == "landmark":
        where = f"at {the(v.name)}" + (f" in {the(room)}" if room else "")
    elif v.kind == "room":
        where = f"in {the(v.name)}"
    else:
        where = f"near {the(v.name)}"
    speech = f"{pet.name} has been {where} since {say_time(ctx, since)}{state}."
    if v.kind in ("door", "stairs"):
        speech = f"{pet.name} is on the move, {where} right now."
    if confidence < LOW_CONFIDENCE:
        speech += " I'm not completely sure, though."
    return {
        "pet": pet.name,
        "place": v.name,
        "place_kind": v.kind,
        "room": room,
        "floor": floor,
        "since": iso(ctx, since),
        "moving": None if moving is None else bool(moving),
        "confidence": round(confidence, 2),
        "app": app_view_for_position(ctx.conn, [tag]),
        "speech": speech,
    }
```

Create `box/src/wheres_allie/mcp/server.py`:
```python
"""MCP server (conventions §11): Streamable HTTP, stateless, JSON responses, mounted at /mcp.

LAN callers need `Authorization: Bearer <lan token>`. Relay-forwarded requests enter through
`handle_mcp_request`, which calls the MCP ASGI app in-process and skips the token check.
"""

import sqlite3
import time
from collections.abc import Callable

from mcp.server.apps import Apps
from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult, TextContent, ToolAnnotations

from wheres_allie.mcp import tools

FLOORPLAN_URI = "ui://wheres-allie/floorplan"
GUIDANCE = (
    "Answers are about the pet's location, routine and behaviour only. Never make medical or "
    "health claims, diagnoses or guesses about illness; if asked, suggest asking a vet. "
    "The `speech` field is a short natural reply you can say as is."
)
READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=False)

try:
    from wheres_allie.mcp.app_resource import floorplan_html  # plan 04
except ImportError:  # plan 04 not merged yet

    def floorplan_html() -> str:
        return "<!doctype html><meta charset=utf-8><p>Floorplan view is not built yet.</p>"


def build_mcp(
    connect: Callable[[], sqlite3.Connection],
    tz_default: str = "America/New_York",
    clock: Callable[[], float] = time.time,
) -> MCPServer:
    """The MCP server. `connect()` returns the db connection a tool call uses; sync tools run in
    worker threads, so it must allow that (the app passes its `check_same_thread=False` conn)."""

    def call(fn, pet: str | None, **kw) -> CallToolResult:
        conn = connect()
        try:
            data = tools.run(conn, tools.load_tz(conn, tz_default), clock(), fn, pet, **kw)
        except tools.Answer as a:
            return CallToolResult(
                content=[TextContent(type="text", text=a.speech)],
                structured_content={"speech": a.speech},
                is_error=True,
            )
        return CallToolResult(
            content=[TextContent(type="text", text=data["speech"])], structured_content=data
        )

    apps = Apps()

    @apps.tool(
        resource_uri=FLOORPLAN_URI,
        annotations=READ_ONLY,
        description=(
            f"Where the pet is right now: room, landmark (bed, bowl, couch...), floor, since when, "
            f"moving or resting, and confidence. Says so if the tag hasn't been heard. {GUIDANCE}"
        ),
    )
    def where_is(pet: str | None = None) -> CallToolResult:
        return call(tools.where_is, pet)

    apps.add_html_resource(
        FLOORPLAN_URI,
        floorplan_html(),
        name="floorplan",
        title="Floorplan",
        description="The home floorplan with the pet's position or path.",
    )
    srv = MCPServer("wheres-allie", title="Where's Allie", instructions=GUIDANCE, extensions=[apps])

    return srv
```

**Step 4: Run test, verify pass**
Run: `cd box && uv run pytest tests/mcp -q`
Expected: `12 passed`

**Step 5: Commit**
```bash
git add box/src/wheres_allie/mcp/tools.py box/src/wheres_allie/mcp/server.py box/tests/mcp/test_contract.py
git commit -m "feat: where_is MCP tool with floorplan UI resource" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: `day_summary` + `timeline` (with the `from` argument)

**Files:**
- Modify: `box/src/wheres_allie/mcp/tools.py`
- Modify: `box/src/wheres_allie/mcp/server.py`
- Test: `box/tests/mcp/test_contract.py`

**Step 1: Write failing test**
Append to `box/tests/mcp/test_contract.py`:
```python
# ---- day_summary + timeline (Task 8)


async def test_day_summary(mcp_server):
    r = await call(mcp_server, "day_summary", {"pet": "allie"})
    assert r["date"] == "2026-09-28"
    assert r["rooms"][:2] == [{"room": OFFICE, "minutes": 444}, {"room": BEDROOM, "minutes": 420}]
    water = next(x for x in r["landmarks"] if x["name"] == WATER)
    assert water["visits"] == 2 and water["last"] == "2026-09-28T09:10:00-04:00"
    assert r["active_minutes"] == 25
    assert r["notable"][:2] == [
        f"Was mostly in {the(OFFICE)}, for 7.5 hours",
        f"Made 2 trips to {the(WATER)}",
    ]
    assert r["notable"][2].startswith(f"Had a long stay at {the(BED)} from")
    assert r["speech"].startswith(f"Today, Allie was mostly in {the(OFFICE)}, for 7.5 hours, made")
    assert_app_view(r)


async def test_timeline_window(mcp_server):
    r = await call(mcp_server, "timeline", {"from": "09:00", "to": "12:30"})
    assert [i["place"] for i in r["items"]] == [OFFICE, WATER, OFFICE, KITCHEN]
    assert r["items"][1] == {
        "start": "2026-09-28T09:10:00-04:00",
        "end": "2026-09-28T09:13:00-04:00",
        "kind": "landmark",
        "place": WATER,
    }
    assert r["speech"] == (
        f"Between about 9 and 12:30, Allie went to {the(OFFICE)}, "
        f"{the(WATER)}, {the(OFFICE)} and {the(KITCHEN)}."
    )
    assert_app_view(r)
```

**Step 2: Run test, verify failure**
Run: `cd box && uv run pytest tests/mcp/test_contract.py -q`
Expected: FAIL: the 2 new tests fail with `AssertionError` (the tools are not registered yet, so `r.is_error` is true)

**Step 3: Implement**
Append to `box/src/wheres_allie/mcp/tools.py`:
```python
def _visits(ctx: Ctx, tag: int, t0: float, t1: float) -> list[tuple]:
    return load_visits(ctx.conn, tag, t0, t1, ctx.now)


def day_summary(ctx: Ctx, pet: Pet, day: str | None = None) -> dict:
    tag, d = _tag(pet), parse_day(ctx, day)
    r = get_rollup(ctx.conn, tag, d, ctx.tz, ctx.lm_room, ctx.now)
    t0, t1 = day_bounds(d, ctx.tz)
    rooms = [{"room": ctx.names.get(k, k), "minutes": round(m)} for k, m in r["rooms"].items()]
    lms = sorted(
        (
            {"name": ctx.names.get(k, k), "visits": len(v), "last": iso(ctx, max(v))}
            for k, v in r["landmarks"].items()
        ),
        key=lambda x: -x["visits"],
    )
    notable = []
    if rooms:
        notable.append(
            f"Was mostly in {the(rooms[0]['room'])}, for {say_minutes(rooms[0]['minutes'])}"
        )
    if lms:
        n = lms[0]["visits"]
        notable.append(f"Made {n} trip{'s' if n != 1 else ''} to {the(lms[0]['name'])}")
    long_stays = [
        (min(e or ctx.now, t1) - max(s, t0), p, s, e)
        for p, k, s, e in _visits(ctx, tag, t0, t1)
        if k == "landmark"
    ]
    if long_stays and max(long_stays)[0] >= 3600:
        _, p, s, e = max(long_stays)
        notable.append(
            f"Had a long stay at {the(ctx.names.get(p, p))} from "
            f"{say_time(ctx, s)} to {say_time(ctx, e) if e else 'now'}"
        )
    if notable:
        phrases = [n[0].lower() + n[1:] for n in notable]
        body = phrases[0] if len(phrases) == 1 else ", ".join(phrases[:-1]) + " and " + phrases[-1]
        speech = f"{say_day(ctx, d).capitalize()}, {pet.name} {body}."
    else:
        speech = f"I don't have any activity for {pet.name} {say_day(ctx, d)}."
    return {
        "pet": pet.name,
        "date": d.isoformat(),
        "rooms": rooms,
        "landmarks": lms,
        "active_minutes": round(r["active_minutes"]),
        "notable": notable,
        "app": app_view_for_range(ctx.conn, [tag], t0, min(t1, ctx.now)),
        "speech": speech,
    }


def _hhmm(ctx: Ctx, d: date, hhmm: str | None, default: float) -> float:
    if not hhmm:
        return default
    try:
        return datetime.combine(d, time.fromisoformat(hhmm), ctx.tz).timestamp()
    except ValueError:
        raise Answer(f"I didn't understand the time {hhmm}. Use a time like 14:30.") from None


def timeline(
    ctx: Ctx, pet: Pet, day: str | None = None, from_: str | None = None, to: str | None = None
) -> dict:
    tag, d = _tag(pet), parse_day(ctx, day)
    t0, t1 = day_bounds(d, ctx.tz)
    a, b = _hhmm(ctx, d, from_, t0), min(_hhmm(ctx, d, to, t1), ctx.now)
    items = [
        {
            "start": iso(ctx, s),
            "end": iso(ctx, e),
            "kind": k,
            "place": "away" if k == "away" else ctx.names.get(p, p),
        }
        for p, k, s, e in _visits(ctx, tag, a, b)
    ]
    places: list[str] = []
    for it in items:
        if it["kind"] in ("room", "landmark") and (not places or places[-1] != it["place"]):
            places.append(it["place"])
    if places:
        shown = [the(p) for p in places[:6]]
        more = " and more" if len(places) > 6 else ""
        listed = shown[0] if len(shown) == 1 else ", ".join(shown[:-1]) + " and " + shown[-1]
        speech = (
            f"Between {say_time(ctx, a)} and {say_time(ctx, b)}, {pet.name} went to {listed}{more}."
        )
    else:
        speech = f"I don't have any visits for {pet.name} in that time."
    return {
        "pet": pet.name,
        "date": d.isoformat(),
        "items": items,
        "app": app_view_for_range(ctx.conn, [tag], a, b),
        "speech": speech,
    }
```
In `box/src/wheres_allie/mcp/server.py`, add these imports:
```python
import inspect
from typing import Annotated

from pydantic import Field
```
Inside `build_mcp`, insert this directly **before** the `apps.add_html_resource(` call. Apps tools must be registered before `MCPServer(..., extensions=[apps])` is built.
```python
    @apps.tool(
        resource_uri=FLOORPLAN_URI,
        annotations=READ_ONLY,
        description=(
            f"What the pet did on a day: minutes per room, landmark visits, active minutes and the "
            f"most notable facts. `date` is YYYY-MM-DD (default today). {GUIDANCE}"
        ),
    )
    def day_summary(pet: str | None = None, date: str | None = None) -> CallToolResult:
        return call(tools.day_summary, pet, day=date)

    def timeline(
        pet: str | None = None, date: str | None = None, to: str | None = None, **kw
    ) -> CallToolResult:
        return call(tools.timeline, pet, day=date, from_=kw.get("from"), to=to)

    # `from` is a Python keyword: publish it via the signature; the SDK passes it in **kw
    timeline.__signature__ = inspect.Signature(
        [
            inspect.Parameter(n, inspect.Parameter.KEYWORD_ONLY, default=None, annotation=a)
            for n, a in (
                ("pet", str | None),
                ("date", str | None),
                ("from_", Annotated[str | None, Field(alias="from")]),
                ("to", str | None),
            )
        ],
        return_annotation=CallToolResult,
    )
    apps.tool(
        resource_uri=FLOORPLAN_URI,
        annotations=READ_ONLY,
        description=(
            f"Ordered visits and transits for a day, optionally between `from` and `to` (HH:MM, "
            f"local time). {GUIDANCE}"
        ),
    )(timeline)
```

**Step 4: Run test, verify pass**
Run: `cd box && uv run pytest tests/mcp -q`
Expected: `14 passed`

**Step 5: Commit**
```bash
git add box/src/wheres_allie/mcp/tools.py box/src/wheres_allie/mcp/server.py box/tests/mcp/test_contract.py
git commit -m "feat: day_summary and timeline MCP tools" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: `last_visit` + `mark_location`

**Files:**
- Modify: `box/src/wheres_allie/mcp/tools.py`
- Modify: `box/src/wheres_allie/mcp/server.py`
- Test: `box/tests/mcp/test_contract.py`

**Step 1: Write failing test**
Append to `box/tests/mcp/test_contract.py`:
```python
# ---- last_visit + mark_location (Task 9)


async def test_last_visit_fuzzy(mcp_server):
    r = await call(mcp_server, "last_visit", {"place": "her water"})
    assert (r["place"], r["minutes"]) == (WATER, 3)
    assert r["last_start"] == "2026-09-28T09:10:00-04:00"
    assert r["speech"] == f"Allie was last at {the(WATER)} at 9:10, for 3 minutes."


async def test_last_visit_ongoing_room(mcp_server):
    r = await call(mcp_server, "last_visit", {"place": "office"})
    assert r["last_end"] is None and r["minutes"] == 150
    assert r["speech"] == f"Allie is at {the(OFFICE)} right now, since about 1."


async def test_mark_location_writes_voice_label(mcp_server, db_path):
    r = await call(mcp_server, "mark_location", {"place": "bed"})
    assert (r["place"], r["vertex_id"]) == (BED, ID[BED])
    assert r["speech"] == f"Got it. I've noted that Allie is at {the(BED)} right now."
    row = connect(db_path).execute("SELECT vertex_id, source, ts_end FROM labels").fetchone()
    assert tuple(row) == (ID[BED], "voice", NOW)
```

**Step 2: Run test, verify failure**
Run: `cd box && uv run pytest tests/mcp/test_contract.py -q`
Expected: FAIL: the 3 new tests fail with `AssertionError` (tools not registered yet)

**Step 3: Implement**
Append to `box/src/wheres_allie/mcp/tools.py`:
```python
def last_visit(ctx: Ctx, pet: Pet, place: str) -> dict:
    tag, p = _tag(pet), match_place(ctx, place)
    ids = [p.vertex_id if p.kind == "landmark" else p.id]  # visits.place_id (plan 03)
    if p.kind == "room":  # a room also counts visits to the landmarks inside it
        ids += [lm for lm, room in ctx.lm_room.items() if room == p.id]
    row = ctx.conn.execute(
        f"SELECT start, \"end\" FROM visits WHERE tag_id = ? AND kind IN ('room', 'landmark') "
        f"AND place_id IN ({','.join('?' * len(ids))}) ORDER BY start DESC LIMIT 1",
        (tag, *ids),
    ).fetchone()
    out = {"pet": pet.name, "place": p.name, "last_start": None, "last_end": None, "minutes": None}
    if row is None:
        return out | {"speech": f"I haven't seen {pet.name} at {the(p.name)} yet."}
    start, end = row[0], visit_end(ctx.conn, tag, *row)
    minutes = round(((end or ctx.now) - start) / 60)
    if end is None:
        speech = f"{pet.name} is at {the(p.name)} right now, since {say_time(ctx, start)}."
    else:
        speech = (
            f"{pet.name} was last at {the(p.name)} {say_time(ctx, start, at=True)}, "
            f"for {say_minutes(minutes)}."
        )
    return out | {
        "last_start": iso(ctx, start),
        "last_end": iso(ctx, end),
        "minutes": minutes,
        "speech": speech,
    }


def mark_location(ctx: Ctx, pet: Pet, place: str) -> dict:
    tag, p = _tag(pet), match_place(ctx, place)
    create_label(ctx.conn, tag, p.vertex_id, "voice", ts_start=ctx.now - 30, ts_end=ctx.now)
    return {
        "pet": pet.name,
        "place": p.name,
        "vertex_id": p.vertex_id,
        "speech": f"Got it. I've noted that {pet.name} is at {the(p.name)} right now.",
    }
```
Inside `build_mcp` in `server.py`, insert this directly **before** `return srv`:
```python
    @srv.tool(
        annotations=READ_ONLY,
        description=(
            f"When the pet was last at a place (a landmark like 'water bowl' or 'bed', or a room) "
            f"and for how long. {GUIDANCE}"
        ),
    )
    def last_visit(place: str, pet: str | None = None) -> CallToolResult:
        return call(tools.last_visit, pet, place=place)

    @srv.tool(
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False),
        description=(
            "Record where the pet is right now (e.g. 'Allie is on her bed') to improve location "
            "accuracy. Confirms the matched place name."
        ),
    )
    def mark_location(place: str, pet: str | None = None) -> CallToolResult:
        return call(tools.mark_location, pet, place=place)
```

**Step 4: Run test, verify pass**
Run: `cd box && uv run pytest tests/mcp -q`
Expected: `17 passed`

**Step 5: Commit**
```bash
git add box/src/wheres_allie/mcp/tools.py box/src/wheres_allie/mcp/server.py box/tests/mcp/test_contract.py
git commit -m "feat: last_visit and mark_location MCP tools" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: `anything_unusual` + full contract (6 tools, guidance, spoken errors)

**Files:**
- Modify: `box/src/wheres_allie/mcp/tools.py`
- Modify: `box/src/wheres_allie/mcp/server.py`
- Test: `box/tests/mcp/test_contract.py`

**Step 1: Write failing test**
Append to `box/tests/mcp/test_contract.py`. This includes the design's "no water bowl since 09:10" day, the learning state, the full tool list with UI `_meta` and the no-medical guidance, and spoken errors.
```python
# ---- anything_unusual + the whole surface (Task 10)


async def test_anything_unusual_no_water_since_0910(mcp_server):
    r = await call(mcp_server, "anything_unusual")
    assert (r["status"], r["days_of_data"]) == ("unusual", 14)
    assert r["reasons"] == [
        {
            "kind": "no_visit",
            "place": WATER,
            "place_id": ID[WATER],
            "since": "09:10",
            "typical_interval": "~3h",
        }
    ]
    assert r["speech"] == (
        f"Allie hasn't been to {the(WATER)} since 09:10; usually it's about every 3h."
    )


async def test_anything_unusual_learning(tmp_path):
    seed(tmp_path / "l.db", history_days=3)
    srv = build_mcp(lambda: connect(tmp_path / "l.db"), clock=lambda: NOW)
    r = await call(srv, "anything_unusual")
    assert (r["status"], r["reasons"], r["days_of_data"]) == ("learning", [], 3)
    assert r["speech"] == "I'm still learning Allie's routine: 3 of 5 days so far."


async def test_lists_six_tools_with_guidance(mcp_server):
    async with Client(mcp_server) as c:
        listed = {t.name: t for t in (await c.list_tools()).tools}
    assert set(listed) == TOOLS
    for name in ("where_is", "day_summary", "timeline"):
        assert listed[name].meta["ui"]["resourceUri"] == FLOORPLAN_URI
    for name in TOOLS - {"mark_location"}:
        assert "Never make medical or health claims" in listed[name].description
    assert set(listed["timeline"].input_schema["properties"]) == {"pet", "date", "from", "to"}


@pytest.mark.parametrize(
    "name,args,said",
    [
        ("where_is", {"pet": "Rex"}, "I don't know a pet called Rex. I know Allie."),
        ("last_visit", {"place": "garage"}, "I don't know a place called garage."),
        ("day_summary", {"date": "2099-01-01"}, "That day hasn't happened yet."),
        ("timeline", {"from": "nine"}, "I didn't understand the time nine."),
    ],
)
async def test_spoken_errors(mcp_server, name, args, said):
    async with Client(mcp_server) as c:
        r = await c.call_tool(name, args)
    assert r.is_error and r.content[0].text.startswith(said)
```

**Step 2: Run test, verify failure**
Run: `cd box && uv run pytest tests/mcp/test_contract.py -q`
Expected: FAIL: the two `anything_unusual` tests and `test_lists_six_tools_with_guidance` fail with `AssertionError`

**Step 3: Implement**
Append to `box/src/wheres_allie/mcp/tools.py`:
```python
def _reason_speech(pet: str, r: dict) -> str:
    if r["kind"] == "no_visit":
        since = f"since {r['since']}" if r["since"] else "today"
        return (
            f"{pet} hasn't been to {the(r['place'])} {since}; "
            f"usually it's about every {r['typical_interval'].lstrip('~')}."
        )
    if r["kind"] == "unusual_location_for_time":
        return (
            f"{pet} spent time in {the(r['room'])} around {r['hour']}, "
            f"which is unusual; at that time it's usually {the(r['usual_room'])}."
        )
    if r["kind"] == "restless_night":
        return (
            f"{pet} was more active than usual overnight: {r['active_minutes']} active minutes "
            f"between midnight and 5, versus up to {r['usual_max_minutes']} normally."
        )
    return (
        f"{pet}'s tag was out of range for {say_minutes(r['minutes'])}, "
        f"longer than any recent absence."
    )


def anything_unusual(ctx: Ctx, pet: Pet, day: str | None = None) -> dict:
    tag, d = _tag(pet), parse_day(ctx, day)
    base = load_baseline(ctx.conn, tag, d, ctx.tz, ctx.lm_room, ctx.now)
    r = get_rollup(ctx.conn, tag, d, ctx.tz, ctx.lm_room, ctx.now)
    reasons = find_anomalies(r, base, ctx.tz, ctx.names, ctx.now)
    if base.learning:
        status = "learning"
        speech = f"I'm still learning {pet.name}'s routine: {base.days} of {MIN_DAYS} days so far."
    elif reasons:
        status, speech = "unusual", " ".join(_reason_speech(pet.name, x) for x in reasons)
    else:
        status = "normal"
        speech = f"Nothing unusual {say_day(ctx, d)}. {pet.name}'s routine looks normal."
    return {
        "pet": pet.name,
        "date": d.isoformat(),
        "status": status,
        "reasons": reasons,
        "days_of_data": base.days,
        "speech": speech,
    }
```
Inside `build_mcp` in `server.py`, insert directly **before** `return srv`:
```python
    @srv.tool(
        annotations=READ_ONLY,
        description=(
            f"Whether the pet's day departs from its usual routine (missed bowl visits, unusual "
            f"room for the time, restless night, long time out of range). Status is 'normal', "
            f"'unusual' or 'learning' (fewer than 5 days of data). {GUIDANCE}"
        ),
    )
    def anything_unusual(pet: str | None = None, date: str | None = None) -> CallToolResult:
        return call(tools.anything_unusual, pet, day=date)
```

**Step 4: Run test, verify pass**
Run: `cd box && uv run pytest tests/brain tests/mcp -q`
Expected: `37 passed`

**Step 5: Commit**
```bash
git add box/src/wheres_allie/mcp/tools.py box/src/wheres_allie/mcp/server.py box/tests/mcp/test_contract.py
git commit -m "feat: anything_unusual MCP tool; full six-tool contract" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: `/mcp` mount, LAN token guard, `handle_mcp_request` for relaylink

**Files:**
- Modify: `box/src/wheres_allie/mcp/server.py`
- Test: `box/tests/mcp/test_http.py`

**Step 1: Write failing test**
```python
# box/tests/mcp/test_http.py
import contextlib
import json

import httpx
from conftest import NOW
from fastapi import FastAPI

from wheres_allie.db import connect
from wheres_allie.mcp.server import build_mcp, ensure_lan_token, handle_mcp_request, mount_mcp

HDRS = {
    "accept": "application/json, text/event-stream",
    "content-type": "application/json",
    "mcp-protocol-version": "2025-11-25",
}
CALL = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {"name": "where_is", "arguments": {}},
}


@contextlib.asynccontextmanager
async def running_app(db_path):
    """A bare FastAPI app with /mcp mounted and the MCP session manager running."""
    srv = build_mcp(lambda: connect(db_path), clock=lambda: NOW)
    app = FastAPI()
    mount_mcp(app, srv, lan_token=lambda: "s3cret")
    async with srv.session_manager.run():  # entered in the test's own task (anyio scopes)
        yield app


async def post(app, headers):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://wheres-allie.local") as c:
        return await c.post("/mcp", json=CALL, headers=headers)


async def test_401_without_token(db_path):
    async with running_app(db_path) as app:
        assert (await post(app, HDRS)).status_code == 401
        assert (await post(app, HDRS | {"authorization": "Bearer nope"})).status_code == 401


async def test_tool_call_with_token(db_path):
    async with running_app(db_path) as app:
        r = await post(app, HDRS | {"authorization": "Bearer s3cret"})
    assert r.status_code == 200
    assert r.json()["result"]["structuredContent"]["place"] == "Office"


async def test_relay_path_skips_token(db_path):
    async with running_app(db_path):
        status, headers, body = await handle_mcp_request(
            "POST",
            "/mcp",
            HDRS | {"authorization": "Bearer relay-token"},
            json.dumps(CALL).encode(),
        )
        assert (await handle_mcp_request("POST", "/other", {}, b""))[0] == 404
    assert status == 200 and headers["content-type"].startswith("application/json")
    assert json.loads(body)["result"]["structuredContent"]["pet"] == "Allie"


def test_ensure_lan_token_generates_once_and_env_wins(db_path):
    conn = connect(db_path)
    token = ensure_lan_token(conn)
    assert len(token) >= 24 and ensure_lan_token(conn) == token
    assert ensure_lan_token(conn, "from-env") == "from-env" == ensure_lan_token(conn)
```

**Step 2: Run test, verify failure**
Run: `cd box && uv run pytest tests/mcp/test_http.py -q`
Expected: FAIL with `ImportError: cannot import name 'handle_mcp_request' from 'wheres_allie.mcp.server'`

**Step 3: Implement**
In `box/src/wheres_allie/mcp/server.py`, add these imports:
```python
import hmac
import json
import secrets

import httpx
from fastapi import FastAPI
from mcp.server.streamable_http_manager import StreamableHTTPASGIApp
from mcp.server.transport_security import TransportSecuritySettings
from starlette.routing import Route

from wheres_allie.db import get_setting, set_setting
```
Add next to the other module constants:
```python
_HOP_HEADERS = {"host", "content-length", "authorization", "connection", "transfer-encoding"}

_relay_asgi = None  # set by mount_mcp; used by handle_mcp_request (relaylink, plan 06)
```
Append at the end of the file:
```python
class _LanTokenGuard:
    """ASGI wrapper: 401 unless `Authorization: Bearer <token>`."""

    def __init__(self, app, token: Callable[[], str]):
        self.app, self.token = app, token

    async def __call__(self, scope, receive, send):
        got = dict(scope["headers"]).get(b"authorization", b"").decode("latin-1")
        if not hmac.compare_digest(got.encode(), f"Bearer {self.token()}".encode()):
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"www-authenticate", b"Bearer"),
                    ],
                }
            )
            await send(
                {
                    "type": "http.response.body",
                    "body": json.dumps({"error": "missing or bad bearer token"}).encode(),
                }
            )
            return
        await self.app(scope, receive, send)


def mount_mcp(app: FastAPI, srv: MCPServer, lan_token: Callable[[], str]) -> None:
    """Add POST/GET/DELETE /mcp to `app`. The caller must run `srv.session_manager.run()` in the
    app lifespan."""
    global _relay_asgi
    srv.streamable_http_app(  # builds srv.session_manager
        stateless_http=True,
        json_response=True,
        # DNS-rebinding protection would reject LAN host names; the bearer token guards /mcp
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    _relay_asgi = StreamableHTTPASGIApp(srv.session_manager)
    app.router.routes.insert(  # first, so a GUI catch-all mount at "/" can't shadow it
        0,
        Route(
            "/mcp",
            endpoint=_LanTokenGuard(_relay_asgi, lan_token),
            methods=["GET", "POST", "DELETE"],
        ),
    )


def ensure_lan_token(conn: sqlite3.Connection, configured: str | None = None) -> str:
    """WA_LAN_TOKEN if set, else the saved token, else a new one; always saved (conventions §3)."""
    saved = get_setting(conn, "lan_token")
    token = configured or saved or secrets.token_urlsafe(24)
    if token != saved:
        set_setting(conn, "lan_token", token)
    return token


async def handle_mcp_request(
    method: str, path: str, headers: dict[str, str], body: bytes
) -> tuple[int, dict[str, str], bytes]:
    """Run one relay-forwarded MCP HTTP request in-process, without the LAN token check."""
    if _relay_asgi is None or path.split("?")[0].rstrip("/") != "/mcp":
        return 404, {"content-type": "application/json"}, b'{"error":"not found"}'
    fwd = {k: v for k, v in headers.items() if k.lower() not in _HOP_HEADERS}
    transport = httpx.ASGITransport(app=_relay_asgi)
    async with httpx.AsyncClient(transport=transport, base_url="http://relaylink") as client:
        r = await client.request(method, "/mcp", headers=fwd, content=body)
    return r.status_code, {k: v for k, v in r.headers.items() if k != "content-length"}, r.content
```

**Step 4: Run test, verify pass**
Run: `cd box && uv run pytest tests/mcp -q`
Expected: `28 passed`

**Step 5: Commit**
```bash
git add box/src/wheres_allie/mcp/server.py box/tests/mcp/test_http.py
git commit -m "feat: mount /mcp with LAN bearer token; in-process relay entry point" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: Wire `/mcp` into the plan-01 app (LAN token, session manager in lifespan)

**Files:**
- Modify: `box/src/wheres_allie/api/app.py`
- Test: `box/tests/mcp/test_app_mount.py`

**Step 1: Write failing test**
```python
# box/tests/mcp/test_app_mount.py
from fastapi.testclient import TestClient

from wheres_allie.api.app import create_app
from wheres_allie.config import Settings

HDRS = {
    "accept": "application/json, text/event-stream",
    "content-type": "application/json",
    "mcp-protocol-version": "2025-11-25",
}
LIST = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}


def test_app_serves_mcp_behind_lan_token(tmp_path):
    (tmp_path / "dist").mkdir()
    (tmp_path / "dist" / "index.html").write_text("<p>gui</p>")
    settings = Settings(data_dir=tmp_path, mqtt_pass="test", web_dist=tmp_path / "dist")
    app = create_app(settings, start_background=False)
    token = app.state.lan_token
    assert len(token) >= 24
    with TestClient(app) as c:
        assert c.get("/").status_code == 200  # the GUI mount at "/" doesn't shadow /mcp
        assert c.post("/mcp", json=LIST, headers=HDRS).status_code == 401
        r = c.post("/mcp", json=LIST, headers=HDRS | {"authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert len(r.json()["result"]["tools"]) == 6
    app2 = create_app(settings, start_background=False)  # same data dir = a restart
    assert app2.state.lan_token == token
```

**Step 2: Run test, verify failure**
Run: `cd box && uv run pytest tests/mcp/test_app_mount.py -q`
Expected: FAIL with `AttributeError: 'State' object has no attribute 'lan_token'`

**Step 3: Implement**
Edit `box/src/wheres_allie/api/app.py` (plan 01's `create_app`):
1. Add the import:
   ```python
   from wheres_allie.mcp.server import build_mcp, ensure_lan_token, mount_mcp
   ```
2. In `create_app`, after `app.state.conn` is set and **above** the final `if settings.web_dist.is_dir(): app.mount("/", …)` line, add:
   ```python
   # MCP at /mcp behind the LAN token (conventions §11)
   app.state.lan_token = ensure_lan_token(app.state.conn, settings.lan_token or None)
   app.state.mcp = build_mcp(lambda: app.state.conn, tz_default=settings.tz)
   mount_mcp(app, app.state.mcp, lan_token=lambda: app.state.lan_token)
   ```
3. In the lifespan, wrap the existing `yield` so the MCP session manager runs while the app runs. This applies with `start_background=False` too. Leave the task cancellation after it as it is.
   ```python
   async with app.state.mcp.session_manager.run():
       yield
   ```

**Step 4: Run test, verify pass**
Run: `cd box && uv run pytest -q`
Expected: every test passes, including plans 01–03 and `tests/mcp/test_app_mount.py`.

**Step 5: Commit**
```bash
git add box/src/wheres_allie/api/app.py box/tests/mcp/test_app_mount.py
git commit -m "feat: serve MCP at /mcp behind the LAN token" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 13: Manual check with MCP Inspector

**Files:**
- Modify: `docs/friction-log.md` (only if something surprised you)

**Step 1: Write failing test:** n/a (manual acceptance).

**Step 2: Run test, verify failure:** n/a.

**Step 3: Run the box and the Inspector**
```bash
# terminal 1: a box with the seeded MCP test data (no MQTT needed)
cd box && uv run python - <<'EOF'
import sys; sys.path[:0] = ["tests"]
from pathlib import Path
from conftest import seed
p = Path("/tmp/wa-inspect/wheres_allie.db"); p.parent.mkdir(exist_ok=True); p.unlink(missing_ok=True)
seed(p, history_days=14)
EOF
WA_DATA_DIR=/tmp/wa-inspect WA_MQTT_PASS=x uv run wheres-allie serve
# terminal 2: read the LAN token, then start the Inspector
sqlite3 /tmp/wa-inspect/wheres_allie.db "SELECT value FROM settings WHERE key='lan_token'"
npx @modelcontextprotocol/inspector
```
MQTT connection errors in terminal 1's log are expected (no broker is running). The seeded data is dated 2026-09-28. On another day `where_is` answers "away" and `anything_unusual` looks at today, so pass `date: "2026-09-28"` to `day_summary`, `timeline` and `anything_unusual`. If plan 01's db file under `WA_DATA_DIR` has another name, use that name in both places.

In the Inspector UI:
1. Set Transport = **Streamable HTTP**, URL = `http://localhost:8080/mcp`.
2. Under Authentication, set header `Authorization` = `Bearer <token>`. Connect.
3. **Tools → List:** 6 tools. `where_is`, `day_summary` and `timeline` show `_meta.ui.resourceUri = ui://wheres-allie/floorplan`.
4. **Resources:** `ui://wheres-allie/floorplan` reads as `text/html;profile=mcp-app`.
5. Call each tool: `day_summary {date:"2026-09-28"}`, `timeline {date:"2026-09-28", from:"09:00", to:"12:30"}`, `last_visit {place:"water"}`, `anything_unusual {date:"2026-09-28"}` → `status:"unusual"` with the `no_visit` water-bowl reason, `mark_location {place:"bed"}`, `where_is`. Each shows `structuredContent` and a text block equal to `speech`. With plan 04 merged, `where_is`, `day_summary` and `timeline` also carry a non-null `app`.
6. Disconnect, remove the header, and reconnect. The connection fails with 401.

**Step 4: Verify**
All 6 steps behave as described. Note anything surprising in `docs/friction-log.md` (MCP SDK 2.x / Inspector friction counts for the hackathon bonus).

**Step 5: Commit** (only if the friction log changed)
```bash
git add docs/friction-log.md
git commit -m "docs: friction log notes from MCP Inspector check" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 14: Phase 6 exit: full suite, lint, push

**Files:**
- Modify: `docs/plans/2026-09-28-wheres-allie-plan-05-brain-mcp.md` (status table)

**Step 1: Write failing test:** n/a.

**Step 2: Run the whole suite and the linter**
```bash
cd box && uv run pytest -q && uv run ruff check src tests && uv run ruff format --check src tests
```
Expected: all tests pass (including plans 01–03). Ruff reports `All checks passed!`. If `ruff format --check` lists files from this plan, run `uv run ruff format <those files>` and re-run.

**Step 3: Implement:** set every row of this plan's status table to `done | yes | yes`.

**Step 4: Verify** there are no uncommitted changes other than the status table: `git status --short`.

**Step 5: Commit and push**
```bash
git add docs/plans/2026-09-28-wheres-allie-plan-05-brain-mcp.md
git commit -m "docs: plan 05 brain + MCP complete" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push origin main
```

---

## Phase exit criteria
- `cd box && uv run pytest tests/brain tests/mcp -q` → 42 passed: 13 brain, 9 tool helpers, 15 contract, 4 HTTP/auth, 1 app mount.
- The design's example day works end to end: with 14 routine days and today's water-bowl visits only at 07:30 and 09:10, `anything_unusual` at 15:30 returns `status:"unusual"` with `{"kind":"no_visit","place":"Water bowl","since":"09:10","typical_interval":"~3h"}`. With fewer than 5 days it returns `status:"learning"` and "N of 5 days so far".
- All 6 tools are listed. `where_is`, `day_summary` and `timeline` carry `_meta.ui.resourceUri = ui://wheres-allie/floorplan` and an `app` key (plan 04's AppView, or `null` before plan 04 lands). Every result's text block equals its `speech`.
- `POST /mcp` without the LAN token → 401. With it → 200. `handle_mcp_request` works without a token (plan 06 depends on it).
- MCP Inspector (Task 13) connects over Streamable HTTP and calls every tool.
- No tool description or speech string uses medical or health wording. `grep -rniE "sick|illness|disease|symptom|diagnos" box/src/wheres_allie/brain box/src/wheres_allie/mcp` matches only the guidance sentence that forbids it.
