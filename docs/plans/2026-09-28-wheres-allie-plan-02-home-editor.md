# Home Model and Plan Editor Implementation Plan

**Goal:** The owner can draw each floor of the home (walls, doors, stairs, landmarks, nodes, underlay) in a browser editor. The box then detects the rooms and builds the walkable graph that the estimator uses.

**Architecture:** The home is one pydantic `Home` document, versioned in the `home` table. `geometry.detect_rooms` finds the planar faces of each floor's noded wall centrelines with shapely `polygonize`. `graph.build_graph` turns rooms, doors, stairs and landmarks into a weighted graph. `GET/PUT /api/home` return `{home, rooms, graph}`. The web editor is a React page around a shared SVG `PlanCanvas` (which the Live, History and MCP App views reuse). All editor logic that can be pure (snapping, history, home edits, viewport math) lives in small TypeScript modules with vitest tests.

**Tech Stack:** Python 3.12, pydantic v2, shapely 2, FastAPI, pytest · React 18, TypeScript, zustand, SVG, vitest + @testing-library/react + jsdom, @playwright/test.

**Timebox:** 5 days (design §9). If the phase runs late, cut features in this order:
1. **Underlay rotation**: delete the Rotation input in `UnderlayPanel` (Task 13). The model field stays, at 0.
2. **45° snapping**: set `ANGLE_STEP_DEG = 90` in `Editor.tsx` (Task 15).
3. **Divider walls**: delete the "Divider (invisible)" checkbox in `Inspector` (Task 13). The backend already handles them, and the fixture doesn't use them.

| Task | Description | Status | Tested | Pushed |
|------|-------------|--------|--------|--------|
| 1 | Home pydantic model | pending | no | no |
| 2 | Home store (load/save versions) | pending | no | no |
| 3 | Room detection + room_at | pending | no | no |
| 4 | Walkable graph | pending | no | no |
| 5 | Allie's 3-floor fixture home | pending | no | no |
| 6 | GET/PUT /api/home + `home.saved` | pending | no | no |
| 7 | Underlay upload + serving | pending | no | no |
| 8 | TS home types + units.ts | pending | no | no |
| 9 | Plan geometry + viewport math | pending | no | no |
| 10 | Shared PlanCanvas renderer | pending | no | no |
| 11 | History reducer + snapping | pending | no | no |
| 12 | Home edit operations | pending | no | no |
| 13 | Editor store + Inspector panels | pending | no | no |
| 14 | Playwright e2e (failing) | pending | no | no |
| 15 | Editor page (tools, save) | pending | no | no |
| 16 | Phase push | pending | no | no |

## Interface additions

Everything here adds to conventions §6, §10 and §14 and changes nothing in them.

**A. Plan-01 names this plan relies on** (confirmed by plan 01 on 2026-09-29; `create_app(settings=None, conn=None, start_background=True)` registers routers above the final static mount; the `client` fixture is `TestClient(create_app(start_background=False))` on a temp `WA_DATA_DIR`):
- `wheres_allie.api.deps`: `get_conn() -> sqlite3.Connection`, `get_bus() -> Bus`, `get_settings() -> Settings` (FastAPI dependencies).
- `Settings.data_dir: Path` (from `WA_DATA_DIR`).
- `Bus.publish(topic, data)` is a plain (non-async) method.
- `api/app.py` registers routers with `app.include_router(<module>.router, prefix="/api")`.
- `box/tests/conftest.py` provides a `client` fixture: a `fastapi.testclient.TestClient` on a fresh app whose `WA_DATA_DIR` is a `tmp_path`.
- `web/src/lib/api.ts` (plan 01, per team-lead ruling) exports `apiGet<T>(path)`, `apiPut<T>(path, body)`, `apiUpload<T>(path, file: File)` (multipart field `file`), all returning `Promise<T>` and throwing on non-2xx.
- `web/vite.config.ts` proxies `/api` to `http://localhost:8080`. The Editor page is routed at `/editor` and `src/pages/Editor.tsx` has a default export.

**B. API payload shapes** (`GET`/`PUT /api/home`):
```jsonc
{ "home": Home,
  "rooms": [{ "id": "kitchen", "floor_id": "main", "name": "Kitchen", "polygon": [[x, y], ...] }],  // exterior ring, not closed
  "graph": { "vertices": { "<vertex id>": Vertex },     // Vertex = conventions §6 dataclass as JSON
             "edges": [["<a>", "<b>", 3.162], ...] } }   // undirected, length_m rounded to mm
```
- `PUT /api/home` returns **422** with `detail: [str]` when an object points at a floor or wall that doesn't exist.
- `wheres_allie.api.routes.home.home_payload(home: Home) -> dict` builds the payload above, and other modules may reuse it.
- **Underlay files:** `POST /api/home/underlay` accepts png, jpg or webp up to 20 MB. SVG is refused because it can carry script. The file is stored at `WA_DATA_DIR/uploads/<16 hex>.<ext>`. `Underlay.image` is the relative path `uploads/<file>`. **It is served at `GET /api/uploads/<file>`**, so the GUI loads it from `/api/${underlay.image}`.

**C. Graph construction constants** (`home/graph.py`):
- A room vertex sits at the polygon centroid, or at shapely's `representative_point()` when the centroid falls outside the polygon (an L-shape, for example).
- A door vertex sits at `wall.a + t·(b−a)`, with `room_id = None` and `name = "Door"`. It joins the rooms found 0.2 m to either side of the wall.
- A stairs end gets `room_id` from `room_at`, and its name is the stairs name.
- `STAIRS_EXTRA_M = 3.0`.
- Coordinates are rounded to 1 cm before noding. Faces smaller than 0.25 m² are dropped.
- Unnamed rooms are numbered in order of centroid (y, then x) per floor.

**D. Web modules**, reused by plans 04 and 05:
```ts
// web/src/lib/types.ts (appended): mirrors conventions §6
export type Pt = [number, number];
export interface Underlay { image: string; scale_m_per_px: number; offset: Pt; rotation_deg: number; opacity: number }
export interface Floor { id: string; name: string; elevation_m: number; underlay: Underlay | null }
export interface Wall { id: string; floor_id: string; a: Pt; b: Pt; thickness_m: number; invisible: boolean }
export interface RoomLabel { id: string; floor_id: string; name: string; seed: Pt }
export interface Door { id: string; wall_id: string; t: number; width_m: number }
export interface StairsEnd { floor_id: string; x: number; y: number }
export interface Stairs { id: string; name: string; a: StairsEnd; b: StairsEnd }
export type LandmarkType = "bed" | "food_bowl" | "water_bowl" | "couch" | "crate" | "door" | "custom";
export interface Landmark { id: string; floor_id: string; x: number; y: number; type: LandmarkType; name: string; radius_m: number }
export interface NodePlacement { id: string; floor_id: string; x: number; y: number; z_m: number; name: string }
export interface Home { version: number; floors: Floor[]; walls: Wall[]; room_labels: RoomLabel[]; doors: Door[]; stairs: Stairs[]; landmarks: Landmark[]; nodes: NodePlacement[] }
export type HomeCollection = "floors" | "walls" | "room_labels" | "doors" | "stairs" | "landmarks" | "nodes";
export type HitColl = HomeCollection | "rooms";
export interface Room { id: string; floor_id: string; name: string; polygon: Pt[] }
export interface Vertex { id: string; kind: "room" | "landmark" | "door" | "stairs"; floor_id: string; x: number; y: number; room_id: string | null; name: string }
export interface GraphJSON { vertices: Record<string, Vertex>; edges: [string, string, number][] }
export interface HomeResponse { home: Home; rooms: Room[]; graph: GraphJSON }

// web/src/lib/units.ts
export type Units = "ft" | "m";
export function formatLength(m: number, units: Units): string;             // "12' 6\"" | "3.81 m"
export function parseLength(s: string, units: Units): number | null;       // metres; accepts 12' 6", 12ft, 3.2m, bare numbers in `units`

// web/src/components/plan/geom.ts
export const dist: (a: Pt, b: Pt) => number;
export const lerp: (a: Pt, b: Pt, t: number) => Pt;
export function nearestOnSegment(p: Pt, a: Pt, b: Pt): { t: number; d: number; p: Pt };
export function doorSegment(a: Pt, b: Pt, t: number, width: number): [Pt, Pt];
export function polygonCentroid(poly: Pt[]): Pt;
export function bounds(pts: Pt[]): Box | null;                               // Box = { x, y, w, h }

// web/src/components/plan/viewport.ts
export interface View { x: number; y: number; w: number; h: number }       // SVG viewBox in metres
export function clientToWorld(v: View, rect: Rect, clientX: number, clientY: number): Pt;
export function zoomAt(v: View, factor: number, p: Pt): View;              // factor > 1 zooms in, p stays fixed
export function panBy(v: View, dx: number, dy: number): View;
export function fitBounds(b: Box | null, pad?: number): View;
```

**E. PlanCanvas props contract** (`web/src/components/plan/PlanCanvas.tsx`). It's a pure renderer: it owns only its pan/zoom view and never fetches data. The MCP App can use it as long as it passes `showUnderlay={false}`.
```ts
export interface Hit { coll: HitColl; id: string; part?: "a" | "b" }  // part: wall endpoint or stairs end
export interface PlanPointer { x: number; y: number; hit: Hit | null; event: React.PointerEvent<SVGSVGElement> } // x,y in metres
export interface PlanCanvasProps {
  home: Home;
  rooms: Room[];                      // derived rooms from the API (fill + name label)
  floorId: string;                    // only this floor's objects are drawn
  selected?: { coll: HitColl; id: string } | null;   // highlighted in --accent
  coverage?: Record<string, number>;  // node id -> ring radius in m (placeholder for coverage heat)
  editing?: boolean;                  // true: show divider walls, room-label seeds, endpoint handles of the selected wall
  showUnderlay?: boolean;             // default true; underlay loads from `/api/${image}`
  fitKey?: string;                    // view refits to the floor's content whenever this changes (default: floorId)
  onPointerDown?: (p: PlanPointer) => boolean | void;  // return true = consumed; otherwise a left/middle drag pans
  onPointerMove?: (p: PlanPointer) => void;           // not called while panning
  onPointerUp?: (p: PlanPointer) => void;
  children?: React.ReactNode;         // overlay drawn last, in world metres (live marker, path, previews)
  className?: string;
}
export function PlanCanvas(props: PlanCanvasProps): JSX.Element;
export function floorBounds(home: Home, floorId: string): Box | null;
```
- The mouse wheel zooms around the cursor.
- The view is `viewBox` in metres, with y pointing down.
- Hit testing is DOM-based: any element with `data-coll`, `data-id` and optionally `data-part` attributes counts. Rooms report `coll: "rooms"`.
- The CSS class names that tests and the e2e rely on are `plan-canvas` on the `<svg>` and `plan-room-name` on room name `<text>`.

**F. Fixture:** `box/tests/fixtures/home_allie.json`.
- Floors: `basement` (0 m), `main` (3 m), `upstairs` (6 m).
- Room ids (from the room labels): `office`, `moms_room`, `kitchen`, `master_bedroom`, `loft`.
- Node ids are the same five strings.
- Landmarks: `bed_master` ("Allie's bed", in the master bedroom), `water_bowl`, `food_bowl` (kitchen), `couch_loft` (loft).
- Doors: `door_basement`, `door_main`.
- Stairs: `stairs_down` (office ↔ kitchen), `stairs_up` (kitchen ↔ loft).

**H. Clarifications for later plans:**
- `NodePlacement.z_m` is the height above **its own floor** (design §4.2). The absolute height is `floor.elevation_m + z_m`. The editor defaults it to 1.0.
- `Vertex.room_id`:
  - landmark: the room that contains it, or None when it's outside every room;
  - stairs end: the room from `room_at`, or None;
  - door: always None;
  - room: its own id.
- Labelled rooms have `Room.id == RoomLabel.id`.
- Plan 02 creates no `home/pathing.py`; plan 04 owns it.
- PlanCanvas works from props alone (no fetch, store or router). It draws an underlay only when `floor.underlay` is set and `showUnderlay` isn't false.

**G. Editor selection:** an object is identified by `(coll, id)`, never by id alone. A node id such as `kitchen` can equal a room-label id.

---

### Task 1: Home pydantic model

