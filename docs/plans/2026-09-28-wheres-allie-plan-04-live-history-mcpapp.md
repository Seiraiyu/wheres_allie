# Live, History and MCP App Implementation Plan

**Goal:** Show where the pet is right now and replay the path they actually took (snapped to the walkable graph) in the GUI, and serve the same floorplan view to Alexa+ as an MCP App (`ui://wheres-allie/floorplan`).
**Architecture:** Backend: a pure `home/pathing.py` (Dijkstra, run-collapse + route fill, raw-evidence centroids) is used by the thin FastAPI routes `api/routes/live.py` and `api/routes/history.py`, and by `mcp/app_resource.py`, which builds the compact `app` view payload that plan 05's tools attach to their results. Frontend: pure replay logic in `web/src/lib/replay.ts`, small shared SVG overlays in `web/src/components/replay/`, drawn as `children` of plan 02's `PlanCanvas` by `Live.tsx`, `History.tsx`, and a separate single-file Vite entry `web/src/mcp-app/`.
**Tech Stack:** Python 3.12, FastAPI, sqlite3, `mcp` FastMCP; React 18 + TypeScript, Vite, `vite-plugin-singlefile`, `@modelcontextprotocol/ext-apps`, vitest, @testing-library/react, @playwright/test.

Design: `docs/plans/2026-09-28-wheres-allie-design.md` §4.5, §4.6 (phases 5 and 8). Contract: `docs/plans/2026-09-28-wheres-allie-conventions.md` (§6 home model, §10 API, §11 MCP, §14 tokens). Needs plans 01, 02 and 03 executed. Task 22 also needs plan 05's `mcp/server.py`.

| Task | Description | Status | Tested | Pushed |
|------|-------------|--------|--------|--------|
| 1 | Verify prerequisite names from plans 01–03 (read-only) | pending | no | no |
| 2 | `home/pathing.py`: `shortest_path` (Dijkstra) | pending | no | no |
| 3 | `home/pathing.py`: `snap_path` (run collapse + route fill) | pending | no | no |
| 4 | `home/pathing.py`: `raw_evidence` + `home_context` | pending | no | no |
| 5 | `devseed.py`: sample home + synthetic day | pending | no | no |
| 6 | `api/routes/live.py`: GET `/api/live` | pending | no | no |
| 7 | `api/routes/history.py`: GET `/api/history/path` | pending | no | no |
| 8 | `api/routes/history.py`: GET `/api/history/visits` | pending | no | no |
| 9 | Wire the live and history routers into the app | pending | no | no |
| 10 | `types.ts` additions + `lib/replay.ts` pure logic | pending | no | no |
| 11 | Replay components: PetMarker, Trail, FloorTabs, useReplayClock, CSS | pending | no | no |
| 12 | `Live.tsx` page | pending | no | no |
| 13 | `History.tsx` page | pending | no | no |
| 14 | Playwright e2e for Live + History on a seeded db | pending | no | no |
| 15 | Phase 5 gate: full test run + push | pending | no | no |
| 16 | MCP App deps + `bridge.ts` | pending | no | no |
| 17 | MCP App sample data + `FloorplanApp.tsx` | pending | no | no |
| 18 | MCP App entry, single-file build config, dev harness | pending | no | no |
| 19 | `mcp/app_resource.py`: resource registration | pending | no | no |
| 20 | `mcp/app_resource.py`: `plan_payload` + view builders | pending | no | no |
| 21 | Playwright render test of the built MCP App | pending | no | no |
| 22 | Link the resource into plan 05's MCP server | pending | no | no |
| 23 | Phase 8 exit: Echo Show check, friction log, push | pending | no | no |

## Interface additions

These add to the conventions and never contradict them.

### A. New Python modules
```python
# box/src/wheres_allie/home/pathing.py
WALK_MPS = 1.0
def shortest_path(graph: Graph, a: str, b: str) -> list[tuple[str, float]]
    # [(a, 0.0), …, (b, total_m)] using Graph edge lengths (stairs incl. +3 m); [] if unreachable
def snap_path(graph: Graph, rows: Iterable[tuple[float, str, int | None]]) -> list[dict]
    # rows = positions (ts, vertex_id, moving) ordered by ts → PathPoint dicts (see B).
    # Consecutive rows at the same vertex collapse to a start and an end point. Between two
    # different vertices, the Dijkstra route's intermediate vertices are inserted at 1 m/s,
    # ending at the next run's start ("waits, then walks"). No route is filled across
    # 'away' or unknown vertex ids.
def raw_evidence(home: Home, readings: Iterable[tuple[float, str, float]], window_s: float = 2.0) -> list[dict]
    # readings (ts, node_id, rssi) → per 2 s window: the centroid of the placed nodes, weighted
    # by 10**(rssi/20), using only nodes on the floor of the loudest node → RawDot dicts
def home_context(conn) -> tuple[Home, list[Room], Graph]   # load_home + detect_rooms + build_graph

# box/src/wheres_allie/devseed.py   (tests, e2e, screenshots; `python -m wheres_allie.devseed <db> --date YYYY-MM-DD`)
DAY: list[tuple[str, int]]            # (vertex_id, minutes) schedule from 08:00 local
def sample_home() -> Home             # floors main/up; rooms kitchen, bedroom (main), loft (up); door d1; stairs s1; landmarks bowl, bed
def seed(conn, day: date, tz: str = "America/New_York", now: float | None = None) -> tuple[float, float]
    # pet 1 "Allie" + tag 1; positions every 10 s + visits for DAY; open visit + position on lm:bed ending at `now`

# box/src/wheres_allie/api/routes/live.py
def qmarks(ids) -> str; def tag_ids(conn, pet_id) -> list[int]; def latest_position(conn, tags) -> sqlite3.Row | None
# box/src/wheres_allie/api/routes/history.py
def resolve_pet(conn, pet: str | None) -> tuple[int, str, list[int]]   # name (case-insensitive) or first pet; 404
def load_path(conn, home, graph, tags, t0, t1, raw=False) -> dict       # {"points": [...], "raw"?: [...]}
def load_visits(conn, graph, tags, t0, t1) -> list[dict]
```

### B. API response shapes (fill in conventions §10)
```ts
// GET /api/live → LiveEntry[] (one per pet, ordered by pet id)
type LiveEntry = { pet: {id: number; name: string}; ts: number|null; vertex_id: string|null; confidence: number|null;
  moving: boolean|null; x: number|null; y: number|null; floor_id: string|null; floor_name: string|null;
  room_id: string|null; room_name: string|null; place: string|null;           // place = vertex name
  place_kind: "room"|"landmark"|"transit"|null; since: number|null;           // since = start of the open visit
  away: boolean };
// GET /api/history/path?pet&from&to[&raw=true]   (pet optional → first pet; to-from in (0, 7 days] else 422)
type PathPoint = { ts: number; vertex_id: string; floor_id: string; x: number; y: number; moving: boolean|null };
type RawDot = { ts: number; floor_id: string; x: number; y: number };
type PathResponse = { points: PathPoint[]; raw?: RawDot[] };
// GET /api/history/visits?pet&from&to → visits overlapping [from, to), ordered by start
type VisitRow = { id: number; place_id: string; kind: "room"|"landmark"|"transit"|"away";
  start: number; end: number|null; name: string; floor_id: string|null };
```
`visits.place_id` is resolved to a name by trying, in order, the vertex ids `place_id`, `room:<place_id>` and `lm:<place_id>`. That works whether plan 03 stores vertex ids or bare room/landmark ids. `devseed` stores bare ids.

### C. PlanCanvas contract needed from plan 02 (`web/src/components/plan/PlanCanvas.tsx`)
```ts
export function PlanCanvas(props: {
  home: Home; rooms: Room[]; floorId: string;
  children?: React.ReactNode;  // overlay drawn LAST inside the plan <svg>, in plan coordinates (metres, y down)
  // …editor-only props stay optional; when none are passed the canvas is view-only (pan/zoom allowed)
}): JSX.Element
```
PlanCanvas must be driven by props only. It must not fetch, read the zustand store, or depend on routing, because the MCP App renders it with no API. It draws an underlay only when `floor.underlay` is set, and the MCP payload strips underlays. If plan 02 used a different name for the overlay slot, Task 1 adds `children` support. That is a one-line `{props.children}` just before `</svg>`.

### D. MCP App (`box/src/wheres_allie/mcp/app_resource.py`) — used by plan 05
```python
FLOORPLAN_URI = APP_URI = "ui://wheres-allie/floorplan"
APP_MIME = "text/html;profile=mcp-app"           # MCP Apps RESOURCE_MIME_TYPE
TOOL_META = {"ui": {"resourceUri": APP_URI}}     # what the tools' _meta must contain
def floorplan_html() -> str                      # the built single-file HTML (package data mcp/static/index.html)
def plan_payload(home, rooms, floor_ids) -> PlanPayload
def app_view_for_position(conn, tag_ids) -> AppView | None
def app_view_for_range(conn, tag_ids, t0, t1) -> AppView | None          # path decimated to ≤ 2000 points
```
```ts
type PlanPayload = { home: Home /* only the given floors; underlay=null; nodes=[] */; rooms: Room[] };
type AppView =
  | { view: "position"; plan: PlanPayload;
      position: { ts: number; vertex_id: string; floor_id: string; x: number; y: number; confidence: number; moving: boolean|null } }
  | { view: "path"; plan: PlanPayload; path: PathPoint[] };
```
**Plan 05 obligations (coordination):**
1. Plan 05's `mcp/server.py` registers the resource with the SDK's MCP Apps extension, `apps.add_html_resource(FLOORPLAN_URI, floorplan_html(), name="floorplan", title="Floorplan")` (served as `text/html;profile=mcp-app`). It binds `where_is`, `day_summary` and `timeline` with `@apps.tool(resource_uri=FLOORPLAN_URI)`, which stamps `_meta` = `TOOL_META`. This was agreed with plan-05.
2. Their `structuredContent` gains one extra key, `app: AppView | null`:
   - `where_is` → `app_view_for_position(conn, tag_ids)`
   - `day_summary` → `app_view_for_range(conn, tag_ids, day_t0, day_t1)`
   - `timeline` → `app_view_for_range(conn, tag_ids, from_ts, to_ts)`
3. `wheres_allie.mcp.server.build_mcp(connect, tz_default=..., clock=...) -> MCPServer`. Task 22's test uses `build_mcp(lambda: None)` with `mcp.Client`.

The UI reads `structuredContent.app`, plus `pet` and `place` for its title bar. Everything else is ignored.

The UI gets data from the host through `ui/notifications/tool-result`, using `@modelcontextprotocol/ext-apps` `App.ontoolresult`. It also accepts a raw `postMessage` fallback of the same JSON-RPC notification from `window.parent`, which the dev harness and Playwright use.

**Spike risk:** plan 01 phase 0 confirms whether MCP Apps render on the Echo Show at all. If they don't, the voice answers still work because `app` is additive, and this UI remains demoable in the Alexa web simulator and the dev harness.

### E. Web additions
- `web/src/lib/types.ts` gains `LiveEntry`, `PathPoint`, `RawDot`, `PathResponse`, `VisitRow`, `PlanPayload`, `AppView`.
- New dependencies: `vite-plugin-singlefile`, `@modelcontextprotocol/ext-apps`, `jsdom` (dev).
- New scripts in `web/package.json`: `"build:mcp-app": "vite build --config vite.mcp-app.config.ts"`, `"dev:mcp-app": "vite --config vite.mcp-app.config.ts"`, `"e2e:live": "playwright test -c playwright.live.config.ts"`.
- The built `box/src/wheres_allie/mcp/static/index.html` is **committed**, so the Python package and its tests don't need pnpm. Rebuild it whenever `src/mcp-app/`, `components/plan/` or `components/replay/` change.
- History supports the deep link `/history?date=YYYY-MM-DD`.

---

### Task 1: Verify prerequisite names from plans 01–03 (read-only)

**Files:** none changed unless a check below says "adapt".

This plan uses the names below. Run each check from the repo root. If a name differs, use the real name everywhere in this plan's code, or make the small adaptation described in the right-hand column.

| Assumed | Check | If different |
|---|---|---|
| `wheres_allie.api.deps.get_conn` (FastAPI dependency yielding `sqlite3.Connection`) | `grep -n "def get_conn" box/src/wheres_allie/api/deps.py` | use the real dependency name in Tasks 6–9 |
| routers are `APIRouter()` included without a prefix, paths start with `/api` | `grep -n "include_router" box/src/wheres_allie/api/app.py` | if routers get `prefix="/api"`, drop `/api` from the route decorators in Tasks 6–8 |
| `load_home`, `detect_rooms`, `build_graph`, `Graph.neighbors`, `Vertex(...)` fields as in conventions §6 | `grep -n "def load_home\|def detect_rooms\|def build_graph\|def neighbors\|class Vertex" -r box/src/wheres_allie/home` | adapt Task 2–4 imports |
| room vertex `name` = room name; landmark vertex `name` = landmark name, `room_id` = containing room | `grep -n "Vertex(" box/src/wheres_allie/home/graph.py` | adapt the expected names in Tests 6 and 8 |
| db file is `<WA_DATA_DIR>/wheres_allie.db`, CLI `wheres-allie serve` | `grep -rn "wheres_allie.db\|def serve" box/src/wheres_allie` | adapt the webServer command in Task 14 |
| GUI served with SPA fallback (deep links like `/history` return index.html) | `grep -n "index.html\|StaticFiles" box/src/wheres_allie/api/app.py` | if missing, Task 14 navigates via `/` and the left rail instead |
| `web/src/lib/api.ts` exports `apiGet<T>(path)` | `grep -n "export" box/web/src/lib/api.ts` | use the real GET helper in Tasks 12–13 |
| `web/src/lib/ws.ts` exports `subscribe(topicPrefix, cb) => unsubscribe` | `grep -n "export" box/web/src/lib/ws.ts` | use the real one in Task 12 |
| `types.ts` exports `Home`, `Room`, `Floor`, `Node` (with `online`) | `grep -n "export type\|export interface" box/web/src/lib/types.ts` | adapt imports |
| PlanCanvas props per Interface additions C | `sed -n '1,60p' box/web/src/components/plan/PlanCanvas.tsx` | add `children?: React.ReactNode` to props and render `{children}` as the last child of the root `<svg>`/`<g>` in plan coordinates |
| Page components are default exports routed at `/live` and `/history` | `grep -n "Live\|History" box/web/src/App.tsx` | match the existing export and route style |
| vitest ignores `e2e/**` | `grep -n "exclude\|include" box/web/vite.config.ts box/web/vitest.config.ts 2>/dev/null` | add `test: { exclude: [...configDefaults.exclude, "e2e/**"] }` (`import { configDefaults } from "vitest/config"`) |
| plan 03's runner does not write positions for a tag with no readings | `grep -n "INSERT INTO positions" -r box/src/wheres_allie/estimator` and read the loop | if it does, Task 14's Live test already asserts only the place card and node dots, not the marker position |