**Files:**
- Create: `box/src/wheres_allie/home/__init__.py` (empty, if plan 01 didn't create it)
- Create: `box/src/wheres_allie/home/model.py`
- Test: `box/tests/home/test_model.py`

**Step 1: Write failing test**
```python
# box/tests/home/test_model.py
import pytest
from pydantic import ValidationError

from wheres_allie.home.model import Door, Floor, Home, Landmark, Wall


def test_empty_home_defaults():
    h = Home()
    assert h.version == 0
    assert h.floors == [] and h.walls == [] and h.nodes == []


def test_roundtrip_json_keeps_tuples_and_defaults():
    h = Home(
        floors=[Floor(id="main", name="Main", elevation_m=0)],
        walls=[Wall(id="w1", floor_id="main", a=(0, 0), b=(4, 0))],
        doors=[Door(id="d1", wall_id="w1", t=0.5)],
    )
    back = Home.model_validate_json(h.model_dump_json())
    assert back == h
    assert back.walls[0].a == (0.0, 0.0)
    assert back.walls[0].thickness_m == 0.12 and back.walls[0].invisible is False
    assert back.doors[0].width_m == 0.9
    assert back.floors[0].underlay is None


def test_landmark_type_is_checked():
    with pytest.raises(ValidationError):
        Landmark(id="l", floor_id="main", x=0, y=0, type="sofa", name="x")
```

**Step 2: Run test, verify failure**
`cd box && uv run pytest tests/home/test_model.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'wheres_allie.home.model'`

**Step 3: Implement** (this is the conventions §6 model verbatim)
```python
# box/src/wheres_allie/home/model.py
"""Home model (conventions §6). Metres, x right, y down."""
from typing import Literal

from pydantic import BaseModel


class Underlay(BaseModel):
    image: str
    scale_m_per_px: float
    offset: tuple[float, float] = (0, 0)
    rotation_deg: float = 0
    opacity: float = 0.4


class Floor(BaseModel):
    id: str
    name: str
    elevation_m: float
    underlay: Underlay | None = None


class Wall(BaseModel):
    id: str
    floor_id: str
    a: tuple[float, float]
    b: tuple[float, float]
    thickness_m: float = 0.12
    invisible: bool = False  # invisible = room divider


class RoomLabel(BaseModel):
    id: str
    floor_id: str
    name: str
    seed: tuple[float, float]  # a point inside the room; names derived rooms


class Door(BaseModel):
    id: str
    wall_id: str
    t: float  # 0..1 along wall a→b
    width_m: float = 0.9


class StairsEnd(BaseModel):
    floor_id: str
    x: float
    y: float


class Stairs(BaseModel):
    id: str
    name: str = "Stairs"
    a: StairsEnd
    b: StairsEnd


LandmarkType = Literal["bed", "food_bowl", "water_bowl", "couch", "crate", "door", "custom"]


class Landmark(BaseModel):
    id: str
    floor_id: str
    x: float
    y: float
    type: LandmarkType
    name: str
    radius_m: float = 0.75


class NodePlacement(BaseModel):
    id: str  # ESPresense room id
    floor_id: str
    x: float
    y: float
    z_m: float
    name: str


class Home(BaseModel):
    version: int = 0
    floors: list[Floor] = []
    walls: list[Wall] = []
    room_labels: list[RoomLabel] = []
    doors: list[Door] = []
    stairs: list[Stairs] = []
    landmarks: list[Landmark] = []
    nodes: list[NodePlacement] = []
```

**Step 4: Run test, verify pass**
`cd box && uv run pytest tests/home/test_model.py -q` → `3 passed`

**Step 5: Commit**
```bash
git add box/src/wheres_allie/home box/tests/home/test_model.py
git commit -m "feat: home pydantic model" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Home store

**Files:**
- Create: `box/src/wheres_allie/home/store.py`
- Test: `box/tests/home/test_store.py`

**Step 1: Write failing test**
```python
# box/tests/home/test_store.py
from wheres_allie import db
from wheres_allie.home.model import Floor, Home
from wheres_allie.home.store import load_home, save_home


def _conn(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    db.migrate(conn)
    return conn


def test_load_empty_returns_blank_home(tmp_path):
    assert load_home(_conn(tmp_path)) == Home()


def test_save_increments_version_and_load_returns_latest(tmp_path):
    conn = _conn(tmp_path)
    v1 = save_home(conn, Home(floors=[Floor(id="a", name="A", elevation_m=0)]))
    v2 = save_home(conn, Home(floors=[Floor(id="b", name="B", elevation_m=0)]))
    assert (v1, v2) == (1, 2)
    h = load_home(conn)
    assert h.version == 2
    assert [f.id for f in h.floors] == ["b"]
```

**Step 2: Run test, verify failure**
`cd box && uv run pytest tests/home/test_store.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'wheres_allie.home.store'`

**Step 3: Implement**
```python
# box/src/wheres_allie/home/store.py
"""Versioned home storage: every save is a new row in `home`."""
import sqlite3
import time

from wheres_allie.home.model import Home


def load_home(conn: sqlite3.Connection) -> Home:
    row = conn.execute("SELECT version, json FROM home ORDER BY version DESC LIMIT 1").fetchone()
    if row is None:
        return Home()
    home = Home.model_validate_json(row[1])
    home.version = row[0]
    return home


def save_home(conn: sqlite3.Connection, home: Home) -> int:
    # ponytail: keeps every version forever (a few KB each); prune in retention.py if it ever matters
    cur = conn.execute(
        "INSERT INTO home (saved_at, json) VALUES (?, ?)", (time.time(), home.model_dump_json())
    )
    conn.commit()
    return cur.lastrowid
```

**Step 4: Run test, verify pass**
`cd box && uv run pytest tests/home/test_store.py -q` → `2 passed`

**Step 5: Commit**
```bash
git add box/src/wheres_allie/home/store.py box/tests/home/test_store.py
git commit -m "feat: versioned home store" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Room detection + room_at

**Files:**
- Create: `box/src/wheres_allie/home/geometry.py`
- Create: `box/tests/home/conftest.py`
- Test: `box/tests/home/test_geometry.py`

**Step 1: Write failing test**
```python
# box/tests/home/conftest.py
import pytest

from wheres_allie.home.model import Floor, Wall


def _rect(floor_id, x0, y0, x1, y1, prefix="w"):
    c = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    return [Wall(id=f"{prefix}{i}", floor_id=floor_id, a=c[i], b=c[(i + 1) % 4]) for i in range(4)]


@pytest.fixture
def rect():
    """rect(floor_id, x0, y0, x1, y1, prefix="w") -> 4 walls around the box."""
    return _rect


@pytest.fixture
def main():
    return Floor(id="main", name="Main", elevation_m=0)
```
```python
# box/tests/home/test_geometry.py
import pytest
from shapely.geometry import Polygon

from wheres_allie.home.geometry import detect_rooms, room_at
from wheres_allie.home.model import Floor, Home, RoomLabel, Wall


def areas(rooms):
    return sorted(Polygon(r.polygon).area for r in rooms)


def test_square_room(rect, main):
    rooms = detect_rooms(Home(floors=[main], walls=rect("main", 0, 0, 4, 3)))
    assert len(rooms) == 1
    assert (rooms[0].id, rooms[0].floor_id, rooms[0].name) == ("room-main-1", "main", "Unnamed room")
    assert areas(rooms) == pytest.approx([12])


def test_two_rooms_sharing_a_wall(rect, main):
    walls = rect("main", 0, 0, 8, 4) + [Wall(id="mid", floor_id="main", a=(4, 0), b=(4, 4))]
    rooms = detect_rooms(Home(floors=[main], walls=walls))
    assert areas(rooms) == pytest.approx([16, 16])
    assert [r.id for r in rooms] == ["room-main-1", "room-main-2"]


def test_wall_with_a_gap_makes_no_room(rect, main):
    walls = rect("main", 0, 0, 4, 3)
    walls[3] = Wall(id="w3", floor_id="main", a=(0, 3), b=(0, 1))  # stops 1 m short
    assert detect_rooms(Home(floors=[main], walls=walls)) == []


def test_near_miss_endpoints_still_close(rect, main):
    walls = rect("main", 0, 0, 4, 3)
    walls[3] = Wall(id="w3", floor_id="main", a=(0, 3), b=(0.004, 0.003))  # < 1 cm off
    assert len(detect_rooms(Home(floors=[main], walls=walls))) == 1


def test_l_shape(main):
    c = [(0, 0), (6, 0), (6, 3), (3, 3), (3, 6), (0, 6)]
    walls = [Wall(id=f"w{i}", floor_id="main", a=c[i], b=c[(i + 1) % 6]) for i in range(6)]
    rooms = detect_rooms(Home(floors=[main], walls=walls))
    assert areas(rooms) == pytest.approx([27])


def test_invisible_divider_splits_open_plan(rect, main):
    walls = rect("main", 0, 0, 8, 4) + [
        Wall(id="div", floor_id="main", a=(3, -0.5), b=(3, 4.5), invisible=True)  # overshoots both walls
    ]
    rooms = detect_rooms(Home(floors=[main], walls=walls))
    assert areas(rooms) == pytest.approx([12, 20])


def test_seed_labels_name_rooms_and_unlabelled_are_numbered(rect, main):
    walls = rect("main", 0, 0, 8, 4) + [Wall(id="mid", floor_id="main", a=(4, 0), b=(4, 4))]
    labels = [
        RoomLabel(id="kitchen", floor_id="main", name="Kitchen", seed=(6, 2)),
        RoomLabel(id="ghost", floor_id="up", name="Other floor", seed=(2, 2)),
    ]
    rooms = detect_rooms(Home(floors=[main], walls=walls, room_labels=labels))
    by_id = {r.id: r.name for r in rooms}
    assert by_id == {"room-main-1": "Unnamed room", "kitchen": "Kitchen"}


def test_floors_are_independent(rect, main):
    up = Floor(id="up", name="Up", elevation_m=3)
    walls = rect("main", 0, 0, 4, 4) + rect("up", 0, 0, 2, 2, prefix="u")
    rooms = detect_rooms(Home(floors=[main, up], walls=walls))
    assert sorted((r.floor_id, round(Polygon(r.polygon).area)) for r in rooms) == [("main", 16), ("up", 4)]


def test_room_at(rect, main):
    rooms = detect_rooms(Home(floors=[main], walls=rect("main", 0, 0, 4, 3)))
    assert room_at(rooms, "main", 1, 1).id == "room-main-1"
    assert room_at(rooms, "main", 5, 1) is None
    assert room_at(rooms, "up", 1, 1) is None
```

**Step 2: Run test, verify failure**
`cd box && uv run pytest tests/home/test_geometry.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'wheres_allie.home.geometry'`

**Step 3: Implement**
```python
# box/src/wheres_allie/home/geometry.py
"""Rooms = faces of each floor's planar wall graph (visible + invisible walls)."""
from dataclasses import dataclass

from shapely.geometry import LineString, Point, Polygon
from shapely.ops import polygonize, unary_union

from wheres_allie.home.model import Home

MIN_ROOM_AREA_M2 = 0.25  # drop slivers from nearly-coincident walls


@dataclass(frozen=True)
class Room:
    id: str
    floor_id: str
    name: str
    polygon: list[tuple[float, float]]


def _cm(p: tuple[float, float]) -> tuple[float, float]:
    return (round(p[0], 2), round(p[1], 2))


def detect_rooms(home: Home) -> list[Room]:
    rooms: list[Room] = []
    for floor in home.floors:
        lines = [
            LineString([_cm(w.a), _cm(w.b)])
            for w in home.walls
            if w.floor_id == floor.id and _cm(w.a) != _cm(w.b)
        ]
        if not lines:
            continue
        noded = unary_union(lines)  # splits walls where they cross or touch
        faces = [f for f in polygonize(getattr(noded, "geoms", [noded])) if f.area >= MIN_ROOM_AREA_M2]
        faces.sort(key=lambda f: (round(f.centroid.y, 3), round(f.centroid.x, 3)))
        labels = [lb for lb in home.room_labels if lb.floor_id == floor.id]
        n = 0
        for face in faces:
            label = next((lb for lb in labels if face.contains(Point(lb.seed))), None)
            if label:
                rid, name = label.id, label.name
            else:
                n += 1
                rid, name = f"room-{floor.id}-{n}", "Unnamed room"
            rooms.append(Room(rid, floor.id, name, [(x, y) for x, y in face.exterior.coords[:-1]]))
    return rooms


def room_at(rooms: list[Room], floor_id: str, x: float, y: float) -> Room | None:
    # ponytail: ignores holes (room fully inside another); fine for real floorplans
    pt = Point(x, y)
    return next(
        (r for r in rooms if r.floor_id == floor_id and Polygon(r.polygon).covers(pt)), None
    )
```

**Step 4: Run test, verify pass**
`cd box && uv run pytest tests/home/test_geometry.py -q` → `9 passed`

**Step 5: Commit**
```bash
git add box/src/wheres_allie/home/geometry.py box/tests/home/conftest.py box/tests/home/test_geometry.py
git commit -m "feat: detect rooms from wall graph faces" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Walkable graph

**Files:**
- Create: `box/src/wheres_allie/home/graph.py`
- Test: `box/tests/home/test_graph.py`

**Step 1: Write failing test**
```python
# box/tests/home/test_graph.py
import math

import pytest

from wheres_allie.home.geometry import detect_rooms
from wheres_allie.home.graph import build_graph
from wheres_allie.home.model import (
    Door, Floor, Home, Landmark, RoomLabel, Stairs, StairsEnd, Wall,
)


def edge_map(g):
    return {frozenset((a, b)): length for a, b, length in g.edges}


def graph_of(home):
    return build_graph(home, detect_rooms(home))


def test_door_connects_two_rooms(rect, main):
    home = Home(
        floors=[main],
        walls=rect("main", 0, 0, 8, 4) + [Wall(id="mid", floor_id="main", a=(4, 0), b=(4, 4))],
        room_labels=[
            RoomLabel(id="a", floor_id="main", name="A", seed=(2, 2)),
            RoomLabel(id="b", floor_id="main", name="B", seed=(6, 2)),
        ],
        doors=[Door(id="d1", wall_id="mid", t=0.5)],
    )
    g = graph_of(home)
    door = g.vertices["door:d1"]
    assert (door.kind, door.x, door.y, door.room_id) == ("door", 4, 2, None)
    e = edge_map(g)
    assert e[frozenset(("door:d1", "room:a"))] == pytest.approx(2)
    assert e[frozenset(("door:d1", "room:b"))] == pytest.approx(2)
    assert frozenset(("room:a", "room:b")) not in e


def test_stairs_connect_floors_with_extra_3m(rect, main):
    up = Floor(id="up", name="Up", elevation_m=3)
    home = Home(
        floors=[main, up],
        walls=rect("main", 0, 0, 4, 4) + rect("up", 0, 0, 4, 4, prefix="u"),
        stairs=[Stairs(id="s1", a=StairsEnd(floor_id="main", x=1, y=1), b=StairsEnd(floor_id="up", x=2, y=1))],
    )
    g = graph_of(home)
    assert edge_map(g)[frozenset(("stairs:s1:a", "stairs:s1:b"))] == pytest.approx(4.0)
    assert g.vertices["stairs:s1:a"].room_id == "room-main-1"
    assert g.vertices["stairs:s1:b"].floor_id == "up"
    assert ("stairs:s1:b", 4.0) in g.neighbors("stairs:s1:a")


def test_all_pairs_within_a_room_and_landmark_room_id(rect, main):
    home = Home(
        floors=[main],
        walls=rect("main", 0, 0, 4, 3),
        landmarks=[
            Landmark(id="bed", floor_id="main", x=1, y=1, type="bed", name="Bed"),
            Landmark(id="bowl", floor_id="main", x=3, y=2, type="water_bowl", name="Bowl"),
        ],
    )
    g = graph_of(home)
    assert g.vertices["lm:bed"].room_id == "room-main-1"
    assert g.vertices["room:room-main-1"].x == pytest.approx(2)
    e = edge_map(g)
    assert len(e) == 3
    assert e[frozenset(("lm:bed", "lm:bowl"))] == pytest.approx(math.hypot(2, 1), abs=1e-3)


def test_landmark_outside_rooms_is_isolated(rect, main):
    home = Home(
        floors=[main],
        walls=rect("main", 0, 0, 4, 3),
        landmarks=[Landmark(id="yard", floor_id="main", x=9, y=9, type="custom", name="Yard")],
    )
    g = graph_of(home)
    assert g.vertices["lm:yard"].room_id is None
    assert g.neighbors("lm:yard") == []
```

**Step 2: Run test, verify failure**
`cd box && uv run pytest tests/home/test_graph.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'wheres_allie.home.graph'`

**Step 3: Implement**
```python
# box/src/wheres_allie/home/graph.py
"""Walkable graph: room centroids, landmarks, doors, stairs ends (conventions §6)."""
import math
from dataclasses import dataclass
from itertools import combinations
from typing import Literal

from shapely.geometry import Polygon

from wheres_allie.home.geometry import Room, room_at
from wheres_allie.home.model import Home

STAIRS_EXTRA_M = 3.0
DOOR_PROBE_M = 0.2  # distance either side of a door where we look for the rooms it joins


@dataclass(frozen=True)
class Vertex:
    id: str
    kind: Literal["room", "landmark", "door", "stairs"]
    floor_id: str
    x: float
    y: float
    room_id: str | None
    name: str


@dataclass
class Graph:
    vertices: dict[str, Vertex]
    edges: list[tuple[str, str, float]]  # (a, b, length_m), undirected

    def neighbors(self, vid: str) -> list[tuple[str, float]]:
        # ponytail: O(E) scan; build an adjacency dict if a hot loop calls this
        return [(b if a == vid else a, length) for a, b, length in self.edges if vid in (a, b)]


def build_graph(home: Home, rooms: list[Room]) -> Graph:
    vertices: dict[str, Vertex] = {}
    members: dict[str, list[str]] = {r.id: [] for r in rooms}

    def add(v: Vertex, room_ids) -> None:
        vertices[v.id] = v
        for rid in room_ids:
            members[rid].append(v.id)

    for r in rooms:
        poly = Polygon(r.polygon)
        c = poly.centroid if poly.contains(poly.centroid) else poly.representative_point()
        add(Vertex(f"room:{r.id}", "room", r.floor_id, c.x, c.y, r.id, r.name), [r.id])

    for lm in home.landmarks:
        room = room_at(rooms, lm.floor_id, lm.x, lm.y)
        rid = room.id if room else None
        add(Vertex(f"lm:{lm.id}", "landmark", lm.floor_id, lm.x, lm.y, rid, lm.name), [rid] if rid else [])

    walls = {w.id: w for w in home.walls}
    for d in home.doors:
        w = walls.get(d.wall_id)
        if w is None:
            continue
        (ax, ay), (bx, by) = w.a, w.b
        x, y = ax + (bx - ax) * d.t, ay + (by - ay) * d.t
        length = math.hypot(bx - ax, by - ay) or 1.0
        nx, ny = -(by - ay) / length * DOOR_PROBE_M, (bx - ax) / length * DOOR_PROBE_M
        sides = (room_at(rooms, w.floor_id, x + nx, y + ny), room_at(rooms, w.floor_id, x - nx, y - ny))
        joined = sorted({r.id for r in sides if r})
        add(Vertex(f"door:{d.id}", "door", w.floor_id, x, y, None, "Door"), joined)

    edges: dict[tuple[str, str], float] = {}
    for s in home.stairs:
        for key, end in (("a", s.a), ("b", s.b)):
            room = room_at(rooms, end.floor_id, end.x, end.y)
            rid = room.id if room else None
            add(Vertex(f"stairs:{s.id}:{key}", "stairs", end.floor_id, end.x, end.y, rid, s.name),
                [rid] if rid else [])
        edges[(f"stairs:{s.id}:a", f"stairs:{s.id}:b")] = (
            math.hypot(s.a.x - s.b.x, s.a.y - s.b.y) + STAIRS_EXTRA_M
        )

    for ids in members.values():
        for a, b in combinations(ids, 2):
            va, vb = vertices[a], vertices[b]
            edges.setdefault(tuple(sorted((a, b))), math.hypot(va.x - vb.x, va.y - vb.y))

    return Graph(vertices, [(a, b, round(length, 3)) for (a, b), length in edges.items()])
```

**Step 4: Run test, verify pass**
`cd box && uv run pytest tests/home/test_graph.py -q` → `4 passed`

**Step 5: Commit**
```bash
git add box/src/wheres_allie/home/graph.py box/tests/home/test_graph.py
git commit -m "feat: walkable graph from rooms, doors, stairs, landmarks" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Allie's 3-floor fixture home

A skeleton of the real house. Later plans load it: the estimator, eval, the MCP tools and the replay bundle's `home.json`. Coordinates are rough. The user redraws the house for real in the editor.

**Files:**
- Create: `box/tests/fixtures/home_allie.json`
- Test: `box/tests/home/test_fixture.py`

**Step 1: Write failing test**
```python
# box/tests/home/test_fixture.py
from pathlib import Path

from wheres_allie.home.geometry import detect_rooms
from wheres_allie.home.graph import build_graph
from wheres_allie.home.model import Home

FIXTURE = Path(__file__).parent.parent / "fixtures" / "home_allie.json"
ROOM_IDS = {"office", "moms_room", "kitchen", "master_bedroom", "loft"}


def test_fixture_rooms_nodes_and_connectivity():
    home = Home.model_validate_json(FIXTURE.read_text())
    rooms = detect_rooms(home)
    assert {r.id for r in rooms} == ROOM_IDS
    assert {n.id for n in home.nodes} == ROOM_IDS
    g = build_graph(home, rooms)
    assert g.vertices["lm:bed_master"].room_id == "master_bedroom"
    seen, todo = {"room:office"}, ["room:office"]
    while todo:
        for nb, _ in g.neighbors(todo.pop()):
            if nb not in seen:
                seen.add(nb)
                todo.append(nb)
    assert seen == set(g.vertices)  # every vertex reachable, across all 3 floors
```

**Step 2: Run test, verify failure**
`cd box && uv run pytest tests/home/test_fixture.py -q`
Expected: FAIL with `FileNotFoundError: ... home_allie.json`

**Step 3: Implement**
```json
{
  "version": 0,
  "floors": [
    {"id": "basement", "name": "Basement", "elevation_m": 0.0},
    {"id": "main", "name": "Main", "elevation_m": 3.0},
    {"id": "upstairs", "name": "Upstairs", "elevation_m": 6.0}
  ],
  "walls": [
    {"id": "b1", "floor_id": "basement", "a": [0, 0], "b": [10, 0]},
    {"id": "b2", "floor_id": "basement", "a": [10, 0], "b": [10, 8]},
    {"id": "b3", "floor_id": "basement", "a": [10, 8], "b": [0, 8]},
    {"id": "b4", "floor_id": "basement", "a": [0, 8], "b": [0, 0]},
    {"id": "b5", "floor_id": "basement", "a": [5, 0], "b": [5, 8]},
    {"id": "m1", "floor_id": "main", "a": [0, 0], "b": [10, 0]},
    {"id": "m2", "floor_id": "main", "a": [10, 0], "b": [10, 8]},
    {"id": "m3", "floor_id": "main", "a": [10, 8], "b": [0, 8]},
    {"id": "m4", "floor_id": "main", "a": [0, 8], "b": [0, 0]},
    {"id": "m5", "floor_id": "main", "a": [5, 0], "b": [5, 8]},
    {"id": "u1", "floor_id": "upstairs", "a": [0, 0], "b": [6, 0]},
    {"id": "u2", "floor_id": "upstairs", "a": [6, 0], "b": [6, 5]},
    {"id": "u3", "floor_id": "upstairs", "a": [6, 5], "b": [0, 5]},
    {"id": "u4", "floor_id": "upstairs", "a": [0, 5], "b": [0, 0]}
  ],
  "room_labels": [
    {"id": "office", "floor_id": "basement", "name": "Office", "seed": [2.5, 4]},
    {"id": "moms_room", "floor_id": "basement", "name": "Mom's room", "seed": [7.5, 4]},
    {"id": "kitchen", "floor_id": "main", "name": "Kitchen", "seed": [2.5, 4]},
    {"id": "master_bedroom", "floor_id": "main", "name": "Master bedroom", "seed": [7.5, 4]},
    {"id": "loft", "floor_id": "upstairs", "name": "Loft", "seed": [3, 2.5]}
  ],
  "doors": [
    {"id": "door_basement", "wall_id": "b5", "t": 0.5},
    {"id": "door_main", "wall_id": "m5", "t": 0.5}
  ],
  "stairs": [
    {"id": "stairs_down", "name": "Basement stairs",
     "a": {"floor_id": "basement", "x": 4.5, "y": 5.0}, "b": {"floor_id": "main", "x": 4.5, "y": 7.5}},
    {"id": "stairs_up", "name": "Loft stairs",
     "a": {"floor_id": "main", "x": 4.5, "y": 1.0}, "b": {"floor_id": "upstairs", "x": 4.5, "y": 3.5}}
  ],
  "landmarks": [
    {"id": "bed_master", "floor_id": "main", "x": 8.5, "y": 1.5, "type": "bed", "name": "Allie's bed"},
    {"id": "water_bowl", "floor_id": "main", "x": 1.0, "y": 7.0, "type": "water_bowl", "name": "Water bowl"},
    {"id": "food_bowl", "floor_id": "main", "x": 2.0, "y": 7.0, "type": "food_bowl", "name": "Food bowl"},
    {"id": "couch_loft", "floor_id": "upstairs", "x": 2.0, "y": 2.0, "type": "couch", "name": "Couch"}
  ],
  "nodes": [
    {"id": "office", "floor_id": "basement", "x": 1.0, "y": 4.0, "z_m": 1.0, "name": "Office"},
    {"id": "moms_room", "floor_id": "basement", "x": 9.0, "y": 4.0, "z_m": 1.0, "name": "Mom's room"},
    {"id": "kitchen", "floor_id": "main", "x": 1.0, "y": 1.0, "z_m": 1.0, "name": "Kitchen"},
    {"id": "master_bedroom", "floor_id": "main", "x": 9.0, "y": 7.0, "z_m": 1.0, "name": "Master bedroom"},
    {"id": "loft", "floor_id": "upstairs", "x": 5.0, "y": 4.5, "z_m": 1.0, "name": "Loft"}
  ]
}
```
Save the JSON above as `box/tests/fixtures/home_allie.json`.

**Step 4: Run test, verify pass**
`cd box && uv run pytest tests/home/test_fixture.py -q` → `1 passed`

**Step 5: Commit**
```bash
git add box/tests/fixtures/home_allie.json box/tests/home/test_fixture.py
git commit -m "test: Allie's 3-floor fixture home" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: GET/PUT /api/home + `home.saved`

**Files:**
- Create: `box/src/wheres_allie/api/routes/home.py`
- Modify: `box/src/wheres_allie/api/app.py` (register the router)
- Test: `box/tests/api/test_home_routes.py`

**Step 1: Write failing test**
```python
# box/tests/api/test_home_routes.py
import json
from pathlib import Path

import pytest

from wheres_allie.api.deps import get_bus
from wheres_allie.home.model import Home

FIXTURE = Path(__file__).parent.parent / "fixtures" / "home_allie.json"


class FakeBus:
    def __init__(self):
        self.events = []

    def publish(self, topic, data):
        self.events.append((topic, data))


@pytest.fixture
def bus(client):
    fake = FakeBus()
    client.app.dependency_overrides[get_bus] = lambda: fake
    yield fake
    client.app.dependency_overrides.pop(get_bus, None)


def test_get_empty_home(client):
    r = client.get("/api/home")
    assert r.status_code == 200
    assert r.json() == {
        "home": Home().model_dump(mode="json"),
        "rooms": [],
        "graph": {"vertices": {}, "edges": []},
    }


def test_put_saves_derives_and_publishes(client, bus):
    r = client.put("/api/home", json=json.loads(FIXTURE.read_text()))
    assert r.status_code == 200
    body = r.json()
    assert body["home"]["version"] == 1
    assert {room["id"] for room in body["rooms"]} >= {"office", "loft"}
    assert body["graph"]["vertices"]["lm:bed_master"]["room_id"] == "master_bedroom"
    assert all(len(e) == 3 for e in body["graph"]["edges"])
    assert bus.events == [("home.saved", {"version": 1})]
    assert client.get("/api/home").json()["home"]["version"] == 1


def test_put_rejects_dangling_refs(client, bus):
    home = {"floors": [{"id": "main", "name": "Main", "elevation_m": 0}],
            "walls": [{"id": "w", "floor_id": "nope", "a": [0, 0], "b": [1, 0]}],
            "doors": [{"id": "d", "wall_id": "missing", "t": 0.5}]}
    r = client.put("/api/home", json=home)
    assert r.status_code == 422
    assert any("nope" in e for e in r.json()["detail"])
    assert any("missing" in e for e in r.json()["detail"])
    assert bus.events == []
```

**Step 2: Run test, verify failure**
`cd box && uv run pytest tests/api/test_home_routes.py -q`
Expected: FAIL with `assert 404 == 200` (the route doesn't exist yet)

**Step 3: Implement**
```python
# box/src/wheres_allie/api/routes/home.py
"""Home model API: GET/PUT /api/home, underlay upload + serving."""
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException

from wheres_allie.api.deps import get_bus, get_conn
from wheres_allie.home.geometry import detect_rooms
from wheres_allie.home.graph import build_graph
from wheres_allie.home.model import Home
from wheres_allie.home.store import load_home, save_home

router = APIRouter()


def home_payload(home: Home) -> dict:
    rooms = detect_rooms(home)
    graph = build_graph(home, rooms)
    return {
        "home": home.model_dump(mode="json"),
        "rooms": [asdict(r) for r in rooms],
        "graph": {
            "vertices": {k: asdict(v) for k, v in graph.vertices.items()},
            "edges": [list(e) for e in graph.edges],
        },
    }


def bad_refs(home: Home) -> list[str]:
    floors = {f.id for f in home.floors}
    walls = {w.id for w in home.walls}
    on_floor = [*home.walls, *home.room_labels, *home.landmarks, *home.nodes]
    errs = [f"{type(o).__name__} {o.id}: unknown floor {o.floor_id}" for o in on_floor
            if o.floor_id not in floors]
    errs += [f"Door {d.id}: unknown wall {d.wall_id}" for d in home.doors if d.wall_id not in walls]
    errs += [f"Stairs {s.id}: unknown floor" for s in home.stairs
             if {s.a.floor_id, s.b.floor_id} - floors]
    return errs


@router.get("/home")
async def get_home(conn=Depends(get_conn)) -> dict:
    return home_payload(load_home(conn))


@router.put("/home")
async def put_home(home: Home, conn=Depends(get_conn), bus=Depends(get_bus)) -> dict:
    if errs := bad_refs(home):
        raise HTTPException(422, errs)
    home.version = save_home(conn, home)
    bus.publish("home.saved", {"version": home.version})
    return home_payload(home)
```
In `box/src/wheres_allie/api/app.py`, add `home` to the `from wheres_allie.api.routes import ...` line. Then add the line below next to the other `include_router` calls, before any static/SPA mount at `/`:
```python
    app.include_router(home.router, prefix="/api")
```

**Step 4: Run test, verify pass**
`cd box && uv run pytest tests/api/test_home_routes.py -q` → `3 passed`

**Step 5: Commit**
```bash
git add box/src/wheres_allie/api/routes/home.py box/src/wheres_allie/api/app.py box/tests/api/test_home_routes.py
git commit -m "feat: GET/PUT /api/home with derived rooms and graph" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Underlay upload + serving

**Files:**
- Modify: `box/src/wheres_allie/api/routes/home.py`
- Test: `box/tests/api/test_underlay.py`

**Step 1: Write failing test**
```python
# box/tests/api/test_underlay.py
PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 32


def test_upload_and_serve(client):
    r = client.post("/api/home/underlay", files={"file": ("plan.PNG", PNG, "image/png")})
    assert r.status_code == 200
    image = r.json()["image"]
    assert image.startswith("uploads/") and image.endswith(".png")
    got = client.get(f"/api/{image}")
    assert got.status_code == 200 and got.content == PNG


def test_rejects_svg(client):
    r = client.post("/api/home/underlay", files={"file": ("x.svg", b"<svg/>", "image/svg+xml")})
    assert r.status_code == 415


def test_serving_refuses_other_names(client):
    assert client.get("/api/uploads/..%2Fwheres_allie.db").status_code == 404
    assert client.get("/api/uploads/0123456789abcdef.png").status_code == 404
```

**Step 2: Run test, verify failure**
`cd box && uv run pytest tests/api/test_underlay.py -q`
Expected: FAIL with `assert 404 == 200` in `test_upload_and_serve`, and `assert 404 == 415`

**Step 3: Implement**. Add these imports at the top of `api/routes/home.py`, merged with the existing ones:
```python
import re
import secrets
from pathlib import Path

from fastapi import UploadFile
from fastapi.responses import FileResponse

from wheres_allie.api.deps import get_settings
```
Append to `api/routes/home.py`:
```python
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}  # no .svg: it could carry script onto our origin
MAX_UPLOAD = 20 * 1024 * 1024
UPLOAD_NAME = re.compile(r"^[0-9a-f]{16}\.(png|jpe?g|webp)$")


@router.post("/home/underlay")
async def upload_underlay(file: UploadFile, settings=Depends(get_settings)) -> dict:
    ext = Path(file.filename or "").suffix.lower()
    if ext not in IMAGE_EXT:
        raise HTTPException(415, "Upload a png, jpg or webp image")
    data = await file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "Image is over 20 MB")
    folder = Path(settings.data_dir) / "uploads"
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{secrets.token_hex(8)}{ext}"
    (folder / name).write_bytes(data)
    return {"image": f"uploads/{name}"}


@router.get("/uploads/{name}")
async def get_upload(name: str, settings=Depends(get_settings)) -> FileResponse:
    path = Path(settings.data_dir) / "uploads" / name
    if not UPLOAD_NAME.match(name) or not path.is_file():
        raise HTTPException(404)
    return FileResponse(path)
```

**Step 4: Run test, verify pass**
`cd box && uv run pytest tests/api/test_underlay.py tests/api/test_home_routes.py -q` → `6 passed`

**Step 5: Commit**
```bash
git add box/src/wheres_allie/api/routes/home.py box/tests/api/test_underlay.py
git commit -m "feat: underlay image upload and serving" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: TS home types + units.ts

**Files:**
- Modify: `box/web/src/lib/types.ts` (append)
- Create or replace: `box/web/src/lib/units.ts` (if plan 01 left a stub, replace it; keep any extra exports it has)
- Test: `box/web/src/lib/units.test.ts`

**Step 1: Write failing test**
```ts
// box/web/src/lib/units.test.ts
import { describe, expect, it } from "vitest";
import { formatLength, parseLength } from "./units";

describe("formatLength", () => {
  it("formats feet and inches", () => expect(formatLength(3.81, "ft")).toBe(`12' 6"`));
  it("rounds inches up into feet", () => expect(formatLength(0.3048 * 2 - 0.001, "ft")).toBe(`2' 0"`));
  it("formats metres", () => expect(formatLength(3.8123, "m")).toBe("3.81 m"));
});

describe("parseLength", () => {
  it("parses feet+inches", () => expect(parseLength(`12' 6"`, "m")).toBeCloseTo(3.81, 3));
  it("parses ft suffix", () => expect(parseLength("12ft", "m")).toBeCloseTo(3.6576, 4));
  it("parses explicit metres", () => expect(parseLength("2m", "ft")).toBe(2));
  it("bare number uses current units", () => {
    expect(parseLength("10", "ft")).toBeCloseTo(3.048, 4);
    expect(parseLength("3.2", "m")).toBe(3.2);
  });
  it("rejects junk", () => expect(parseLength("abc", "m")).toBeNull());
});
```

**Step 2: Run test, verify failure**
`cd box/web && pnpm vitest run src/lib/units.test.ts`
Expected: FAIL with `Failed to resolve import "./units"` or `formatLength is not a function`

**Step 3: Implement**
```ts
// box/web/src/lib/units.ts
// The only place ft/m conversion lives (conventions §4). Model values are always metres.
export type Units = "ft" | "m";
const M_PER_FT = 0.3048;
const M_PER_IN = 0.0254;

export function formatLength(m: number, units: Units): string {
  if (units === "m") return `${m.toFixed(2)} m`;
  const inches = Math.round(m / M_PER_IN);
  return `${Math.floor(inches / 12)}' ${inches % 12}"`;
}

export function parseLength(s: string, units: Units): number | null {
  const t = s.trim().toLowerCase();
  const ftIn = t.match(/^(\d+(?:\.\d+)?)\s*(?:'|ft|′)\s*(?:(\d+(?:\.\d+)?)\s*(?:"|in|″)?)?$/);
  if (ftIn) return (parseFloat(ftIn[1]) * 12 + parseFloat(ftIn[2] ?? "0")) * M_PER_IN;
  const num = t.match(/^(\d+(?:\.\d+)?)\s*(m)?$/);
  if (!num) return null;
  const v = parseFloat(num[1]);
  return num[2] || units === "m" ? v : v * M_PER_FT;
}
```
Append the whole type block from **Interface additions D** (the `types.ts` part, from `export type Pt` to `HomeResponse`) to `box/web/src/lib/types.ts`. If plan 01 already defines a name there, keep plan 01's definition only when it's identical. Otherwise use this one.

**Step 4: Run test, verify pass**
`cd box/web && pnpm vitest run src/lib/units.test.ts && pnpm exec tsc --noEmit` → `8 passed`, tsc clean

**Step 5: Commit**
```bash
git add box/web/src/lib/units.ts box/web/src/lib/units.test.ts box/web/src/lib/types.ts
git commit -m "feat: web home types and ft/m units" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Plan geometry + viewport math

**Files:**
- Create: `box/web/src/components/plan/geom.ts`
- Create: `box/web/src/components/plan/viewport.ts`
- Test: `box/web/src/components/plan/geom.test.ts`, `box/web/src/components/plan/viewport.test.ts`

**Step 1: Write failing test**
```ts
// box/web/src/components/plan/geom.test.ts
import { describe, expect, it } from "vitest";
import { bounds, dist, doorSegment, nearestOnSegment, polygonCentroid } from "./geom";

describe("geom", () => {
  it("dist", () => expect(dist([0, 0], [3, 4])).toBe(5));
  it("nearestOnSegment projects and clamps", () => {
    expect(nearestOnSegment([2, 1], [0, 0], [4, 0])).toEqual({ t: 0.5, d: 1, p: [2, 0] });
    expect(nearestOnSegment([-3, 0], [0, 0], [4, 0]).t).toBe(0);
  });
  it("doorSegment is centred and stays on the wall", () => {
    expect(doorSegment([0, 0], [4, 0], 0.5, 1)).toEqual([[1.5, 0], [2.5, 0]]);
    expect(doorSegment([0, 0], [4, 0], 0, 1)).toEqual([[0, 0], [1, 0]]);
  });
  it("polygonCentroid", () => {
    const [x, y] = polygonCentroid([[0, 0], [4, 0], [4, 3], [0, 3]]);
    expect(x).toBeCloseTo(2);
    expect(y).toBeCloseTo(1.5);
  });
  it("bounds", () => {
    expect(bounds([])).toBeNull();
    expect(bounds([[1, 2], [4, -1]])).toEqual({ x: 1, y: -1, w: 3, h: 3 });
  });
});
```
```ts
// box/web/src/components/plan/viewport.test.ts
import { describe, expect, it } from "vitest";
import { clientToWorld, fitBounds, panBy, zoomAt } from "./viewport";

const rect = { left: 0, top: 0, width: 200, height: 100 };

describe("viewport", () => {
  it("clientToWorld accounts for letterboxing", () => {
    // 10x10 view in a 200x100 box: scale 10, 50px bars left/right
    expect(clientToWorld({ x: 0, y: 0, w: 10, h: 10 }, rect, 150, 50)).toEqual([10, 5]);
    expect(clientToWorld({ x: 0, y: 0, w: 10, h: 10 }, rect, 50, 0)).toEqual([0, 0]);
  });
  it("clientToWorld survives a zero-size rect (jsdom)", () => {
    const [x, y] = clientToWorld({ x: 0, y: 0, w: 10, h: 10 }, { left: 0, top: 0, width: 0, height: 0 }, 3, 4);
    expect(Number.isFinite(x) && Number.isFinite(y)).toBe(true);
  });
  it("zoomAt keeps the pivot fixed", () => {
    expect(zoomAt({ x: 0, y: 0, w: 10, h: 10 }, 2, [2, 3])).toEqual({ x: 1, y: 1.5, w: 5, h: 5 });
  });
  it("zoomAt clamps", () => {
    expect(zoomAt({ x: 0, y: 0, w: 10, h: 10 }, 1000, [0, 0]).w).toBe(1);
    expect(zoomAt({ x: 0, y: 0, w: 10, h: 10 }, 0.0001, [0, 0]).w).toBe(500);
  });
  it("panBy", () => expect(panBy({ x: 0, y: 0, w: 1, h: 1 }, 2, -1)).toEqual({ x: 2, y: -1, w: 1, h: 1 }));
  it("fitBounds pads and has an empty default", () => {
    expect(fitBounds(null)).toEqual({ x: -1, y: -1, w: 12, h: 9 });
    expect(fitBounds({ x: 0, y: 0, w: 10, h: 8 })).toEqual({ x: -1, y: -1, w: 12, h: 10 });
  });
});
```

**Step 2: Run test, verify failure**
`cd box/web && pnpm vitest run src/components/plan`
Expected: FAIL with `Failed to resolve import "./geom"` / `"./viewport"`

**Step 3: Implement**
```ts
// box/web/src/components/plan/geom.ts
import type { Pt } from "../../lib/types";

export interface Box { x: number; y: number; w: number; h: number }

export const dist = (a: Pt, b: Pt) => Math.hypot(b[0] - a[0], b[1] - a[1]);
export const lerp = (a: Pt, b: Pt, t: number): Pt => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];

export function nearestOnSegment(p: Pt, a: Pt, b: Pt): { t: number; d: number; p: Pt } {
  const dx = b[0] - a[0], dy = b[1] - a[1];
  const len2 = dx * dx + dy * dy;
  const t = len2 === 0 ? 0 : Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / len2));
  const q = lerp(a, b, t);
  return { t, d: dist(p, q), p: q };
}

/** The door opening along wall a→b, centred at t, clamped so it stays on the wall. */
export function doorSegment(a: Pt, b: Pt, t: number, width: number): [Pt, Pt] {
  const len = dist(a, b);
  if (len === 0) return [a, a];
  const h = Math.min(width / 2 / len, 0.5);
  const c = Math.max(h, Math.min(1 - h, t));
  return [lerp(a, b, c - h), lerp(a, b, c + h)];
}

export function polygonCentroid(poly: Pt[]): Pt {
  let a = 0, cx = 0, cy = 0;
  poly.forEach(([x0, y0], i) => {
    const [x1, y1] = poly[(i + 1) % poly.length];
    const c = x0 * y1 - x1 * y0;
    a += c; cx += (x0 + x1) * c; cy += (y0 + y1) * c;
  });
  if (Math.abs(a) < 1e-9) {
    const n = poly.length || 1;
    return [poly.reduce((s, p) => s + p[0], 0) / n, poly.reduce((s, p) => s + p[1], 0) / n];
  }
  return [cx / (3 * a), cy / (3 * a)];
}

export function bounds(pts: Pt[]): Box | null {
  if (!pts.length) return null;
  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
  const x = Math.min(...xs), y = Math.min(...ys);
  return { x, y, w: Math.max(...xs) - x, h: Math.max(...ys) - y };
}
```
```ts
// box/web/src/components/plan/viewport.ts
// The SVG viewBox is the view, in metres. preserveAspectRatio is the default (xMidYMid meet).
import type { Pt } from "../../lib/types";
import type { Box } from "./geom";

export interface View { x: number; y: number; w: number; h: number }
type Rect = { left: number; top: number; width: number; height: number };
const MIN_W = 1, MAX_W = 500;

export function clientToWorld(v: View, r: Rect, cx: number, cy: number): Pt {
  const s = r.width && r.height ? Math.min(r.width / v.w, r.height / v.h) : 1;
  const ox = (r.width - v.w * s) / 2, oy = (r.height - v.h * s) / 2;
  return [v.x + (cx - r.left - ox) / s, v.y + (cy - r.top - oy) / s];
}

export function zoomAt(v: View, factor: number, p: Pt): View {
  const f = Math.min(Math.max(factor, v.w / MAX_W), v.w / MIN_W);
  return { x: p[0] - (p[0] - v.x) / f, y: p[1] - (p[1] - v.y) / f, w: v.w / f, h: v.h / f };
}

export const panBy = (v: View, dx: number, dy: number): View => ({ ...v, x: v.x + dx, y: v.y + dy });

export function fitBounds(b: Box | null, pad = 1): View {
  if (!b) return { x: -1, y: -1, w: 12, h: 9 };
  const w = Math.max(b.w, 4) + 2 * pad, h = Math.max(b.h, 3) + 2 * pad;
  return { x: b.x + b.w / 2 - w / 2, y: b.y + b.h / 2 - h / 2, w, h };
}
```

**Step 4: Run test, verify pass**
`cd box/web && pnpm vitest run src/components/plan` → `11 passed`

**Step 5: Commit**
```bash
git add box/web/src/components/plan/geom.ts box/web/src/components/plan/viewport.ts box/web/src/components/plan/*.test.ts
git commit -m "feat: plan geometry and viewport math" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Shared PlanCanvas renderer

**Files:**
- Create: `box/web/src/components/plan/PlanCanvas.tsx`
- Create: `box/web/src/components/plan/plan.css`
- Test: `box/web/src/components/plan/PlanCanvas.test.tsx`

**Step 1: Write failing test**
Install the test DOM if plan 01 didn't: `cd box/web && pnpm add -D jsdom @testing-library/react`
```tsx
// box/web/src/components/plan/PlanCanvas.test.tsx
// @vitest-environment jsdom
import { cleanup, fireEvent, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Home, Room } from "../../lib/types";
import { PlanCanvas, type PlanPointer } from "./PlanCanvas";

const wall = (id: string, floor_id: string, a: [number, number], b: [number, number], invisible = false) =>
  ({ id, floor_id, a, b, thickness_m: 0.12, invisible });

const home: Home = {
  version: 1,
  floors: [
    { id: "main", name: "Main", elevation_m: 0, underlay: null },
    { id: "up", name: "Up", elevation_m: 3, underlay: null },
  ],
  walls: [
    wall("w0", "main", [0, 0], [4, 0]), wall("w1", "main", [4, 0], [4, 3]),
    wall("w2", "main", [4, 3], [0, 3]), wall("w3", "main", [0, 3], [0, 0]),
    wall("div", "main", [2, 0], [2, 3], true), wall("u0", "up", [0, 0], [1, 0]),
  ],
  room_labels: [{ id: "kitchen", floor_id: "main", name: "Kitchen", seed: [1, 1] }],
  doors: [{ id: "d1", wall_id: "w0", t: 0.5, width_m: 0.9 }],
  stairs: [{ id: "s1", name: "Stairs", a: { floor_id: "main", x: 1, y: 2 }, b: { floor_id: "up", x: 1, y: 2 } }],
  landmarks: [{ id: "l1", floor_id: "main", x: 3, y: 2, type: "bed", name: "Allie's bed", radius_m: 0.75 }],
  nodes: [{ id: "kitchen", floor_id: "main", x: 3, y: 1, z_m: 1, name: "Kitchen node" }],
};
const rooms: Room[] = [{ id: "kitchen", floor_id: "main", name: "Kitchen", polygon: [[0, 0], [4, 0], [4, 3], [0, 3]] }];

afterEach(cleanup);

describe("PlanCanvas", () => {
  it("draws only the current floor and hides dividers when not editing", () => {
    const { container, getByText } = render(<PlanCanvas home={home} rooms={rooms} floorId="main" />);
    expect(container.querySelectorAll('[data-coll="walls"]')).toHaveLength(4);
    expect(container.querySelectorAll('[data-coll="doors"]')).toHaveLength(1);
    expect(getByText("Kitchen")).toHaveProperty("tagName", "text");
    getByText("Allie's bed");
    getByText("Kitchen node");
    getByText("Stairs → Up");
    expect(container.querySelector('[data-coll="room_labels"]')).toBeNull();
  });

  it("editing shows dividers, seeds and handles of the selected wall", () => {
    const { container } = render(
      <PlanCanvas home={home} rooms={rooms} floorId="main" editing selected={{ coll: "walls", id: "w0" }} />,
    );
    expect(container.querySelectorAll('[data-coll="walls"][data-id]:not([data-part])')).toHaveLength(5);
    expect(container.querySelectorAll('[data-coll="walls"][data-part]')).toHaveLength(2);
    expect(container.querySelector('[data-coll="room_labels"]')).not.toBeNull();
  });

  it("reports hits with coll, id and part", () => {
    const down = vi.fn((_p: PlanPointer) => true);
    const { container } = render(
      <PlanCanvas home={home} rooms={rooms} floorId="main" editing selected={{ coll: "walls", id: "w0" }} onPointerDown={down} />,
    );
    fireEvent.pointerDown(container.querySelector('[data-coll="landmarks"] .plan-landmark')!);
    expect(down.mock.calls[0][0].hit).toEqual({ coll: "landmarks", id: "l1" });
    fireEvent.pointerDown(container.querySelector('[data-part="b"]')!);
    expect(down.mock.calls[1][0].hit).toEqual({ coll: "walls", id: "w0", part: "b" });
    fireEvent.pointerDown(container.querySelector("svg")!);
    expect(down.mock.calls[2][0].hit).toBeNull();
  });

  it("renders overlay children and coverage rings", () => {
    const { container } = render(
      <PlanCanvas home={home} rooms={rooms} floorId="main" coverage={{ kitchen: 4 }}>
        <circle className="pet" cx={1} cy={1} r={0.2} />
      </PlanCanvas>,
    );
    expect(container.querySelector("circle.pet")).not.toBeNull();
    expect(container.querySelector(".plan-coverage")?.getAttribute("r")).toBe("4");
  });
});
```

**Step 2: Run test, verify failure**
`cd box/web && pnpm vitest run src/components/plan/PlanCanvas.test.tsx`
Expected: FAIL with `Failed to resolve import "./PlanCanvas"`

**Step 3: Implement**
```tsx
// box/web/src/components/plan/PlanCanvas.tsx
// Shared SVG floorplan renderer (Editor, Live, History, MCP App). World units are metres, y down.
import { useEffect, useId, useRef, useState, type PointerEvent as RPointerEvent, type ReactNode } from "react";
import type { HitColl, Home, LandmarkType, Pt, Room, Underlay } from "../../lib/types";
import { bounds, doorSegment, polygonCentroid, type Box } from "./geom";
import { clientToWorld, fitBounds, panBy, zoomAt, type View } from "./viewport";
import "./plan.css";

export interface Hit { coll: HitColl; id: string; part?: "a" | "b" }
export interface PlanPointer { x: number; y: number; hit: Hit | null; event: RPointerEvent<SVGSVGElement> }
export interface PlanCanvasProps {
  home: Home;
  rooms: Room[];
  floorId: string;
  selected?: { coll: HitColl; id: string } | null;
  coverage?: Record<string, number>;
  editing?: boolean;
  showUnderlay?: boolean;
  fitKey?: string;
  onPointerDown?: (p: PlanPointer) => boolean | void;
  onPointerMove?: (p: PlanPointer) => void;
  onPointerUp?: (p: PlanPointer) => void;
  children?: ReactNode;
  className?: string;
}

// ponytail: letter glyphs; swap for drawn icons if time allows
const GLYPH: Record<LandmarkType, string> = {
  bed: "B", food_bowl: "F", water_bowl: "W", couch: "C", crate: "K", door: "D", custom: "★",
};

function readHit(target: EventTarget): Hit | null {
  const el = (target as Element).closest?.("[data-coll]");
  if (!el) return null;
  const part = el.getAttribute("data-part") as "a" | "b" | null;
  const hit: Hit = { coll: el.getAttribute("data-coll") as HitColl, id: el.getAttribute("data-id")! };
  if (part) hit.part = part;
  return hit;
}

export function floorBounds(home: Home, floorId: string): Box | null {
  const on = (o: { floor_id: string }) => o.floor_id === floorId;
  return bounds([
    ...home.walls.filter(on).flatMap((w) => [w.a, w.b]),
    ...[...home.landmarks, ...home.nodes].filter(on).map((o): Pt => [o.x, o.y]),
    ...home.stairs.flatMap((s) => [s.a, s.b]).filter(on).map((e): Pt => [e.x, e.y]),
  ]);
}

function UnderlayImage({ u }: { u: Underlay }) {
  const href = `/api/${u.image}`;
  const [size, setSize] = useState<Pt | null>(null);
  useEffect(() => {
    const img = new Image();
    img.onload = () => setSize([img.naturalWidth, img.naturalHeight]);
    img.src = href;
  }, [href]);
  if (!size) return null;
  return (
    <image href={href} width={size[0]} height={size[1]} opacity={u.opacity} pointerEvents="none"
      transform={`translate(${u.offset[0]} ${u.offset[1]}) rotate(${u.rotation_deg}) scale(${u.scale_m_per_px})`} />
  );
}

export function PlanCanvas(props: PlanCanvasProps) {
  const { home, rooms, floorId, selected = null, coverage, editing = false, showUnderlay = true } = props;
  const svgRef = useRef<SVGSVGElement>(null);
  const pan = useRef<{ x: number; y: number } | null>(null);
  const gridId = `grid${useId().replace(/:/g, "")}`;
  const [view, setView] = useState<View>(() => fitBounds(floorBounds(home, floorId)));
  const fitKey = props.fitKey ?? floorId;
  useEffect(() => setView(fitBounds(floorBounds(home, floorId))), [fitKey]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const rect = svg.getBoundingClientRect();
      setView((v) => zoomAt(v, Math.exp(-e.deltaY * 0.0015), clientToWorld(v, rect, e.clientX, e.clientY)));
    };
    svg.addEventListener("wheel", onWheel, { passive: false });
    return () => svg.removeEventListener("wheel", onWheel);
  }, []);

  const toPointer = (e: RPointerEvent<SVGSVGElement>): PlanPointer => {
    const [x, y] = clientToWorld(view, e.currentTarget.getBoundingClientRect(), e.clientX, e.clientY);
    return { x, y, hit: readHit(e.target), event: e };
  };
  const onDown = (e: RPointerEvent<SVGSVGElement>) => {
    const p = toPointer(e); // read the hit before capture retargets later events
    e.currentTarget.setPointerCapture?.(e.pointerId);
    if (props.onPointerDown?.(p)) return;
    if (e.button !== 2) pan.current = { x: e.clientX, y: e.clientY };
  };
  const onMove = (e: RPointerEvent<SVGSVGElement>) => {
    if (pan.current) {
      const rect = e.currentTarget.getBoundingClientRect();
      const a = clientToWorld(view, rect, pan.current.x, pan.current.y);
      const b = clientToWorld(view, rect, e.clientX, e.clientY);
      pan.current = { x: e.clientX, y: e.clientY };
      setView((v) => panBy(v, a[0] - b[0], a[1] - b[1]));
      return;
    }
    props.onPointerMove?.(toPointer(e));
  };
  const onUp = (e: RPointerEvent<SVGSVGElement>) => {
    if (pan.current) {
      pan.current = null;
      return;
    }
    props.onPointerUp?.(toPointer(e));
  };

  const fs = view.w / 60; // label size tracks zoom so text stays readable
  const sel = (coll: HitColl, id: string) => (selected?.coll === coll && selected.id === id ? " is-selected" : "");
  const on = (o: { floor_id: string }) => o.floor_id === floorId;
  const walls = home.walls.filter((w) => on(w) && (editing || !w.invisible));
  const wallById = new Map(home.walls.map((w) => [w.id, w]));
  const floorName = (id: string) => home.floors.find((f) => f.id === id)?.name ?? id;
  const underlay = home.floors.find((f) => f.id === floorId)?.underlay;
  const selWall = editing && selected?.coll === "walls" ? home.walls.find((w) => w.id === selected.id && on(w)) : undefined;
  const floorRooms = rooms.filter(on);

  return (
    <svg ref={svgRef} className={`plan-canvas ${props.className ?? ""}`}
      viewBox={`${view.x} ${view.y} ${view.w} ${view.h}`}
      onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp}>
      <defs>
        <pattern id={gridId} width={1} height={1} patternUnits="userSpaceOnUse">
          <path d="M 0.5 0 V 1 M 0 0.5 H 1" className="plan-grid-minor" />
          <path d="M 0 0 V 1 M 0 0 H 1" className="plan-grid-major" />
        </pattern>
      </defs>
      <rect x={view.x} y={view.y} width={view.w} height={view.h} fill={`url(#${gridId})`} />
      {showUnderlay && underlay && <UnderlayImage u={underlay} />}

      {floorRooms.map((r) => (
        <polygon key={r.id} data-coll="rooms" data-id={r.id} className={`plan-room${sel("rooms", r.id)}`}
          points={r.polygon.map((p) => p.join(",")).join(" ")} />
      ))}

      {walls.map((w) => (
        <g key={w.id} data-coll="walls" data-id={w.id}
          className={`plan-wall${w.invisible ? " is-divider" : ""}${sel("walls", w.id)}`}>
          <line x1={w.a[0]} y1={w.a[1]} x2={w.b[0]} y2={w.b[1]} className="plan-wall-line" strokeWidth={w.thickness_m} />
          <line x1={w.a[0]} y1={w.a[1]} x2={w.b[0]} y2={w.b[1]} className="plan-hit" />
        </g>
      ))}

      {home.doors.map((d) => {
        const w = wallById.get(d.wall_id);
        if (!w || !on(w)) return null;
        const [p, q] = doorSegment(w.a, w.b, d.t, d.width_m);
        return (
          <g key={d.id} data-coll="doors" data-id={d.id} className={`plan-door${sel("doors", d.id)}`}>
            <line x1={p[0]} y1={p[1]} x2={q[0]} y2={q[1]} className="plan-door-gap" strokeWidth={w.thickness_m + 0.04} />
            <line x1={p[0]} y1={p[1]} x2={q[0]} y2={q[1]} className="plan-door-line" />
            <line x1={p[0]} y1={p[1]} x2={q[0]} y2={q[1]} className="plan-hit" />
          </g>
        );
      })}

      {floorRooms.map((r) => {
        const [x, y] = polygonCentroid(r.polygon);
        return <text key={r.id} x={x} y={y} fontSize={fs * 1.2} className="plan-room-name">{r.name}</text>;
      })}

      {home.stairs.flatMap((s) =>
        (["a", "b"] as const).filter((k) => on(s[k])).map((k) => {
          const e = s[k], other = s[k === "a" ? "b" : "a"];
          return (
            <g key={s.id + k} data-coll="stairs" data-id={s.id} data-part={k}
              className={`plan-stairs-g${sel("stairs", s.id)}`} transform={`translate(${e.x} ${e.y})`}>
              <rect x={-0.45} y={-0.45} width={0.9} height={0.9} className="plan-stairs" />
              <path d="M -0.45 -0.15 H 0.45 M -0.45 0.15 H 0.45" className="plan-stairs-tread" />
              <text y={0.45 + fs} fontSize={fs} className="plan-label">{`${s.name} → ${floorName(other.floor_id)}`}</text>
            </g>
          );
        }),
      )}

      {home.landmarks.filter(on).map((lm) => (
        <g key={lm.id} data-coll="landmarks" data-id={lm.id} className={`plan-landmark-g${sel("landmarks", lm.id)}`}
          transform={`translate(${lm.x} ${lm.y})`}>
          <circle r={lm.radius_m} className="plan-landmark-zone" />
          <circle r={0.22} className="plan-landmark" />
          <text fontSize={0.26} className="plan-landmark-glyph">{GLYPH[lm.type]}</text>
          <text y={0.22 + fs} fontSize={fs} className="plan-label">{lm.name}</text>
        </g>
      ))}

      {home.nodes.filter(on).map((n) => (
        <g key={n.id} data-coll="nodes" data-id={n.id} className={`plan-node-g${sel("nodes", n.id)}`}
          transform={`translate(${n.x} ${n.y})`}>
          {coverage?.[n.id] ? <circle r={coverage[n.id]} className="plan-coverage" /> : null}
          <rect x={-0.15} y={-0.15} width={0.3} height={0.3} transform="rotate(45)" className="plan-node" />
          <text y={0.2 + fs} fontSize={fs} className="plan-label">{n.name}</text>
        </g>
      ))}

      {editing && home.room_labels.filter(on).map((lb) => (
        <circle key={lb.id} data-coll="room_labels" data-id={lb.id} cx={lb.seed[0]} cy={lb.seed[1]} r={0.15}
          className={`plan-seed${sel("room_labels", lb.id)}`} />
      ))}

      {selWall && (["a", "b"] as const).map((k) => (
        <circle key={k} data-coll="walls" data-id={selWall.id} data-part={k}
          cx={selWall[k][0]} cy={selWall[k][1]} r={0.15} className="plan-handle" />
      ))}

      {props.children}
    </svg>
  );
}
```
```css
/* box/web/src/components/plan/plan.css */
.plan-canvas { width: 100%; height: 100%; display: block; background: var(--bg); touch-action: none; user-select: none; }
.plan-grid-minor { stroke: var(--line); stroke-width: 0.01; opacity: 0.6; fill: none; }
.plan-grid-major { stroke: var(--line); stroke-width: 0.02; fill: none; }
.plan-room { fill: var(--room-fill); stroke: none; }
.plan-room.is-selected { fill: rgba(0, 111, 255, 0.1); }
.plan-room-name { fill: var(--muted); text-anchor: middle; dominant-baseline: central; font-family: var(--font); font-weight: 600; pointer-events: none; }
.plan-wall-line { stroke: var(--wall); stroke-linecap: square; }
.plan-wall.is-divider .plan-wall-line { stroke: var(--muted); stroke-width: 0.03; stroke-dasharray: 0.15 0.1; }
.plan-hit { stroke: transparent; stroke-width: 0.4; pointer-events: stroke; }
.plan-wall.is-selected .plan-wall-line, .plan-door.is-selected .plan-door-line { stroke: var(--accent); }
.plan-door-gap { stroke: var(--bg); }
.plan-door-line { stroke: var(--accent); stroke-width: 0.03; }
.plan-stairs { fill: var(--panel); stroke: var(--wall); stroke-width: 0.03; }
.plan-stairs-tread { stroke: var(--wall); stroke-width: 0.02; }
.plan-landmark-zone { fill: var(--accent); opacity: 0.06; pointer-events: none; }
.plan-landmark { fill: var(--panel); stroke: var(--accent); stroke-width: 0.03; }
.plan-landmark-glyph { fill: var(--accent); text-anchor: middle; dominant-baseline: central; font-family: var(--font); font-weight: 700; pointer-events: none; }
.plan-node { fill: var(--accent-2); stroke: var(--panel); stroke-width: 0.03; }
.plan-coverage { fill: var(--accent-2); fill-opacity: 0.08; stroke: var(--accent-2); stroke-width: 0.02; stroke-dasharray: 0.2 0.15; pointer-events: none; }
.plan-label { fill: var(--text); text-anchor: middle; font-family: var(--font); pointer-events: none; }
.plan-seed { fill: var(--warn); stroke: var(--panel); stroke-width: 0.03; }
.plan-handle { fill: var(--panel); stroke: var(--accent); stroke-width: 0.04; }
.is-selected .plan-landmark, .is-selected .plan-node, .is-selected .plan-stairs, .plan-seed.is-selected { stroke: var(--accent); stroke-width: 0.08; }
```

**Step 4: Run test, verify pass**
`cd box/web && pnpm vitest run src/components/plan && pnpm exec tsc --noEmit` → `15 passed`, tsc clean

**Step 5: Commit**
```bash
git add box/web/src/components/plan box/web/package.json box/web/pnpm-lock.yaml
git commit -m "feat: shared SVG PlanCanvas with pan/zoom and hit testing" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: History reducer + snapping

**Files:**
- Create: `box/web/src/pages/editor/history.ts`
- Create: `box/web/src/pages/editor/snap.ts`
- Test: `box/web/src/pages/editor/history.test.ts`, `box/web/src/pages/editor/snap.test.ts`

**Step 1: Write failing test**
```ts
// box/web/src/pages/editor/history.test.ts
import { describe, expect, it } from "vitest";
import { initHistory, push, redo, undo } from "./history";

describe("history", () => {
  it("undo/redo walk the stack", () => {
    const h = push(push(initHistory(1), 2), 3);
    expect(undo(h).present).toBe(2);
    expect(undo(undo(h)).present).toBe(1);
    expect(redo(undo(h)).present).toBe(3);
  });
  it("a new push clears the redo stack", () => {
    expect(push(undo(push(initHistory(1), 2)), 9).future).toEqual([]);
  });
  it("same key coalesces into one undo step", () => {
    const h = push(push(push(initHistory(1), 2, "drag"), 3, "drag"), 4, "drag");
    expect(h.past).toEqual([1]);
    expect(undo(h).present).toBe(1);
  });
  it("undo breaks coalescing", () => {
    const h = push(undo(push(initHistory(1), 2, "k")), 3, "k");
    expect(h.past).toEqual([1]);
  });
  it("no-ops return the same object", () => {
    const h = initHistory(1);
    expect(push(h, 1)).toBe(h);
    expect(undo(h)).toBe(h);
    expect(redo(h)).toBe(h);
  });
  it("caps the undo stack", () => {
    let h = initHistory(0);
    for (let i = 1; i <= 250; i++) h = push(h, i);
    expect(h.past).toHaveLength(200);
  });
});
```
```ts
// box/web/src/pages/editor/snap.test.ts
import { describe, expect, it } from "vitest";
import { snapPoint } from "./snap";

const base = { endpoints: [], grid: 0.05, angleStepDeg: 45, tol: 0.25 };

describe("snapPoint", () => {
  it("snaps to a nearby endpoint first", () => {
    expect(snapPoint([4.1, 0.1], { ...base, anchor: [0, 0], endpoints: [[4, 0]] }))
      .toEqual({ p: [4, 0], kind: "endpoint" });
  });
  it("snaps to 90° from the anchor and rounds the length to the grid", () => {
    expect(snapPoint([3.0, 0.3], { ...base, anchor: [0, 0], angleStepDeg: 90 }))
      .toEqual({ p: [3, 0], kind: "angle" });
  });
  it("snaps to 45° diagonals", () => {
    const s = snapPoint([2, 2.2], { ...base, anchor: [0, 0] });
    expect(s.kind).toBe("angle");
    expect(s.p[0]).toBeCloseTo(s.p[1], 6);
  });
  it("falls back to the grid without an anchor", () => {
    expect(snapPoint([1.23, 4.56], { ...base, grid: 0.5 })).toEqual({ p: [1, 4.5], kind: "grid" });
  });
});
```

**Step 2: Run test, verify failure**
`cd box/web && pnpm vitest run src/pages/editor`
Expected: FAIL with `Failed to resolve import "./history"` / `"./snap"`

**Step 3: Implement**
```ts
// box/web/src/pages/editor/history.ts
// Undo/redo stack. Pushes with the same non-null key (one drag, one text field) coalesce into one step.
export interface History<T> { past: T[]; present: T; future: T[]; key: string | null }
const LIMIT = 200;

export const initHistory = <T>(present: T): History<T> => ({ past: [], present, future: [], key: null });

export function push<T>(h: History<T>, next: T, key: string | null = null): History<T> {
  if (next === h.present) return h;
  if (key !== null && key === h.key) return { ...h, present: next, future: [] };
  return { past: [...h.past, h.present].slice(-LIMIT), present: next, future: [], key };
}

export function undo<T>(h: History<T>): History<T> {
  if (!h.past.length) return h;
  return { past: h.past.slice(0, -1), present: h.past[h.past.length - 1], future: [h.present, ...h.future], key: null };
}

export function redo<T>(h: History<T>): History<T> {
  if (!h.future.length) return h;
  return { past: [...h.past, h.present], present: h.future[0], future: h.future.slice(1), key: null };
}
```
```ts
// box/web/src/pages/editor/snap.ts
import { dist } from "../../components/plan/geom";
import type { Pt } from "../../lib/types";

export interface SnapOpts { anchor?: Pt | null; endpoints: Pt[]; grid: number; angleStepDeg: number; tol: number }
export interface Snap { p: Pt; kind: "endpoint" | "angle" | "grid" }

const mm = (v: number) => Math.round(v * 1000) / 1000;

/** Priority: existing wall endpoint within tol → angle from anchor (length on grid) → grid. */
export function snapPoint(raw: Pt, o: SnapOpts): Snap {
  let best: Pt | null = null;
  let bestD = o.tol;
  for (const e of o.endpoints) {
    const d = dist(raw, e);
    if (d <= bestD) { best = e; bestD = d; }
  }
  if (best) return { p: best, kind: "endpoint" };
  if (o.anchor && o.angleStepDeg > 0) {
    const [ax, ay] = o.anchor;
    const step = (o.angleStepDeg * Math.PI) / 180;
    const ang = Math.round(Math.atan2(raw[1] - ay, raw[0] - ax) / step) * step;
    const len = Math.round(dist(o.anchor, raw) / o.grid) * o.grid;
    return { p: [mm(ax + Math.cos(ang) * len), mm(ay + Math.sin(ang) * len)], kind: "angle" };
  }
  return { p: [mm(Math.round(raw[0] / o.grid) * o.grid), mm(Math.round(raw[1] / o.grid) * o.grid)], kind: "grid" };
}
```

**Step 4: Run test, verify pass**
`cd box/web && pnpm vitest run src/pages/editor` → `10 passed`

**Step 5: Commit**
```bash
git add box/web/src/pages/editor/history.ts box/web/src/pages/editor/snap.ts box/web/src/pages/editor/*.test.ts
git commit -m "feat: editor undo history and wall snapping" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: Home edit operations

**Files:**
- Create: `box/web/src/pages/editor/ops.ts`
- Test: `box/web/src/pages/editor/ops.test.ts`

**Step 1: Write failing test**
```ts
// box/web/src/pages/editor/ops.test.ts
import { describe, expect, it } from "vitest";
import type { Home } from "../../lib/types";
import * as ops from "./ops";

function twoFloors(): Home {
  let h = ops.addFloor(ops.emptyHome(), "Main").home;
  h = ops.addFloor(h, "Up").home;
  return h;
}

describe("ops", () => {
  it("addFloor stacks elevations 3 m apart", () => {
    const h = twoFloors();
    expect(h.floors.map((f) => [f.name, f.elevation_m])).toEqual([["Main", 0], ["Up", 3]]);
    expect(h.floors[0].id).toMatch(/^[0-9a-f]{8}$/);
  });

  it("addWall + placeDoor, deleting the wall removes its door", () => {
    const h = twoFloors();
    const w = ops.addWall(h, h.floors[0].id, [0, 0], [4, 0]);
    const d = ops.placeDoor(w.home, w.id, 0.25);
    expect(d.home.doors[0]).toMatchObject({ wall_id: w.id, t: 0.25, width_m: 0.9 });
    const del = ops.deleteObj(d.home, "walls", w.id);
    expect(del.walls).toEqual([]);
    expect(del.doors).toEqual([]);
  });

  it("deleting a floor cascades to everything on it", () => {
    let h = twoFloors();
    const [main, up] = h.floors.map((f) => f.id);
    h = ops.addWall(h, main, [0, 0], [1, 0]).home;
    h = ops.addLandmark(h, main, [1, 1], "bed").home;
    h = ops.addStairs(h, { floor_id: main, x: 0, y: 0 }, { floor_id: up, x: 0, y: 0 }).home;
    h = ops.deleteObj(h, "floors", main);
    expect([h.floors.length, h.walls.length, h.landmarks.length, h.stairs.length]).toEqual([1, 0, 0, 0]);
  });

  it("moveWallEnd drags connected corners along", () => {
    let h = twoFloors();
    const f = h.floors[0].id;
    const a = ops.addWall(h, f, [0, 0], [4, 0]);
    const b = ops.addWall(a.home, f, [4, 0], [4, 3]);
    h = ops.moveTo(b.home, "walls", a.id, "b", [5, 0]);
    expect(h.walls.map((w) => [w.a, w.b])).toEqual([[[0, 0], [5, 0]], [[5, 0], [4, 3]]]);
  });

  it("updateObj only touches its own collection (node id can equal a label id)", () => {
    let h = twoFloors();
    const f = h.floors[0].id;
    h = ops.addNode(h, { id: "kitchen", name: "Kitchen" }, f, [1, 1]).home;
    h = { ...h, room_labels: [{ id: "kitchen", floor_id: f, name: "Kitchen", seed: [1, 1] }] };
    h = ops.updateObj(h, "nodes", "kitchen", { name: "Node K" });
    expect(h.nodes[0].name).toBe("Node K");
    expect(h.room_labels[0].name).toBe("Kitchen");
  });

  it("moveTo moves one stairs end", () => {
    let h = twoFloors();
    const [main, up] = h.floors.map((f) => f.id);
    const s = ops.addStairs(h, { floor_id: main, x: 0, y: 0 }, { floor_id: up, x: 0, y: 0 });
    h = ops.moveTo(s.home, "stairs", s.id, "b", [2, 3]);
    expect(h.stairs[0].a).toEqual({ floor_id: main, x: 0, y: 0 });
    expect(h.stairs[0].b).toEqual({ floor_id: up, x: 2, y: 3 });
  });

  it("recalibrate scales about the first point", () => {
    const u = { image: "uploads/x.png", scale_m_per_px: 0.01, offset: [0, 0] as [number, number], rotation_deg: 0, opacity: 0.4 };
    expect(ops.recalibrate(u, [1, 1], [3, 1], 4)).toMatchObject({ scale_m_per_px: 0.02, offset: [-1, -1] });
    expect(ops.recalibrate(u, [1, 1], [1, 1], 4)).toBe(u);
  });
});
```

**Step 2: Run test, verify failure**
`cd box/web && pnpm vitest run src/pages/editor/ops.test.ts`
Expected: FAIL with `Failed to resolve import "./ops"`

**Step 3: Implement**
```ts
// box/web/src/pages/editor/ops.ts
// Pure edits on the Home document. Every function returns a new Home; nothing mutates.
import { dist } from "../../components/plan/geom";
import type { Home, HomeCollection, LandmarkType, Pt, StairsEnd, Underlay } from "../../lib/types";

export type Added = { home: Home; id: string };

// getRandomValues works on plain-http LAN origins; crypto.randomUUID does not.
export const newId = () =>
  Array.from(crypto.getRandomValues(new Uint8Array(4)), (b) => b.toString(16).padStart(2, "0")).join("");

export const emptyHome = (): Home => ({
  version: 0, floors: [], walls: [], room_labels: [], doors: [], stairs: [], landmarks: [], nodes: [],
});

export const LANDMARK_NAMES: Record<LandmarkType, string> = {
  bed: "Bed", food_bowl: "Food bowl", water_bowl: "Water bowl", couch: "Couch", crate: "Crate", door: "Door", custom: "Spot",
};

export function addFloor(h: Home, name?: string): Added {
  const id = newId();
  const elevation_m = h.floors.length ? Math.max(...h.floors.map((f) => f.elevation_m)) + 3 : 0;
  return { id, home: { ...h, floors: [...h.floors, { id, name: name ?? `Floor ${h.floors.length + 1}`, elevation_m, underlay: null }] } };
}

export function addWall(h: Home, floor_id: string, a: Pt, b: Pt): Added {
  const id = newId();
  return { id, home: { ...h, walls: [...h.walls, { id, floor_id, a, b, thickness_m: 0.12, invisible: false }] } };
}

export function placeDoor(h: Home, wall_id: string, t: number): Added {
  const id = newId();
  return { id, home: { ...h, doors: [...h.doors, { id, wall_id, t, width_m: 0.9 }] } };
}

export function addLandmark(h: Home, floor_id: string, p: Pt, type: LandmarkType): Added {
  const id = newId();
  const lm = { id, floor_id, x: p[0], y: p[1], type, name: LANDMARK_NAMES[type], radius_m: 0.75 };
  return { id, home: { ...h, landmarks: [...h.landmarks, lm] } };
}

export function addNode(h: Home, n: { id: string; name: string | null }, floor_id: string, p: Pt): Added {
  const node = { id: n.id, floor_id, x: p[0], y: p[1], z_m: 1.0, name: n.name ?? n.id };
  return { id: n.id, home: { ...h, nodes: [...h.nodes.filter((x) => x.id !== n.id), node] } };
}

export function addLabel(h: Home, floor_id: string, seed: Pt, name: string): Added {
  const id = newId();
  return { id, home: { ...h, room_labels: [...h.room_labels, { id, floor_id, name, seed }] } };
}

export function addStairs(h: Home, a: StairsEnd, b: StairsEnd): Added {
  const id = newId();
  return { id, home: { ...h, stairs: [...h.stairs, { id, name: "Stairs", a, b }] } };
}

export function updateObj(h: Home, coll: HomeCollection, id: string, patch: object): Home {
  const list = (h[coll] as { id: string }[]).map((o) => (o.id === id ? { ...o, ...patch } : o));
  return { ...h, [coll]: list } as Home;
}

export function deleteObj(h: Home, coll: HomeCollection, id: string): Home {
  const out = { ...h, [coll]: (h[coll] as { id: string }[]).filter((o) => o.id !== id) } as Home;
  if (coll === "walls") out.doors = out.doors.filter((d) => d.wall_id !== id);
  if (coll !== "floors") return out;
  const keep = (o: { floor_id: string }) => o.floor_id !== id;
  const walls = out.walls.filter(keep);
  const wallIds = new Set(walls.map((w) => w.id));
  return {
    ...out, walls,
    room_labels: out.room_labels.filter(keep), landmarks: out.landmarks.filter(keep), nodes: out.nodes.filter(keep),
    doors: out.doors.filter((d) => wallIds.has(d.wall_id)),
    stairs: out.stairs.filter((s) => keep(s.a) && keep(s.b)),
  };
}

/** Move one wall end; every wall end on the floor sitting at the same spot follows (keeps corners joined). */
export function moveWallEnd(h: Home, wallId: string, part: "a" | "b", p: Pt): Home {
  const w = h.walls.find((x) => x.id === wallId);
  if (!w) return h;
  const old = w[part];
  const at = (q: Pt) => dist(q, old) < 1e-3;
  return {
    ...h,
    walls: h.walls.map((x) => (x.floor_id !== w.floor_id ? x : { ...x, a: at(x.a) ? p : x.a, b: at(x.b) ? p : x.b })),
  };
}

export function moveTo(h: Home, coll: HomeCollection, id: string, part: "a" | "b" | undefined, p: Pt): Home {
  switch (coll) {
    case "landmarks":
    case "nodes":
      return updateObj(h, coll, id, { x: p[0], y: p[1] });
    case "room_labels":
      return updateObj(h, coll, id, { seed: p });
    case "stairs": {
      const s = h.stairs.find((x) => x.id === id);
      return s && part ? updateObj(h, "stairs", id, { [part]: { ...s[part], x: p[0], y: p[1] } }) : h;
    }
    case "walls":
      return part ? moveWallEnd(h, id, part, p) : h;
    default:
      return h;
  }
}

/** Two-point calibration: p1→p2 on the plan is really `realM` metres. Scales the underlay about p1. */
export function recalibrate(u: Underlay, p1: Pt, p2: Pt, realM: number): Underlay {
  const measured = dist(p1, p2);
  if (measured === 0 || realM <= 0) return u;
  const k = realM / measured;
  return {
    ...u,
    scale_m_per_px: u.scale_m_per_px * k,
    offset: [p1[0] - (p1[0] - u.offset[0]) * k, p1[1] - (p1[1] - u.offset[1]) * k],
  };
}
```

**Step 4: Run test, verify pass**
`cd box/web && pnpm vitest run src/pages/editor/ops.test.ts` → `7 passed`

**Step 5: Commit**
```bash
git add box/web/src/pages/editor/ops.ts box/web/src/pages/editor/ops.test.ts
git commit -m "feat: pure home edit operations" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 13: Editor store + Inspector panels

**Files:**
- Create: `box/web/src/pages/editor/store.ts`
- Create: `box/web/src/pages/editor/Inspector.tsx`
- Test: `box/web/src/pages/editor/store.test.ts`

**Step 1: Write failing test**
```ts
// box/web/src/pages/editor/store.test.ts
import { beforeEach, describe, expect, it } from "vitest";
import * as ops from "./ops";
import { useEditor } from "./store";

const dirty = () => useEditor.getState().hist.present !== useEditor.getState().saved;

describe("editor store", () => {
  beforeEach(() => {
    const saved = ops.addFloor(ops.emptyHome(), "Main").home;
    useEditor.getState().load(saved, saved, []);
  });

  it("commit marks dirty, undo back to saved is clean", () => {
    const s = useEditor.getState();
    s.commit(ops.addWall(s.hist.present, s.floorId, [0, 0], [1, 0]).home);
    expect(dirty()).toBe(true);
    useEditor.getState().undo();
    expect(dirty()).toBe(false);
  });

  it("markSaved stores the server home and rooms", () => {
    const s = useEditor.getState();
    s.commit(ops.addWall(s.hist.present, s.floorId, [0, 0], [1, 0]).home);
    const server = { ...useEditor.getState().hist.present, version: 7 };
    useEditor.getState().markSaved(server, [{ id: "r", floor_id: s.floorId, name: "R", polygon: [] }]);
    expect(useEditor.getState().hist.present.version).toBe(7);
    expect(useEditor.getState().rooms).toHaveLength(1);
    expect(dirty()).toBe(false);
  });

  it("changing tool or floor clears the selection", () => {
    useEditor.getState().select({ coll: "floors", id: "x" });
    useEditor.getState().setTool("wall");
    expect(useEditor.getState().selected).toBeNull();
  });
});
```

**Step 2: Run test, verify failure**
`cd box/web && pnpm vitest run src/pages/editor/store.test.ts`
Expected: FAIL with `Failed to resolve import "./store"`

**Step 3: Implement**
```ts
// box/web/src/pages/editor/store.ts
import { create } from "zustand";
import type { Home, HomeCollection, Room } from "../../lib/types";
import { initHistory, push, redo, undo, type History } from "./history";
import { emptyHome } from "./ops";

export type Tool = "select" | "wall" | "door" | "stairs" | "landmark" | "node" | "underlay" | "label";
export interface Sel { coll: HomeCollection; id: string }

interface EditorState {
  hist: History<Home>;
  saved: Home | null; // dirty = hist.present !== saved
  rooms: Room[];      // derived rooms from the last GET/PUT
  floorId: string;
  tool: Tool;
  selected: Sel | null;
  load(home: Home, saved: Home, rooms: Room[]): void;
  commit(next: Home, key?: string): void;
  undo(): void;
  redo(): void;
  markSaved(home: Home, rooms: Room[]): void;
  setFloor(id: string): void;
  setTool(tool: Tool): void;
  select(sel: Sel | null): void;
}

export const useEditor = create<EditorState>((set) => ({
  hist: initHistory(emptyHome()),
  saved: null,
  rooms: [],
  floorId: "",
  tool: "select",
  selected: null,
  load: (home, saved, rooms) =>
    set({
      hist: initHistory(home), saved, rooms, selected: null,
      floorId: [...home.floors].sort((a, b) => a.elevation_m - b.elevation_m)[0]?.id ?? "",
    }),
  commit: (next, key) => set((s) => ({ hist: push(s.hist, next, key ?? null) })),
  undo: () => set((s) => ({ hist: undo(s.hist), selected: null })),
  redo: () => set((s) => ({ hist: redo(s.hist), selected: null })),
  markSaved: (home, rooms) => set((s) => ({ hist: { ...s.hist, present: home, key: null }, saved: home, rooms })),
  setFloor: (floorId) => set({ floorId, selected: null }),
  setTool: (tool) => set({ tool, selected: null }),
  select: (selected) => set({ selected }),
}));
```
```tsx
// box/web/src/pages/editor/Inspector.tsx
// Right-hand inspector: selected object's fields, floor properties, and the underlay panel.
import { useState, type FormEvent } from "react";
import { dist } from "../../components/plan/geom";
import type { Door, Floor, Home, Landmark, LandmarkType, NodePlacement, Pt, RoomLabel, Stairs, Wall } from "../../lib/types";
import { apiUpload } from "../../lib/api";
import { formatLength, parseLength, type Units } from "../../lib/units";
import * as ops from "./ops";
import { useEditor, type Sel } from "./store";

type Commit = (h: Home, key?: string) => void;

function Text({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return <label>{label}<input value={value} onChange={(e) => onChange(e.target.value)} /></label>;
}

function Num({ label, value, step = 0.01, onChange }: { label: string; value: number; step?: number; onChange: (v: number) => void }) {
  return (
    <label>{label}
      <input type="number" step={step} value={value}
        onChange={(e) => { const v = parseFloat(e.target.value); if (!Number.isNaN(v)) onChange(v); }} />
    </label>
  );
}

const TITLES: Record<Sel["coll"], string> = {
  floors: "Floor", walls: "Wall", room_labels: "Room", doors: "Door", stairs: "Stairs", landmarks: "Landmark", nodes: "Node",
};

export function Inspector({ home, selected, units, commit, onDelete }:
  { home: Home; selected: Sel; units: Units; commit: Commit; onDelete: () => void }) {
  const { coll, id } = selected;
  const obj = (home[coll] as { id: string }[]).find((o) => o.id === id);
  if (!obj) return <p className="muted">Nothing selected</p>;
  const set = (field: string) => (value: unknown) =>
    commit(ops.updateObj(home, coll, id, { [field]: value }), `edit:${coll}:${id}:${field}`);
  const floorName = (fid: string) => home.floors.find((f) => f.id === fid)?.name ?? fid;

  let fields: JSX.Element | null = null;
  if (coll === "walls") {
    const w = obj as Wall;
    fields = <>
      <p>Length <strong>{formatLength(dist(w.a, w.b), units)}</strong></p>
      <Num label="Thickness (m)" value={w.thickness_m} onChange={set("thickness_m")} />
      {/* cut order #3: delete this checkbox to drop divider walls */}
      <label className="check"><input type="checkbox" checked={w.invisible}
        onChange={(e) => set("invisible")(e.target.checked)} />Divider (invisible)</label>
    </>;
  } else if (coll === "doors") {
    const d = obj as Door;
    fields = <>
      <Num label="Width (m)" value={d.width_m} onChange={set("width_m")} />
      <label>Position<input type="range" min={0} max={1} step={0.01} value={d.t}
        onChange={(e) => set("t")(parseFloat(e.target.value))} /></label>
    </>;
  } else if (coll === "landmarks") {
    const lm = obj as Landmark;
    fields = <>
      <Text label="Name" value={lm.name} onChange={set("name")} />
      <label>Type<select value={lm.type} onChange={(e) => set("type")(e.target.value as LandmarkType)}>
        {Object.entries(ops.LANDMARK_NAMES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
      </select></label>
      <Num label="Radius (m)" value={lm.radius_m} onChange={set("radius_m")} />
    </>;
  } else if (coll === "nodes") {
    const n = obj as NodePlacement;
    fields = <>
      <p>ESPresense id <code>{n.id}</code></p>
      <Text label="Name" value={n.name} onChange={set("name")} />
      <Num label="Height above floor (m)" value={n.z_m} onChange={set("z_m")} />
    </>;
  } else if (coll === "room_labels") {
    fields = <Text label="Name" value={(obj as RoomLabel).name} onChange={set("name")} />;
  } else if (coll === "stairs") {
    const s = obj as Stairs;
    fields = <>
      <Text label="Name" value={s.name} onChange={set("name")} />
      <p className="muted">{floorName(s.a.floor_id)} ↔ {floorName(s.b.floor_id)}</p>
    </>;
  }
  return (
    <div className="inspector-body">
      <h3>{TITLES[coll]}</h3>
      {fields}
      <button className="danger" onClick={onDelete}>Delete</button>
    </div>
  );
}

export function FloorForm({ home, floor, commit, onDelete }:
  { home: Home; floor: Floor; commit: Commit; onDelete: () => void }) {
  const set = (field: string) => (value: unknown) =>
    commit(ops.updateObj(home, "floors", floor.id, { [field]: value }), `edit:floors:${floor.id}:${field}`);
  return (
    <div className="inspector-body">
      <h3>Floor</h3>
      <Text label="Name" value={floor.name} onChange={set("name")} />
      <Num label="Elevation (m)" value={floor.elevation_m} step={0.1} onChange={set("elevation_m")} />
      {home.floors.length > 1 && <button className="danger" onClick={onDelete}>Delete floor</button>}
    </div>
  );
}

export function UnderlayPanel({ home, floor, units, commit, calib, setCalib }: {
  home: Home; floor: Floor; units: Units; commit: Commit; calib: Pt[] | null; setCalib: (c: Pt[] | null) => void;
}) {
  const [real, setReal] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const u = floor.underlay;
  const setU = (next: object | null, key?: string) =>
    commit(ops.updateObj(home, "floors", floor.id, { underlay: next === null ? null : { ...u, ...next } }), key);

  async function upload(file: File) {
    let image: string;
    try {
      ({ image } = await apiUpload<{ image: string }>("/api/home/underlay", file));
    } catch (e) {
      setErr(`Upload failed: ${e}`);
      return;
    }
    setErr(null);
    const latest = useEditor.getState().hist.present; // the user may have edited during the upload
    commit(ops.updateObj(latest, "floors", floor.id, {
      underlay: { image, scale_m_per_px: 0.02, offset: [0, 0], rotation_deg: 0, opacity: 0.4 },
    }));
  }

  function apply(e: FormEvent) {
    e.preventDefault();
    const m = parseLength(real, units);
    if (!m || !u || !calib || calib.length < 2) { setErr(`Enter a length like 12' 6" or 3.8 m`); return; }
    setU(ops.recalibrate(u, calib[0], calib[1], m));
    setCalib(null);
    setReal("");
    setErr(null);
  }

  return (
    <div className="inspector-body">
      <h3>Underlay</h3>
      <label>Floorplan image<input type="file" accept="image/png,image/jpeg,image/webp"
        onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} /></label>
      {u && <>
        <label>Opacity<input type="range" min={0.1} max={1} step={0.05} value={u.opacity}
          onChange={(e) => setU({ opacity: parseFloat(e.target.value) }, `underlay:${floor.id}:opacity`)} /></label>
        {/* cut order #1: delete this input to drop underlay rotation */}
        <Num label="Rotation (°)" value={u.rotation_deg} step={0.5}
          onChange={(v) => setU({ rotation_deg: v }, `underlay:${floor.id}:rotation`)} />
        {calib === null && <button onClick={() => setCalib([])}>Calibrate scale</button>}
        {calib !== null && calib.length < 2 && <p>Click point {calib.length + 1} of 2 on a known length</p>}
        {calib !== null && calib.length === 2 && (
          <form onSubmit={apply}>
            <Text label="Real distance" value={real} onChange={setReal} />
            <button type="submit">Apply</button>
          </form>
        )}
        <button className="danger" onClick={() => setU(null)}>Remove underlay</button>
      </>}
      {err && <p className="editor-error">{err}</p>}
    </div>
  );
}
```
`calib` and `setCalib` are owned by the Editor page, because clicks on the plan add the points (Task 15). ponytail: there's no offset nudge. The user uploads the underlay first and traces walls on top of it. Add offset inputs only if someone needs to align an underlay to walls that already exist.

**Step 4: Run test, verify pass**
`cd box/web && pnpm vitest run src/pages/editor/store.test.ts && pnpm exec tsc --noEmit` → `3 passed`, tsc clean

**Step 5: Commit**
```bash
git add box/web/src/pages/editor/store.ts box/web/src/pages/editor/store.test.ts box/web/src/pages/editor/Inspector.tsx
git commit -m "feat: editor store with undo and inspector panels" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 14: Playwright e2e (failing)