**Step 1: Write failing test:** none (read-only verification).
**Step 2: Run test, verify failure:** n/a.
**Step 3: Implement:** make only the "If different" adaptations above. If PlanCanvas needed `children`, that is the only production edit.
**Step 4: Run test, verify pass:** `cd box && uv run pytest -q && cd web && pnpm test`. Expected: the pre-existing suites pass.
**Step 5: Commit** (only if PlanCanvas or the vitest config changed):
```bash
git add box/web/src/components/plan/PlanCanvas.tsx box/web/vite.config.ts
git commit -m "feat: PlanCanvas renders overlay children for live/history/mcp-app" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: `home/pathing.py`: `shortest_path` (Dijkstra)

**Files:**
- Create: `box/src/wheres_allie/home/pathing.py`
- Test: `box/tests/home/test_pathing.py`

**Step 1: Write failing test**
```python
# box/tests/home/test_pathing.py
from wheres_allie.home.graph import Graph, Vertex
from wheres_allie.home.pathing import shortest_path


def V(id, x, y, floor="f1", kind="room"):
    return Vertex(id=id, kind=kind, floor_id=floor, x=x, y=y, room_id=None, name=id)


def graph() -> Graph:
    vs = [V("A", 0, 0), V("B", 3, 0), V("C", 3, 4), V("D", 3, 4, "f2", "stairs"), V("E", 9, 9)]
    edges = [("A", "B", 3.0), ("B", "C", 4.0), ("A", "C", 10.0), ("C", "D", 3.0)]
    return Graph(vertices={v.id: v for v in vs}, edges=edges)


def test_shortest_path_prefers_the_short_route():
    assert shortest_path(graph(), "A", "C") == [("A", 0.0), ("B", 3.0), ("C", 7.0)]


def test_shortest_path_crosses_floors():
    assert shortest_path(graph(), "A", "D") == [("A", 0.0), ("B", 3.0), ("C", 7.0), ("D", 10.0)]


def test_shortest_path_same_vertex_and_unreachable():
    assert shortest_path(graph(), "A", "A") == [("A", 0.0)]
    assert shortest_path(graph(), "A", "E") == []
```

**Step 2: Run test, verify failure**
Run: `cd box && uv run pytest tests/home/test_pathing.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'wheres_allie.home.pathing'`

**Step 3: Implement**
```python
# box/src/wheres_allie/home/pathing.py
"""Snap estimator positions onto walkable routes for history replay."""
from __future__ import annotations

import heapq
import math

from wheres_allie.home.graph import Graph


def shortest_path(graph: Graph, a: str, b: str) -> list[tuple[str, float]]:
    """Dijkstra over graph edge lengths: [(a, 0.0), ..., (b, total_m)], or [] if unreachable."""
    dist = {a: 0.0}
    prev: dict[str, str] = {}
    heap = [(0.0, a)]
    while heap:
        d, u = heapq.heappop(heap)
        if u == b:
            break
        if d > dist[u]:
            continue
        for w, length in graph.neighbors(u):
            nd = d + length
            if nd < dist.get(w, math.inf):
                dist[w] = nd
                prev[w] = u
                heapq.heappush(heap, (nd, w))
    if b not in dist:
        return []
    path = [b]
    while path[-1] != a:
        path.append(prev[path[-1]])
    return [(v, dist[v]) for v in reversed(path)]
```

**Step 4: Run test, verify pass**
Run: `cd box && uv run pytest tests/home/test_pathing.py -q`
Expected: PASS (3 passed)

**Step 5: Commit**
```bash
git add box/src/wheres_allie/home/pathing.py box/tests/home/test_pathing.py
git commit -m "feat: shortest path on the walkable graph" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: `home/pathing.py`: `snap_path`

**Files:**
- Modify: `box/src/wheres_allie/home/pathing.py`
- Test: `box/tests/home/test_pathing.py`

**Step 1: Write failing test** (append)
```python
from wheres_allie.home.pathing import snap_path


def pts(points):
    return [(p["ts"], p["vertex_id"], p["moving"]) for p in points]


def test_snap_point_carries_vertex_geometry():
    assert snap_path(graph(), [(0, "D", 1)]) == [
        {"ts": 0, "vertex_id": "D", "floor_id": "f2", "x": 3, "y": 4, "moving": True}
    ]


def test_snap_collapses_runs_and_fills_the_route():
    rows = [(0, "A", 0), (10, "A", 0), (17, "C", 1), (20, "C", 0), (30, "D", None)]
    assert pts(snap_path(graph(), rows)) == [
        (0, "A", False), (10, "A", False),
        (13.0, "B", True),                   # A->B->C is 7 m, walked in the 7 s gap
        (17, "C", True), (20, "C", False),
        (27.0, "C", False),                  # C->D is 3 m: wait at C, then walk
        (30, "D", None),
    ]


def test_snap_waits_then_walks_across_long_gaps():
    assert pts(snap_path(graph(), [(0, "A", 0), (100, "B", 0)])) == [
        (0, "A", False), (97.0, "A", False), (100, "B", False)
    ]


def test_snap_never_routes_across_away_or_unknown_vertices():
    rows = [(0, "A", 0), (5, "away", None), (10, "C", 0), (12, "gone", 0), (14, "C", 0)]
    assert pts(snap_path(graph(), rows)) == [(0, "A", False), (10, "C", False), (14, "C", False)]
```

**Step 2: Run test, verify failure**
Run: `cd box && uv run pytest tests/home/test_pathing.py -q`
Expected: FAIL with `ImportError: cannot import name 'snap_path'`

**Step 3: Implement** (append to `pathing.py`; add `from collections.abc import Iterable` to the imports)
```python
WALK_MPS = 1.0  # ponytail: fixed dog walking speed for route fills; learn from motion data if replays look off


def snap_path(graph: Graph, rows: Iterable[tuple[float, str, int | None]]) -> list[dict]:
    """positions rows (ts, vertex_id, moving), ordered by ts -> replay points on graph vertices."""
    runs: list[dict] = []
    broken = True  # True after 'away' or an unknown vertex: don't invent a route across it
    for ts, vid, moving in rows:
        if vid not in graph.vertices:
            broken = True
            continue
        mv = None if moving is None else bool(moving)
        if runs and not broken and runs[-1]["vid"] == vid:
            runs[-1].update(end=ts, mv_end=mv)
        else:
            runs.append({"vid": vid, "start": ts, "end": ts, "mv": mv, "mv_end": mv, "broken": broken})
        broken = False

    out: list[dict] = []

    def emit(vid: str, ts: float, moving: bool | None) -> None:
        v = graph.vertices[vid]
        out.append({"ts": ts, "vertex_id": vid, "floor_id": v.floor_id, "x": v.x, "y": v.y,
                    "moving": moving})

    routes: dict[tuple[str, str], list[tuple[str, float]]] = {}
    for i, run in enumerate(runs):
        if i and not run["broken"]:
            prev = runs[i - 1]
            key = (prev["vid"], run["vid"])
            if key not in routes:
                routes[key] = shortest_path(graph, *key)
            hops = routes[key]
            total = hops[-1][1] if hops else 0.0
            if total > 0:
                travel = min(total / WALK_MPS, run["start"] - prev["end"])
                depart = run["start"] - travel
                if depart > prev["end"]:
                    emit(prev["vid"], depart, out[-1]["moving"])
                for vid, cum in hops[1:-1]:
                    emit(vid, depart + travel * cum / total, True)
        emit(run["vid"], run["start"], run["mv"])
        if run["end"] > run["start"]:
            emit(run["vid"], run["end"], run["mv_end"])
    return out
```

**Step 4: Run test, verify pass**
Run: `cd box && uv run pytest tests/home/test_pathing.py -q`
Expected: PASS (7 passed)

**Step 5: Commit**
```bash
git add box/src/wheres_allie/home/pathing.py box/tests/home/test_pathing.py
git commit -m "feat: snap positions to walkable routes for replay" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: `home/pathing.py`: `raw_evidence` + `home_context`

**Files:**
- Modify: `box/src/wheres_allie/home/pathing.py`
- Test: `box/tests/home/test_pathing.py`

**Step 1: Write failing test** (append)
```python
from wheres_allie.home.model import Home, NodePlacement
from wheres_allie.home.pathing import raw_evidence


def test_raw_evidence_is_weighted_centroid_on_the_loudest_floor():
    home = Home(nodes=[
        NodePlacement(id="n1", floor_id="f1", x=0, y=0, z_m=1, name="n1"),
        NodePlacement(id="n2", floor_id="f1", x=10, y=0, z_m=1, name="n2"),
        NodePlacement(id="n3", floor_id="f2", x=5, y=5, z_m=4, name="n3"),
    ])
    readings = [(0.5, "n1", -60.0), (1.0, "n2", -60.0), (1.5, "n3", -85.0),  # window [0,2)
                (2.5, "n3", -70.0), (3.0, "unplaced", -40.0)]                  # window [2,4)
    assert raw_evidence(home, readings) == [
        {"ts": 1.0, "floor_id": "f1", "x": 5.0, "y": 0.0},
        {"ts": 3.0, "floor_id": "f2", "x": 5.0, "y": 5.0},
    ]
```

**Step 2: Run test, verify failure**
Run: `cd box && uv run pytest tests/home/test_pathing.py -q`
Expected: FAIL with `ImportError: cannot import name 'raw_evidence'`

**Step 3: Implement** (append to `pathing.py`, and add these imports at the top)
```python
import sqlite3