**Files:**
- Create: `box/web/playwright.config.ts` (if plan 01 already has one, add the `webServer` entries and `testMatch` below to it)
- Create: `box/web/e2e/editor.e2e.ts`
- Modify: `box/web/package.json` (script `"e2e": "playwright test"`)
- Modify: `box/.gitignore` (add `.e2e-data/`)

The file is named `*.e2e.ts`, not `*.spec.ts`, so that vitest's default glob doesn't pick it up.

**Step 1: Write failing test**
```ts
// box/web/playwright.config.ts
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "e2e",
  testMatch: "*.e2e.ts",
  use: { baseURL: "http://localhost:5173" },
  webServer: [
    {
      // fresh box with an empty home; MQTT is unreachable here, ingest just keeps retrying
      command: "rm -rf ../.e2e-data && cd .. && WA_DATA_DIR=.e2e-data WA_MQTT_HOST=127.0.0.1 WA_MQTT_PASS=e2e uv run wheres-allie serve",
      url: "http://localhost:8080/api/health",
      reuseExistingServer: false,
      timeout: 60_000,
    },
    { command: "pnpm dev --port 5173 --strictPort", url: "http://localhost:5173", reuseExistingServer: true },
  ],
});
```
```ts
// box/web/e2e/editor.e2e.ts
import { expect, test } from "@playwright/test";

test("draw 4 walls → room appears after save → name it", async ({ page }) => {
  await page.goto("/editor");
  const svg = page.locator("svg.plan-canvas");
  await expect(svg).toBeVisible();

  await page.getByRole("button", { name: "Wall" }).click();
  const box = (await svg.boundingBox())!;
  const cx = box.x + box.width / 2, cy = box.y + box.height / 2;
  const corners = [[cx - 150, cy - 100], [cx + 150, cy - 100], [cx + 150, cy + 100], [cx - 150, cy + 100], [cx - 150, cy - 100]];
  for (const [x, y] of corners) await page.mouse.click(x, y); // last click closes the chain
  await expect(page.locator('[data-coll="walls"]:not([data-part])')).toHaveCount(4);

  await page.getByRole("button", { name: /^Save/ }).click();
  await expect(page.locator("text.plan-room-name")).toHaveText("Unnamed room");

  await page.getByRole("button", { name: "Room label" }).click();
  await page.mouse.click(cx, cy);
  await page.getByLabel("Name").fill("Kitchen");
  await page.getByRole("button", { name: /^Save/ }).click();
  await expect(page.locator("text.plan-room-name")).toHaveText("Kitchen");

  await page.reload();
  await expect(page.locator("text.plan-room-name")).toHaveText("Kitchen");
});
```
Add `"e2e": "playwright test"` to `scripts` in `box/web/package.json`, and `.e2e-data/` to `box/.gitignore`.