from wheres_allie.home.geometry import Room, detect_rooms
from wheres_allie.home.graph import build_graph
from wheres_allie.home.model import Home, NodePlacement
from wheres_allie.home.store import load_home
```
```python
def raw_evidence(home: Home, readings: Iterable[tuple[float, str, float]],
                 window_s: float = 2.0) -> list[dict]:
    """Per window: RSSI-weighted centroid of the hearing nodes on the loudest node's floor."""
    nodes = {n.id: n for n in home.nodes}
    windows: dict[int, list[tuple[NodePlacement, float]]] = {}
    for ts, node_id, rssi in readings:
        if node_id in nodes:
            windows.setdefault(int(ts // window_s), []).append((nodes[node_id], rssi))
    out = []
    for k in sorted(windows):
        heard = windows[k]
        floor = max(heard, key=lambda h: h[1])[0].floor_id
        pts = [(n, 10 ** (rssi / 20)) for n, rssi in heard if n.floor_id == floor]
        w = sum(wt for _, wt in pts)
        out.append({"ts": (k + 0.5) * window_s, "floor_id": floor,
                    "x": sum(n.x * wt for n, wt in pts) / w,
                    "y": sum(n.y * wt for n, wt in pts) / w})
    return out


def home_context(conn: sqlite3.Connection) -> tuple[Home, list[Room], Graph]:
    # ponytail: rebuilt per request (small homes, ms); cache on home.version if it shows in profiles
    home = load_home(conn)
    rooms = detect_rooms(home)
    return home, rooms, build_graph(home, rooms)
```

**Step 4: Run test, verify pass**
Run: `cd box && uv run pytest tests/home/test_pathing.py -q`
Expected: PASS (8 passed)

**Step 5: Commit**
```bash
git add box/src/wheres_allie/home/pathing.py box/tests/home/test_pathing.py
git commit -m "feat: raw evidence centroids and home context loader" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: `devseed.py`: sample home + synthetic day

**Files:**
- Create: `box/src/wheres_allie/devseed.py`
- Test: `box/tests/test_devseed.py`

**Step 1: Write failing test**
```python
# box/tests/test_devseed.py
import sqlite3
from datetime import date

from wheres_allie import db
from wheres_allie.devseed import DAY, seed


def test_seed_writes_a_day_for_allie():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    db.migrate(conn)
    t0, t1 = seed(conn, date(2026, 9, 27), now=2_000_000_000.0)
    assert t1 - t0 == 86400
    n, first = conn.execute("SELECT count(*), min(ts) FROM positions WHERE ts < ?", (t1,)).fetchone()
    assert first == t0 + 8 * 3600
    assert n == sum(m for _, m in DAY) * 6          # one row per 10 s
    places = [r[0] for r in conn.execute("SELECT place_id FROM visits ORDER BY start")]
    assert places == ["kitchen", "bowl", "kitchen", "bed", "loft", "bedroom", "bed"]
    assert conn.execute('SELECT count(*) FROM visits WHERE "end" IS NULL').fetchone()[0] == 1
```

**Step 2: Run test, verify failure**
Run: `cd box && uv run pytest tests/test_devseed.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'wheres_allie.devseed'`

**Step 3: Implement**
```python
# box/src/wheres_allie/devseed.py
"""Deterministic sample home + one synthetic day for Allie (API tests, e2e, screenshots).

    uv run python -m wheres_allie.devseed /tmp/wa/wheres_allie.db --date 2026-09-27
"""
from __future__ import annotations

import argparse
import sqlite3
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from wheres_allie import db
from wheres_allie.home.graph import Vertex
from wheres_allie.home.model import (Door, Floor, Home, Landmark, NodePlacement, RoomLabel,
                                     Stairs, StairsEnd, Wall)
from wheres_allie.home.pathing import home_context
from wheres_allie.home.store import save_home

# (vertex_id, minutes) from 08:00 local time on the seeded day
DAY = [("room:kitchen", 20), ("lm:bowl", 2), ("room:kitchen", 10), ("lm:bed", 60),
       ("room:loft", 15), ("room:bedroom", 30)]
STEP_S = 10.0


def sample_home() -> Home:
    def wall(id, floor, a, b):
        return Wall(id=id, floor_id=floor, a=a, b=b)

    return Home(
        floors=[Floor(id="main", name="Main", elevation_m=3.0),
                Floor(id="up", name="Upstairs", elevation_m=6.0)],
        walls=[wall("m1", "main", (0, 0), (4, 0)), wall("m2", "main", (4, 0), (8, 0)),
               wall("m3", "main", (8, 0), (8, 4)), wall("m4", "main", (8, 4), (4, 4)),
               wall("m5", "main", (4, 4), (0, 4)), wall("m6", "main", (0, 4), (0, 0)),
               wall("m7", "main", (4, 0), (4, 4)),
               wall("u1", "up", (0, 0), (4, 0)), wall("u2", "up", (4, 0), (4, 4)),
               wall("u3", "up", (4, 4), (0, 4)), wall("u4", "up", (0, 4), (0, 0))],
        room_labels=[RoomLabel(id="kitchen", floor_id="main", name="Kitchen", seed=(2, 2)),
                     RoomLabel(id="bedroom", floor_id="main", name="Master Bedroom", seed=(6, 2)),
                     RoomLabel(id="loft", floor_id="up", name="Loft", seed=(2, 2))],
        doors=[Door(id="d1", wall_id="m7", t=0.5)],
        stairs=[Stairs(id="s1", a=StairsEnd(floor_id="main", x=7, y=3),
                       b=StairsEnd(floor_id="up", x=3, y=3))],
        landmarks=[Landmark(id="bowl", floor_id="main", x=1, y=1, type="water_bowl",
                            name="Water bowl"),
                   Landmark(id="bed", floor_id="main", x=7, y=1, type="bed", name="Allie's bed")],
        nodes=[NodePlacement(id="kitchen", floor_id="main", x=2, y=3.5, z_m=4.0, name="Kitchen"),
               NodePlacement(id="master_bedroom", floor_id="main", x=6, y=3.5, z_m=4.0,
                             name="Master Bedroom"),
               NodePlacement(id="loft", floor_id="up", x=2, y=3.5, z_m=7.0, name="Loft")],
    )


def _dwell(conn: sqlite3.Connection, v: Vertex, start: float, end: float, open_: bool) -> None:
    t = start
    while t < end:
        conn.execute(
            "INSERT INTO positions (ts, tag_id, vertex_id, room_id, floor_id, confidence, moving)"
            " VALUES (?, 1, ?, ?, ?, 0.8, ?)", (t, v.id, v.room_id, v.floor_id, int(t == start)))
        t += STEP_S
    conn.execute('INSERT INTO visits (tag_id, place_id, kind, start, "end") VALUES (1, ?, ?, ?, ?)',
                 (v.id.split(":", 1)[1], v.kind, start, None if open_ else end))


def seed(conn: sqlite3.Connection, day: date, tz: str = "America/New_York",
         now: float | None = None) -> tuple[float, float]:
    """Writes home, pet Allie + tag, the DAY schedule, and 'on her bed' until now. Returns [t0, t1)."""
    save_home(conn, sample_home())
    _home, _rooms, graph = home_context(conn)
    conn.execute("INSERT INTO pets (id, name, species) VALUES (1, 'Allie', 'dog')")
    conn.execute("INSERT INTO tags (id, pet_id, ibeacon_id) VALUES (1, 1, 'iBeacon:demo-allie')")
    zone = ZoneInfo(tz)
    t0 = datetime(day.year, day.month, day.day, tzinfo=zone).timestamp()
    nxt = day + timedelta(days=1)
    t1 = datetime(nxt.year, nxt.month, nxt.day, tzinfo=zone).timestamp()
    ts = t0 + 8 * 3600
    for vid, minutes in DAY:
        _dwell(conn, graph.vertices[vid], ts, ts + minutes * 60, open_=False)
        ts += minutes * 60
    now = time.time() if now is None else now
    _dwell(conn, graph.vertices["lm:bed"], now - 600, now, open_=True)
    conn.commit()
    return t0, t1


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("db_path")
    p.add_argument("--date", default=str(date.today() - timedelta(days=1)))
    p.add_argument("--tz", default="America/New_York")
    a = p.parse_args()
    conn = db.connect(a.db_path)
    db.migrate(conn)
    t0, t1 = seed(conn, date.fromisoformat(a.date), a.tz)
    print(f"seeded {a.db_path}: {a.date} = [{t0:.0f}, {t1:.0f})")


if __name__ == "__main__":
    main()
```

**Step 4: Run test, verify pass**
Run: `cd box && uv run pytest tests/test_devseed.py -q`
Expected: PASS. A `KeyError: 'room:kitchen'` means plan 02 names room vertices differently: fix `DAY` and Task 1's table.

**Step 5: Commit**
```bash
git add box/src/wheres_allie/devseed.py box/tests/test_devseed.py
git commit -m "feat: devseed sample home and synthetic day for tests and e2e" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: `api/routes/live.py`: GET `/api/live`

**Files:**
- Create: `box/src/wheres_allie/api/routes/live.py`
- Create: `box/tests/live_history/conftest.py`
- Test: `box/tests/live_history/test_live_api.py`

**Step 1: Write failing test**
```python
# box/tests/live_history/conftest.py
import sqlite3
from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from wheres_allie import db
from wheres_allie.api.deps import get_conn
from wheres_allie.devseed import seed

NOW = 2_000_000_000.0
DAY = date(2026, 9, 27)


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:", check_same_thread=False)
    c.row_factory = sqlite3.Row
    db.migrate(c)
    yield c
    c.close()


@pytest.fixture
def day(conn):
    return seed(conn, DAY, now=NOW)


@pytest.fixture
def client(conn, day):
    from wheres_allie.api.routes import history, live

    app = FastAPI()
    app.include_router(live.router)
    app.include_router(history.router)
    app.dependency_overrides[get_conn] = lambda: conn
    return TestClient(app)
```
```python
# box/tests/live_history/test_live_api.py
NOW = 2_000_000_000.0  # same as conftest.NOW


def test_live_reports_allie_on_her_bed(client):
    [e] = client.get("/api/live").json()
    assert e["pet"] == {"id": 1, "name": "Allie"}
    assert (e["vertex_id"], e["place"], e["place_kind"]) == ("lm:bed", "Allie's bed", "landmark")
    assert (e["room_name"], e["floor_id"], e["floor_name"]) == ("Master Bedroom", "main", "Main")
    assert (e["x"], e["y"], e["away"], e["moving"]) == (7, 1, False, False)
    assert e["since"] == NOW - 600 and e["confidence"] == 0.8


def test_live_away_has_no_place(client, conn):
    conn.execute("INSERT INTO positions (ts, tag_id, vertex_id, confidence) VALUES (?, 1, 'away', 0.9)",
                 (NOW + 1,))
    [e] = client.get("/api/live").json()
    assert e["away"] is True and e["place"] is None and e["x"] is None


def test_live_pet_without_positions(client, conn):
    conn.execute("INSERT INTO pets (id, name) VALUES (2, 'Bo')")
    bo = client.get("/api/live").json()[1]
    assert bo["pet"]["name"] == "Bo" and bo["vertex_id"] is None and bo["away"] is False
```

**Step 2: Run test, verify failure**
Run: `cd box && uv run pytest tests/live_history/test_live_api.py -q`
Expected: FAIL with `ImportError: cannot import name 'live' from 'wheres_allie.api.routes'`

**Step 3: Implement**
```python
# box/src/wheres_allie/api/routes/live.py
"""GET /api/live: each pet's latest smoothed position, resolved to place/room/floor."""
from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends

from wheres_allie.api.deps import get_conn
from wheres_allie.home.pathing import home_context

router = APIRouter()
Conn = Annotated[sqlite3.Connection, Depends(get_conn)]
PLACE_KIND = {"room": "room", "landmark": "landmark", "door": "transit", "stairs": "transit"}
FIELDS = ("ts", "vertex_id", "confidence", "moving", "x", "y", "floor_id", "floor_name",
          "room_id", "room_name", "place", "place_kind", "since")


def qmarks(ids) -> str:
    return ",".join("?" * len(ids))


def tag_ids(conn: sqlite3.Connection, pet_id: int) -> list[int]:
    return [r[0] for r in conn.execute("SELECT id FROM tags WHERE pet_id = ?", (pet_id,))]


def latest_position(conn: sqlite3.Connection, tags: list[int]) -> sqlite3.Row | None:
    if not tags:
        return None
    return conn.execute(
        "SELECT ts, tag_id, vertex_id, room_id, floor_id, confidence, moving FROM positions"
        f" WHERE tag_id IN ({qmarks(tags)}) ORDER BY ts DESC LIMIT 1", tags).fetchone()


@router.get("/api/live")
def live(conn: Conn) -> list[dict]:
    home, rooms, graph = home_context(conn)
    floors = {f.id: f.name for f in home.floors}
    room_names = {r.id: r.name for r in rooms}
    out = []
    for pet in conn.execute("SELECT id, name FROM pets ORDER BY id").fetchall():
        e: dict = dict.fromkeys(FIELDS)
        e.update(pet={"id": pet["id"], "name": pet["name"]}, away=False)
        row = latest_position(conn, tag_ids(conn, pet["id"]))
        if row:
            e.update(ts=row["ts"], vertex_id=row["vertex_id"], confidence=row["confidence"],
                     moving=None if row["moving"] is None else bool(row["moving"]),
                     away=row["vertex_id"] == "away")
            v = graph.vertices.get(row["vertex_id"])
            if v:
                room_id = row["room_id"] or v.room_id
                e.update(x=v.x, y=v.y, floor_id=v.floor_id, floor_name=floors.get(v.floor_id),
                         room_id=room_id, room_name=room_names.get(room_id), place=v.name,
                         place_kind=PLACE_KIND[v.kind])
            since = conn.execute('SELECT start FROM visits WHERE tag_id = ? AND "end" IS NULL'
                                 " ORDER BY start DESC LIMIT 1", (row["tag_id"],)).fetchone()
            e["since"] = since[0] if since else None
        out.append(e)
    return out
```
Also create a stub so the conftest import resolves, and fill it in Task 7:
```python
# box/src/wheres_allie/api/routes/history.py
from fastapi import APIRouter

router = APIRouter()
```

**Step 4: Run test, verify pass**
Run: `cd box && uv run pytest tests/live_history/test_live_api.py -q`
Expected: PASS (3 passed)

**Step 5: Commit**
```bash
git add box/src/wheres_allie/api/routes/live.py box/src/wheres_allie/api/routes/history.py box/tests/live_history/
git commit -m "feat: GET /api/live with place, room, floor and since" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: `api/routes/history.py`: GET `/api/history/path`

**Files:**
- Modify: `box/src/wheres_allie/api/routes/history.py`
- Test: `box/tests/live_history/test_history_api.py`

**Step 1: Write failing test**
```python
# box/tests/live_history/test_history_api.py
def test_path_snaps_the_day_onto_the_graph(client, day):
    t0, t1 = day
    body = client.get("/api/history/path", params={"pet": "allie", "from": t0, "to": t1}).json()
    pts = body["points"]
    assert "raw" not in body
    assert pts[0]["vertex_id"] == "room:kitchen" and pts[0]["ts"] == t0 + 8 * 3600
    assert [p["ts"] for p in pts] == sorted(p["ts"] for p in pts)
    vids = [p["vertex_id"] for p in pts]
    assert "door:d1" in vids                                   # kitchen -> bed goes through the door
    assert vids.index("stairs:s1:a") < vids.index("stairs:s1:b") < vids.index("room:loft")
    assert {p["floor_id"] for p in pts} == {"main", "up"}


def test_path_defaults_to_first_pet_and_returns_raw_evidence(client, conn, day):
    t0, t1 = day
    conn.execute("INSERT INTO readings (ts, tag_id, node_id, rssi) VALUES (?, 1, 'kitchen', -60),"
                 " (?, 1, 'loft', -90)", (t0 + 100, t0 + 100.5))
    body = client.get("/api/history/path", params={"from": t0, "to": t1, "raw": "true"}).json()
    assert body["raw"] == [{"ts": t0 + 101, "floor_id": "main", "x": 2.0, "y": 3.5}]


def test_path_rejects_unknown_pet_and_bad_ranges(client, day):
    t0, t1 = day
    assert client.get("/api/history/path", params={"pet": "Rex", "from": t0, "to": t1}).status_code == 404
    assert client.get("/api/history/path", params={"from": t1, "to": t0}).status_code == 422
    assert client.get("/api/history/path", params={"from": t0, "to": t0 + 8 * 86400}).status_code == 422
```

**Step 2: Run test, verify failure**
Run: `cd box && uv run pytest tests/live_history/test_history_api.py -q`
Expected: FAIL with `assert 404 == 200`-style errors / `KeyError: 'points'` (route not found)

**Step 3: Implement** (replace the stub)
```python
# box/src/wheres_allie/api/routes/history.py
"""GET /api/history/path and /api/history/visits: a pet's day, replayed on the walkable graph."""
from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from wheres_allie.api.deps import get_conn
from wheres_allie.api.routes.live import qmarks, tag_ids
from wheres_allie.home.graph import Graph
from wheres_allie.home.model import Home
from wheres_allie.home.pathing import home_context, raw_evidence, snap_path

router = APIRouter()
Conn = Annotated[sqlite3.Connection, Depends(get_conn)]
From = Annotated[float, Query(alias="from")]
To = Annotated[float, Query(alias="to")]
MAX_SPAN_S = 7 * 86400


def resolve_pet(conn: sqlite3.Connection, pet: str | None) -> tuple[int, str, list[int]]:
    if pet:
        row = conn.execute("SELECT id, name FROM pets WHERE name = ? COLLATE NOCASE",
                           (pet,)).fetchone()
    else:
        row = conn.execute("SELECT id, name FROM pets ORDER BY id LIMIT 1").fetchone()
    if row is None:
        raise HTTPException(404, f"unknown pet {pet!r}")
    return row["id"], row["name"], tag_ids(conn, row["id"])


def check_range(t0: float, t1: float) -> None:
    if not 0 < t1 - t0 <= MAX_SPAN_S:
        raise HTTPException(422, "need from < to, at most 7 days apart")


def load_path(conn: sqlite3.Connection, home: Home, graph: Graph, tags: list[int],
              t0: float, t1: float, raw: bool = False) -> dict:
    out: dict = {"points": []}
    if raw:
        out["raw"] = []
    if not tags:
        return out
    where = f"tag_id IN ({qmarks(tags)}) AND ts >= ? AND ts < ? ORDER BY ts"
    rows = conn.execute(f"SELECT ts, vertex_id, moving FROM positions WHERE {where}",
                        (*tags, t0, t1)).fetchall()
    out["points"] = snap_path(graph, rows)
    if raw:
        readings = conn.execute(f"SELECT ts, node_id, rssi FROM readings WHERE {where}",
                                (*tags, t0, t1)).fetchall()
        out["raw"] = raw_evidence(home, readings)
    return out


@router.get("/api/history/path")
def history_path(conn: Conn, t0: From, t1: To, pet: str | None = None, raw: bool = False) -> dict:
    check_range(t0, t1)
    _, _, tags = resolve_pet(conn, pet)
    home, _, graph = home_context(conn)
    return load_path(conn, home, graph, tags, t0, t1, raw)
```

**Step 4: Run test, verify pass**
Run: `cd box && uv run pytest tests/live_history -q`
Expected: PASS (6 passed)

**Step 5: Commit**
```bash
git add box/src/wheres_allie/api/routes/history.py box/tests/live_history/test_history_api.py
git commit -m "feat: GET /api/history/path with snapped route and raw evidence" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: `api/routes/history.py`: GET `/api/history/visits`

**Files:**
- Modify: `box/src/wheres_allie/api/routes/history.py`
- Test: `box/tests/live_history/test_history_api.py`

**Step 1: Write failing test** (append)
```python
def test_visits_are_named_and_ordered(client, day):
    t0, t1 = day
    vs = client.get("/api/history/visits", params={"from": t0, "to": t1}).json()
    assert [(v["name"], v["kind"]) for v in vs] == [
        ("Kitchen", "room"), ("Water bowl", "landmark"), ("Kitchen", "room"),
        ("Allie's bed", "landmark"), ("Loft", "room"), ("Master Bedroom", "room")]
    assert vs[4]["floor_id"] == "up" and vs[0]["start"] == t0 + 8 * 3600
    assert vs[0]["end"] == t0 + 8 * 3600 + 20 * 60
```

**Step 2: Run test, verify failure**
Run: `cd box && uv run pytest tests/live_history/test_history_api.py -q`
Expected: FAIL (`/api/history/visits` → 404, `TypeError: string indices must be integers`)

**Step 3: Implement** (append to `history.py`)
```python
def place_label(graph: Graph, place_id: str) -> tuple[str, str | None]:
    """visits.place_id may be a vertex id or a bare room/landmark id."""
    for vid in (place_id, f"room:{place_id}", f"lm:{place_id}"):
        if v := graph.vertices.get(vid):
            return v.name, v.floor_id
    return ("Away" if place_id == "away" else place_id), None


def load_visits(conn: sqlite3.Connection, graph: Graph, tags: list[int],
                t0: float, t1: float) -> list[dict]:
    if not tags:
        return []
    rows = conn.execute(
        f'SELECT id, place_id, kind, start, "end" FROM visits WHERE tag_id IN ({qmarks(tags)})'
        ' AND start < ? AND ("end" IS NULL OR "end" > ?) ORDER BY start', (*tags, t1, t0))
    out = []
    for r in rows:
        name, floor_id = place_label(graph, r["place_id"])
        out.append({**dict(r), "name": name, "floor_id": floor_id})
    return out


@router.get("/api/history/visits")
def history_visits(conn: Conn, t0: From, t1: To, pet: str | None = None) -> list[dict]:
    check_range(t0, t1)
    _, _, tags = resolve_pet(conn, pet)
    _, _, graph = home_context(conn)
    return load_visits(conn, graph, tags, t0, t1)
```

**Step 4: Run test, verify pass**
Run: `cd box && uv run pytest tests/live_history -q`
Expected: PASS (7 passed)

**Step 5: Commit**
```bash
git add box/src/wheres_allie/api/routes/history.py box/tests/live_history/test_history_api.py
git commit -m "feat: GET /api/history/visits with resolved place names" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Wire the live and history routers into the app

**Files:**
- Modify: `box/src/wheres_allie/api/app.py` (next to the existing `include_router` calls)
- Test: `box/tests/live_history/test_app_routes.py`

**Step 1: Write failing test**
```python
# box/tests/live_history/test_app_routes.py
from wheres_allie.api import app as app_module


def test_app_serves_live_and_history_routes():
    # Build the app exactly as plan 01's API tests do (see tests/api/test_health.py);
    # create_app() is the conventional factory.
    app = app_module.create_app()
    paths = {getattr(r, "path", "") for r in app.routes}
    assert {"/api/live", "/api/history/path", "/api/history/visits"} <= paths
```
If plan 01's factory takes arguments (for example `create_app(settings)`), copy the construction line from plan 01's health test.

**Step 2: Run test, verify failure**
Run: `cd box && uv run pytest tests/live_history/test_app_routes.py -q`
Expected: FAIL with `AssertionError` (the paths are missing)

**Step 3: Implement.** In `app.py`, extend the routes import and add two lines beside the other routers:
```python
from wheres_allie.api.routes import history, live  # merge into the existing routes import
...
    app.include_router(live.router)
    app.include_router(history.router)
```
These routers must be included **before** any SPA catch-all or `StaticFiles` mount at `/`.

**Step 4: Run test, verify pass**
Run: `cd box && uv run pytest -q`
Expected: PASS (whole suite green)

**Step 5: Commit**
```bash
git add box/src/wheres_allie/api/app.py box/tests/live_history/test_app_routes.py
git commit -m "feat: mount live and history API routes" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: `types.ts` additions + `lib/replay.ts` pure logic

**Files:**
- Modify: `box/web/src/lib/types.ts` (append)
- Create: `box/web/src/lib/replay.ts`
- Test: `box/web/src/lib/replay.test.ts`

**Step 1: Write failing test**
```ts
// box/web/src/lib/replay.test.ts
import { describe, expect, it } from "vitest";
import { dayBounds, floorSegments, indexAt, poseAt, trailAt, visitIndexAt } from "./replay";
import type { PathPoint, VisitRow } from "./types";

const P = (ts: number, x: number, floor_id = "main", moving: boolean | null = false): PathPoint =>
  ({ ts, vertex_id: `v${ts}`, floor_id, x, y: 0, moving });
const pts = [P(0, 0), P(10, 0), P(20, 10, "main", true), P(30, 10, "up"), P(40, 10, "up")];

describe("indexAt", () => {
  it("finds the last point at or before t", () => {
    expect(indexAt(pts, -1)).toBe(-1);
    expect(indexAt(pts, 0)).toBe(0);
    expect(indexAt(pts, 15)).toBe(1);
    expect(indexAt(pts, 99)).toBe(4);
  });
});

describe("poseAt", () => {
  it("is null before the first point", () => expect(poseAt(pts, -5)).toBeNull());
  it("holds still while dwelling", () =>
    expect(poseAt(pts, 5)).toEqual({ x: 0, y: 0, floor_id: "main", moving: false }));
  it("interpolates within a floor and reports motion", () =>
    expect(poseAt(pts, 15)).toEqual({ x: 5, y: 0, floor_id: "main", moving: true }));
  it("switches floor at the next point instead of drawing across floors", () => {
    expect(poseAt(pts, 25)?.floor_id).toBe("main");
    expect(poseAt(pts, 30)?.floor_id).toBe("up");
  });
  it("stays at the last point after the end", () =>
    expect(poseAt(pts, 99)).toEqual({ x: 10, y: 0, floor_id: "up", moving: false }));
});

describe("trailAt", () => {
  it("keeps same-floor points within the window, ending at the head", () => {
    expect(trailAt(pts, 25, 100).map((p) => p.ts)).toEqual([0, 10, 20, 25]);
    expect(trailAt(pts, 25, 12).map((p) => p.ts)).toEqual([20, 25]);
    expect(trailAt(pts, 35, 100).map((p) => p.ts)).toEqual([30, 35]);
    expect(trailAt(pts, -1, 100)).toEqual([]);
  });
});

describe("floorSegments", () => {
  it("splits the timeline where the floor changes", () =>
    expect(floorSegments(pts)).toEqual([
      { floor_id: "main", start: 0, end: 30 },
      { floor_id: "up", start: 30, end: 40 },
    ]));
});

describe("visitIndexAt", () => {
  const vs = [{ start: 0, end: 10 }, { start: 10, end: null }] as VisitRow[];
  it("finds the visit covering t", () => {
    expect(visitIndexAt(vs, -1)).toBe(-1);
    expect(visitIndexAt(vs, 5)).toBe(0);
    expect(visitIndexAt(vs, 50)).toBe(1);
  });
});

describe("dayBounds", () => {
  it("returns local midnight to next midnight", () => {
    const [t0, t1] = dayBounds("2026-07-15");
    expect(t1 - t0).toBe(86400);
    expect(new Date(t0 * 1000).getHours()).toBe(0);
  });
});
```

**Step 2: Run test, verify failure**
Run: `cd box/web && pnpm vitest run src/lib/replay.test.ts`
Expected: FAIL with `Failed to resolve import "./replay"`

**Step 3: Implement**
Append to `box/web/src/lib/types.ts`:
```ts
// --- plan 04: live / history / MCP App (mirrors api/routes/live.py, history.py, mcp/app_resource.py) ---
export type LiveEntry = {
  pet: { id: number; name: string };
  ts: number | null; vertex_id: string | null; confidence: number | null; moving: boolean | null;
  x: number | null; y: number | null; floor_id: string | null; floor_name: string | null;
  room_id: string | null; room_name: string | null; place: string | null;
  place_kind: "room" | "landmark" | "transit" | null; since: number | null; away: boolean;
};
export type PathPoint = { ts: number; vertex_id: string; floor_id: string; x: number; y: number; moving: boolean | null };
export type RawDot = { ts: number; floor_id: string; x: number; y: number };
export type PathResponse = { points: PathPoint[]; raw?: RawDot[] };
export type VisitRow = {
  id: number; place_id: string; kind: "room" | "landmark" | "transit" | "away";
  start: number; end: number | null; name: string; floor_id: string | null;
};
export type PlanPayload = { home: Home; rooms: Room[] };
export type AppView =
  | { view: "position"; plan: PlanPayload;
      position: { ts: number; vertex_id: string; floor_id: string; x: number; y: number; confidence: number; moving: boolean | null } }
  | { view: "path"; plan: PlanPayload; path: PathPoint[] };
```
```ts
// box/web/src/lib/replay.ts
// Pure replay math shared by History, Live and the MCP App.
import type { PathPoint, VisitRow } from "./types";

export type Pose = { x: number; y: number; floor_id: string; moving: boolean | null };
export type TrailPoint = { x: number; y: number; ts: number };

/** Index of the last point with ts <= t, or -1. */
export function indexAt(points: PathPoint[], t: number): number {
  let lo = 0, hi = points.length - 1, ans = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (points[mid].ts <= t) { ans = mid; lo = mid + 1; } else hi = mid - 1;
  }
  return ans;
}

/** Interpolated pose at t. Floor changes happen at the next point (no lines across floors). */
export function poseAt(points: PathPoint[], t: number): Pose | null {
  const i = indexAt(points, t);
  if (i < 0) return null;
  const a = points[i], b = points[i + 1];
  if (!b || b.floor_id !== a.floor_id || b.ts === a.ts)
    return { x: a.x, y: a.y, floor_id: a.floor_id, moving: a.moving };
  const f = (t - a.ts) / (b.ts - a.ts);
  const moved = a.x !== b.x || a.y !== b.y;
  return { x: a.x + (b.x - a.x) * f, y: a.y + (b.y - a.y) * f, floor_id: a.floor_id, moving: moved ? true : a.moving };
}

/** Same-floor points in (t - trailSec, t], plus the interpolated head at t. */
export function trailAt(points: PathPoint[], t: number, trailSec: number): TrailPoint[] {
  const pose = poseAt(points, t);
  if (!pose) return [];
  const out: TrailPoint[] = [];
  for (let j = indexAt(points, t); j >= 0; j--) {
    const p = points[j];
    if (p.ts < t - trailSec || p.floor_id !== pose.floor_id) break;
    out.unshift({ x: p.x, y: p.y, ts: p.ts });
  }
  out.push({ x: pose.x, y: pose.y, ts: t });
  return out;
}

export function floorSegments(points: PathPoint[]): { floor_id: string; start: number; end: number }[] {
  const segs: { floor_id: string; start: number; end: number }[] = [];
  for (const p of points) {
    const last = segs[segs.length - 1];
    if (last) last.end = p.ts;
    if (!last || last.floor_id !== p.floor_id) segs.push({ floor_id: p.floor_id, start: p.ts, end: p.ts });
  }
  return segs;
}

export function visitIndexAt(visits: VisitRow[], t: number): number {
  for (let i = visits.length - 1; i >= 0; i--)
    if (visits[i].start <= t && (visits[i].end ?? Infinity) > t) return i;
  return -1;
}

/** Local-day bounds in unix seconds (the browser's time zone). */
export function dayBounds(date: string): [number, number] {
  const d = new Date(`${date}T00:00:00`);
  const next = new Date(d);
  next.setDate(d.getDate() + 1);
  return [d.getTime() / 1000, next.getTime() / 1000];
}

export const todayISO = () => new Date().toLocaleDateString("en-CA");
export const fmtTime = (ts: number) =>
  new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
```

**Step 4: Run test, verify pass**
Run: `cd box/web && pnpm vitest run src/lib/replay.test.ts`
Expected: PASS (all tests green)

**Step 5: Commit**
```bash
git add box/web/src/lib/types.ts box/web/src/lib/replay.ts box/web/src/lib/replay.test.ts
git commit -m "feat: replay math (pose, trail, floor strip, visits) and types" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: Replay components: PetMarker, Trail, FloorTabs, useReplayClock, CSS

**Files:**
- Create: `box/web/src/components/replay/PetMarker.tsx`
- Create: `box/web/src/components/replay/Trail.tsx`
- Create: `box/web/src/components/replay/FloorTabs.tsx` (skip it if plan 02 already exports an equivalent `FloorTabs`, and import that one instead in Tasks 12, 13 and 17)
- Create: `box/web/src/components/replay/useReplayClock.ts`
- Create: `box/web/src/components/replay/replay.css`
- Test: `box/web/src/components/replay/PetMarker.test.tsx`

**Step 1: Write failing test**
```tsx
// box/web/src/components/replay/PetMarker.test.tsx
// @vitest-environment jsdom
import { render } from "@testing-library/react";
import { expect, it } from "vitest";
import { PetMarker } from "./PetMarker";

it("draws a halo that grows as confidence drops, and pulses while moving", () => {
  const { container, rerender } = render(<svg><PetMarker x={1} y={2} confidence={1} moving={false} /></svg>);
  const halo = () => Number(container.querySelector(".pet-halo")!.getAttribute("r"));
  const sure = halo();
  expect(container.querySelector(".pet-moving")).toBeNull();
  rerender(<svg><PetMarker x={1} y={2} confidence={0.2} moving /></svg>);
  expect(halo()).toBeGreaterThan(sure);
  expect(container.querySelector(".pet-moving")).not.toBeNull();
});
```

**Step 2: Run test, verify failure**
Run: `cd box/web && pnpm add -D jsdom && pnpm vitest run src/components/replay`
Expected: FAIL with `Failed to resolve import "./PetMarker"`

**Step 3: Implement**
```tsx
// box/web/src/components/replay/PetMarker.tsx
import "./replay.css";

type Props = { x: number; y: number; confidence: number; moving: boolean; label?: string; animate?: boolean };

/** Pet dot in plan metres. The halo radius shows uncertainty; it pulses while moving. */
export function PetMarker({ x, y, confidence, moving, label, animate }: Props) {
  const halo = 0.3 + (1 - Math.max(0, Math.min(1, confidence))) * 1.5;
  return (
    <g data-testid="pet-marker" className={animate ? "pet-marker glide" : "pet-marker"}
       style={{ transform: `translate(${x}px, ${y}px)` }}>
      <circle r={halo} className="pet-halo" />
      <circle r={0.25} className={moving ? "pet-dot pet-moving" : "pet-dot"} />
      {label && <text y={-0.45} className="pet-label">{label}</text>}
    </g>
  );
}
```
```tsx
// box/web/src/components/replay/Trail.tsx
import type { TrailPoint } from "../../lib/replay";

/** Path behind the pet; older segments fade out over trailSec. */
export function Trail({ points, t, trailSec }: { points: TrailPoint[]; t: number; trailSec: number }) {
  return (
    <g>
      {points.slice(1).map((p, i) => {
        const a = points[i];
        return <line key={i} className="trail" x1={a.x} y1={a.y} x2={p.x} y2={p.y}
                     opacity={Math.max(0.05, 1 - (t - p.ts) / trailSec)} />;
      })}
    </g>
  );
}
```
```tsx
// box/web/src/components/replay/FloorTabs.tsx
import type { Floor } from "../../lib/types";

export function FloorTabs({ floors, value, onChange }: { floors: Floor[]; value: string; onChange: (id: string) => void }) {
  return (
    <div className="floor-tabs" role="tablist">
      {floors.map((f) => (
        <button key={f.id} role="tab" aria-selected={f.id === value} onClick={() => onChange(f.id)}>{f.name}</button>
      ))}
    </div>
  );
}
```
```ts
// box/web/src/components/replay/useReplayClock.ts
import { useEffect, useState } from "react";

/** Replay time in unix seconds; advances at `speed`× real time while playing, capped at `end`. */
export function useReplayClock(start: number, end: number, speed: number, playing: boolean) {
  const [t, setT] = useState(start);
  useEffect(() => setT(start), [start]);
  useEffect(() => {
    if (!playing) return;
    let raf = 0, last = performance.now();
    const tick = (now: number) => {
      setT((cur) => Math.min(end, cur + ((now - last) / 1000) * speed));
      last = now;
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing, speed, end]);
  return [t, setT] as const;
}
```
```css
/* box/web/src/components/replay/replay.css (SVG sizes are metres) */
.pet-halo { fill: var(--accent); fill-opacity: .15; stroke: var(--accent); stroke-opacity: .35; stroke-width: .03; }
.pet-dot { fill: var(--accent); stroke: #fff; stroke-width: .06; }
.pet-moving { animation: pet-pulse 1s ease-in-out infinite; transform-box: fill-box; transform-origin: center; }
@keyframes pet-pulse { 50% { transform: scale(1.5); } }
.pet-label { font-size: .35px; text-anchor: middle; fill: var(--text); font-weight: 600; }
.pet-marker.glide { transition: transform 1.5s linear; }
.trail { stroke: var(--accent); stroke-width: .12; stroke-linecap: round; }
.raw-dot { fill: var(--warn); fill-opacity: .6; }
.node-dot { stroke: #fff; stroke-width: .05; }
.node-dot.online { fill: var(--accent-2); }
.node-dot.offline { fill: var(--danger); }

.floor-tabs { display: flex; gap: 4px; }
.floor-tabs button { border: 1px solid var(--line); background: var(--panel); color: var(--muted); border-radius: var(--radius); padding: 4px 10px; font: inherit; cursor: pointer; }
.floor-tabs button[aria-selected="true"] { color: var(--accent); border-color: var(--accent); }

.replay-page { display: flex; height: 100%; background: var(--bg); color: var(--text); font-family: var(--font); }
.replay-main { flex: 1; display: flex; flex-direction: column; gap: 8px; padding: 12px; min-width: 0; }
.replay-main > svg, .replay-main > .plan-canvas { flex: 1; min-height: 0; }
.side-panel { width: 320px; border-left: 1px solid var(--line); background: var(--panel); padding: 16px; overflow-y: auto; }
.page-empty { padding: 24px; color: var(--muted); }
.muted { color: var(--muted); }
.place-card { border: 1px solid var(--line); border-radius: var(--radius); padding: 12px; margin-bottom: 12px; }
.place-card h2 { margin: 0 0 4px; font-size: 16px; }
.place-card .place { margin: 0 0 4px; font-weight: 600; }
.replay-toolbar, .replay-controls { display: flex; gap: 12px; align-items: center; }
.replay-time { font-variant-numeric: tabular-nums; }
.floor-strip { position: relative; height: 10px; background: var(--line); border-radius: 5px; overflow: hidden; }
.floor-seg { position: absolute; top: 0; bottom: 0; }
.floor-0 { background: var(--accent); } .floor-1 { background: var(--accent-2); } .floor-2 { background: var(--warn); }
.floor-strip-cursor { position: absolute; top: 0; bottom: 0; width: 2px; background: var(--text); }
.scrubber { width: 100%; }
.visit-list { list-style: none; margin: 0; padding: 0; }
.visit-list button { width: 100%; text-align: left; background: none; border: 0; border-radius: var(--radius); padding: 6px 8px; font: inherit; color: inherit; cursor: pointer; }
.visit-list li.active button { background: rgba(0, 111, 255, .08); color: var(--accent); }
.visit-time { font-variant-numeric: tabular-nums; color: var(--muted); margin-right: 6px; }
```

**Step 4: Run test, verify pass**
Run: `cd box/web && pnpm vitest run src/components/replay && pnpm tsc --noEmit`
Expected: PASS, and no type errors

**Step 5: Commit**
```bash
git add box/web/src/components/replay box/web/package.json box/web/pnpm-lock.yaml
git commit -m "feat: shared replay overlays (marker, trail, floor tabs, clock)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: `Live.tsx` page

**Files:**
- Modify (replace the placeholder): `box/web/src/pages/Live.tsx`
- Test: covered by e2e in Task 14. Here: typecheck + build.

**Step 1: Write failing test:** the e2e in Task 14 covers the page. For this task the "failing check" is the typecheck of the new imports.
**Step 2: Run test, verify failure**
Run: `cd box/web && pnpm tsc --noEmit`
Expected: passes before the change. After Step 3 it must still pass (this is the gate for this task).

**Step 3: Implement**
```tsx
// box/web/src/pages/Live.tsx
import { useCallback, useEffect, useState } from "react";
import { PlanCanvas } from "../components/plan/PlanCanvas";
import { FloorTabs } from "../components/replay/FloorTabs";
import { PetMarker } from "../components/replay/PetMarker";
import "../components/replay/replay.css";
import { apiGet } from "../lib/api";
import { fmtTime } from "../lib/replay";
import type { LiveEntry, Node, PlanPayload } from "../lib/types";
import { subscribe } from "../lib/ws";

export default function Live() {
  const [plan, setPlan] = useState<PlanPayload | null>(null);
  const [live, setLive] = useState<LiveEntry[]>([]);
  const [nodes, setNodes] = useState<Node[]>([]);
  const [floorId, setFloorId] = useState<string | null>(null);

  const loadPlan = useCallback(() => void apiGet<PlanPayload>("/api/home").then(setPlan), []);
  const loadLive = useCallback(() => void apiGet<LiveEntry[]>("/api/live").then(setLive), []);
  const loadNodes = useCallback(() => void apiGet<Node[]>("/api/nodes").then(setNodes), []);

  useEffect(() => {
    loadPlan(); loadLive(); loadNodes();
    const offs = [subscribe("position", loadLive), subscribe("node.health", loadNodes), subscribe("home.saved", loadPlan)];
    return () => offs.forEach((off) => off());
  }, [loadPlan, loadLive, loadNodes]);

  // Follow the first pet across floors; the tabs still let you look at another floor.
  const petFloor = live.find((e) => e.floor_id)?.floor_id ?? null;
  useEffect(() => { if (petFloor) setFloorId(petFloor); }, [petFloor]);

  if (!plan) return <div className="page-empty">Loading…</div>;
  const floor = floorId ?? plan.home.floors[0]?.id;
  if (!floor) return <div className="page-empty">Draw your home in the Editor first.</div>;
  const online = new Map(nodes.map((n) => [n.id, Boolean(n.online)]));

  return (
    <div className="replay-page">
      <div className="replay-main">
        <FloorTabs floors={plan.home.floors} value={floor} onChange={setFloorId} />
        <PlanCanvas home={plan.home} rooms={plan.rooms} floorId={floor}>
          {plan.home.nodes.filter((n) => n.floor_id === floor).map((n) => (
            <circle key={n.id} className={`node-dot ${online.get(n.id) ? "online" : "offline"}`} cx={n.x} cy={n.y} r={0.18}>
              <title>{n.name}</title>
            </circle>
          ))}
          {live.filter((e) => e.floor_id === floor && e.x !== null && e.y !== null).map((e) => (
            <PetMarker key={e.pet.id} x={e.x!} y={e.y!} confidence={e.confidence ?? 0}
                       moving={Boolean(e.moving)} label={e.pet.name} animate />
          ))}
        </PlanCanvas>
      </div>
      <aside className="side-panel">
        {live.map((e) => <PlaceCard key={e.pet.id} e={e} />)}
        {live.length === 0 && <p className="muted">No pets yet. Add one in Setup.</p>}
      </aside>
    </div>
  );
}

function PlaceCard({ e }: { e: LiveEntry }) {
  const where = e.away ? "Away (tag not heard)"
    : e.place ? [e.place, e.place_kind === "landmark" ? e.room_name : null, e.floor_name].filter(Boolean).join(" · ")
    : "No position yet";
  return (
    <section className="place-card" data-testid="place-card">
      <h2>{e.pet.name}</h2>
      <p className="place">{where}</p>
      {e.ts !== null && (
        <p className="muted">
          {e.moving ? "Moving" : "Still"}
          {e.since !== null && ` · since ${fmtTime(e.since)}`}
          {e.confidence !== null && ` · ${Math.round(e.confidence * 100)}% sure`}
        </p>
      )}
    </section>
  );
}
```

**Step 4: Run test, verify pass**
Run: `cd box/web && pnpm tsc --noEmit && pnpm test`
Expected: PASS

**Step 5: Commit**
```bash
git add box/web/src/pages/Live.tsx
git commit -m "feat: Live page with pet marker, place card and node health" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 13: `History.tsx` page

**Files:**
- Modify (replace the placeholder): `box/web/src/pages/History.tsx`

**Step 1: Write failing test:** covered by e2e (Task 14).
**Step 2: Run test, verify failure:** `cd box/web && pnpm tsc --noEmit` (gate).

**Step 3: Implement**
```tsx
// box/web/src/pages/History.tsx
import { useEffect, useMemo, useRef, useState } from "react";
import { PlanCanvas } from "../components/plan/PlanCanvas";
import { FloorTabs } from "../components/replay/FloorTabs";
import { PetMarker } from "../components/replay/PetMarker";
import { Trail } from "../components/replay/Trail";
import { useReplayClock } from "../components/replay/useReplayClock";
import "../components/replay/replay.css";
import { apiGet } from "../lib/api";
import { dayBounds, floorSegments, fmtTime, poseAt, todayISO, trailAt, visitIndexAt } from "../lib/replay";
import type { PathResponse, PlanPayload, VisitRow } from "../lib/types";

const TRAIL_S = 300;
const SPEEDS = [1, 5, 15, 30, 60, 120];
type Pet = { id: number; name: string };

export default function History() {
  const [date, setDate] = useState(() => new URLSearchParams(location.search).get("date") ?? todayISO());
  const [pets, setPets] = useState<Pet[]>([]);
  const [pet, setPet] = useState("");
  const [plan, setPlan] = useState<PlanPayload | null>(null);
  const [path, setPath] = useState<PathResponse>({ points: [] });
  const [visits, setVisits] = useState<VisitRow[]>([]);
  const [showRaw, setShowRaw] = useState(false);
  const [speed, setSpeed] = useState(60);
  const [playing, setPlaying] = useState(false);
  const [floorOverride, setFloorOverride] = useState<string | null>(null);
  const [t0, t1] = useMemo(() => dayBounds(date), [date]);

  useEffect(() => {
    void apiGet<PlanPayload>("/api/home").then(setPlan);
    void apiGet<Pet[]>("/api/pets").then((ps) => { setPets(ps); if (ps[0]) setPet(ps[0].name); });
  }, []);

  useEffect(() => {
    if (!pet) return;
    const q = `pet=${encodeURIComponent(pet)}&from=${t0}&to=${t1}`;
    setPlaying(false);
    void apiGet<PathResponse>(`/api/history/path?${q}${showRaw ? "&raw=true" : ""}`).then(setPath);
    void apiGet<VisitRow[]>(`/api/history/visits?${q}`).then(setVisits);
  }, [pet, t0, t1, showRaw]);

  const pts = path.points;
  const first = pts[0]?.ts ?? t0;
  const last = pts[pts.length - 1]?.ts ?? t1;
  const [t, setT] = useReplayClock(first, t1, speed, playing);
  useEffect(() => { if (playing && t >= last) setPlaying(false); }, [t, playing, last]);

  const active = visitIndexAt(visits, t);
  const activeRef = useRef<HTMLLIElement>(null);
  useEffect(() => { activeRef.current?.scrollIntoView({ block: "nearest" }); }, [active]);

  if (!plan) return <div className="page-empty">Loading…</div>;
  const floors = plan.home.floors;
  const pose = poseAt(pts, t);
  const floor = floorOverride ?? pose?.floor_id ?? floors[0]?.id;
  if (!floor) return <div className="page-empty">Draw your home in the Editor first.</div>;
  const floorIdx = new Map(floors.map((f, i) => [f.id, i]));
  const pct = (ts: number) => ((ts - t0) / (t1 - t0)) * 100;
  const seek = (ts: number) => { setPlaying(false); setFloorOverride(null); setT(ts); };
  const togglePlay = () => {
    setFloorOverride(null);
    if (!playing && t >= last) setT(first);
    setPlaying(!playing);
  };

  return (
    <div className="replay-page">
      <div className="replay-main">
        <div className="replay-toolbar">
          <input type="date" aria-label="Day" value={date} onChange={(e) => e.target.value && setDate(e.target.value)} />
          {pets.length > 1 && (
            <select aria-label="Pet" value={pet} onChange={(e) => setPet(e.target.value)}>
              {pets.map((p) => <option key={p.id}>{p.name}</option>)}
            </select>
          )}
          <label><input type="checkbox" checked={showRaw} onChange={(e) => setShowRaw(e.target.checked)} /> Raw evidence</label>
        </div>
        <FloorTabs floors={floors} value={floor} onChange={setFloorOverride} />
        <PlanCanvas home={plan.home} rooms={plan.rooms} floorId={floor}>
          {showRaw && path.raw?.filter((d) => d.floor_id === floor && d.ts <= t && d.ts > t - TRAIL_S).map((d) => (
            <circle key={d.ts} className="raw-dot" cx={d.x} cy={d.y} r={0.12} />
          ))}
          {pose && pose.floor_id === floor && (
            <>
              <Trail points={trailAt(pts, t, TRAIL_S)} t={t} trailSec={TRAIL_S} />
              <PetMarker x={pose.x} y={pose.y} confidence={1} moving={Boolean(pose.moving)} />
            </>
          )}
        </PlanCanvas>
        <div className="replay-controls">
          <button onClick={togglePlay} disabled={!pts.length}>{playing ? "Pause" : "Play"}</button>
          <select aria-label="Speed" value={speed} onChange={(e) => setSpeed(Number(e.target.value))}>
            {SPEEDS.map((s) => <option key={s} value={s}>{s}×</option>)}
          </select>
          <span className="replay-time" data-testid="replay-time">{fmtTime(t)}</span>
          {!pts.length && <span className="muted">No path recorded this day.</span>}
        </div>
        <div className="floor-strip" aria-hidden>
          {floorSegments(pts).map((s) => {
            const i = floorIdx.get(s.floor_id) ?? 0;
            return <div key={s.start} className={`floor-seg floor-${i % 3}`} title={floors[i]?.name}
                        style={{ left: `${pct(s.start)}%`, width: `${Math.max(0.2, pct(s.end) - pct(s.start))}%` }} />;
          })}
          <div className="floor-strip-cursor" style={{ left: `${pct(t)}%` }} />
        </div>
        <input className="scrubber" type="range" aria-label="Time" min={t0} max={t1} step={1} value={t}
               onChange={(e) => seek(Number(e.target.value))} />
      </div>
      <aside className="side-panel">
        <h2>Visits</h2>
        {visits.length === 0 && <p className="muted">No visits recorded this day.</p>}
        <ol className="visit-list">
          {visits.map((v, i) => (
            <li key={v.id} ref={i === active ? activeRef : undefined} className={i === active ? "active" : undefined}>
              <button onClick={() => seek(v.start)}>
                <span className="visit-time">{fmtTime(v.start)}</span>{v.name}
                <span className="muted"> {v.end !== null ? `${Math.round((v.end - v.start) / 60)} min` : "now"}</span>
              </button>
            </li>
          ))}
        </ol>
      </aside>
    </div>
  );
}
```

**Step 4: Run test, verify pass**
Run: `cd box/web && pnpm tsc --noEmit && pnpm test && pnpm build`
Expected: PASS, and the build succeeds

**Step 5: Commit**
```bash
git add box/web/src/pages/History.tsx
git commit -m "feat: History page with path replay, scrubber, floor strip and visits" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 14: Playwright e2e for Live + History on a seeded db

**Files:**
- Create: `box/web/playwright.live.config.ts`
- Create: `box/web/e2e/live-history/live-history.spec.ts`
- Modify: `box/web/package.json` (the `e2e:live` script)

**Step 1: Write failing test**
```ts
// box/web/playwright.live.config.ts
import { defineConfig } from "@playwright/test";

const DATA = "/tmp/wa-e2e";
export default defineConfig({
  testDir: "e2e/live-history",
  use: { baseURL: "http://127.0.0.1:8099", timezoneId: "America/New_York" },
  webServer: {
    // Fresh db seeded with the sample home and 2026-09-27; box serves the built GUI (run `pnpm build` first).
    command: `bash -c 'rm -rf ${DATA} && mkdir -p ${DATA} && cd .. && uv run python -m wheres_allie.devseed ${DATA}/wheres_allie.db --date 2026-09-27 && WA_DATA_DIR=${DATA} WA_HTTP_PORT=8099 WA_MQTT_HOST=127.0.0.1 WA_MQTT_PASS=e2e uv run wheres-allie serve'`,
    url: "http://127.0.0.1:8099/api/health",
    timeout: 60_000,
    reuseExistingServer: false,
  },
});
```
```ts
// box/web/e2e/live-history/live-history.spec.ts
import { expect, test } from "@playwright/test";

test("live shows Allie's card and the node health dots", async ({ page }) => {
  await page.goto("/live");
  await expect(page.getByTestId("place-card")).toContainText("Allie");
  await expect(page.locator(".node-dot")).toHaveCount(2); // main floor: kitchen + master_bedroom
});

test("history replays the seeded day across floors", async ({ page }) => {
  await page.goto("/history?date=2026-09-27");
  const visits = page.locator(".visit-list li");
  await expect(visits).toHaveCount(6);
  await visits.filter({ hasText: "Loft" }).getByRole("button").click();
  await expect(page.getByRole("tab", { name: "Upstairs" })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByTestId("pet-marker")).toBeVisible();

  await visits.first().getByRole("button").click();
  await expect(page.getByRole("tab", { name: "Main" })).toHaveAttribute("aria-selected", "true");
  const before = await page.getByTestId("replay-time").textContent();
  await page.getByLabel("Speed").selectOption("120");
  await page.getByRole("button", { name: "Play" }).click();
  await expect(page.getByTestId("replay-time")).not.toHaveText(before ?? "", { timeout: 5_000 });
  await page.getByRole("button", { name: "Pause" }).click();
});
```
Add to the `scripts` in `box/web/package.json`: `"e2e:live": "playwright test -c playwright.live.config.ts"`.

**Step 2: Run test, verify failure**
Run: `cd box/web && pnpm exec playwright install chromium && pnpm e2e:live`
Expected: before Tasks 12–13 are built it FAILS (no `place-card` / `.visit-list`). If it already passes because Tasks 12–13 are done, break it once by changing `toHaveCount(6)` to 7, confirm the failure, then revert.

**Step 3: Implement:** no production code (Tasks 6–13 are the implementation). Build the GUI the box serves: `cd box/web && pnpm build`.

**Step 4: Run test, verify pass**
Run: `cd box/web && pnpm build && pnpm e2e:live`
Expected: PASS (2 passed)

**Step 5: Commit**
```bash
git add box/web/playwright.live.config.ts box/web/e2e/live-history box/web/package.json
git commit -m "test: e2e for Live and History against a seeded box" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 15: Phase 5 gate: full test run + push

**Files:** none.

**Step 1–2:** n/a.
**Step 3:** Update this plan's status table rows 1–14 to `done | yes | no`.
**Step 4: Run test, verify pass**
Run: `cd box && uv run ruff check . && uv run pytest -q && cd web && pnpm test && pnpm build && pnpm e2e:live`
Expected: everything green
**Step 5: Commit + push**
```bash
git add docs/plans/2026-09-28-wheres-allie-plan-04-live-history-mcpapp.md
git commit -m "docs: phase 5 (live + history) complete" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push origin main
```
Then set the Pushed column to `yes` for rows 1–15 (this gets committed with the next task).

---

### Task 16: MCP App deps + `bridge.ts`

**Files:**
- Modify: `box/web/package.json`
- Create: `box/web/src/mcp-app/bridge.ts`
- Test: `box/web/src/mcp-app/bridge.test.ts`

**Step 1: Write failing test**
```ts
// box/web/src/mcp-app/bridge.test.ts
import { expect, it } from "vitest";
import { extractToolData } from "./bridge";

it("reads structuredContent from a tool-result notification only", () => {
  const msg = { jsonrpc: "2.0", method: "ui/notifications/tool-result", params: { structuredContent: { pet: "Allie" } } };
  expect(extractToolData(msg)).toEqual({ pet: "Allie" });
  expect(extractToolData({ method: "ui/notifications/tool-input", params: {} })).toBeNull();
  expect(extractToolData("junk")).toBeNull();
});
```

**Step 2: Run test, verify failure**
Run: `cd box/web && pnpm add @modelcontextprotocol/ext-apps && pnpm add -D vite-plugin-singlefile && pnpm vitest run src/mcp-app`
Expected: FAIL with `Failed to resolve import "./bridge"`
If `@modelcontextprotocol/ext-apps` fails to install, skip it and delete the `App` block in Step 3. The raw `postMessage` path is enough for the harness, but it does **not** perform the `ui/initialize` handshake that real hosts expect. Record that in `docs/friction-log.md`.

**Step 3: Implement**
```ts
// box/web/src/mcp-app/bridge.ts
// Host bridge for the MCP App: the ext-apps SDK for real hosts, plus a raw postMessage
// fallback (same JSON-RPC notification) for the dev harness and Playwright.
import { App } from "@modelcontextprotocol/ext-apps";
import type { AppView } from "../lib/types";

export type ToolData = { pet?: string; place?: string; date?: string; app?: AppView | null };

export function extractToolData(msg: unknown): ToolData | null {
  const m = msg as { method?: string; params?: { structuredContent?: ToolData } } | null;
  if (typeof m !== "object" || m?.method !== "ui/notifications/tool-result") return null;
  return m.params?.structuredContent ?? null;
}

export function connectHost(onData: (d: ToolData) => void): void {
  window.addEventListener("message", (e) => {
    if (e.source !== window.parent) return;
    const d = extractToolData(e.data);
    if (d) onData(d);
  });
  try {
    const app = new App({ name: "wheres-allie-floorplan", version: "1.0.0" });
    app.ontoolresult = (result) => {
      const sc = (result as { structuredContent?: ToolData }).structuredContent;
      if (sc) onData(sc);
    };
    Promise.resolve(app.connect()).catch(() => {}); // no host (harness): raw listener above still works
  } catch {
    /* no host */
  }
}
```

**Step 4: Run test, verify pass**
Run: `cd box/web && pnpm vitest run src/mcp-app && pnpm tsc --noEmit`
Expected: PASS

**Step 5: Commit**
```bash
git add box/web/package.json box/web/pnpm-lock.yaml box/web/src/mcp-app/bridge.ts box/web/src/mcp-app/bridge.test.ts docs/plans/2026-09-28-wheres-allie-plan-04-live-history-mcpapp.md
git commit -m "feat: MCP App host bridge (ext-apps + postMessage fallback)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 17: MCP App sample data + `FloorplanApp.tsx`

**Files:**
- Create: `box/web/src/mcp-app/sample.ts`
- Create: `box/web/src/mcp-app/FloorplanApp.tsx`
- Create: `box/web/src/mcp-app/mcp-app.css`
- Test: `box/web/src/mcp-app/FloorplanApp.test.tsx`

**Step 1: Write failing test**
```tsx
// box/web/src/mcp-app/FloorplanApp.test.tsx
// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { FloorplanApp } from "./FloorplanApp";
import { samplePath, samplePosition } from "./sample";

it("waits until a tool result arrives", () => {
  render(<FloorplanApp data={null} />);
  expect(screen.getByText(/Waiting/)).toBeTruthy();
});

it("shows the pet on the plan for where_is", () => {
  render(<FloorplanApp data={samplePosition} />);
  expect(screen.getByTestId("pet-marker")).toBeTruthy();
  expect(screen.getByText("Allie · Allie's bed")).toBeTruthy();
});

it("plays the path for timeline/day_summary", () => {
  render(<FloorplanApp data={samplePath} />);
  expect(screen.getByTestId("pet-marker")).toBeTruthy();
  expect(screen.getByRole("button", { name: "Pause" })).toBeTruthy(); // autoplays
  expect(screen.getByLabelText("Time")).toBeTruthy();
});
```

**Step 2: Run test, verify failure**
Run: `cd box/web && pnpm vitest run src/mcp-app`
Expected: FAIL with `Failed to resolve import "./FloorplanApp"`

**Step 3: Implement**
```ts
// box/web/src/mcp-app/sample.ts
// Sample tool results for tests and the dev harness (same home as box devseed.py).
import type { Home, PathPoint, Room } from "../lib/types";
import type { ToolData } from "./bridge";

type XY = [number, number];
const wall = (id: string, floor_id: string, a: XY, b: XY) => ({ id, floor_id, a, b, thickness_m: 0.12, invisible: false });
const box = (x0: number, y0: number, x1: number, y1: number): XY[] => [[x0, y0], [x1, y0], [x1, y1], [x0, y1]];

const home: Home = {
  version: 1,
  floors: [{ id: "main", name: "Main", elevation_m: 3, underlay: null }, { id: "up", name: "Upstairs", elevation_m: 6, underlay: null }],
  walls: [
    wall("m1", "main", [0, 0], [8, 0]), wall("m2", "main", [8, 0], [8, 4]), wall("m3", "main", [8, 4], [0, 4]),
    wall("m4", "main", [0, 4], [0, 0]), wall("m5", "main", [4, 0], [4, 4]),
    wall("u1", "up", [0, 0], [4, 0]), wall("u2", "up", [4, 0], [4, 4]), wall("u3", "up", [4, 4], [0, 4]), wall("u4", "up", [0, 4], [0, 0]),
  ],
  room_labels: [
    { id: "kitchen", floor_id: "main", name: "Kitchen", seed: [2, 2] },
    { id: "bedroom", floor_id: "main", name: "Master Bedroom", seed: [6, 2] },
    { id: "loft", floor_id: "up", name: "Loft", seed: [2, 2] },
  ],
  doors: [{ id: "d1", wall_id: "m5", t: 0.5, width_m: 0.9 }],
  stairs: [{ id: "s1", name: "Stairs", a: { floor_id: "main", x: 7, y: 3 }, b: { floor_id: "up", x: 3, y: 3 } }],
  landmarks: [
    { id: "bowl", floor_id: "main", x: 1, y: 1, type: "water_bowl", name: "Water bowl", radius_m: 0.75 },
    { id: "bed", floor_id: "main", x: 7, y: 1, type: "bed", name: "Allie's bed", radius_m: 0.75 },
  ],
  nodes: [],
};
const rooms: Room[] = [
  { id: "kitchen", floor_id: "main", name: "Kitchen", polygon: box(0, 0, 4, 4) },
  { id: "bedroom", floor_id: "main", name: "Master Bedroom", polygon: box(4, 0, 8, 4) },
  { id: "loft", floor_id: "up", name: "Loft", polygon: box(0, 0, 4, 4) },
];
const plan = { home, rooms };
const T = 1_790_000_000;
const P = (dt: number, vertex_id: string, floor_id: string, x: number, y: number, moving = false): PathPoint =>
  ({ ts: T + dt, vertex_id, floor_id, x, y, moving });

export const samplePosition: ToolData = {
  pet: "Allie", place: "Allie's bed",
  app: { view: "position", plan, position: { ts: T, vertex_id: "lm:bed", floor_id: "main", x: 7, y: 1, confidence: 0.86, moving: false } },
};
export const samplePath: ToolData = {
  pet: "Allie", date: "2026-09-27",
  app: {
    view: "path", plan,
    path: [
      P(0, "room:kitchen", "main", 2, 2), P(600, "room:kitchen", "main", 2, 2),
      P(603, "door:d1", "main", 4, 2, true), P(606, "lm:bed", "main", 7, 1, true), P(1800, "lm:bed", "main", 7, 1),
      P(1802, "stairs:s1:a", "main", 7, 3, true), P(1806, "stairs:s1:b", "up", 3, 3, true),
      P(1808, "room:loft", "up", 2, 2, true), P(2400, "room:loft", "up", 2, 2),
    ],
  },
};
```
```tsx
// box/web/src/mcp-app/FloorplanApp.tsx
import { useEffect, useState } from "react";
import { PlanCanvas } from "../components/plan/PlanCanvas";
import { PetMarker } from "../components/replay/PetMarker";
import { Trail } from "../components/replay/Trail";
import { useReplayClock } from "../components/replay/useReplayClock";
import { fmtTime, poseAt, trailAt } from "../lib/replay";
import type { AppView } from "../lib/types";
import type { ToolData } from "./bridge";
import "./mcp-app.css";

const PLAYBACK_S = 60; // any range replays in about a minute
const TRAIL_S = 1800;

export function FloorplanApp({ data }: { data: ToolData | null }) {
  const app = data?.app;
  if (!app || (app.view === "path" && !app.path.length))
    return <div className="mcp-empty">Waiting for {data?.pet ?? "your pet"}'s data…</div>;
  const title = [data?.pet, data?.place].filter(Boolean).join(" · ");
  return (
    <div className="mcp-root">
      {title && <header className="mcp-title">{title}</header>}
      {app.view === "position" ? <PositionView app={app} /> : <PathView app={app} />}
    </div>
  );
}

function PositionView({ app }: { app: Extract<AppView, { view: "position" }> }) {
  const p = app.position;
  return (
    <PlanCanvas home={app.plan.home} rooms={app.plan.rooms} floorId={p.floor_id}>
      <PetMarker x={p.x} y={p.y} confidence={p.confidence} moving={Boolean(p.moving)} />
    </PlanCanvas>
  );
}

function PathView({ app }: { app: Extract<AppView, { view: "path" }> }) {
  const pts = app.path;
  const start = pts[0].ts, end = pts[pts.length - 1].ts;
  const [playing, setPlaying] = useState(true);
  const [t, setT] = useReplayClock(start, end, Math.max(1, (end - start) / PLAYBACK_S), playing);
  useEffect(() => { if (t >= end) setPlaying(false); }, [t, end]);
  const pose = poseAt(pts, t);
  const floorId = pose?.floor_id ?? pts[0].floor_id;
  const floorName = app.plan.home.floors.find((f) => f.id === floorId)?.name ?? "";
  return (
    <>
      <PlanCanvas home={app.plan.home} rooms={app.plan.rooms} floorId={floorId}>
        <Trail points={trailAt(pts, t, TRAIL_S)} t={t} trailSec={TRAIL_S} />
        {pose && <PetMarker x={pose.x} y={pose.y} confidence={1} moving={Boolean(pose.moving)} />}
      </PlanCanvas>
      <div className="mcp-player">
        <button onClick={() => { if (!playing && t >= end) setT(start); setPlaying(!playing); }}>
          {playing ? "Pause" : "Play"}
        </button>
        <input type="range" aria-label="Time" min={start} max={end} step={1} value={t}
               onChange={(e) => { setPlaying(false); setT(Number(e.target.value)); }} />
        <span className="mcp-clock">{fmtTime(t)} · {floorName}</span>
      </div>
    </>
  );
}
```
```css
/* box/web/src/mcp-app/mcp-app.css */
html, body, #root { margin: 0; height: 100%; background: var(--bg); color: var(--text); font-family: var(--font); }
.mcp-root { display: flex; flex-direction: column; height: 100vh; }
.mcp-root > svg, .mcp-root > .plan-canvas { flex: 1; min-height: 0; }
.mcp-title { padding: 8px 12px; font-weight: 600; font-size: clamp(14px, 3vw, 22px); }
.mcp-empty { display: grid; place-items: center; height: 100vh; color: var(--muted); }
.mcp-player { display: flex; gap: 12px; align-items: center; padding: 8px 12px; }
.mcp-player input { flex: 1; }
.mcp-player button { min-width: 72px; min-height: 40px; border-radius: var(--radius); border: 1px solid var(--line); background: var(--panel); color: var(--text); font: inherit; }
.mcp-clock { font-variant-numeric: tabular-nums; white-space: nowrap; }
```

**Step 4: Run test, verify pass**
Run: `cd box/web && pnpm vitest run src/mcp-app && pnpm tsc --noEmit`
Expected: PASS (4 tests). If `tsc` complains about the sample `Home` fields, align `sample.ts` with plan 02's `types.ts` (field names are fixed by conventions §6).

**Step 5: Commit**
```bash
git add box/web/src/mcp-app/
git commit -m "feat: MCP App floorplan view (current dot + path mini-player)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 18: MCP App entry, single-file build config, dev harness

**Files:**
- Create: `box/web/src/mcp-app/index.html`
- Create: `box/web/src/mcp-app/main.tsx`
- Create: `box/web/src/mcp-app/dev.html`
- Create: `box/web/src/mcp-app/dev.ts`
- Create: `box/web/vite.mcp-app.config.ts`
- Modify: `box/web/package.json` (the `build:mcp-app` and `dev:mcp-app` scripts)
- Output (committed): `box/src/wheres_allie/mcp/static/index.html`

**Step 1: Write failing test**
The check is a shell assertion on the build output:
```bash
cd box/web && test -f ../src/wheres_allie/mcp/static/index.html && grep -q '<div id="root"></div>' ../src/wheres_allie/mcp/static/index.html && ! grep -q '<script[^>]*src=' ../src/wheres_allie/mcp/static/index.html && echo OK
```
**Step 2: Run test, verify failure**
Expected: no output and exit code 1 (the file doesn't exist yet)

**Step 3: Implement**
```html
<!-- box/web/src/mcp-app/index.html -->
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Where's Allie</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="./main.tsx"></script>
  </body>
</html>
```
```tsx
// box/web/src/mcp-app/main.tsx
import { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "../theme/tokens.css";
import { connectHost, type ToolData } from "./bridge";
import { FloorplanApp } from "./FloorplanApp";

document.documentElement.dataset.theme = matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";

function Root() {
  const [data, setData] = useState<ToolData | null>(null);
  useEffect(() => connectHost(setData), []); // not StrictMode: the bridge connects exactly once
  return <FloorplanApp data={data} />;
}

createRoot(document.getElementById("root")!).render(<Root />);
```
```ts
// box/web/vite.mcp-app.config.ts
// Builds src/mcp-app into ONE self-contained HTML, served by the box as ui://wheres-allie/floorplan.
import react from "@vitejs/plugin-react";
import { resolve } from "node:path";
import { defineConfig } from "vite";
import { viteSingleFile } from "vite-plugin-singlefile";

export default defineConfig({
  root: resolve(__dirname, "src/mcp-app"),
  plugins: [react(), viteSingleFile()],
  build: {
    outDir: resolve(__dirname, "../src/wheres_allie/mcp/static"),
    emptyOutDir: true,
    rollupOptions: { input: resolve(__dirname, "src/mcp-app/index.html") },
  },
});
```
```html
<!-- box/web/src/mcp-app/dev.html  (dev only: pnpm dev:mcp-app → http://localhost:5173/dev.html) -->
<!doctype html>
<html lang="en">
  <head><meta charset="UTF-8" /><title>MCP App harness</title></head>
  <body style="margin:0;font-family:system-ui">
    <div style="padding:8px;display:flex;gap:8px">
      <button id="pos">where_is result</button>
      <button id="path">timeline result</button>
      <select id="size">
        <option value="1280x800">Echo Show 8 (1280×800)</option>
        <option value="960x480">Echo Show 5 (960×480)</option>
        <option value="1920x1080">Echo Show 15 (1920×1080)</option>
        <option value="390x700">Phone (390×700)</option>
      </select>
    </div>
    <iframe id="app" src="./index.html" style="border:1px solid #ccc;width:1280px;height:800px"></iframe>
    <script type="module" src="./dev.ts"></script>
  </body>
</html>
```
```ts
// box/web/src/mcp-app/dev.ts
import { samplePath, samplePosition } from "./sample";

const frame = document.getElementById("app") as HTMLIFrameElement;
const send = (structuredContent: unknown) =>
  frame.contentWindow?.postMessage({ jsonrpc: "2.0", method: "ui/notifications/tool-result", params: { structuredContent } }, "*");
document.getElementById("pos")!.onclick = () => send(samplePosition);
document.getElementById("path")!.onclick = () => send(samplePath);
(document.getElementById("size") as HTMLSelectElement).onchange = (e) => {
  const [w, h] = (e.target as HTMLSelectElement).value.split("x");
  frame.style.width = `${w}px`;
  frame.style.height = `${h}px`;
};
```
Add to the `scripts` in `box/web/package.json`:
```json
"build:mcp-app": "vite build --config vite.mcp-app.config.ts",
"dev:mcp-app": "vite --config vite.mcp-app.config.ts"
```
Then build: `cd box/web && pnpm build:mcp-app`

**Step 4: Run test, verify pass**
Run the Step 1 command again.
Expected: `OK`. Also run `pnpm dev:mcp-app`, open `http://localhost:5173/dev.html`, click both buttons and each size: the plan, marker and player must fit without scrolling.

**Step 5: Commit**
```bash
git add box/web/src/mcp-app/index.html box/web/src/mcp-app/main.tsx box/web/src/mcp-app/dev.html box/web/src/mcp-app/dev.ts box/web/vite.mcp-app.config.ts box/web/package.json box/src/wheres_allie/mcp/static/index.html
git commit -m "feat: single-file MCP App build and dev harness" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 19: `mcp/app_resource.py`: constants + `floorplan_html()`

**Files:**
- Create: `box/src/wheres_allie/mcp/app_resource.py`
- Test: `box/tests/mcp/test_app_resource.py`

**Step 1: Write failing test**
```python
# box/tests/mcp/test_app_resource.py
from wheres_allie.mcp.app_resource import (APP_MIME, APP_URI, FLOORPLAN_URI, TOOL_META,
                                           floorplan_html)


def test_floorplan_html_is_the_single_file_app():
    assert FLOORPLAN_URI == APP_URI == "ui://wheres-allie/floorplan"
    assert APP_MIME == "text/html;profile=mcp-app"
    html = floorplan_html()
    assert '<div id="root"></div>' in html
    assert "<script" in html and 'src="./' not in html and 'src="/' not in html  # everything inlined
    assert TOOL_META == {"ui": {"resourceUri": "ui://wheres-allie/floorplan"}}
```

**Step 2: Run test, verify failure**
Run: `cd box && uv run pytest tests/mcp/test_app_resource.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'wheres_allie.mcp.app_resource'`

**Step 3: Implement**
```python
# box/src/wheres_allie/mcp/app_resource.py
"""MCP App UI resource (ui://wheres-allie/floorplan) and the `app` view payloads tools attach."""
from __future__ import annotations

from importlib.resources import files

FLOORPLAN_URI = APP_URI = "ui://wheres-allie/floorplan"
APP_MIME = "text/html;profile=mcp-app"
TOOL_META = {"ui": {"resourceUri": APP_URI}}


def floorplan_html() -> str:
    """Built by `pnpm build:mcp-app` (box/web) and committed as package data.

    Registered by plan 05's mcp/server.py via apps.add_html_resource(FLOORPLAN_URI, ...)."""
    return (files("wheres_allie.mcp") / "static" / "index.html").read_text(encoding="utf-8")
```

**Step 4: Run test, verify pass**
Run: `cd box && uv run pytest tests/mcp/test_app_resource.py -q`
Expected: PASS

**Step 5: Commit**
```bash
git add box/src/wheres_allie/mcp/app_resource.py box/tests/mcp/test_app_resource.py
git commit -m "feat: floorplan MCP App HTML accessor and constants" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 20: `mcp/app_resource.py`: `plan_payload` + view builders

**Files:**
- Modify: `box/src/wheres_allie/mcp/app_resource.py`
- Test: `box/tests/mcp/test_app_resource.py`

**Step 1: Write failing test** (append)
```python
import json
import sqlite3
from datetime import date

import pytest

from wheres_allie import db
from wheres_allie.devseed import seed
from wheres_allie.home.pathing import home_context
from wheres_allie.mcp.app_resource import app_view_for_position, app_view_for_range, plan_payload

NOW = 2_000_000_000.0


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    db.migrate(c)
    yield c
    c.close()


def test_plan_payload_keeps_only_requested_floors(conn):
    seed(conn, date(2026, 9, 27), now=NOW)
    home, rooms, _ = home_context(conn)
    p = plan_payload(home, rooms, ["up"])
    assert [f["id"] for f in p["home"]["floors"]] == ["up"]
    assert {w["floor_id"] for w in p["home"]["walls"]} == {"up"}
    assert p["home"]["doors"] == [] and p["home"]["nodes"] == [] and p["home"]["landmarks"] == []
    assert [s["id"] for s in p["home"]["stairs"]] == ["s1"]
    assert [r["id"] for r in p["rooms"]] == ["loft"]


def test_position_view(conn):
    seed(conn, date(2026, 9, 27), now=NOW)
    v = app_view_for_position(conn, [1])
    assert v["view"] == "position"
    assert (v["position"]["vertex_id"], v["position"]["x"], v["position"]["y"]) == ("lm:bed", 7, 1)
    assert [f["id"] for f in v["plan"]["home"]["floors"]] == ["main"]
    json.dumps(v)  # must be JSON-serialisable for structuredContent
    assert app_view_for_position(conn, [99]) is None


def test_range_view(conn):
    t0, t1 = seed(conn, date(2026, 9, 27), now=NOW)
    v = app_view_for_range(conn, [1], t0, t1)
    assert v["view"] == "path" and {p["floor_id"] for p in v["path"]} == {"main", "up"}
    assert [f["id"] for f in v["plan"]["home"]["floors"]] == ["main", "up"]
    json.dumps(v)
    assert app_view_for_range(conn, [1], t1, t1 + 3600) is None
```

**Step 2: Run test, verify failure**
Run: `cd box && uv run pytest tests/mcp/test_app_resource.py -q`
Expected: FAIL with `ImportError: cannot import name 'app_view_for_position'`

**Step 3: Implement** (append to `app_resource.py`; add the imports at the top)
```python
import sqlite3
from dataclasses import asdict

from wheres_allie.api.routes.history import load_path
from wheres_allie.api.routes.live import latest_position
from wheres_allie.home.geometry import Room
from wheres_allie.home.model import Home
from wheres_allie.home.pathing import home_context
```
```python
MAX_APP_POINTS = 2000


def plan_payload(home: Home, rooms: list[Room], floor_ids: list[str]) -> dict:
    """Just enough home geometry for PlanCanvas to draw the given floors (no underlays, no nodes)."""
    keep = set(floor_ids)
    walls = [w for w in home.walls if w.floor_id in keep]
    wall_ids = {w.id for w in walls}
    sub = home.model_copy(update={
        "floors": [f.model_copy(update={"underlay": None}) for f in home.floors if f.id in keep],
        "walls": walls,
        "room_labels": [r for r in home.room_labels if r.floor_id in keep],
        "doors": [d for d in home.doors if d.wall_id in wall_ids],
        "stairs": [s for s in home.stairs if s.a.floor_id in keep or s.b.floor_id in keep],
        "landmarks": [lm for lm in home.landmarks if lm.floor_id in keep],
        "nodes": [],
    })
    return {"home": sub.model_dump(mode="json"),
            "rooms": [asdict(r) for r in rooms if r.floor_id in keep]}


def app_view_for_position(conn: sqlite3.Connection, tag_ids: list[int]) -> dict | None:
    home, rooms, graph = home_context(conn)
    row = latest_position(conn, tag_ids)
    v = graph.vertices.get(row["vertex_id"]) if row else None
    if v is None:  # no data, or 'away'
        return None
    return {"view": "position", "plan": plan_payload(home, rooms, [v.floor_id]),
            "position": {"ts": row["ts"], "vertex_id": v.id, "floor_id": v.floor_id, "x": v.x,
                         "y": v.y, "confidence": row["confidence"],
                         "moving": None if row["moving"] is None else bool(row["moving"])}}


def app_view_for_range(conn: sqlite3.Connection, tag_ids: list[int], t0: float,
                       t1: float) -> dict | None:
    home, rooms, graph = home_context(conn)
    path = load_path(conn, home, graph, tag_ids, t0, t1)["points"]
    if not path:
        return None
    if len(path) > MAX_APP_POINTS:
        # ponytail: naive decimation keeps the Alexa payload small; use RDP if replays look jumpy
        path = path[:: len(path) // MAX_APP_POINTS + 1] + [path[-1]]
    used = {p["floor_id"] for p in path}
    floors = [f.id for f in home.floors if f.id in used]
    return {"view": "path", "plan": plan_payload(home, rooms, floors), "path": path}
```

**Step 4: Run test, verify pass**
Run: `cd box && uv run pytest tests/mcp/test_app_resource.py -q`
Expected: PASS (4 passed)

**Step 5: Commit**
```bash
git add box/src/wheres_allie/mcp/app_resource.py box/tests/mcp/test_app_resource.py
git commit -m "feat: MCP App view payloads (plan subset + position or path)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 21: Playwright render test of the built MCP App

**Files:**
- Create: `box/web/e2e/live-history/mcp-app.spec.ts`

**Step 1: Write failing test**
```ts
// box/web/e2e/live-history/mcp-app.spec.ts
// Renders the committed single-file build exactly as a host would load it (file://, no server).
import { expect, test, type Page } from "@playwright/test";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { samplePath, samplePosition } from "../../src/mcp-app/sample";

const APP = pathToFileURL(resolve("../src/wheres_allie/mcp/static/index.html")).href; // cwd = box/web

async function deliver(page: Page, data: unknown) {
  await page.goto(APP);
  // Retry until React's effect has attached the listener.
  await expect(async () => {
    await page.evaluate((d) => window.postMessage(
      { jsonrpc: "2.0", method: "ui/notifications/tool-result", params: { structuredContent: d } }, "*"), data);
    await expect(page.getByTestId("pet-marker")).toBeVisible({ timeout: 500 });
  }).toPass({ timeout: 10_000 });
}

test("where_is result shows Allie on her bed", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await deliver(page, samplePosition);
  await expect(page.getByText("Allie · Allie's bed")).toBeVisible();
  expect(errors).toEqual([]);
});

test("timeline result autoplays the path", async ({ page }) => {
  await deliver(page, samplePath);
  await expect(page.getByRole("button", { name: "Pause" })).toBeVisible();
  await expect(page.getByLabel("Time")).toBeVisible();
});
```

**Step 2: Run test, verify failure**
Run: `cd box/web && pnpm e2e:live -g "result"`
Expected: FAIL if the build is stale or missing. To prove the test bites, temporarily rename `../src/wheres_allie/mcp/static/index.html`, confirm `net::ERR_FILE_NOT_FOUND`, then rename it back.

**Step 3: Implement:** none (Tasks 16–18 are the implementation). Rebuild: `pnpm build:mcp-app`.

**Step 4: Run test, verify pass**
Run: `cd box/web && pnpm build:mcp-app && pnpm e2e:live`
Expected: PASS (4 passed: the 2 Live/History tests and the 2 MCP App tests)

**Step 5: Commit**
```bash
git add box/web/e2e/live-history/mcp-app.spec.ts box/src/wheres_allie/mcp/static/index.html
git commit -m "test: e2e render of the single-file MCP App" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 22: Link the resource into plan 05's MCP server

**Needs plan 05's `box/src/wheres_allie/mcp/server.py` and `tools.py`.** If they don't exist yet, leave this task `pending` and do it right after plan 05's MCP-tools task.

**Files:**
- Modify: `box/src/wheres_allie/mcp/server.py` (only if it still serves the placeholder HTML)
- Modify: `box/src/wheres_allie/mcp/tools.py` (only if the `app` key is missing)
- Test: `box/tests/mcp/test_server_app_link.py`

**Step 1: Write failing test**
```python
# box/tests/mcp/test_server_app_link.py
import mcp

from wheres_allie.mcp.app_resource import APP_URI, TOOL_META
from wheres_allie.mcp.server import build_mcp


async def test_server_serves_floorplan_and_tools_link_it():
    srv = build_mcp(lambda: None)  # listing/reading needs no db
    async with mcp.Client(srv) as c:
        res = await c.read_resource(APP_URI)
        html = res.contents[0].text
        assert '<div id="root"></div>' in html  # the real build, not plan 05's placeholder
        assert res.contents[0].mimeType == "text/html;profile=mcp-app"
        tools = {t.name: t for t in (await c.list_tools()).tools}
    for name in ("where_is", "day_summary", "timeline"):
        assert tools[name].meta == TOOL_META, name
```

**Step 2: Run test, verify failure**
Run: `cd box && uv run pytest tests/mcp/test_server_app_link.py -q`
Expected: PASS if plan 05 already wired everything (then go straight to Step 5). Otherwise it fails with `AssertionError` on the URI or on the tool meta.

**Step 3: Implement** (only what is missing)
`server.py` (plan 05) should already do `apps.add_html_resource(FLOORPLAN_URI, floorplan_html(), ...)` and fall back to placeholder HTML on `ImportError`. Once this module exists, the real HTML is served automatically. If the fallback still triggers, fix the import. The tools are bound with `@apps.tool(resource_uri=FLOORPLAN_URI)`. In `tools.py`, make sure `structuredContent` has the `app` key:
```python
from wheres_allie.mcp.app_resource import app_view_for_position, app_view_for_range

result["app"] = app_view_for_position(conn, tag_ids)             # where_is
result["app"] = app_view_for_range(conn, tag_ids, day_t0, day_t1)  # day_summary
result["app"] = app_view_for_range(conn, tag_ids, from_ts, to_ts)  # timeline
```
Use plan 05's own names for `conn`, `tag_ids` and the time bounds. If `read_resource` / `list_resources` have different names on the SDK v2 server object, use plan 05's MCP contract-test client instead (same assertions).

**Step 4: Run test, verify pass**
Run: `cd box && uv run pytest -q`
Expected: PASS (including plan 05's MCP contract tests)

**Step 5: Commit**
```bash
git add box/src/wheres_allie/mcp/server.py box/src/wheres_allie/mcp/tools.py box/tests/mcp/test_server_app_link.py
git commit -m "feat: link where_is/day_summary/timeline to the floorplan MCP App" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 23: Phase 8 exit: Echo Show check, friction log, push

**Files:**
- Modify: `docs/friction-log.md`
- Modify: this plan (status table)

**Step 1–2:** n/a (manual acceptance).
**Step 3: Manual acceptance**
1. `cd box && uv run wheres-allie serve` with real or replayed data. In MCP Inspector (`npx @modelcontextprotocol/inspector`, Streamable HTTP `http://<box>:8080/mcp`, bearer = `WA_LAN_TOKEN`), call `where_is`. Check that `_meta.ui.resourceUri` is present and that `structuredContent.app.view == "position"`. Then read the resource `ui://wheres-allie/floorplan`.
2. Through the relay (plan 06), ask on the Echo Show: "Alexa, where's Allie?" and "What did Allie do today?". Expect the dot on the plan, and the path mini-player.
3. Repeat in the Alexa app on a phone.
4. If the Show doesn't render MCP Apps (plan 01 phase 0 spike result), use the Alexa+ web simulator plus `pnpm dev:mcp-app` harness screenshots for the video.

Write what happened (host behaviour, CSP or size limits hit, the handshake, anything surprising) in `docs/friction-log.md` with the date.
**Step 4: Run test, verify pass**
Run: `cd box && uv run ruff check . && uv run pytest -q && cd web && pnpm test && pnpm build && pnpm build:mcp-app && git diff --exit-code ../src/wheres_allie/mcp/static/index.html && pnpm e2e:live`
Expected: all green. `git diff --exit-code` proves the committed MCP App build is current.
**Step 5: Commit + push**
Set rows 16–23 to `done | yes | yes`.
```bash
git add docs/friction-log.md docs/plans/2026-09-28-wheres-allie-plan-04-live-history-mcpapp.md
git commit -m "docs: phase 8 (MCP App) complete, friction notes" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push origin main
```

---

## Phase exit criteria

**Phase 5 (Live + History)**
- `uv run pytest -q` is green, including `tests/home/test_pathing.py`, `tests/test_devseed.py` and `tests/live_history/*`.
- `pnpm test` is green (`replay.test.ts`, `PetMarker.test.tsx`).
- `pnpm e2e:live`: Live shows Allie's card and node dots. History lists 6 visits, jumping to "Loft" switches to the Upstairs tab with the marker visible, and Play at 120× advances the clock.
- A seeded day's path crosses floors only via `stairs:*:a → stairs:*:b`, and kitchen → bed passes `door:d1` (a snapped route, not a straight line through walls).

**Phase 8 (MCP App)**
- `box/src/wheres_allie/mcp/static/index.html` is a single self-contained file (no external `src=`) and matches a fresh `pnpm build:mcp-app`.
- The resource `ui://wheres-allie/floorplan` lists with mimeType `text/html;profile=mcp-app` and reads back HTML containing `<div id="root"></div>`.
- `where_is`, `day_summary` and `timeline` carry `_meta.ui.resourceUri` and a JSON-serialisable `structuredContent.app` (or `null`).
- The MCP App renders both views in Playwright (file://) and in the dev harness at Echo Show 5, 8 and 15 sizes. Echo Show and Alexa-app behaviour is recorded in `docs/friction-log.md`.