**Step 2: Run test, verify failure**
`cd box/web && pnpm exec playwright install chromium && pnpm e2e`
Expected: FAIL with `locator.click: Timeout ... waiting for getByRole('button', { name: 'Wall' })` (the Editor page is still the plan-01 placeholder)

**Step 3: Implement**. Nothing here; Task 15 makes this test pass.

**Step 4: Run test, verify pass**. Deferred to Task 15, Step 4.

**Step 5: Commit**
```bash
git add box/web/playwright.config.ts box/web/e2e/editor.e2e.ts box/web/package.json box/.gitignore
git commit -m "test: e2e for drawing a room in the editor" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 15: Editor page (tools, save)

**Files:**
- Modify (replace placeholder): `box/web/src/pages/Editor.tsx`
- Create: `box/web/src/pages/editor/editor.css`
- Test: `box/web/e2e/editor.e2e.ts` (from Task 14)

**Step 1: Write failing test**. Already written: `box/web/e2e/editor.e2e.ts`.

**Step 2: Run test, verify failure**
`cd box/web && pnpm e2e`
Expected: FAIL with `Timeout ... getByRole('button', { name: 'Wall' })`

**Step 3: Implement**
```tsx
// box/web/src/pages/Editor.tsx
import { useEffect, useMemo, useState } from "react";
import { dist, nearestOnSegment } from "../components/plan/geom";
import { PlanCanvas, type Hit, type PlanPointer } from "../components/plan/PlanCanvas";
import { apiGet, apiPut } from "../lib/api";
import type { HomeCollection, HomeResponse, LandmarkType, Pt, StairsEnd } from "../lib/types";
import { formatLength, type Units } from "../lib/units";
import { FloorForm, Inspector, UnderlayPanel } from "./editor/Inspector";
import * as ops from "./editor/ops";
import { snapPoint } from "./editor/snap";
import { useEditor, type Tool } from "./editor/store";
import "./editor/editor.css";

const GRID_M = 0.05;
const SNAP_TOL_M = 0.25;
const ANGLE_STEP_DEG = 45; // cut order #2: set to 90 to drop 45° snapping

const TOOLS: { id: Tool; label: string; key: string; glyph: string }[] = [
  { id: "select", label: "Select", key: "v", glyph: "↖" },
  { id: "wall", label: "Wall", key: "w", glyph: "▭" },
  { id: "door", label: "Door", key: "d", glyph: "⌒" },
  { id: "stairs", label: "Stairs", key: "s", glyph: "≡" },
  { id: "landmark", label: "Landmark", key: "l", glyph: "◎" },
  { id: "node", label: "Node", key: "n", glyph: "◆" },
  { id: "underlay", label: "Underlay", key: "u", glyph: "▦" },
  { id: "label", label: "Room label", key: "r", glyph: "Aa" },
];
const HINTS: Record<Tool, string> = {
  select: "Click to select · drag to move · Delete removes · drag empty space to pan",
  wall: "Click or drag to draw · click the start to close · Esc ends · hold Alt to skip snapping",
  door: "Click a wall to add a door",
  stairs: "Click the bottom end, switch floor, click the top end",
  landmark: "Pick a type on the right, then click to place",
  node: "Pick an unplaced node on the right, then click to place",
  underlay: "Upload a floorplan image, then calibrate with two points",
  label: "Click inside a room to name it",
};
type NodeRow = { id: string; name: string | null };

export default function Editor() {
  const s = useEditor();
  const { hist, saved, rooms, floorId, tool, selected } = s;
  const home = hist.present;
  const dirty = home !== saved;
  const [units, setUnits] = useState<Units>("ft");
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [down, setDown] = useState<Pt | null>(null);          // wall tool: pointer-down point
  const [anchor, setAnchor] = useState<Pt | null>(null);      // wall tool: end of the chain so far
  const [chainStart, setChainStart] = useState<Pt | null>(null);
  const [cursor, setCursor] = useState<Pt | null>(null);
  const [drag, setDrag] = useState<{ hit: Hit; key: string } | null>(null);
  const [stairsStart, setStairsStart] = useState<StairsEnd | null>(null);
  const [lmType, setLmType] = useState<LandmarkType>("bed");
  const [nodes, setNodes] = useState<NodeRow[]>([]);
  const [nodePick, setNodePick] = useState<NodeRow | null>(null);
  const [calib, setCalib] = useState<Pt[] | null>(null);

  async function save() {
    const st = useEditor.getState();
    try {
      const r = await apiPut<HomeResponse>("/api/home", st.hist.present);
      useEditor.getState().markSaved(r.home, r.rooms);
      setError(null);
    } catch (e) {
      setError(`Save failed: ${e}`);
    }
  }

  useEffect(() => {
    apiGet<{ units: Units }>("/api/settings").then((st) => setUnits(st.units)).catch(() => {});
    apiGet<HomeResponse>("/api/home")
      .then((r) => {
        const start = r.home.floors.length ? r.home : ops.addFloor(r.home, "Main").home;
        useEditor.getState().load(start, r.home, r.rooms);
        setLoaded(true);
      })
      .catch((e) => setError(`Could not load the home: ${e}`));
  }, []);

  useEffect(() => {
    if (tool === "node") apiGet<NodeRow[]>("/api/nodes").then(setNodes).catch(() => setNodes([]));
  }, [tool]);
  useEffect(() => { setDown(null); setAnchor(null); setChainStart(null); setCursor(null); setCalib(null); }, [tool, floorId]);
  useEffect(() => setStairsStart(null), [tool]); // survives a floor switch on purpose

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).closest?.("input, textarea, select")) return;
      const st = useEditor.getState();
      const mod = e.ctrlKey || e.metaKey;
      const k = e.key.toLowerCase();
      if (mod && k === "z") { e.preventDefault(); if (e.shiftKey) st.redo(); else st.undo(); }
      else if (mod && k === "y") { e.preventDefault(); st.redo(); }
      else if (mod && k === "s") { e.preventDefault(); void save(); }
      else if ((e.key === "Delete" || e.key === "Backspace") && st.selected) {
        st.commit(ops.deleteObj(st.hist.present, st.selected.coll, st.selected.id));
        st.select(null);
      } else if (e.key === "Escape") {
        setDown(null); setAnchor(null); setChainStart(null); setStairsStart(null); setCalib(null); st.select(null);
      } else if (!mod) {
        const t = TOOLS.find((x) => x.key === k);
        if (t) st.setTool(t.id);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const floorWalls = useMemo(() => home.walls.filter((w) => w.floor_id === floorId), [home.walls, floorId]);
  const snap = (p: PlanPointer, from: Pt | null, ignore?: Pt): Pt => {
    if (p.event.altKey) return [p.x, p.y];
    const endpoints = floorWalls.flatMap((w) => [w.a, w.b]).filter((e) => !ignore || dist(e, ignore) > 1e-3);
    return snapPoint([p.x, p.y], { anchor: from, endpoints, grid: GRID_M, angleStepDeg: ANGLE_STEP_DEG, tol: SNAP_TOL_M }).p;
  };
  const place = (r: ops.Added, coll: HomeCollection) => {
    s.commit(r.home);
    s.select({ coll, id: r.id });
    return true;
  };

  const onDown = (p: PlanPointer): boolean => {
    const here: Pt = [p.x, p.y];
    switch (tool) {
      case "select":
        if (!p.hit || p.hit.coll === "rooms") { s.select(null); return false; }
        s.select({ coll: p.hit.coll, id: p.hit.id });
        setDrag({ hit: p.hit, key: `drag:${ops.newId()}` });
        return true;
      case "wall":
        setDown(snap(p, anchor));
        return true;
      case "door": {
        const w = p.hit?.coll === "walls" ? home.walls.find((x) => x.id === p.hit!.id) : undefined;
        return w ? place(ops.placeDoor(home, w.id, nearestOnSegment(here, w.a, w.b).t), "doors") : false;
      }
      case "landmark":
        return place(ops.addLandmark(home, floorId, snap(p, null), lmType), "landmarks");
      case "label":
        return place(ops.addLabel(home, floorId, here, "New room"), "room_labels");
      case "node":
        if (!nodePick) return false;
        setNodePick(null);
        return place(ops.addNode(home, nodePick, floorId, snap(p, null)), "nodes");
      case "stairs": {
        const [x, y] = snap(p, null);
        const end = { floor_id: floorId, x, y };
        if (!stairsStart || stairsStart.floor_id === floorId) { setStairsStart(end); return true; }
        setStairsStart(null);
        return place(ops.addStairs(home, stairsStart, end), "stairs");
      }
      case "underlay":
        if (!calib) return false;
        setCalib([...calib, here].slice(-2));
        return true;
    }
  };

  const onMove = (p: PlanPointer) => {
    if (tool === "wall") setCursor(snap(p, anchor ?? down));
    if (tool !== "select" || !drag) return;
    const { coll, id, part } = drag.hit;
    if (coll === "rooms") return;
    const old = coll === "walls" && part ? home.walls.find((w) => w.id === id)?.[part] : undefined;
    s.commit(ops.moveTo(home, coll, id, part, snap(p, null, old)), drag.key);
  };

  const onUp = (p: PlanPointer) => {
    setDrag(null);
    if (tool !== "wall" || !down) return;
    const start = anchor ?? down;
    const end = snap(p, start);
    setDown(null);
    if (dist(start, end) <= 0.05) {       // a click, not a drag: start a chain here
      if (!anchor) { setAnchor(end); setChainStart(end); }
      return;
    }
    s.commit(ops.addWall(home, floorId, start, end).home);
    const first = chainStart ?? start;
    if (dist(end, first) < 1e-6) { setAnchor(null); setChainStart(null); }  // closed the loop
    else { setAnchor(end); setChainStart(first); }
  };

  const floors = [...home.floors].sort((a, b) => a.elevation_m - b.elevation_m);
  const floor = home.floors.find((f) => f.id === floorId);
  const unplaced = nodes.filter((n) => !home.nodes.some((p) => p.id === n.id));
  const from = anchor ?? down;

  if (!loaded) return <div className="editor-loading">{error ?? "Loading…"}</div>;

  return (
    <div className="editor">
      <div className="editor-stage">
        <PlanCanvas home={home} rooms={rooms} floorId={floorId} selected={selected} editing
          fitKey={`${floorId}:${loaded}`} onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp}>
          {tool === "wall" && from && cursor && (
            <g className="editor-preview">
              <line x1={from[0]} y1={from[1]} x2={cursor[0]} y2={cursor[1]} />
              <text x={(from[0] + cursor[0]) / 2} y={(from[1] + cursor[1]) / 2 - 0.2} fontSize={0.3}>
                {formatLength(dist(from, cursor), units)}
              </text>
            </g>
          )}
          {tool === "wall" && cursor && <circle cx={cursor[0]} cy={cursor[1]} r={0.08} className="editor-cursor" />}
          {stairsStart?.floor_id === floorId && <circle cx={stairsStart.x} cy={stairsStart.y} r={0.3} className="editor-pending" />}
          {calib?.map((c, i) => <circle key={i} cx={c[0]} cy={c[1]} r={0.1} className="editor-pending" />)}
        </PlanCanvas>

        <div className="floor-tabs" role="tablist">
          {floors.map((f) => (
            <button key={f.id} role="tab" aria-selected={f.id === floorId} onClick={() => s.setFloor(f.id)}>{f.name}</button>
          ))}
          <button aria-label="Add floor" title="Add floor"
            onClick={() => { const r = ops.addFloor(home); s.commit(r.home); s.setFloor(r.id); }}>+</button>
        </div>

        <div className="editor-actions">
          {error && <span className="editor-error">{error}</span>}
          <button aria-label="Undo" title="Undo (Ctrl+Z)" onClick={s.undo} disabled={!hist.past.length}>↶</button>
          <button aria-label="Redo" title="Redo (Ctrl+Shift+Z)" onClick={s.redo} disabled={!hist.future.length}>↷</button>
          <button className="primary" onClick={save} disabled={!dirty} title="Save (Ctrl+S)">
            Save{dirty && <span className="dirty-dot" title="Unsaved changes" />}
          </button>
        </div>

        <div className="tool-palette" role="toolbar" aria-label="Tools">
          {TOOLS.map((t) => (
            <button key={t.id} aria-label={t.label} title={`${t.label} (${t.key.toUpperCase()})`}
              aria-pressed={tool === t.id} onClick={() => s.setTool(t.id)}>{t.glyph}</button>
          ))}
        </div>
        <div className="editor-hint">
          {stairsStart ? "Now switch to the other floor and click the top end of the stairs" : HINTS[tool]}
        </div>
      </div>

      <aside className="inspector">
        {selected ? (
          <Inspector home={home} selected={selected} units={units} commit={s.commit}
            onDelete={() => { s.commit(ops.deleteObj(home, selected.coll, selected.id)); s.select(null); }} />
        ) : (
          <>
            {tool === "landmark" && (
              <label>Landmark type
                <select value={lmType} onChange={(e) => setLmType(e.target.value as LandmarkType)}>
                  {Object.entries(ops.LANDMARK_NAMES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                </select>
              </label>
            )}
            {tool === "node" && (
              <div className="inspector-body">
                <h3>Unplaced nodes</h3>
                {unplaced.length === 0 && <p className="muted">No unplaced nodes. Add one on the Nodes page.</p>}
                {unplaced.map((n) => (
                  <button key={n.id} aria-pressed={nodePick?.id === n.id} onClick={() => setNodePick(n)}>{n.name ?? n.id}</button>
                ))}
              </div>
            )}
            {tool === "underlay" && floor && (
              <UnderlayPanel home={home} floor={floor} units={units} commit={s.commit} calib={calib} setCalib={setCalib} />
            )}
            {floor && (
              <FloorForm home={home} floor={floor} commit={s.commit} onDelete={() => {
                const rest = floors.find((f) => f.id !== floor.id);
                s.commit(ops.deleteObj(home, "floors", floor.id));
                if (rest) s.setFloor(rest.id);
              }} />
            )}
          </>
        )}
      </aside>
    </div>
  );
}
```
```css
/* box/web/src/pages/editor/editor.css */
.editor { display: grid; grid-template-columns: 1fr 320px; height: 100vh; min-height: 0; }
.editor-stage { position: relative; min-width: 0; min-height: 0; }
.editor-loading { padding: 24px; color: var(--muted); }
.floor-tabs, .editor-actions, .tool-palette {
  position: absolute; display: flex; gap: 2px; align-items: center; padding: 4px;
  background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.06);
}
.floor-tabs { top: 12px; left: 12px; }
.editor-actions { top: 12px; right: 12px; }
.tool-palette { bottom: 16px; left: 50%; transform: translateX(-50%); }
.floor-tabs button, .editor-actions button, .tool-palette button, .inspector button {
  border: 0; background: transparent; color: var(--text); font: inherit; padding: 6px 10px; border-radius: 6px; cursor: pointer;
}
.tool-palette button { width: 40px; height: 40px; font-size: 16px; }
.floor-tabs button[aria-selected="true"], .tool-palette button[aria-pressed="true"], .inspector button[aria-pressed="true"] {
  background: var(--accent); color: #fff;
}
button:disabled { opacity: 0.4; cursor: default; }
.editor-actions .primary { background: var(--accent); color: #fff; }
.dirty-dot { display: inline-block; width: 6px; height: 6px; margin-left: 6px; border-radius: 50%; background: var(--warn); vertical-align: middle; }
.editor-hint { position: absolute; bottom: 72px; left: 50%; transform: translateX(-50%); color: var(--muted); font-size: 12px; white-space: nowrap; pointer-events: none; }
.inspector { border-left: 1px solid var(--line); background: var(--panel); padding: 16px; overflow: auto; display: flex; flex-direction: column; gap: 16px; }
.inspector-body { display: flex; flex-direction: column; gap: 10px; }
.inspector h3 { margin: 0; font-size: 14px; }
.inspector label { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--muted); }
.inspector label.check { flex-direction: row; align-items: center; gap: 8px; }
.inspector input:not([type="checkbox"]):not([type="range"]), .inspector select {
  font: inherit; color: var(--text); background: var(--bg); border: 1px solid var(--line); border-radius: 6px; padding: 6px 8px;
}
.inspector .danger { color: var(--danger); align-self: flex-start; }
.editor-preview line { stroke: var(--accent); stroke-width: 0.06; stroke-dasharray: 0.2 0.1; }
.editor-preview text { fill: var(--accent); text-anchor: middle; font-family: var(--font); }
.editor-cursor { fill: var(--accent); pointer-events: none; }
.editor-pending { fill: var(--warn); pointer-events: none; }
.editor-error { color: var(--danger); font-size: 12px; }
.muted { color: var(--muted); }
```

**Step 4: Run test, verify pass**
`cd box/web && pnpm exec tsc --noEmit && pnpm test && pnpm e2e` → tsc clean, all vitest pass, `1 passed` (Playwright)
Then run the full backend suite: `cd box && uv run pytest -q`. Everything should pass.

**Step 5: Commit**
```bash
git add box/web/src/pages/Editor.tsx box/web/src/pages/editor/editor.css
git commit -m "feat: plan editor page with wall, door, stairs, landmark, node, underlay tools" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 16: Phase push

**Files:**
- Modify: `docs/plans/2026-09-28-wheres-allie-plan-02-home-editor.md` (status table: every row `done | yes | yes`)
- Modify: `docs/plans/2026-09-28-wheres-allie-design.md` (phase 2 row `done | yes | yes`)

**Step 1: Write failing test**. None; this task only verifies.

**Step 2: Run the full gate**
```bash
cd box && uv run ruff check . && uv run pytest -q
cd web && pnpm exec tsc --noEmit && pnpm test && pnpm build && pnpm e2e
```
Expected: all green. If anything fails, fix it in the task that owns the file before continuing.

**Step 3: Manual smoke** (`cd box && uv run wheres-allie serve` plus `cd box/web && pnpm dev`, then open `http://localhost:5173/editor`):
- Draw a 2-room floor, add a door on the shared wall, save. Both rooms fill and are labelled.
- Add a floor, place stairs (click on floor 1, switch tab, click on floor 2). Each floor shows `Stairs → <other floor>`.
- Place each landmark type, move one by dragging, then undo and redo. The whole drag undoes as one step.
- Node tool: with a node heard on MQTT, place it. It disappears from the unplaced list.
- Underlay: upload a PNG, calibrate on a known wall, adjust opacity. It persists after save and reload.
- Select a wall and toggle Divider. After saving, the room splits.

**Step 4: Update the status tables, then commit and push**
```bash
git add docs/plans/2026-09-28-wheres-allie-plan-02-home-editor.md docs/plans/2026-09-28-wheres-allie-design.md
git commit -m "docs: mark phase 2 (home editor) done" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push origin main
```

**Step 5: Confirm the push.** `git status` should show `Your branch is up to date with 'origin/main'`.

---

## Phase exit criteria
- [ ] `uv run pytest -q` passes, including `tests/home/*` (model, store, geometry ×9, graph ×4, fixture) and `tests/api/test_home_routes.py` and `test_underlay.py`.
- [ ] `GET /api/home` on the fixture returns 5 named rooms across 3 floors, and a graph in which every vertex is reachable from `room:office`.
- [ ] `PUT /api/home` publishes `home.saved` on the bus and returns 422 on dangling refs.
- [ ] `box/tests/fixtures/home_allie.json` is committed (plans 03–07 depend on it).
- [ ] `pnpm test` passes (units, geom, viewport, PlanCanvas, history, snap, ops, store). `pnpm exec tsc --noEmit` and `pnpm build` are clean.
- [ ] `pnpm e2e` passes: draw 4 walls → "Unnamed room" after save → labelled "Kitchen" → survives a reload.
- [ ] `PlanCanvas` matches the contract in Interface additions E, so plans 04 and 05 can import it unchanged.
- [ ] The manual smoke checklist (Task 16, Step 3) is done on Chrome.
- [ ] At most 5 working days used. Anything cut is listed in the friction log / PR notes in cut order (rotation → 45° → dividers).
- [ ] The phase is pushed to `origin/main`.
