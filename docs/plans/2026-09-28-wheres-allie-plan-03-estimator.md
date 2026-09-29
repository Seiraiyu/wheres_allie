# wheres_allie Estimator + Calibration Implementation Plan

**Goal:** Turn raw per-node RSSI readings into a stable, snapped position for each tagged pet every 2 s (walkable-graph vertex, or `away`). Write positions and visits (30 s minimum dwell, with transits kept separately). Prove on recorded data that the result beats the ESPresense nearest-node baseline. Then let the owner teach the model spots it gets wrong, such as under the master bed, through labels and fingerprints, and show the gain.

**Architecture:** An online HMM runs over the vertices of the walkable graph (plan 02) plus the extra `away` state. `window.py` buckets `readings` and `motion` rows into 2 s windows. `emission.py` scores each window against every state:
- `PhysicsEmission`: log-distance path loss plus 10 dB per floor crossed, a Gaussian with an outlier floor, and a per-node "was it heard" term.
- `BlendedEmission`: mixes in learned per-vertex fingerprints with weight `n/(n+20)`.

`hmm.py` runs a log-space forward filter. Its transitions come from shortest-path distances within `max_speed*dt`, the tag's motion state changes how likely the pet is to stay put, and a 30-window Viterbi pass produces the smoothed output. `visits.py` turns the smoothed stream into visits. `runner.py` is the asyncio task in the app lifespan: it writes `positions`/`visits` and publishes `position`/`visit` on the bus. `eval.py` plus `wheres-allie eval` score the HMM against the nearest-node baseline on a replay bundle. Phase 4 adds `calibration/labels.py` (labels, with their windows snapshotted so they survive retention), `calibration/fingerprints.py`, `/api/calibrate/*`, and the Calibrate GUI page.

**Tech Stack:** Python 3.12, numpy (no scipy), sqlite3, FastAPI, typer, pytest. React 18 + TypeScript, vitest.

**Depends on:** plan 01 (`db.connect/migrate`, `bus.Bus`, `api/app.py` `create_app(settings=None, conn=None, start_background=True)` + lifespan `tasks` list, `api/deps.py` `get_conn/get_bus`, `cli.py` typer `app` with `serve` only, `tools/import_raw_log.py`) and plan 02 (`home/model.py`, `home/store.py`, `home/geometry.py` `detect_rooms/room_at`, `home/graph.py` `Vertex/Graph/build_graph`, `tests/fixtures/home_allie.json`). All commands run from `box/` unless a step says otherwise.

| Task | Description | Status | Tested | Pushed |
|------|-------------|--------|--------|--------|
| 1 | `estimator/window.py`: 2 s windows from readings + motion | pending | no | no |
| 2 | Synthetic test homes + `PhysicsEmission` | pending | no | no |
| 3 | `HmmFilter`: transition matrix + forward filter | pending | no | no |
| 4 | `HmmFilter.smoothed()`: Viterbi over the last 30 windows | pending | no | no |
| 5 | `VisitTracker`: visits, transits, away | pending | no | no |
| 6 | `EstimatorRunner`: per-tag cursor, backfill catch-up → positions/visits/bus | pending | no | no |
| 7 | Start the estimator task in the app lifespan | pending | no | no |
| 8 | `eval.py`: scoring + nearest-node baseline | pending | no | no |
| 9 | `evaluate()` on a bundle + `wheres-allie eval` CLI | pending | no | no |
| 10 | Real-data ground truth + first eval run | pending | no | no |
| 11 | Phase 3 exit: full suite, push | pending | no | no |
| 12 | `calibration/labels.py`: labels + snapshotted samples | pending | no | no |
| 13 | `calibration/fingerprints.py` | pending | no | no |
| 14 | `BlendedEmission` + under-bed flip test | pending | no | no |
| 15 | Runner rebuilds emission when labels change | pending | no | no |
| 16 | Eval uses bundle labels, reports physics vs blended | pending | no | no |
| 17 | `/api/calibrate/label` + `/api/calibrate/stats` | pending | no | no |
| 18 | GUI: `calibrateSteps.ts` step logic + vitest | pending | no | no |
| 19 | GUI: `Calibrate.tsx` guided walk + "here now" | pending | no | no |
| 20 | Real-data calibration gain | pending | no | no |
| 21 | Phase 4 exit: full suite, push | pending | no | no |

## Interface additions

These add to conventions §7 and §10. None of them changes anything already defined there.

```python
# estimator/window.py
WINDOW_S = 2.0
def make_windows(tag_id: int, readings: list[tuple[float, str, float]],   # (ts, node_id, rssi) sorted
                 motion: list[tuple[float, bool]], online_nodes: set[str],
                 t_from: float, t_to: float, dt: float = 2.0) -> list[Window]  # t_end = t_from+dt, +2dt, ... <= t_to
def online_nodes(conn) -> set[str]                                   # nodes.online = 1
def load_windows(conn, tag_id, t_from, t_to, dt=2.0) -> list[Window]  # moving = latest motion edge before t_end
# estimator/emission.py
AWAY = "away"
PhysicsEmission(home, graph, tx_power_dbm=-59.0, path_loss_n=2.5, floor_db=10.0, sigma_db=6.0,
                threshold_dbm=-95.0, heard_max=0.6, heard_scale_db=3.0)
    .node_ll(w, node_id) -> np.ndarray      # one node's term for every vertex; .vertex_row: dict[vertex_id, row]
BlendedEmission(physics: PhysicsEmission, fingerprints: dict[str, Fingerprint]); .weight(vertex_id) -> float
# estimator/hmm.py
HmmFilter(graph, emission, max_speed_mps=3.0, dt=2.0, exit_vertices: set[str] | None = None, history=30)
    # exit_vertices = lm:<id> of landmarks with type "door" (see runner.exit_vertices(home))
    .states: list[str]   # graph vertex ids in dict order, then "away"
# estimator/visits.py
@dataclass class VisitEvent: op: Literal["open","close","transit"]; place_id: str
                             kind: Literal["room","landmark","transit","away"]; start: float; end: float | None
#   place_id: room vertex -> room_id; landmark -> its vertex id "lm:<id>"; door/stairs -> vertex id (always transit);
#   away -> "away". "open" is emitted when dwell reaches 30 s (visits row with end NULL), "close" sets end.
# estimator/runner.py
class EstimatorRunner(conn, dt=2.0): .use_model(home, graph); .cursor(tag_id) -> float | None
    .run_until(until_ts) -> tuple[list[(topic, data)], bool caught_up]   # sync; call via to_thread
#   per-tag cursor = end of last processed window, persisted in settings "estimator.last_ts.<tag_id>"
#   (no cursor -> starts at the tag's earliest reading, floored to 2 s). <= 1800 windows (1 h) per tag per call.
#   Every window -> a positions row; the bus gets only the newest position per tag per call, plus every visit event.
async def catch_up(conn, bus, until_ts, runner=None) -> EstimatorRunner   # loops run_until to until_ts, publishing
async def run_estimator(conn, bus, dt=2.0) -> None   # forever: catch_up(now - 1 s), sleep to the next 2 s boundary
def exit_vertices(home) -> set[str]
# estimator/eval.py
def evaluate(bundle_path, truth_csv=None, **physics_kw) -> dict
#   keys: room_acc, landmark_acc (None if no landmark truth), transit_false_visit_rate, windows,
#         baseline_room_acc, baseline_transit_false_visit_rate
#   + when the bundle has labels: physics_room_acc, physics_landmark_acc,
#         physics_transit_false_visit_rate, fingerprinted_vertices
#   truth_csv columns = bundle ground_truth.csv (ts_start,ts_end,ibeacon_id,place); blank ibeacon_id = any
# calibration/labels.py
def create_label(conn, tag_id, vertex_id, source, ts_start=None, ts_end=None) -> dict  # default: 30 s before now
def load_samples(conn) -> dict[str, list[Window]];  def labels_version(conn) -> tuple
#   samples snapshot: settings key "calib:label:<label id>" = JSON [[{node: [rssi...]}, [online nodes]], ...]
# calibration/fingerprints.py
MIN_SAMPLES = 20 (readings); BLEND_K = 20; def blend_weight(n) -> float
@dataclass NodeStat(mean, std, heard_rate, heard); @dataclass Fingerprint(vertex_id, n, nodes); .node_ll(w, node) -> float | None
def build_fingerprints(samples: dict[str, list[Window]]) -> dict[str, Fingerprint]
```
- Bus payloads. `position`: `{ts, tag_id, pet, vertex_id, room_id, floor_id, confidence, moving, x, y}`. `visit`: `{id, op, tag_id, pet, place_id, kind, start, end}`. `label`: the label dict plus `pet`.
- `app.state.estimator_task` is the `asyncio.Task` that runs `run_estimator`.
- `positions.vertex_id = "away"` with `room_id`/`floor_id` NULL while the pet is away.
- `POST /api/calibrate/label` (conventions §10) → `{id, tag_id, pet, vertex_id, ts_start, ts_end, source, samples}`. 404 means an unknown pet. 422 means an unknown vertex or a bad time span. `source` defaults to `"tap"`.
- `GET /api/calibrate/stats?pet=` → `{pet, vertices: [{vertex_id, labels, samples, weight}], eval: null}`.
- CLI: `wheres-allie eval --bundle X [--truth Y] [--tx-power DBM] [--floor-db DB] [--check]` prints JSON. `--check` exits 1 unless `room_acc > baseline_room_acc`.
- From plan 02: `NodePlacement.z_m` is the height above the node's own floor, so its absolute height is `floor.elevation_m + z_m`. Stairs and landmark vertices carry the `room_id` of the room they sit in, and door vertices have `room_id=None`.

---

# Phase 3: Estimator

### Task 1: `estimator/window.py`

**Files:**
- Create: `box/src/wheres_allie/estimator/__init__.py` (empty)
- Create: `box/src/wheres_allie/estimator/window.py`
- Test: `box/tests/estimator/test_window.py`

**Step 1: Write failing test**
```python
from wheres_allie.estimator.window import make_windows


def test_make_windows_buckets_readings_and_motion():
    readings = [(0.5, "a", -70.0), (1.9, "a", -72.0), (1.95, "b", -80.0), (2.0, "a", -60.0)]
    motion = [(1.0, True), (3.5, False)]
    ws = make_windows(7, readings, motion, {"a", "b"}, t_from=0.0, t_to=6.0)
    assert [w.t_end for w in ws] == [2.0, 4.0, 6.0]
    assert ws[0].rssi == {"a": [-70.0, -72.0], "b": [-80.0]}
    assert ws[1].rssi == {"a": [-60.0]}  # ts 2.0 belongs to [2, 4)
    assert ws[2].rssi == {}
    assert [w.moving for w in ws] == [True, False, False]
    assert ws[0].online_nodes == {"a", "b"} and ws[0].tag_id == 7


def test_moving_unknown_without_motion_rows():
    assert make_windows(1, [], [], set(), 0.0, 2.0)[0].moving is None
```

**Step 2: Run test, verify failure**
Run: `uv run pytest tests/estimator/test_window.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'wheres_allie.estimator'`

**Step 3: Implement**
`box/src/wheres_allie/estimator/__init__.py`: an empty file.

`box/src/wheres_allie/estimator/window.py`:
```python
"""2 s evidence windows for the HMM (conventions §7)."""

import bisect
import sqlite3
from dataclasses import dataclass

WINDOW_S = 2.0


@dataclass
class Window:
    tag_id: int
    t_end: float  # window covers [t_end - 2, t_end)
    rssi: dict[str, list[float]]  # node_id -> readings in window
    online_nodes: set[str]
    moving: bool | None  # None = unknown


def make_windows(
    tag_id: int,
    readings: list[tuple[float, str, float]],  # (ts, node_id, rssi), sorted by ts
    motion: list[tuple[float, bool]],  # (ts, moving) edges, sorted by ts
    online_nodes: set[str],
    t_from: float,
    t_to: float,
    dt: float = WINDOW_S,
) -> list[Window]:
    """Consecutive windows ending at t_from+dt, t_from+2dt, ... <= t_to."""
    rts = [r[0] for r in readings]
    mts = [m[0] for m in motion]
    out = []
    t_end = t_from + dt
    while t_end <= t_to + 1e-9:
        rssi: dict[str, list[float]] = {}
        lo, hi = bisect.bisect_left(rts, t_end - dt), bisect.bisect_left(rts, t_end)
        for _, node, v in readings[lo:hi]:
            rssi.setdefault(node, []).append(v)
        i = bisect.bisect_left(mts, t_end) - 1  # latest motion edge before t_end
        moving = motion[i][1] if i >= 0 else None
        out.append(Window(tag_id, t_end, rssi, set(online_nodes), moving))
        t_end += dt
    return out


def online_nodes(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT id FROM nodes WHERE online = 1")}


def load_windows(
    conn: sqlite3.Connection, tag_id: int, t_from: float, t_to: float, dt: float = WINDOW_S
) -> list[Window]:
    readings = [
        (r[0], r[1], r[2])
        for r in conn.execute(
            "SELECT ts, node_id, rssi FROM readings WHERE tag_id = ? AND ts >= ? AND ts < ?"
            " ORDER BY ts",
            (tag_id, t_from, t_to),
        )
    ]
    last = conn.execute(
        "SELECT ts, moving FROM motion WHERE tag_id = ? AND ts < ? ORDER BY ts DESC LIMIT 1",
        (tag_id, t_from),
    ).fetchall()
    motion = [(r[0], bool(r[1])) for r in last] + [
        (r[0], bool(r[1]))
        for r in conn.execute(
            "SELECT ts, moving FROM motion WHERE tag_id = ? AND ts >= ? AND ts < ? ORDER BY ts",
            (tag_id, t_from, t_to),
        )
    ]
    return make_windows(tag_id, readings, motion, online_nodes(conn), t_from, t_to, dt)
```

**Step 4: Run test, verify pass**
Run: `uv run pytest tests/estimator/test_window.py -q`
Expected: `2 passed`

**Step 5: Commit**
```bash
git add src/wheres_allie/estimator/__init__.py src/wheres_allie/estimator/window.py tests/estimator/test_window.py
git commit -m "feat: estimator 2 s evidence windows

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 2: Synthetic test homes + `PhysicsEmission`

The fixtures build `Graph` objects by hand, so the math is tested without depending on plan 02's `build_graph`. `simulate` draws readings from the physics model itself: each node reports with probability `p_heard`, with RSSI drawn from N(mu, 4 dB).

**Files:**
- Create: `box/tests/estimator/conftest.py`
- Create: `box/src/wheres_allie/estimator/emission.py`
- Test: `box/tests/estimator/test_emission.py`

**Step 1: Write failing test**
`box/tests/estimator/conftest.py`:
```python
"""Synthetic homes + a physics-model reading simulator for estimator tests."""

import itertools
import math

import numpy as np
import pytest

from wheres_allie.estimator.emission import PhysicsEmission
from wheres_allie.estimator.window import Window
from wheres_allie.home.graph import Graph, Vertex
from wheres_allie.home.model import Floor, Home, Landmark, NodePlacement


def _graph(vertices: list[Vertex], links: list[tuple[str, str, float | None]]) -> Graph:
    """Connect every pair of vertices sharing a room_id, plus the explicit links."""
    vs = {v.id: v for v in vertices}
    edges = [
        (a.id, b.id, math.dist((a.x, a.y), (b.x, b.y)))
        for a, b in itertools.combinations(vertices, 2)
        if a.room_id and a.room_id == b.room_id
    ]
    for a, b, length in links:
        edges.append(
            (
                a,
                b,
                length if length is not None else math.dist((vs[a].x, vs[a].y), (vs[b].x, vs[b].y)),
            )
        )
    return Graph(vertices=vs, edges=edges)


@pytest.fixture
def two_rooms() -> tuple[Home, Graph]:
    """Floor f0: room A (x 0-5) | door at x=5 | room B (x 5-10). Bed in A, front door in B."""
    home = Home(
        floors=[Floor(id="f0", name="Main", elevation_m=0.0)],
        landmarks=[
            Landmark(id="bed", floor_id="f0", x=1.0, y=1.0, type="bed", name="Bed"),
            Landmark(id="front", floor_id="f0", x=9.5, y=3.5, type="door", name="Front door"),
        ],
        nodes=[
            NodePlacement(id="nA", floor_id="f0", x=0.5, y=0.5, z_m=1.0, name="A"),
            NodePlacement(id="nB", floor_id="f0", x=9.5, y=0.5, z_m=1.0, name="B"),
        ],
    )
    vs = [
        Vertex("room:A", "room", "f0", 2.5, 2.0, "A", "Room A"),
        Vertex("lm:bed", "landmark", "f0", 1.0, 1.0, "A", "Bed"),
        Vertex("room:B", "room", "f0", 7.5, 2.0, "B", "Room B"),
        Vertex("lm:front", "landmark", "f0", 9.5, 3.5, "B", "Front door"),
        Vertex("door:d", "door", "f0", 5.0, 2.0, None, "Door"),
    ]
    return home, _graph(
        vs,
        [
            ("door:d", "room:A", None),
            ("door:d", "lm:bed", None),
            ("door:d", "room:B", None),
            ("door:d", "lm:front", None),
        ],
    )


@pytest.fixture
def two_floors() -> tuple[Home, Graph]:
    """Basement office (node under the kitchen's west end) + main kitchen (node at the east end),
    joined by stairs. Standing at room:kitchen, the basement node is closer than the kitchen one."""
    home = Home(
        floors=[
            Floor(id="b", name="Basement", elevation_m=0.0),
            Floor(id="m", name="Main", elevation_m=2.7),
        ],
        nodes=[
            NodePlacement(id="office", floor_id="b", x=2.0, y=3.0, z_m=1.0, name="Office"),
            NodePlacement(id="kitchen", floor_id="m", x=8.0, y=3.0, z_m=1.0, name="Kitchen"),
        ],
    )
    vs = [
        Vertex("room:office", "room", "b", 2.0, 3.0, "office", "Office"),
        Vertex("stairs:s:a", "stairs", "b", 6.0, 1.0, "office", "Stairs"),
        Vertex("room:kitchen", "room", "m", 2.0, 3.0, "kitchen", "Kitchen"),
        Vertex("stairs:s:b", "stairs", "m", 6.0, 1.0, "kitchen", "Stairs"),
    ]
    return home, _graph(vs, [("stairs:s:a", "stairs:s:b", 3.0)])


@pytest.fixture
def simulate():
    """simulate(home, graph, vertex_id, n, t0=0, moving=None, seed=0) -> list[Window] drawn
    from the physics model itself (report prob per window + N(mu, 4 dB))."""

    def _sim(home, graph, vertex_id, n, t0=0.0, moving=None, seed=0):
        em = PhysicsEmission(home, graph)
        rng = np.random.default_rng(seed)
        r = em.vertex_row[vertex_id]
        out = []
        for k in range(n):
            rssi = {}
            for node, c in em.node_col.items():
                if rng.random() < np.exp(em.log_heard[r, c]):
                    rssi[node] = [float(em.mu[r, c] + rng.normal(0, 4.0))]
            out.append(Window(1, t0 + 2.0 * (k + 1), rssi, set(em.node_ids), moving))
        return out

    return _sim
```
`box/tests/estimator/test_emission.py`:
```python
import numpy as np

from wheres_allie.estimator.emission import PhysicsEmission
from wheres_allie.estimator.window import Window

STATES = ["room:A", "lm:bed", "room:B", "lm:front", "door:d", "away"]


def test_strong_reading_favours_nearby_vertex(two_rooms):
    em = PhysicsEmission(*two_rooms)
    ll = em.log_likelihood(Window(1, 2.0, {"nA": [-60.0]}, {"nA", "nB"}, None), STATES)
    assert STATES[int(np.argmax(ll))] == "lm:bed"
    assert ll[STATES.index("away")] < ll[STATES.index("lm:bed")]


def test_silence_favours_away(two_rooms):
    em = PhysicsEmission(*two_rooms)
    ll = em.log_likelihood(Window(1, 2.0, {}, {"nA", "nB"}, None), STATES)
    assert STATES[int(np.argmax(ll))] == "away"


def test_offline_node_contributes_nothing(two_rooms):
    em = PhysicsEmission(*two_rooms)
    only_a = em.log_likelihood(Window(1, 2.0, {"nA": [-70.0]}, {"nA"}, None), STATES)
    b_ignored = em.log_likelihood(
        Window(1, 2.0, {"nA": [-70.0], "nB": [-50.0]}, {"nA"}, None), STATES
    )
    np.testing.assert_allclose(only_a, b_ignored)


def test_floor_crossing_costs_10_db(two_floors):
    home, graph = two_floors
    em = PhysicsEmission(home, graph)
    same = PhysicsEmission(
        home.model_copy(
            update={"floors": [f.model_copy(update={"id": f.id}) for f in home.floors]}
        ),
        graph,
        floor_db=0.0,
    )
    r, c = em.vertex_row["room:kitchen"], em.node_col["office"]
    assert same.mu[r, c] - em.mu[r, c] == 10.0
```

**Step 2: Run test, verify failure**
Run: `uv run pytest tests/estimator/test_emission.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'wheres_allie.estimator.emission'`

**Step 3: Implement**
The model, per (vertex, node):
- `mu = tx - 10·n·log10(max(d, 0.5)) - floor_db·|level(vertex) - level(node)|`. Here `d` is the 3D distance, the vertex z is `floor elevation + 0.3 m` (pet height), and the node z is `floor elevation + z_m`.
- `p_heard = 0.6·sigmoid((mu + 95)/3)`, clipped to [0.001, 0.999]. The 0.6 cap exists because a node reports only every 2–5 s, so a silent 2 s window is weak evidence.
- Heard: `log p_heard + log((1-0.1)·N(mean; mu, 6) + 0.1/60)`. The outlier floor caps what one multipath reading can cost.
- Unheard: `log(1-p_heard)`.
- Offline nodes, and online nodes that aren't placed on the plan, add 0.
- `away`: each heard node costs `log(0.001)`, and silence costs nothing.

`box/src/wheres_allie/estimator/emission.py`:
```python
"""Emission models P(window | state) for the HMM (design §4.3)."""

import math
from typing import Protocol

import numpy as np

from wheres_allie.estimator.window import Window
from wheres_allie.home.graph import Graph
from wheres_allie.home.model import Home

AWAY = "away"
PET_HEIGHT_M = 0.3
AWAY_HEARD_P = 1e-3  # chance a node reports the tag while the pet is out of the house
_LOG_SQRT_2PI = 0.5 * math.log(2 * math.pi)


class EmissionModel(Protocol):
    def log_likelihood(self, w: Window, states: list[str]) -> np.ndarray: ...


OUTLIER_P = 0.1  # share of readings that are multipath junk, uniform over a 60 dB span
_LOG_OUTLIER = math.log(OUTLIER_P / 60.0)


def rssi_logpdf(x: float, mu, sd):
    """Gaussian around the expected RSSI mixed with a uniform outlier floor, so one bad reading
    costs at most ~4 nats instead of arbitrarily much."""
    g = np.log1p(-OUTLIER_P) - 0.5 * ((x - mu) / sd) ** 2 - np.log(sd) - _LOG_SQRT_2PI
    return np.logaddexp(g, _LOG_OUTLIER)


class PhysicsEmission:
    """Log-distance path loss from each placed node to each vertex, plus floor attenuation.

    Per online node: heard -> log p_heard + rssi_logpdf(mean rssi; mu, sigma);
    unheard -> log(1 - p_heard),
    where p_heard = heard_max * sigmoid((mu - threshold) / heard_scale). Offline nodes add 0.
    heard_max < 1 because a node reports only every 2-5 s, so a silent 2 s window is weak evidence.
    """

    def __init__(
        self,
        home: Home,
        graph: Graph,
        tx_power_dbm: float = -59.0,  # rssi@1m, as the BC021 advertises
        path_loss_n: float = 2.5,
        floor_db: float = 10.0,
        sigma_db: float = 6.0,
        threshold_dbm: float = -95.0,
        heard_max: float = 0.6,
        heard_scale_db: float = 3.0,
    ):
        self.sigma = sigma_db
        floors = sorted(home.floors, key=lambda f: f.elevation_m)
        level = {f.id: i for i, f in enumerate(floors)}
        elev = {f.id: f.elevation_m for f in floors}
        self.node_ids = [n.id for n in home.nodes]
        self.node_col = {nid: i for i, nid in enumerate(self.node_ids)}
        self.vertex_row = {vid: i for i, vid in enumerate(graph.vertices)}
        mu = np.zeros((len(graph.vertices), len(home.nodes)))
        for vid, r in self.vertex_row.items():
            v = graph.vertices[vid]
            vz = elev[v.floor_id] + PET_HEIGHT_M
            for c, n in enumerate(home.nodes):
                d = math.dist((v.x, v.y, vz), (n.x, n.y, elev[n.floor_id] + n.z_m))
                crossings = abs(level[v.floor_id] - level[n.floor_id])
                mu[r, c] = (
                    tx_power_dbm - 10 * path_loss_n * math.log10(max(d, 0.5)) - floor_db * crossings
                )
        self.mu = mu
        p = heard_max / (1 + np.exp(-(mu - threshold_dbm) / heard_scale_db))
        p = np.clip(p, 1e-3, 1 - 1e-3)
        self.log_heard, self.log_unheard = np.log(p), np.log1p(-p)

    def node_ll(self, w: Window, node: str) -> np.ndarray:
        """One online node's log-likelihood term for every vertex (self.vertex_row order)."""
        c = self.node_col.get(node)
        if c is None:  # online but not placed on the plan: no geometry, no evidence
            return np.zeros(len(self.vertex_row))
        vals = w.rssi.get(node)
        if not vals:
            return self.log_unheard[:, c]
        return self.log_heard[:, c] + rssi_logpdf(float(np.mean(vals)), self.mu[:, c], self.sigma)

    def vertex_ll(self, w: Window) -> np.ndarray:
        ll = np.zeros(len(self.vertex_row))
        for node in w.online_nodes:
            ll += self.node_ll(w, node)
        return ll

    def log_likelihood(self, w: Window, states: list[str]) -> np.ndarray:
        return assemble(self.vertex_ll(w), self.vertex_row, away_ll(w), states)


def away_ll(w: Window) -> float:
    heard = sum(1 for n in w.online_nodes if w.rssi.get(n))
    return heard * math.log(AWAY_HEARD_P)


def assemble(
    vll: np.ndarray, vertex_row: dict[str, int], a: float, states: list[str]
) -> np.ndarray:
    return np.array([a if s == AWAY else vll[vertex_row[s]] for s in states])
```

**Step 4: Run test, verify pass**
Run: `uv run pytest tests/estimator/test_emission.py -q`
Expected: `4 passed`

**Step 5: Commit**
```bash
git add tests/estimator/conftest.py tests/estimator/test_emission.py src/wheres_allie/estimator/emission.py
git commit -m "feat: physics emission model (path loss, floor attenuation, heard-rate)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 3: `HmmFilter`: transition matrix + forward filter

The transition model:
- `reach = max_speed·dt`, which is 6 m by default.
- For i ≠ j, a move is allowed if j is a graph neighbour of i, or if the shortest-path distance `D[i,j] ≤ reach` (Floyd–Warshall).
- Move weights are `exp(-D/reach)`, row-normalised.
- `P(stay)` is 0.999 when the tag is still (`moving=False`), 0.9 when unknown, and 0.6 when moving. The remaining `leave` mass is split as follows: `leave·0.2` goes to `away` from exit landmarks (landmarks of type `door`), `leave·0.002` goes to `away` from any other vertex, and the rest goes to moves.
- `away` stays with probability 0.95. It returns with 0.05: 80% of that goes to exit vertices (when there are any) and the rest spreads uniformly over all vertices.
- A vertex with no moves keeps all of its non-away mass.

**Files:**
- Create: `box/src/wheres_allie/estimator/hmm.py`
- Test: `box/tests/estimator/test_hmm.py`

**Step 1: Write failing test**
```python
import numpy as np

from wheres_allie.estimator.emission import PhysicsEmission
from wheres_allie.estimator.hmm import HmmFilter
from wheres_allie.estimator.window import Window


def _filter(home, graph, **kw):
    return HmmFilter(graph, PhysicsEmission(home, graph), exit_vertices={"lm:front"}, **kw)


def test_transition_rows_are_stochastic_and_respect_reach(two_rooms):
    f = _filter(*two_rooms)
    for moving in (True, False, None):
        t = np.exp(f.log_transition(moving))
        np.testing.assert_allclose(t.sum(axis=1), 1.0)
    t = np.exp(f.log_transition(False))
    i = f.states.index
    assert t[i("lm:bed"), i("lm:bed")] == 0.999
    # bed -> front door is 4.1 + 4.5 m of path > 6 m reach and not adjacent: impossible in one step
    assert t[i("lm:bed"), i("lm:front")] == 0.0
    # exit landmark leaks to away far more than an interior vertex
    assert t[i("lm:front"), i("away")] > 50 * t[i("room:A"), i("away")]


def test_converges_to_true_vertex(two_rooms, simulate):
    home, graph = two_rooms
    for truth in ("lm:bed", "room:B"):
        f = _filter(home, graph)
        for w in simulate(home, graph, truth, 10):
            e = f.step(w)
        # room:B and the front door are 2 dB apart for 2 nodes: the room is what must be right
        assert graph.vertices[e.vertex_id].room_id == graph.vertices[truth].room_id
    assert e.confidence > 0.3


def test_floor_bleed_beats_nearest_node(two_floors, simulate):
    home, graph = two_floors
    ws = simulate(home, graph, "room:kitchen", 15, seed=1)
    nearest = max(
        ("office", "kitchen"),
        key=lambda n: np.mean([np.mean(w.rssi[n]) for w in ws if n in w.rssi]),
    )
    assert nearest == "office"  # the node one floor down is louder
    f = HmmFilter(graph, PhysicsEmission(home, graph))
    for w in ws:
        e = f.step(w)
    assert e.vertex_id == "room:kitchen"


def test_still_tag_holds_state_through_outliers(two_rooms):
    home, graph = two_rooms
    at_bed = {"nA": [-59.0], "nB": [-82.0]}  # what the physics model expects at lm:bed
    settle = [Window(1, 2.0 * (k + 1), at_bed, {"nA", "nB"}, None) for k in range(10)]
    # one window that looks like the doorway (both nodes mid-range)
    blip = {"nA": [-74.0], "nB": [-72.0]}
    for moving, expect_bed in ((False, True), (True, False)):
        f = _filter(home, graph)
        for w in settle + [Window(1, 22.0, blip, {"nA", "nB"}, moving)]:
            e = f.step(w)
        assert (e.vertex_id == "lm:bed") is expect_bed


def test_silence_becomes_away(two_rooms, simulate):
    home, graph = two_rooms
    f = _filter(home, graph)
    for w in simulate(home, graph, "lm:front", 5):
        f.step(w)
    for k in range(30):
        e = f.step(Window(1, 100.0 + 2 * k, {}, {"nA", "nB"}, None))
    assert e.vertex_id == "away"
```

**Step 2: Run test, verify failure**
Run: `uv run pytest tests/estimator/test_hmm.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'wheres_allie.estimator.hmm'`

**Step 3: Implement**
```python
"""Online HMM over walkable-graph vertices + `away` (design §4.3)."""

from collections import deque
from dataclasses import dataclass

import numpy as np

from wheres_allie.estimator.emission import AWAY, EmissionModel
from wheres_allie.estimator.window import Window
from wheres_allie.home.graph import Graph

STAY = {False: 0.999, None: 0.9, True: 0.6}  # P(stay) by tag motion state
EXIT_SHARE = 0.2  # share of "leave" mass that goes to `away` from an exit vertex
OTHER_EXIT_SHARE = 0.002  # ... from any other vertex (tag dropped, dead zone)
AWAY_STAY = 0.95
AWAY_TO_EXIT = 0.8  # share of "return" mass that lands on exit vertices (if any)


@dataclass
class Estimate:
    ts: float
    vertex_id: str
    confidence: float
    moving: bool | None


def logsumexp(a: np.ndarray, axis=None) -> np.ndarray:
    m = np.max(a, axis=axis, keepdims=True)
    m = np.where(np.isfinite(m), m, 0.0)
    out = np.log(np.sum(np.exp(a - m), axis=axis, keepdims=True)) + m
    return out.squeeze(axis) if axis is not None else out.item()


def shortest_paths(graph: Graph, ids: list[str]) -> np.ndarray:
    """All-pairs shortest path lengths (Floyd-Warshall; homes have < 200 vertices)."""
    idx = {v: i for i, v in enumerate(ids)}
    d = np.full((len(ids), len(ids)), np.inf)
    np.fill_diagonal(d, 0.0)
    for a, b, length in graph.edges:
        i, j = idx[a], idx[b]
        d[i, j] = d[j, i] = min(d[i, j], length)
    for k in range(len(ids)):
        d = np.minimum(d, d[:, k : k + 1] + d[k : k + 1, :])
    return d


def move_weights(graph: Graph, ids: list[str], reach_m: float) -> np.ndarray:
    """Row-normalised P(j | i leaves). j is allowed if it is a graph neighbour of i or its
    shortest-path distance is <= reach_m (= max_speed * dt); weight exp(-dist / reach_m)."""
    d = shortest_paths(graph, ids)
    idx = {v: i for i, v in enumerate(ids)}
    allowed = d <= reach_m
    for a, b, _ in graph.edges:
        allowed[idx[a], idx[b]] = allowed[idx[b], idx[a]] = True
    np.fill_diagonal(allowed, False)
    w = np.where(allowed, np.exp(-np.where(np.isfinite(d), d, 0.0) / reach_m), 0.0)
    rows = w.sum(axis=1, keepdims=True)
    return np.divide(w, rows, out=np.zeros_like(w), where=rows > 0)


class HmmFilter:
    def __init__(
        self,
        graph: Graph,
        emission: EmissionModel,
        max_speed_mps: float = 3.0,
        dt: float = 2.0,
        exit_vertices: set[str] | None = None,
        history: int = 30,
    ):
        self.graph, self.emission = graph, emission
        ids = list(graph.vertices)
        self.states = ids + [AWAY]
        n = len(ids)
        self._moves = move_weights(graph, ids, max_speed_mps * dt)
        exits = np.array([v in (exit_vertices or set()) for v in ids])
        self._exit_share = np.where(exits, EXIT_SHARE, OTHER_EXIT_SHARE)
        back = np.full(n, 1.0 / n) if n else np.zeros(0)
        if exits.any():
            back = (1 - AWAY_TO_EXIT) * back + AWAY_TO_EXIT * exits / exits.sum()
        self._away_row = np.append((1 - AWAY_STAY) * back, AWAY_STAY)
        self._log_t: dict[bool | None, np.ndarray] = {}
        self.log_alpha = np.full(n + 1, -np.log(n + 1))
        self._hist: deque = deque(maxlen=history)  # (ts, moving, log_prev, ll, log_post)

    def log_transition(self, moving: bool | None) -> np.ndarray:
        if moving not in self._log_t:
            n = len(self.states) - 1
            stay = STAY[moving]
            leave = 1 - stay
            t = np.zeros((n + 1, n + 1))
            has_moves = self._moves.sum(axis=1) > 0
            t[:n, :n] = (leave * (1 - self._exit_share))[:, None] * self._moves
            t[:n, n] = leave * self._exit_share
            t[np.arange(n), np.arange(n)] = np.where(has_moves, stay, 1 - leave * self._exit_share)
            t[n] = self._away_row
            with np.errstate(divide="ignore"):
                self._log_t[moving] = np.log(t)
        return self._log_t[moving]

    def step(self, w: Window) -> Estimate:
        log_t = self.log_transition(w.moving)
        ll = self.emission.log_likelihood(w, self.states)
        post = logsumexp(self.log_alpha[:, None] + log_t, axis=0) + ll
        post -= logsumexp(post)
        self._hist.append((w.t_end, w.moving, self.log_alpha, ll, post))
        self.log_alpha = post
        i = int(np.argmax(post))
        return Estimate(w.t_end, self.states[i], float(np.exp(post[i])), w.moving)
```

**Step 4: Run test, verify pass**
Run: `uv run pytest tests/estimator/test_hmm.py -q`
Expected: `5 passed`

**Step 5: Commit**
```bash
git add src/wheres_allie/estimator/hmm.py tests/estimator/test_hmm.py
git commit -m "feat: HMM forward filter over the walkable graph + away

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 4: `HmmFilter.smoothed()`: Viterbi over the last 30 windows

**Files:**
- Modify: `box/src/wheres_allie/estimator/hmm.py`
- Test: `box/tests/estimator/test_hmm.py`

**Step 1: Write failing test**
Append to `box/tests/estimator/test_hmm.py`:
```python
def test_smoothed_removes_single_window_blip(two_rooms, simulate):
    home, graph = two_rooms
    ws = (
        simulate(home, graph, "room:A", 8)
        + [Window(1, 17.0, {"nB": [-55.0]}, {"nA", "nB"}, None)]
        + simulate(home, graph, "room:A", 8, t0=18.0, seed=2)
    )
    f = _filter(home, graph)
    for w in ws:
        f.step(w)
    path = f.smoothed()
    assert len(path) == len(ws)
    assert all(e.vertex_id == "room:A" for e in path)
```

**Step 2: Run test, verify failure**
Run: `uv run pytest tests/estimator/test_hmm.py -q -k smoothed`
Expected: FAIL with `AttributeError: 'HmmFilter' object has no attribute 'smoothed'`

**Step 3: Implement**
Add this method at the end of `class HmmFilter` in `hmm.py`. `step()` already buffers `(ts, moving, log_prev, ll, log_post)`.
```python
    def smoothed(self) -> list[Estimate]:
        """Viterbi path over the buffered windows (last 60 s), seeded by the filtered belief
        just before the buffer. Confidence = filtered posterior of the chosen vertex."""
        if not self._hist:
            return []
        back = []
        delta = None
        for k, (_, moving, log_prev, ll, _) in enumerate(self._hist):
            cand = (log_prev if k == 0 else delta)[:, None] + self.log_transition(moving)
            back.append(np.argmax(cand, axis=0))
            delta = cand[back[-1], np.arange(len(self.states))] + ll
        path = [int(np.argmax(delta))]
        for bp in reversed(back[1:]):
            path.append(int(bp[path[-1]]))
        path.reverse()
        return [
            Estimate(ts, self.states[s], float(np.exp(post[s])), moving)
            for (ts, moving, _, _, post), s in zip(self._hist, path)
        ]
```

**Step 4: Run test, verify pass**
Run: `uv run pytest tests/estimator/test_hmm.py -q`
Expected: `6 passed`

**Step 5: Commit**
```bash
git add src/wheres_allie/estimator/hmm.py tests/estimator/test_hmm.py
git commit -m "feat: Viterbi smoothing over the last 60 s

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 5: `VisitTracker`

**Files:**
- Create: `box/src/wheres_allie/estimator/visits.py`
- Test: `box/tests/estimator/test_visits.py`

**Step 1: Write failing test**
```python
from wheres_allie.estimator.hmm import Estimate
from wheres_allie.estimator.visits import VisitTracker
from wheres_allie.home.graph import Vertex

OFFICE = Vertex("room:office", "room", "b", 2, 3, "office", "Office")
LOFT = Vertex("room:loft", "room", "u", 2, 3, "loft", "Loft")
BED = Vertex("lm:bed", "landmark", "m", 1, 1, "master", "Bed")
STAIRS = Vertex("stairs:s:a", "stairs", "b", 6, 1, None, "Stairs")


def run(seq):
    """seq: list of (vertex|None, seconds); one Estimate every 2 s."""
    t, out, tr = 0.0, [], VisitTracker()
    for v, secs in seq:
        for _ in range(int(secs / 2)):
            out += tr.update(Estimate(t, v.id if v else "away", 0.9, None), v)
            t += 2.0
    return out


def test_short_loft_pass_is_transit_not_visit():
    ev = run([(OFFICE, 40), (LOFT, 14), (OFFICE, 40)])
    assert [(e.op, e.place_id, e.kind) for e in ev] == [
        ("open", "office", "room"),
        ("close", "office", "room"),
        ("transit", "loft", "transit"),
        ("open", "office", "room"),
    ]
    assert ev[0].start == 0.0 and ev[0].end is None and ev[1].end == 40.0
    assert (ev[2].start, ev[2].end) == (40.0, 54.0)


def test_landmark_stairs_and_away():
    ev = run([(BED, 32), (STAIRS, 60), (None, 32)])
    assert [(e.op, e.place_id, e.kind) for e in ev] == [
        ("open", "lm:bed", "landmark"),
        ("close", "lm:bed", "landmark"),
        ("transit", "stairs:s:a", "transit"),  # never opened, however long
        ("open", "away", "away"),
    ]
```

**Step 2: Run test, verify failure**
Run: `uv run pytest tests/estimator/test_visits.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'wheres_allie.estimator.visits'`

**Step 3: Implement**
```python
"""Turn the position stream into visits: >= 30 s dwell is a room/landmark/away visit,
anything shorter (or any door/stairs vertex) is a transit (design §4.3)."""

from dataclasses import dataclass
from typing import Literal

from wheres_allie.estimator.hmm import Estimate
from wheres_allie.home.graph import Vertex

MIN_DWELL_S = 30.0


@dataclass
class VisitEvent:
    op: Literal["open", "close", "transit"]  # open: dwell reached 30 s (end=None); close: left
    place_id: str  # room id, landmark vertex id, door/stairs vertex id, or "away"
    kind: Literal["room", "landmark", "transit", "away"]
    start: float
    end: float | None


def place_of(e: Estimate, v: Vertex | None) -> tuple[str, str]:
    if v is None:
        return "away", "away"
    if v.kind == "landmark":
        return v.id, "landmark"
    if v.kind == "room" and v.room_id:
        return v.room_id, "room"
    return v.id, "transit"  # doors and stairs are never somewhere you "visit"


class VisitTracker:
    def __init__(self, min_dwell_s: float = MIN_DWELL_S):
        self.min_dwell = min_dwell_s
        self.place: tuple[str, str] | None = None
        self.start = 0.0
        self.opened = False

    def update(self, e: Estimate, v: Vertex | None) -> list[VisitEvent]:
        place = place_of(e, v)
        events = []
        if place != self.place:
            if self.place is not None:
                pid, kind = self.place
                if self.opened:
                    events.append(VisitEvent("close", pid, kind, self.start, e.ts))
                else:
                    events.append(VisitEvent("transit", pid, "transit", self.start, e.ts))
            self.place, self.start, self.opened = place, e.ts, False
        pid, kind = place
        if not self.opened and kind != "transit" and e.ts - self.start >= self.min_dwell:
            self.opened = True
            events.append(VisitEvent("open", pid, kind, self.start, None))
        return events
```

**Step 4: Run test, verify pass**
Run: `uv run pytest tests/estimator/test_visits.py -q`
Expected: `2 passed`

**Step 5: Commit**
```bash
git add src/wheres_allie/estimator/visits.py tests/estimator/test_visits.py
git commit -m "feat: visit tracker with 30 s dwell and explicit transits

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 6: `EstimatorRunner`

The runner goes by the timestamps on the readings, not by the wall clock. Each tag has a cursor, which is the end of its last processed window, persisted in `settings["estimator.last_ts.<tag_id>"]`. When a tag has no cursor yet, processing starts at its earliest reading. Readings backfilled days into the past (judge mode's demo-seed) and live readings therefore go through the same path, and a restart resumes without writing duplicates.

Each `run_until(until_ts)` call:
1. Rebuilds the model if `max(home.version)` changed.
2. For each tag, walks 2 s windows from its cursor up to `until_ts`, at most 1800 windows (1 h) per call.
3. For each window, steps the filter, writes the end of the Viterbi path to `positions`, and feeds `VisitTracker`.
4. Saves the cursor.
5. Returns the bus messages and whether every tag has caught up.

`catch_up()` loops `run_until` in `asyncio.to_thread` and publishes the messages, because `Bus` is not thread-safe. Only the newest position per chunk is published, so a backfill doesn't flood the WebSocket. `run_estimator` calls `catch_up(now - 1 s)` and then sleeps to the next 2 s boundary.

**Files:**
- Create: `box/src/wheres_allie/estimator/runner.py`
- Test: `box/tests/estimator/test_runner.py`

**Step 1: Write failing test**
```python
import asyncio

from wheres_allie import db
from wheres_allie.estimator.runner import EstimatorRunner, catch_up


def _conn():
    conn = db.connect(":memory:")
    db.migrate(conn)
    conn.execute("INSERT INTO pets (id, name) VALUES (1, 'Allie')")
    conn.execute("INSERT INTO tags (id, pet_id, ibeacon_id) VALUES (1, 1, 'iBeacon:x')")
    conn.executemany("INSERT INTO nodes (id, online) VALUES (?, 1)", [("nA",), ("nB",)])
    return conn


def _at_bed(conn, t0, seconds):
    """Readings as if the pet lies on the bed: nA loud, nB faint, one pair per 2 s."""
    conn.executemany(
        "INSERT INTO readings (ts, tag_id, node_id, rssi) VALUES (?, 1, ?, ?)",
        [
            (t0 + 2 * k + d, n, r)
            for k in range(int(seconds / 2))
            for d, n, r in ((0.5, "nA", -59.0), (1.0, "nB", -82.0))
        ],
    )


def _count(conn, table):
    return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def test_live_passes_write_positions_and_a_visit(two_rooms):
    conn = _conn()
    runner = EstimatorRunner(conn)
    runner.use_model(*two_rooms)
    msgs = []
    for k in range(20):  # 40 s, one pass per window as in live operation
        _at_bed(conn, 1000.0 + 2 * k, 2)
        msgs += runner.run_until(1000.0 + 2 * k + 2)[0]
    pos = conn.execute("SELECT vertex_id, room_id FROM positions ORDER BY ts DESC").fetchone()
    assert tuple(pos) == ("lm:bed", "A")
    assert _count(conn, "positions") == 20
    visits = conn.execute('SELECT place_id, kind, "end" FROM visits').fetchall()
    assert [tuple(v) for v in visits] == [("lm:bed", "landmark", None)]
    topics = [m[0] for m in msgs]
    assert topics.count("position") == 20 and topics.count("visit") == 1
    assert msgs[-1][1]["pet"] == "Allie"


def test_backfilled_past_readings_are_caught_up_once(two_rooms):
    conn = _conn()
    _at_bed(conn, 1000.0, 3 * 3600)  # 3 h of history, far in the past
    runner = EstimatorRunner(conn)
    runner.use_model(*two_rooms)
    msgs, done = runner.run_until(1000.0 + 3 * 3600)
    assert not done and _count(conn, "positions") == 1800  # one 1 h chunk per pass
    assert [m[0] for m in msgs].count("position") == 1  # only the newest goes on the bus
    while not done:
        msgs, done = runner.run_until(1000.0 + 3 * 3600)
    assert _count(conn, "positions") == 5400
    assert conn.execute("SELECT value FROM settings WHERE key = 'estimator.last_ts.1'").fetchone()[
        0
    ] == repr(1000.0 + 3 * 3600)
    assert [tuple(v) for v in conn.execute("SELECT place_id, kind FROM visits")] == [
        ("lm:bed", "landmark")
    ]
    fresh = EstimatorRunner(conn)  # restart: resumes from the persisted cursor, no duplicates
    fresh.use_model(*two_rooms)
    assert fresh.run_until(1000.0 + 3 * 3600) == ([], True)
    assert _count(conn, "positions") == 5400


def test_catch_up_publishes_to_bus(two_rooms):
    conn = _conn()
    _at_bed(conn, 1000.0, 60)

    class Bus:
        sent = []

        def publish(self, topic, data):
            self.sent.append(topic)

    runner = EstimatorRunner(conn)
    runner.use_model(*two_rooms)
    bus = Bus()
    asyncio.run(catch_up(conn, bus, 1060.0, runner))
    assert _count(conn, "positions") == 30
    assert bus.sent.count("position") == 1 and "visit" in bus.sent


def test_no_home_is_a_noop():
    conn = _conn()
    _at_bed(conn, 1000.0, 10)
    assert EstimatorRunner(conn).run_until(1010.0) == ([], True)
```

**Step 2: Run test, verify failure**
Run: `uv run pytest tests/estimator/test_runner.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'wheres_allie.estimator.runner'`

**Step 3: Implement**
```python
"""Estimator loop. Each tag has a cursor (settings `estimator.last_ts.<tag_id>` = end of the last
processed window). Every pass walks 2 s windows from the cursor up to "now", so backfilled past
readings (judge-mode demo-seed) and live readings take the same path. Positions and visits are
written to the db. The async loop publishes the returned bus messages, because Bus is not
thread-safe and the work runs in asyncio.to_thread (design §4.3, conventions §7)."""

import asyncio
import logging
import math
import sqlite3
import time

from wheres_allie.bus import Bus
from wheres_allie.estimator.emission import EmissionModel, PhysicsEmission
from wheres_allie.estimator.hmm import Estimate, HmmFilter
from wheres_allie.estimator.visits import VisitEvent, VisitTracker
from wheres_allie.estimator.window import WINDOW_S, load_windows
from wheres_allie.home.geometry import detect_rooms
from wheres_allie.home.graph import Graph, build_graph
from wheres_allie.home.model import Home
from wheres_allie.home.store import load_home

log = logging.getLogger(__name__)
CHUNK_WINDOWS = 1800  # max windows (1 h of data) per tag per pass, so a long backfill yields
LAG_S = 1.0  # stay this far behind the wall clock so in-flight readings land in their window


def exit_vertices(home: Home) -> set[str]:
    return {f"lm:{lm.id}" for lm in home.landmarks if lm.type == "door"}


def make_emission(conn: sqlite3.Connection, home: Home, graph: Graph) -> EmissionModel:
    return PhysicsEmission(home, graph)


class EstimatorRunner:
    def __init__(self, conn: sqlite3.Connection, dt: float = WINDOW_S):
        self.conn, self.dt = conn, dt
        self.version = None  # (home version, ...) the model was built from
        self.graph: Graph | None = None
        self.filters: dict[int, HmmFilter] = {}
        self.trackers: dict[int, VisitTracker] = {}
        self.open_visit: dict[int, int] = {}  # tag_id -> visits.id of the open visit

    def model_version(self) -> tuple:
        return (self.conn.execute("SELECT max(version) FROM home").fetchone()[0],)

    def use_model(self, home: Home, graph: Graph) -> None:
        self.home, self.graph = home, graph
        self.emission = make_emission(self.conn, home, graph)
        self.filters.clear()  # past positions stay; filters restart on the new graph
        self.version = self.model_version()

    def load_model(self) -> None:
        home = load_home(self.conn)
        self.use_model(home, build_graph(home, detect_rooms(home)))

    def cursor(self, tag_id: int) -> float | None:
        row = self.conn.execute(
            "SELECT value FROM settings WHERE key = ?", (f"estimator.last_ts.{tag_id}",)
        ).fetchone()
        if row:
            return float(row[0])
        first = self.conn.execute(
            "SELECT min(ts) FROM readings WHERE tag_id = ?", (tag_id,)
        ).fetchone()[0]
        return None if first is None else math.floor(first / self.dt) * self.dt

    def run_until(self, until_ts: float) -> tuple[list[tuple[str, dict]], bool]:
        """Process each tag's windows from its cursor up to until_ts, at most CHUNK_WINDOWS per
        tag. Returns (bus messages, caught_up). Only the newest position per tag is returned
        as a message; every window is written to `positions`."""
        if self.model_version() != self.version:
            self.load_model()
        if not self.graph or not self.graph.vertices:
            return [], True
        msgs, caught_up = [], True
        tags = self.conn.execute(
            "SELECT t.id, p.name FROM tags t JOIN pets p ON p.id = t.pet_id"
        ).fetchall()
        for tag_id, pet in tags:
            start = self.cursor(tag_id)
            if start is None or start + self.dt > until_ts:
                continue
            end = min(until_ts, start + CHUNK_WINDOWS * self.dt)
            caught_up &= end == until_ts
            f = self.filters.get(tag_id)
            if f is None:
                f = self.filters[tag_id] = HmmFilter(
                    self.graph, self.emission, exit_vertices=exit_vertices(self.home)
                )
            tracker = self.trackers.setdefault(tag_id, VisitTracker())
            last = None
            for w in load_windows(self.conn, tag_id, start, end, self.dt):
                f.step(w)
                e = f.smoothed()[-1]  # ponytail: end of the 60 s Viterbi path; fixed-lag if jittery
                last = self._write_position(tag_id, pet, e)
                for ev in tracker.update(e, self.graph.vertices.get(e.vertex_id)):
                    msgs.append(("visit", self._write_visit(tag_id, pet, ev)))
            if last:
                msgs.append(("position", last))
                self.conn.execute(
                    "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                    (f"estimator.last_ts.{tag_id}", repr(last["ts"])),
                )
        self.conn.commit()
        return msgs, caught_up

    def _write_position(self, tag_id: int, pet: str, e: Estimate) -> dict:
        v = self.graph.vertices.get(e.vertex_id)
        row = {
            "ts": e.ts,
            "tag_id": tag_id,
            "vertex_id": e.vertex_id,
            "room_id": v.room_id if v else None,
            "floor_id": v.floor_id if v else None,
            "confidence": e.confidence,
            "moving": None if e.moving is None else int(e.moving),
        }
        self.conn.execute(
            "INSERT INTO positions (ts, tag_id, vertex_id, room_id, floor_id, confidence, moving)"
            " VALUES (:ts, :tag_id, :vertex_id, :room_id, :floor_id, :confidence, :moving)",
            row,
        )
        return {**row, "pet": pet, "x": v.x if v else None, "y": v.y if v else None}

    def _write_visit(self, tag_id: int, pet: str, ev: VisitEvent) -> dict:
        if ev.op == "close" and tag_id in self.open_visit:
            vid = self.open_visit.pop(tag_id)
            self.conn.execute('UPDATE visits SET "end" = ? WHERE id = ?', (ev.end, vid))
        else:
            vid = self.conn.execute(
                'INSERT INTO visits (tag_id, place_id, kind, start, "end") VALUES (?, ?, ?, ?, ?)',
                (tag_id, ev.place_id, ev.kind, ev.start, ev.end),
            ).lastrowid
            if ev.op == "open":
                self.open_visit[tag_id] = vid
        return {
            "id": vid,
            "op": ev.op,
            "tag_id": tag_id,
            "pet": pet,
            "place_id": ev.place_id,
            "kind": ev.kind,
            "start": ev.start,
            "end": ev.end,
        }


async def catch_up(
    conn: sqlite3.Connection, bus: Bus, until_ts: float, runner: EstimatorRunner | None = None
) -> EstimatorRunner:
    """Process every tag up to until_ts in 1 h chunks, publishing as it goes."""
    runner = runner or EstimatorRunner(conn)
    done = False
    while not done:
        msgs, done = await asyncio.to_thread(runner.run_until, until_ts)
        for topic, data in msgs:
            bus.publish(topic, data)
    return runner


async def run_estimator(conn: sqlite3.Connection, bus: Bus, dt: float = WINDOW_S) -> None:
    runner = EstimatorRunner(conn, dt)
    while True:
        try:
            await catch_up(conn, bus, time.time() - LAG_S, runner)
        except Exception:
            log.exception("estimator pass failed")
        await asyncio.sleep(dt - time.time() % dt)
```

**Step 4: Run test, verify pass**
Run: `uv run pytest tests/estimator/test_runner.py -q`
Expected: `4 passed`

**Step 5: Commit**
```bash
git add src/wheres_allie/estimator/runner.py tests/estimator/test_runner.py
git commit -m "feat: estimator runner with persisted cursors and backfill catch-up

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 7: Start the estimator task in the app lifespan

Plan 01's `create_app(settings=None, conn=None, start_background=True)` sets `app.state.conn`/`bus` at creation. Its lifespan starts `run_ingest` and `run_retention` in a local `tasks` list under `if start_background:`, and cancels that list after `yield`. The estimator joins that list, and it is also stored on `app.state` so it can be inspected.

**Files:**
- Modify: `box/src/wheres_allie/api/app.py`
- Test: `box/tests/estimator/test_lifespan.py`

**Step 1: Write failing test**
```python
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("WA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("WA_MQTT_PASS", "test")
    monkeypatch.setenv("WA_MQTT_HOST", "127.0.0.1")  # ingest just retries with backoff


def test_lifespan_starts_estimator(env):
    from wheres_allie.api.app import create_app

    app = create_app()
    with TestClient(app):
        assert not app.state.estimator_task.done()
    assert app.state.estimator_task.cancelled() or app.state.estimator_task.done()


def test_no_estimator_without_background(env):
    from wheres_allie.api.app import create_app

    app = create_app(start_background=False)
    with TestClient(app):
        assert getattr(app.state, "estimator_task", None) is None
```

**Step 2: Run test, verify failure**
Run: `uv run pytest tests/estimator/test_lifespan.py -q`
Expected: `test_lifespan_starts_estimator` FAILS with `AttributeError: 'State' object has no attribute 'estimator_task'`

**Step 3: Implement**
In `api/app.py`:
1. Add `from wheres_allie.estimator.runner import run_estimator` to the imports.
2. Inside `lifespan`, in the `if start_background:` block, add the following after the ingest and retention tasks are appended to `tasks`:
```python
            app.state.estimator_task = asyncio.create_task(
                run_estimator(app.state.conn, app.state.bus), name="estimator"
            )
            tasks.append(app.state.estimator_task)
```
Plan 01's existing shutdown code already cancels everything in `tasks`, so shutdown needs no change.

**Step 4: Run test, verify pass**
Run: `uv run pytest tests/estimator/test_lifespan.py tests/api -q`
Expected: all pass

**Step 5: Commit**
```bash
git add src/wheres_allie/api/app.py tests/estimator/test_lifespan.py
git commit -m "feat: run the estimator in the app lifespan

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 8: `eval.py`: scoring + nearest-node baseline

Metrics:
- **Room accuracy:** over windows inside a truth span, whether the predicted vertex's `room_id` equals the truth room. A truth place is either a vertex id (its room_id is used) or a room id. Door and stairs vertices have `room_id=None`, so they count as wrong.
- **Landmark accuracy:** over truth spans whose place is `lm:*`, whether the exact vertex was predicted.
- **Transit false-visit rate:** run the same `VisitTracker` over the predictions. Take every visit (dwell ≥ 30 s) that overlaps truth. The rate is the fraction of those visits whose room matches none of the overlapping truth rooms.

The baseline is the room of the loudest node in each window, held through silent windows, which is how the ESPresense companion behaves. It is scored as `room:<id>`.

**Files:**
- Create: `box/src/wheres_allie/estimator/eval.py`
- Test: `box/tests/estimator/test_eval.py`

**Step 1: Write failing test**
```python
from wheres_allie.estimator.eval import Truth, score


def test_score_room_landmark_and_false_visits(two_rooms, simulate):
    home, graph = two_rooms
    ws = simulate(home, graph, "lm:bed", 30)  # t_end 2..60
    truth = [Truth(0.0, 61.0, "lm:bed")]
    right = score(graph, ws, ["lm:bed"] * 30, truth)
    assert right == {
        "room_acc": 1.0,
        "landmark_acc": 1.0,
        "transit_false_visit_rate": 0.0,
        "windows": 30,
    }
    same_room = score(graph, ws, ["room:A"] * 30, truth)
    assert same_room["room_acc"] == 1.0 and same_room["landmark_acc"] == 0.0
    # 40 s wrongly in B = false visit; 10 s at the door = transit; 50 s on the bed = right
    ws = simulate(home, graph, "lm:bed", 50)  # t_end 2..100
    truth = [Truth(0.0, 101.0, "lm:bed")]
    wrong = score(graph, ws, ["room:B"] * 20 + ["door:d"] * 5 + ["lm:bed"] * 25, truth)
    assert wrong["room_acc"] == 25 / 50
    assert wrong["transit_false_visit_rate"] == 0.5


def test_baseline_room_ids_score_as_rooms(two_rooms, simulate):
    home, graph = two_rooms
    ws = simulate(home, graph, "room:B", 5)
    assert score(graph, ws, ["B"] * 5, [Truth(0, 99, "B")])["room_acc"] == 1.0
```

**Step 2: Run test, verify failure**
Run: `uv run pytest tests/estimator/test_eval.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'wheres_allie.estimator.eval'`

**Step 3: Implement**
```python
"""`wheres-allie eval`: HMM vs nearest-node baseline on a replay bundle + ground truth."""

import csv
import io
import json
import math
import zipfile
from dataclasses import dataclass

import numpy as np

from wheres_allie.estimator.emission import EmissionModel, PhysicsEmission
from wheres_allie.estimator.hmm import Estimate, HmmFilter
from wheres_allie.estimator.runner import exit_vertices
from wheres_allie.estimator.visits import VisitTracker
from wheres_allie.estimator.window import Window, make_windows
from wheres_allie.home.geometry import Room, detect_rooms, room_at
from wheres_allie.home.graph import Graph, build_graph
from wheres_allie.home.model import Home


@dataclass
class Truth:
    ts_start: float
    ts_end: float
    place: str  # vertex id or room id


@dataclass
class Bundle:
    home: Home
    ids: set[str]  # the first pet's ibeacon ids (normal + motion)
    readings: list[tuple[float, str, float]]
    motion: list[tuple[float, bool]]
    labels: list[tuple[float, float, str]]  # (ts_start, ts_end, vertex_id)
    truth: list[Truth]


def _csv(z: zipfile.ZipFile, name: str) -> list[dict]:
    if name not in z.namelist():
        return []
    return list(csv.DictReader(io.StringIO(z.read(name).decode())))


def read_truth(rows: list[dict], ids: set[str]) -> list[Truth]:
    return [
        Truth(float(r["ts_start"]), float(r["ts_end"]), r["place"])
        for r in rows
        if not r.get("ibeacon_id") or r["ibeacon_id"] in ids
    ]


def load_bundle(path: str) -> Bundle:
    with zipfile.ZipFile(path) as z:
        manifest = json.loads(z.read("manifest.json"))
        pet = manifest["pets"][0]  # ponytail: first pet only; demo data has one
        ids = {pet["ibeacon_id"], pet.get("motion_ibeacon_id")} - {None, ""}
        home = Home.model_validate_json(z.read("home.json"))
        readings = sorted(
            (float(r["ts"]), r["node_id"], float(r["rssi"]))
            for r in _csv(z, "readings.csv")
            if r["ibeacon_id"] in ids
        )
        motion = sorted(
            (float(r["ts"]), r["moving"] in ("1", "true", "True"))
            for r in _csv(z, "motion.csv")
            if r["ibeacon_id"] in ids
        )
        labels = [
            (float(r["ts_start"]), float(r["ts_end"]), r["vertex_id"])
            for r in _csv(z, "labels.csv")
            if r["ibeacon_id"] in ids
        ]
        truth = read_truth(_csv(z, "ground_truth.csv"), ids)
    return Bundle(home, ids, readings, motion, labels, truth)


def nearest_node_rooms(home: Home, rooms: list[Room], windows: list[Window]) -> list[str | None]:
    """ESPresense-companion style: room of the loudest node; holds the last room when silent."""
    where = {}
    for n in home.nodes:
        r = room_at(rooms, n.floor_id, n.x, n.y)
        where[n.id] = r.id if r else None
    out, last = [], None
    for w in windows:
        if w.rssi:
            last = where.get(max(w.rssi, key=lambda n: np.mean(w.rssi[n])))
        out.append(last)
    return out


def hmm_vertices(
    graph: Graph, emission: EmissionModel, home: Home, windows: list[Window]
) -> list[str]:
    f = HmmFilter(graph, emission, exit_vertices=exit_vertices(home))
    out = []
    for w in windows:
        f.step(w)
        out.append(f.smoothed()[-1].vertex_id)  # same online output the runner writes
    return out


def _truth_at(truth: list[Truth], ts: float) -> Truth | None:
    return next((t for t in truth if t.ts_start <= ts < t.ts_end), None)


def score(
    graph: Graph, windows: list[Window], vertices: list[str | None], truth: list[Truth]
) -> dict:
    """vertices[i] is the predicted vertex id for windows[i] (room:<id> for the baseline)."""

    def room_of(place: str | None) -> str | None:
        v = graph.vertices.get(place) if place else None
        return v.room_id if v else place  # an unknown place is a room id (or away/None)

    room_hits, room_n, lm_hits, lm_n = 0, 0, 0, 0
    for w, pred in zip(windows, vertices):
        t = _truth_at(truth, w.t_end)
        if t is None:
            continue
        room_n += 1
        room_hits += room_of(pred) == room_of(t.place)
        if t.place.startswith("lm:"):
            lm_n += 1
            lm_hits += pred == t.place

    # visits (>= 30 s) that overlap ground truth but put the pet in the wrong room
    tracker, visits, open_ = VisitTracker(), [], None
    for w, pred in zip(windows, vertices):
        v = graph.vertices.get(pred) if pred else None
        for ev in tracker.update(Estimate(w.t_end, pred or "away", 1.0, None), v):
            if ev.op == "open":
                open_ = ev
            elif ev.op == "close":
                visits.append((ev.place_id, ev.start, ev.end))
                open_ = None
    if open_ and windows:
        visits.append((open_.place_id, open_.start, windows[-1].t_end))
    judged = false = 0
    for place, start, end in visits:
        overlap = [t for t in truth if t.ts_start < end and start < t.ts_end]
        if overlap:
            judged += 1
            false += all(room_of(place) != room_of(t.place) for t in overlap)
    return {
        "room_acc": room_hits / room_n if room_n else None,
        "landmark_acc": lm_hits / lm_n if lm_n else None,
        "transit_false_visit_rate": false / judged if judged else 0.0,
        "windows": room_n,
    }


def evaluate(bundle_path: str, truth_csv: str | None = None, **physics_kw) -> dict:
    """physics_kw are PhysicsEmission knobs (tx_power_dbm, floor_db, ...) for tuning."""
    b = load_bundle(bundle_path)
    truth = b.truth
    if truth_csv:
        with open(truth_csv, newline="") as fh:
            truth = read_truth(list(csv.DictReader(fh)), b.ids)
    if not b.readings or not truth:
        raise ValueError("bundle has no readings for the pet, or there is no ground truth")
    rooms = detect_rooms(b.home)
    graph = build_graph(b.home, rooms)
    t0 = math.floor(b.readings[0][0])
    windows = make_windows(
        0, b.readings, b.motion, {n.id for n in b.home.nodes}, t0, b.readings[-1][0] + 2.0
    )
    physics = PhysicsEmission(b.home, graph, **physics_kw)
    phys = score(graph, windows, hmm_vertices(graph, physics, b.home, windows), truth)
    base_rooms = nearest_node_rooms(b.home, rooms, windows)
    base = score(graph, windows, [f"room:{r}" if r else None for r in base_rooms], truth)
    out = {
        **phys,
        "baseline_room_acc": base["room_acc"],
        "baseline_transit_false_visit_rate": base["transit_false_visit_rate"],
    }
    return out
```

**Step 4: Run test, verify pass**
Run: `uv run pytest tests/estimator/test_eval.py -q`
Expected: `2 passed`

**Step 5: Commit**
```bash
git add src/wheres_allie/estimator/eval.py tests/estimator/test_eval.py
git commit -m "feat: eval scoring (room/landmark/false-visit) + nearest-node baseline

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 9: `evaluate()` on a bundle + `wheres-allie eval` CLI

This is an end-to-end floor-bleed case built on plan 02's real `detect_rooms`/`build_graph`:
- Basement office: 0–8 × 0–6 m. Its node sits right under the kitchen centre.
- Main kitchen: 0–12 × 0–6 m. Its node is at the far east wall.
- The pet stands at the kitchen centre. The office node is 2 dB louder, so the baseline is always wrong.

**Files:**
- Modify: `box/src/wheres_allie/cli.py`
- Test: `box/tests/estimator/test_eval_bundle.py`

**Step 1: Write failing test**
```python
import json
import zipfile

from typer.testing import CliRunner

from wheres_allie.cli import app
from wheres_allie.estimator.eval import evaluate
from wheres_allie.home.model import (
    Floor, Home, NodePlacement, RoomLabel, Stairs, StairsEnd, Wall,
)


def _rect(floor_id, x0, y0, x1, y1, prefix):
    pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    return [Wall(id=f"{prefix}{i}", floor_id=floor_id, a=pts[i], b=pts[(i + 1) % 4])
            for i in range(4)]


HOME = Home(
    floors=[Floor(id="b", name="Basement", elevation_m=0.0),
            Floor(id="m", name="Main", elevation_m=2.7)],
    walls=_rect("b", 0, 0, 8, 6, "wb") + _rect("m", 0, 0, 12, 6, "wm"),
    room_labels=[RoomLabel(id="office", floor_id="b", name="Office", seed=(4, 3)),
                 RoomLabel(id="kitchen", floor_id="m", name="Kitchen", seed=(6, 3))],
    stairs=[Stairs(id="s", a=StairsEnd(floor_id="b", x=1, y=5), b=StairsEnd(floor_id="m", x=1, y=5))],
    nodes=[NodePlacement(id="office", floor_id="b", x=6, y=3, z_m=1.0, name="Office"),
           NodePlacement(id="kitchen", floor_id="m", x=11.8, y=3, z_m=1.0, name="Kitchen")],
)


def write_bundle(path, labels=""):
    """60 windows with the pet at the kitchen centre; truth = kitchen for all of it."""
    rows = "".join(f"{1000 + 2 * k + 0.5},ib,office,-76.5,,\n{1000 + 2 * k + 1.0},ib,kitchen,-78.5,,\n"
                   for k in range(60))
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("manifest.json", json.dumps({"format": 1, "created": 0, "tz": "UTC", "from": 1000,
                   "to": 1120, "pets": [{"name": "Allie", "ibeacon_id": "ib",
                                         "motion_ibeacon_id": None}]}))
        z.writestr("home.json", HOME.model_dump_json())
        z.writestr("readings.csv", "ts,ibeacon_id,node_id,rssi,distance,rssi_var\n" + rows)
        z.writestr("motion.csv", "ts,ibeacon_id,moving\n")
        z.writestr("labels.csv", "ts_start,ts_end,ibeacon_id,vertex_id,source\n" + labels)
        z.writestr("ground_truth.csv", "ts_start,ts_end,ibeacon_id,place\n1000,1122,ib,kitchen\n")
    return str(path)


def test_hmm_beats_nearest_node_on_floor_bleed(tmp_path):
    r = evaluate(write_bundle(tmp_path / "a.bundle"))
    assert r["windows"] == 60
    assert r["room_acc"] >= 0.9
    assert r["baseline_room_acc"] <= 0.1
    assert r["landmark_acc"] is None


def test_cli_eval_prints_json_and_checks(tmp_path):
    p = write_bundle(tmp_path / "a.bundle")
    res = CliRunner().invoke(app, ["eval", "--bundle", p, "--check"])
    assert res.exit_code == 0, res.output
    assert json.loads(res.output)["room_acc"] >= 0.9
    truth = tmp_path / "t.csv"
    truth.write_text("ts_start,ts_end,ibeacon_id,place\n1000,1122,,office\n")
    res = CliRunner().invoke(app, ["eval", "--bundle", p, "--truth", str(truth), "--check"])
    assert res.exit_code == 1  # truth says office: the baseline wins, --check fails
```

**Step 2: Run test, verify failure**
Run: `uv run pytest tests/estimator/test_eval_bundle.py -q`
Expected: `test_hmm_beats_nearest_node_on_floor_bleed` passes, because `evaluate` exists since Task 8. `test_cli_eval_prints_json_and_checks` FAILS with `exit_code == 2` ("No such command 'eval'"). If the first test fails, look at `build_graph(HOME, detect_rooms(HOME))`. It must produce `room:office` at about (4,3), `room:kitchen` at about (6,3), and stairs vertices at (1,5). Fix plan 02, not this test.

**Step 3: Implement**
In `box/src/wheres_allie/cli.py` (plan 01 has only `serve`), add the following. `json` and `Path` imports go at the top of the file if they aren't there already:
```python
import json
from pathlib import Path


@app.command("eval")
def eval_cmd(
    bundle: Path = typer.Option(..., "--bundle", exists=True, dir_okay=False),
    truth: Path | None = typer.Option(None, "--truth", exists=True, dir_okay=False),
    tx_power: float | None = typer.Option(None, "--tx-power", help="Tag RSSI at 1 m, dBm"),
    floor_db: float | None = typer.Option(None, "--floor-db", help="Loss per floor crossed, dB"),
    check: bool = typer.Option(False, "--check", help="Exit 1 unless we beat nearest-node"),
) -> None:
    """Room/landmark accuracy of the HMM vs the nearest-node baseline on a recorded bundle."""
    from wheres_allie.estimator.eval import evaluate

    knobs = {"tx_power_dbm": tx_power, "floor_db": floor_db}
    r = evaluate(str(bundle), str(truth) if truth else None,
                 **{k: v for k, v in knobs.items() if v is not None})
    typer.echo(json.dumps(r, indent=2))
    if check and not (r["room_acc"] or 0) > (r["baseline_room_acc"] or 0):
        raise typer.Exit(1)
```

**Step 4: Run test, verify pass**
Run: `uv run pytest tests/estimator/test_eval_bundle.py -q`
Expected: `2 passed`

**Step 5: Commit**
```bash
git add src/wheres_allie/cli.py tests/estimator/test_eval_bundle.py
git commit -m "feat: wheres-allie eval CLI (HMM vs nearest-node on a bundle)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 10: Real-data ground truth + first eval run

`data/allie-raw.log` runs from 22:34:08 to 23:39 EDT on 2026-09-28. Of the entries in `data/ground-truth.md`, only "~22:37 master bedroom (seen)" and "~22:43 on master bed (likely)" fall inside the log. "Under master bed ~22:05" and "office ~22:20" are earlier than the log, so they can't be scored until a longer log is recorded (flag this to the owner). Nothing here adds truth that the owner didn't state.

**Files:**
- Create: `box/tests/fixtures/allie-truth.csv`

**Step 1: Find the ids**
Run: `jq -r '(.room_labels[] | "\(.id)\t\(.name)"), (.landmarks[] | "lm:\(.id)\t\(.name)")' tests/fixtures/home_allie.json`
Expected: the output includes `master_bedroom	Master bedroom` and `lm:bed_master	Allie's bed` (these are the ids in plan 02's fixture).

**Step 2: Write the truth file**
Timestamps are unix seconds: 22:37:40 = 1790649460, 22:42:30 = 1790649750, 22:43:00 = 1790649780, 22:50:00 = 1790650200 (EDT = UTC-4). A blank `ibeacon_id` means Allie's tag:
```csv
ts_start,ts_end,ibeacon_id,place
1790649460,1790649750,,master_bedroom
1790649780,1790650200,,lm:bed_master
```

**Step 3: Build the bundle and run the eval**
```bash
uv run python tools/import_raw_log.py --help   # confirm plan 01's flag names first
uv run python tools/import_raw_log.py ../data/allie-raw.log --home tests/fixtures/home_allie.json --out /tmp/allie-2026-09-28.bundle
uv run wheres-allie eval --bundle /tmp/allie-2026-09-28.bundle --truth tests/fixtures/allie-truth.csv
```
Expected: a JSON object with all six keys and `windows` > 200. Then try the tuning knobs. The real tag reads about -80 dBm at 2–6 m, which is far below the -59 dBm @1 m model, most likely because of body and floor-level loss:
```bash
for tx in -59 -65 -70 -75; do uv run wheres-allie eval --bundle /tmp/allie-2026-09-28.bundle --truth tests/fixtures/allie-truth.csv --tx-power $tx | jq -c '{tx: '$tx', room_acc, baseline_room_acc}'; done
```
If one tx value is clearly best, change the `tx_power_dbm` default in `PhysicsEmission.__init__` to it and re-run `uv run pytest tests/estimator -q`. The synthetic tests draw from the model itself, so they stay green.

**Step 4: Verify**
Run: `uv run pytest -q`
Expected: all pass. Paste the eval JSON into the commit body.

**Step 5: Commit**
```bash
git add tests/fixtures/allie-truth.csv src/wheres_allie/estimator/emission.py
git commit -m "test: ground truth for the 2026-09-28 Allie log + first eval numbers

<paste eval JSON here>

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 11: Phase 3 exit

**Step 1:** Run `uv run pytest -q && uv run ruff check . && uv run ruff format --check .` Expected: all pass, with no lint errors.
**Step 2:** Run `WA_DATA_DIR=/tmp/wa uv run wheres-allie serve` with plan 01's replayer or live nodes. Save a home in the editor. Then run `sqlite3 /tmp/wa/wheres_allie.db "select * from positions order by ts desc limit 3"` and confirm that a row appears every 2 s.
**Step 3:** Update the Status table (Tasks 1–11 → done / yes), then commit and push:
```bash
git add docs/plans/2026-09-28-wheres-allie-plan-03-estimator.md
git commit -m "docs: phase 3 estimator complete

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push origin main
```

---

# Phase 4: Calibration

### Task 12: `calibration/labels.py`

When a label is created, its windows are snapshotted into `settings["calib:label:<id>"]`. The nightly 30-day `readings` retention would otherwise erase the fingerprints.

**Files:**
- Create: `box/src/wheres_allie/calibration/__init__.py` (empty)
- Create: `box/src/wheres_allie/calibration/labels.py`
- Test: `box/tests/calibration/test_labels.py`

**Step 1: Write failing test**
```python
import pytest

from wheres_allie import db
from wheres_allie.calibration.labels import create_label, labels_version, load_samples


@pytest.fixture
def conn():
    c = db.connect(":memory:")
    db.migrate(c)
    c.execute("INSERT INTO pets (id, name) VALUES (1, 'Allie')")
    c.execute("INSERT INTO tags (id, pet_id, ibeacon_id) VALUES (1, 1, 'iBeacon:x')")
    c.executemany("INSERT INTO nodes (id, online) VALUES (?, 1)", [("a",), ("b",)])
    c.executemany(
        "INSERT INTO readings (ts, tag_id, node_id, rssi) VALUES (?, 1, ?, ?)",
        [(100.0 + k, "a", -70.0 - k % 2) for k in range(30)] + [(500.0, "a", -40.0)],
    )
    return c


def test_label_snapshots_its_windows(conn):
    lab = create_label(conn, 1, "lm:bed", "tap", ts_end=130.0)
    assert (lab["ts_start"], lab["samples"]) == (100.0, 30)
    assert labels_version(conn) == (1, lab["id"])
    conn.execute("DELETE FROM readings")  # retention must not lose calibration
    ws = load_samples(conn)["lm:bed"]
    assert len(ws) == 15
    assert ws[0].rssi == {"a": [-70.0, -71.0]} and ws[0].online_nodes == {"a", "b"}


def test_label_rejects_bad_input(conn):
    with pytest.raises(ValueError):
        create_label(conn, 1, "lm:bed", "guess")
    with pytest.raises(ValueError):
        create_label(conn, 1, "lm:bed", "tap", ts_start=200.0, ts_end=100.0)
```

**Step 2: Run test, verify failure**
Run: `uv run pytest tests/calibration/test_labels.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'wheres_allie.calibration'`

**Step 3: Implement**
```python
"""Calibration labels ("Allie is here", guided walk) and their training samples.

A label's samples are its 2 s windows, snapshotted into settings[`calib:label:<id>`] when the
label is created, so fingerprints survive the 30-day readings retention."""

import json
import sqlite3
import time

from wheres_allie.estimator.window import Window, load_windows

LABEL_S = 30.0  # default label span: the 30 s before "now"
SOURCES = ("walk", "tap", "voice", "import")


def create_label(
    conn: sqlite3.Connection,
    tag_id: int,
    vertex_id: str,
    source: str,
    ts_start: float | None = None,
    ts_end: float | None = None,
) -> dict:
    if source not in SOURCES:
        raise ValueError(f"source must be one of {SOURCES}")
    ts_end = time.time() if ts_end is None else ts_end
    ts_start = ts_end - LABEL_S if ts_start is None else ts_start
    if not ts_start < ts_end or ts_end - ts_start > 3600:
        raise ValueError("need ts_start < ts_end, at most 1 h apart")
    windows = load_windows(conn, tag_id, ts_start, ts_end)
    lid = conn.execute(
        "INSERT INTO labels (tag_id, vertex_id, ts_start, ts_end, source) VALUES (?, ?, ?, ?, ?)",
        (tag_id, vertex_id, ts_start, ts_end, source),
    ).lastrowid
    conn.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        (f"calib:label:{lid}", json.dumps([[w.rssi, sorted(w.online_nodes)] for w in windows])),
    )
    conn.commit()
    return {
        "id": lid,
        "tag_id": tag_id,
        "vertex_id": vertex_id,
        "ts_start": ts_start,
        "ts_end": ts_end,
        "source": source,
        "samples": sum(len(v) for w in windows for v in w.rssi.values()),
    }


def load_samples(conn: sqlite3.Connection) -> dict[str, list[Window]]:
    """vertex_id -> labelled windows, pooled over all tags (the house, not the dog, sets RSSI)."""
    out: dict[str, list[Window]] = {}
    rows = conn.execute(
        "SELECT l.tag_id, l.vertex_id, s.value FROM labels l"
        " JOIN settings s ON s.key = 'calib:label:' || l.id"
    )
    for tag_id, vertex_id, value in rows:
        out.setdefault(vertex_id, []).extend(
            Window(tag_id, 0.0, rssi, set(online), None) for rssi, online in json.loads(value)
        )
    return out


def labels_version(conn: sqlite3.Connection) -> tuple:
    return tuple(conn.execute("SELECT count(*), max(id) FROM labels").fetchone())
```

**Step 4: Run test, verify pass**
Run: `uv run pytest tests/calibration/test_labels.py -q`
Expected: `2 passed`

**Step 5: Commit**
```bash
git add src/wheres_allie/calibration tests/calibration/test_labels.py
git commit -m "feat: calibration labels with retention-proof sample snapshots

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 13: `calibration/fingerprints.py`

The definitions:
- A sample is one reading, so a 30 s label with 2 nodes gives about 25–30 samples. The minimum is 20.
- Per node: the mean and std (floor 3 dB) are computed over per-window mean RSSI in the windows where the node heard the tag.
- `heard_rate` is heard windows ÷ windows the node was online, clipped to [0.05, 0.95].
- The Gaussian is used only when the node heard the tag in at least 3 windows.

**Files:**
- Create: `box/src/wheres_allie/calibration/fingerprints.py`
- Test: `box/tests/calibration/test_fingerprints.py` (created here, then extended in Task 14)

**Step 1: Write failing test**
```python
import numpy as np
import pytest

from wheres_allie.calibration.fingerprints import build_fingerprint
from wheres_allie.estimator.window import Window

ONLINE = {"master_bedroom", "moms_room"}
UNDER_BED = {"master_bedroom": [-89.0], "moms_room": [-81.0]}  # the real 2026-09-28 readings


def _windows(rssi, n, t0=0.0, jitter=1.0, seed=0):
    rng = np.random.default_rng(seed)
    return [
        Window(
            1,
            t0 + 2 * (k + 1),
            {nd: [v[0] + rng.normal(0, jitter)] for nd, v in rssi.items()},
            set(ONLINE),
            None,
        )
        for k in range(n)
    ]


def test_build_fingerprint_stats():
    ws = _windows(UNDER_BED, 10, jitter=0.0) + [Window(1, 99, {"moms_room": [-81.0]}, ONLINE, None)]
    fp = build_fingerprint("lm:bed", ws)
    assert fp.n == 21
    st = fp.nodes["master_bedroom"]
    assert (st.mean, st.std, st.heard) == (-89.0, 3.0, 10)
    assert st.heard_rate == pytest.approx(10 / 11)
    assert fp.nodes["moms_room"].heard_rate == 0.95  # 11/11 clipped
```

**Step 2: Run test, verify failure**
Run: `uv run pytest tests/calibration/test_fingerprints.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'wheres_allie.calibration.fingerprints'`

**Step 3: Implement**
```python
"""Per-vertex RSSI fingerprints learned from labelled windows (design §4.3 emission 1)."""

import math
from dataclasses import dataclass

import numpy as np

from wheres_allie.estimator.emission import rssi_logpdf
from wheres_allie.estimator.window import Window

MIN_SAMPLES = 20  # readings before a fingerprint is trusted at all
BLEND_K = 20  # blend weight n / (n + 20): 20 samples -> half fingerprint, 180 -> 90 %
MIN_HEARD_WINDOWS = 3  # per node, before its RSSI Gaussian is used
MIN_STD_DB = 3.0


@dataclass
class NodeStat:
    mean: float  # of per-window mean RSSI, over windows where the node heard the tag
    std: float
    heard_rate: float  # heard windows / windows the node was online, clipped to [0.05, 0.95]
    heard: int  # windows heard


@dataclass
class Fingerprint:
    vertex_id: str
    n: int  # samples = readings across all nodes
    nodes: dict[str, NodeStat]

    def node_ll(self, w: Window, node: str) -> float | None:
        """This node's log-likelihood term, or None when the fingerprint never saw the node."""
        st = self.nodes.get(node)
        if st is None:
            return None
        vals = w.rssi.get(node)
        if not vals:
            return math.log1p(-st.heard_rate)
        ll = math.log(st.heard_rate)
        if st.heard >= MIN_HEARD_WINDOWS:
            ll += float(rssi_logpdf(float(np.mean(vals)), st.mean, st.std))
        return ll


def blend_weight(n: int) -> float:
    return n / (n + BLEND_K) if n >= MIN_SAMPLES else 0.0


def build_fingerprint(vertex_id: str, windows: list[Window]) -> Fingerprint:
    means: dict[str, list[float]] = {}
    online: dict[str, int] = {}
    n = 0
    for w in windows:
        for node in w.online_nodes:
            online[node] = online.get(node, 0) + 1
            if w.rssi.get(node):
                means.setdefault(node, []).append(float(np.mean(w.rssi[node])))
                n += len(w.rssi[node])
    nodes = {}
    for node, k in online.items():
        m = means.get(node, [])
        nodes[node] = NodeStat(
            mean=float(np.mean(m)) if m else -100.0,
            std=max(float(np.std(m)) if len(m) > 1 else 0.0, MIN_STD_DB),
            heard_rate=min(max(len(m) / k, 0.05), 0.95),
            heard=len(m),
        )
    return Fingerprint(vertex_id, n, nodes)


def build_fingerprints(samples: dict[str, list[Window]]) -> dict[str, Fingerprint]:
    return {vid: build_fingerprint(vid, ws) for vid, ws in samples.items() if ws}
```

**Step 4: Run test, verify pass**
Run: `uv run pytest tests/calibration/test_fingerprints.py -q`
Expected: `1 passed`

**Step 5: Commit**
```bash
git add src/wheres_allie/calibration/fingerprints.py tests/calibration/test_fingerprints.py
git commit -m "feat: per-vertex RSSI fingerprints from labelled windows

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 14: `BlendedEmission` + the under-bed flip

The test house recreates the real case from 2026-09-28. Under the master bed, the master-bedroom node reads -89 dBm while the node one floor down reads -81. Physics alone puts the pet in the basement. One 30 s label at the bed, giving 30 samples and w = 0.6, flips the answer.

**Files:**
- Modify: `box/src/wheres_allie/estimator/emission.py`
- Test: `box/tests/calibration/test_fingerprints.py`

**Step 1: Write failing test**
Replace `box/tests/calibration/test_fingerprints.py` with:
```python
import itertools
import math

import numpy as np
import pytest

from wheres_allie.calibration.fingerprints import build_fingerprint, build_fingerprints
from wheres_allie.estimator.emission import BlendedEmission, PhysicsEmission
from wheres_allie.estimator.hmm import HmmFilter
from wheres_allie.estimator.window import Window
from wheres_allie.home.graph import Graph, Vertex
from wheres_allie.home.model import Floor, Home, NodePlacement

ONLINE = {"master_bedroom", "moms_room"}
UNDER_BED = {"master_bedroom": [-89.0], "moms_room": [-81.0]}  # the real 2026-09-28 readings


@pytest.fixture
def house() -> tuple[Home, Graph]:
    """Main-floor master bedroom (bed at its west end, node at its east end) over the basement
    mom's room (node under the bed; the room's centre is 7.6 m from that node)."""
    home = Home(
        floors=[
            Floor(id="b", name="Basement", elevation_m=0.0),
            Floor(id="m", name="Main", elevation_m=2.7),
        ],
        nodes=[
            NodePlacement(id="master_bedroom", floor_id="m", x=6.0, y=0.0, z_m=1.0, name="Master"),
            NodePlacement(id="moms_room", floor_id="b", x=0.0, y=0.0, z_m=1.0, name="Mom's"),
        ],
    )
    vs = {
        v.id: v
        for v in [
            Vertex("room:master", "room", "m", 5.0, 1.0, "master", "Master bedroom"),
            Vertex("lm:bed", "landmark", "m", 1.0, 0.0, "master", "Master bed"),
            Vertex("stairs:s:b", "stairs", "m", 8.0, 4.0, "master", "Stairs"),
            Vertex("room:moms", "room", "b", 5.4, 5.3, "moms", "Mom's room"),
            Vertex("stairs:s:a", "stairs", "b", 8.0, 4.0, "moms", "Stairs"),
        ]
    }
    edges = [
        (a.id, b.id, math.dist((a.x, a.y), (b.x, b.y)))
        for a, b in itertools.combinations(vs.values(), 2)
        if a.room_id == b.room_id
    ]
    return home, Graph(vs, edges + [("stairs:s:a", "stairs:s:b", 3.0)])


def _windows(rssi, n, t0=0.0, jitter=1.0, seed=0):
    rng = np.random.default_rng(seed)
    return [
        Window(
            1,
            t0 + 2 * (k + 1),
            {nd: [v[0] + rng.normal(0, jitter)] for nd, v in rssi.items()},
            set(ONLINE),
            None,
        )
        for k in range(n)
    ]


def _run(graph, emission, windows):
    f = HmmFilter(graph, emission)
    for w in windows:
        e = f.step(w)
    return e.vertex_id


def test_build_fingerprint_stats():
    ws = _windows(UNDER_BED, 10, jitter=0.0) + [Window(1, 99, {"moms_room": [-81.0]}, ONLINE, None)]
    fp = build_fingerprint("lm:bed", ws)
    assert fp.n == 21
    st = fp.nodes["master_bedroom"]
    assert (st.mean, st.std, st.heard) == (-89.0, 3.0, 10)
    assert st.heard_rate == pytest.approx(10 / 11)
    assert fp.nodes["moms_room"].heard_rate == 0.95  # 11/11 clipped


def test_under_bed_fingerprint_flips_physics(house):
    home, graph = house
    physics = PhysicsEmission(home, graph)
    live = _windows(UNDER_BED, 15, t0=1000.0, seed=1)
    assert _run(graph, physics, live) != "lm:bed"  # physics alone blames the basement

    fps = build_fingerprints({"lm:bed": _windows(UNDER_BED, 15, seed=2)})  # one 30 s label
    assert fps["lm:bed"].n == 30
    blended = BlendedEmission(physics, fps)
    assert blended.weight("lm:bed") == pytest.approx(30 / 50)
    assert _run(graph, blended, live) == "lm:bed"


def test_too_few_samples_is_physics_only(house):
    home, graph = house
    physics = PhysicsEmission(home, graph)
    blended = BlendedEmission(physics, build_fingerprints({"lm:bed": _windows(UNDER_BED, 5)}))
    assert blended.weight("lm:bed") == 0.0
    w = _windows(UNDER_BED, 1)[0]
    states = list(graph.vertices) + ["away"]
    np.testing.assert_allclose(blended.log_likelihood(w, states), physics.log_likelihood(w, states))
```

**Step 2: Run test, verify failure**
Run: `uv run pytest tests/calibration/test_fingerprints.py -q`
Expected: FAIL with `ImportError: cannot import name 'BlendedEmission'`

**Step 3: Implement**
Append to `box/src/wheres_allie/estimator/emission.py`. The import inside `__init__` avoids an import cycle, because `fingerprints` imports `rssi_logpdf` from `emission`:
```python
class BlendedEmission:
    """Per state: (1 - w) * physics + w * fingerprint, in log space, w = n / (n + 20) once the
    state's fingerprint has >= 20 samples. Nodes a fingerprint never saw use the physics term."""

    def __init__(self, physics: PhysicsEmission, fingerprints: dict):  # vertex_id -> Fingerprint
        from wheres_allie.calibration.fingerprints import blend_weight  # (import cycle)

        self.physics = physics
        self.fps = {
            vid: (fp, blend_weight(fp.n))
            for vid, fp in fingerprints.items()
            if blend_weight(fp.n) > 0 and vid in physics.vertex_row
        }

    def weight(self, vertex_id: str) -> float:
        return self.fps[vertex_id][1] if vertex_id in self.fps else 0.0

    def log_likelihood(self, w: Window, states: list[str]) -> np.ndarray:
        ph = self.physics
        terms = {node: ph.node_ll(w, node) for node in w.online_nodes}
        vll = sum(terms.values(), np.zeros(len(ph.vertex_row)))
        for vid, (fp, wt) in self.fps.items():
            r = ph.vertex_row[vid]
            learned = 0.0
            for node, t in terms.items():
                x = fp.node_ll(w, node)
                learned += t[r] if x is None else x
            vll[r] = (1 - wt) * vll[r] + wt * learned
        return assemble(vll, ph.vertex_row, away_ll(w), states)
```

**Step 4: Run test, verify pass**
Run: `uv run pytest tests/calibration tests/estimator -q`
Expected: all pass (`3 passed` in `test_fingerprints.py`)

**Step 5: Commit**
```bash
git add src/wheres_allie/estimator/emission.py tests/calibration/test_fingerprints.py
git commit -m "feat: blended fingerprint/physics emission; under-bed case now correct

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 15: Runner rebuilds the emission when labels change

**Files:**
- Modify: `box/src/wheres_allie/estimator/runner.py`
- Test: `box/tests/estimator/test_runner.py`

**Step 1: Write failing test**
Append to `box/tests/estimator/test_runner.py`:
```python
def test_new_label_swaps_in_blended_emission(two_rooms):
    from wheres_allie.calibration.labels import create_label
    from wheres_allie.estimator.emission import BlendedEmission, PhysicsEmission

    conn = _conn()
    runner = EstimatorRunner(conn)
    runner.use_model(*two_rooms)
    _at_bed(conn, 1000.0, 2)
    runner.run_until(1002.0)
    assert type(runner.emission) is PhysicsEmission
    conn.executemany(
        "INSERT INTO readings (ts, tag_id, node_id, rssi) VALUES (?, 1, ?, ?)",
        [(1010.0 + k, n, -70.0) for k in range(30) for n in ("nA", "nB")],
    )
    create_label(conn, 1, "room:A", "tap", ts_end=1040.0)
    runner.run_until(1042.0)
    assert type(runner.emission) is BlendedEmission
    assert runner.filters[1].emission is runner.emission
```

**Step 2: Run test, verify failure**
Run: `uv run pytest tests/estimator/test_runner.py -q -k label`
Expected: FAIL with `assert <class '...PhysicsEmission'> is <class '...BlendedEmission'>`

**Step 3: Implement**
Replace `box/src/wheres_allie/estimator/runner.py` with:
```python
"""Estimator loop. Each tag has a cursor (settings `estimator.last_ts.<tag_id>` = end of the last
processed window). Every pass walks 2 s windows from the cursor up to "now", so backfilled past
readings (judge-mode demo-seed) and live readings take the same path. Positions and visits are
written to the db. The async loop publishes the returned bus messages, because Bus is not
thread-safe and the work runs in asyncio.to_thread (design §4.3, conventions §7)."""

import asyncio
import logging
import math
import sqlite3
import time

from wheres_allie.bus import Bus
from wheres_allie.calibration.fingerprints import build_fingerprints
from wheres_allie.calibration.labels import labels_version, load_samples
from wheres_allie.estimator.emission import BlendedEmission, EmissionModel, PhysicsEmission
from wheres_allie.estimator.hmm import Estimate, HmmFilter
from wheres_allie.estimator.visits import VisitEvent, VisitTracker
from wheres_allie.estimator.window import WINDOW_S, load_windows
from wheres_allie.home.geometry import detect_rooms
from wheres_allie.home.graph import Graph, build_graph
from wheres_allie.home.model import Home
from wheres_allie.home.store import load_home

log = logging.getLogger(__name__)
CHUNK_WINDOWS = 1800  # max windows (1 h of data) per tag per pass, so a long backfill yields
LAG_S = 1.0  # stay this far behind the wall clock so in-flight readings land in their window


def exit_vertices(home: Home) -> set[str]:
    return {f"lm:{lm.id}" for lm in home.landmarks if lm.type == "door"}


def make_emission(conn: sqlite3.Connection, home: Home, graph: Graph) -> EmissionModel:
    physics = PhysicsEmission(home, graph)
    fps = build_fingerprints(load_samples(conn))
    return BlendedEmission(physics, fps) if fps else physics


class EstimatorRunner:
    def __init__(self, conn: sqlite3.Connection, dt: float = WINDOW_S):
        self.conn, self.dt = conn, dt
        self.version = None  # (home version, ...) the model was built from
        self.graph: Graph | None = None
        self.filters: dict[int, HmmFilter] = {}
        self.trackers: dict[int, VisitTracker] = {}
        self.open_visit: dict[int, int] = {}  # tag_id -> visits.id of the open visit

    def model_version(self) -> tuple:
        return (self.conn.execute("SELECT max(version) FROM home").fetchone()[0],)

    def use_model(self, home: Home, graph: Graph) -> None:
        self.home, self.graph = home, graph
        self.labels = labels_version(self.conn)
        self.emission = make_emission(self.conn, home, graph)
        self.filters.clear()  # past positions stay; filters restart on the new graph
        self.version = self.model_version()

    def load_model(self) -> None:
        home = load_home(self.conn)
        self.use_model(home, build_graph(home, detect_rooms(home)))

    def cursor(self, tag_id: int) -> float | None:
        row = self.conn.execute(
            "SELECT value FROM settings WHERE key = ?", (f"estimator.last_ts.{tag_id}",)
        ).fetchone()
        if row:
            return float(row[0])
        first = self.conn.execute(
            "SELECT min(ts) FROM readings WHERE tag_id = ?", (tag_id,)
        ).fetchone()[0]
        return None if first is None else math.floor(first / self.dt) * self.dt

    def run_until(self, until_ts: float) -> tuple[list[tuple[str, dict]], bool]:
        """Process each tag's windows from its cursor up to until_ts, at most CHUNK_WINDOWS per
        tag. Returns (bus messages, caught_up). Only the newest position per tag is returned
        as a message; every window is written to `positions`."""
        if self.model_version() != self.version:
            self.load_model()
        elif labels_version(self.conn) != self.labels:  # new label: same graph, new emission
            self.labels = labels_version(self.conn)
            self.emission = make_emission(self.conn, self.home, self.graph)
            for f in self.filters.values():
                f.emission = self.emission
        if not self.graph or not self.graph.vertices:
            return [], True
        msgs, caught_up = [], True
        tags = self.conn.execute(
            "SELECT t.id, p.name FROM tags t JOIN pets p ON p.id = t.pet_id"
        ).fetchall()
        for tag_id, pet in tags:
            start = self.cursor(tag_id)
            if start is None or start + self.dt > until_ts:
                continue
            end = min(until_ts, start + CHUNK_WINDOWS * self.dt)
            caught_up &= end == until_ts
            f = self.filters.get(tag_id)
            if f is None:
                f = self.filters[tag_id] = HmmFilter(
                    self.graph, self.emission, exit_vertices=exit_vertices(self.home)
                )
            tracker = self.trackers.setdefault(tag_id, VisitTracker())
            last = None
            for w in load_windows(self.conn, tag_id, start, end, self.dt):
                f.step(w)
                e = f.smoothed()[-1]  # ponytail: end of the 60 s Viterbi path; fixed-lag if jittery
                last = self._write_position(tag_id, pet, e)
                for ev in tracker.update(e, self.graph.vertices.get(e.vertex_id)):
                    msgs.append(("visit", self._write_visit(tag_id, pet, ev)))
            if last:
                msgs.append(("position", last))
                self.conn.execute(
                    "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                    (f"estimator.last_ts.{tag_id}", repr(last["ts"])),
                )
        self.conn.commit()
        return msgs, caught_up

    def _write_position(self, tag_id: int, pet: str, e: Estimate) -> dict:
        v = self.graph.vertices.get(e.vertex_id)
        row = {
            "ts": e.ts,
            "tag_id": tag_id,
            "vertex_id": e.vertex_id,
            "room_id": v.room_id if v else None,
            "floor_id": v.floor_id if v else None,
            "confidence": e.confidence,
            "moving": None if e.moving is None else int(e.moving),
        }
        self.conn.execute(
            "INSERT INTO positions (ts, tag_id, vertex_id, room_id, floor_id, confidence, moving)"
            " VALUES (:ts, :tag_id, :vertex_id, :room_id, :floor_id, :confidence, :moving)",
            row,
        )
        return {**row, "pet": pet, "x": v.x if v else None, "y": v.y if v else None}

    def _write_visit(self, tag_id: int, pet: str, ev: VisitEvent) -> dict:
        if ev.op == "close" and tag_id in self.open_visit:
            vid = self.open_visit.pop(tag_id)
            self.conn.execute('UPDATE visits SET "end" = ? WHERE id = ?', (ev.end, vid))
        else:
            vid = self.conn.execute(
                'INSERT INTO visits (tag_id, place_id, kind, start, "end") VALUES (?, ?, ?, ?, ?)',
                (tag_id, ev.place_id, ev.kind, ev.start, ev.end),
            ).lastrowid
            if ev.op == "open":
                self.open_visit[tag_id] = vid
        return {
            "id": vid,
            "op": ev.op,
            "tag_id": tag_id,
            "pet": pet,
            "place_id": ev.place_id,
            "kind": ev.kind,
            "start": ev.start,
            "end": ev.end,
        }


async def catch_up(
    conn: sqlite3.Connection, bus: Bus, until_ts: float, runner: EstimatorRunner | None = None
) -> EstimatorRunner:
    """Process every tag up to until_ts in 1 h chunks, publishing as it goes."""
    runner = runner or EstimatorRunner(conn)
    done = False
    while not done:
        msgs, done = await asyncio.to_thread(runner.run_until, until_ts)
        for topic, data in msgs:
            bus.publish(topic, data)
    return runner


async def run_estimator(conn: sqlite3.Connection, bus: Bus, dt: float = WINDOW_S) -> None:
    runner = EstimatorRunner(conn, dt)
    while True:
        try:
            await catch_up(conn, bus, time.time() - LAG_S, runner)
        except Exception:
            log.exception("estimator pass failed")
        await asyncio.sleep(dt - time.time() % dt)
```

**Step 4: Run test, verify pass**
Run: `uv run pytest tests/estimator/test_runner.py -q`
Expected: `5 passed`

**Step 5: Commit**
```bash
git add src/wheres_allie/estimator/runner.py tests/estimator/test_runner.py
git commit -m "feat: estimator picks up new calibration labels live

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 16: Eval uses bundle labels, reports physics vs blended

**Files:**
- Modify: `box/src/wheres_allie/estimator/eval.py`
- Test: `box/tests/estimator/test_eval_bundle.py`

**Step 1: Write failing test**
Append to `box/tests/estimator/test_eval_bundle.py`:
```python
def test_labels_add_physics_comparison(tmp_path):
    r = evaluate(write_bundle(tmp_path / "a.bundle", labels="1000,1030,ib,room:kitchen,walk\n"))
    assert r["fingerprinted_vertices"] == ["room:kitchen"]
    assert r["physics_room_acc"] >= 0.9
    assert r["room_acc"] >= r["physics_room_acc"]


def test_no_labels_no_physics_keys(tmp_path):
    assert "physics_room_acc" not in evaluate(write_bundle(tmp_path / "a.bundle"))
```

**Step 2: Run test, verify failure**
Run: `uv run pytest tests/estimator/test_eval_bundle.py -q -k labels`
Expected: FAIL with `KeyError: 'fingerprinted_vertices'`

**Step 3: Implement**
Replace `box/src/wheres_allie/estimator/eval.py` with the version below. Compared with Task 8, two things change: it imports `build_fingerprints`/`BlendedEmission`, and the tail of `evaluate()` plus the new `label_samples()` are added.
```python
"""`wheres-allie eval`: HMM vs nearest-node baseline on a replay bundle + ground truth."""

import csv
import io
import json
import math
import zipfile
from dataclasses import dataclass

import numpy as np

from wheres_allie.calibration.fingerprints import build_fingerprints
from wheres_allie.estimator.emission import BlendedEmission, EmissionModel, PhysicsEmission
from wheres_allie.estimator.hmm import Estimate, HmmFilter
from wheres_allie.estimator.runner import exit_vertices
from wheres_allie.estimator.visits import VisitTracker
from wheres_allie.estimator.window import Window, make_windows
from wheres_allie.home.geometry import Room, detect_rooms, room_at
from wheres_allie.home.graph import Graph, build_graph
from wheres_allie.home.model import Home


@dataclass
class Truth:
    ts_start: float
    ts_end: float
    place: str  # vertex id or room id


@dataclass
class Bundle:
    home: Home
    ids: set[str]  # the first pet's ibeacon ids (normal + motion)
    readings: list[tuple[float, str, float]]
    motion: list[tuple[float, bool]]
    labels: list[tuple[float, float, str]]  # (ts_start, ts_end, vertex_id)
    truth: list[Truth]


def _csv(z: zipfile.ZipFile, name: str) -> list[dict]:
    if name not in z.namelist():
        return []
    return list(csv.DictReader(io.StringIO(z.read(name).decode())))


def read_truth(rows: list[dict], ids: set[str]) -> list[Truth]:
    return [
        Truth(float(r["ts_start"]), float(r["ts_end"]), r["place"])
        for r in rows
        if not r.get("ibeacon_id") or r["ibeacon_id"] in ids
    ]


def load_bundle(path: str) -> Bundle:
    with zipfile.ZipFile(path) as z:
        manifest = json.loads(z.read("manifest.json"))
        pet = manifest["pets"][0]  # ponytail: first pet only; demo data has one
        ids = {pet["ibeacon_id"], pet.get("motion_ibeacon_id")} - {None, ""}
        home = Home.model_validate_json(z.read("home.json"))
        readings = sorted(
            (float(r["ts"]), r["node_id"], float(r["rssi"]))
            for r in _csv(z, "readings.csv")
            if r["ibeacon_id"] in ids
        )
        motion = sorted(
            (float(r["ts"]), r["moving"] in ("1", "true", "True"))
            for r in _csv(z, "motion.csv")
            if r["ibeacon_id"] in ids
        )
        labels = [
            (float(r["ts_start"]), float(r["ts_end"]), r["vertex_id"])
            for r in _csv(z, "labels.csv")
            if r["ibeacon_id"] in ids
        ]
        truth = read_truth(_csv(z, "ground_truth.csv"), ids)
    return Bundle(home, ids, readings, motion, labels, truth)


def nearest_node_rooms(home: Home, rooms: list[Room], windows: list[Window]) -> list[str | None]:
    """ESPresense-companion style: room of the loudest node; holds the last room when silent."""
    where = {}
    for n in home.nodes:
        r = room_at(rooms, n.floor_id, n.x, n.y)
        where[n.id] = r.id if r else None
    out, last = [], None
    for w in windows:
        if w.rssi:
            last = where.get(max(w.rssi, key=lambda n: np.mean(w.rssi[n])))
        out.append(last)
    return out


def hmm_vertices(
    graph: Graph, emission: EmissionModel, home: Home, windows: list[Window]
) -> list[str]:
    f = HmmFilter(graph, emission, exit_vertices=exit_vertices(home))
    out = []
    for w in windows:
        f.step(w)
        out.append(f.smoothed()[-1].vertex_id)  # same online output the runner writes
    return out


def _truth_at(truth: list[Truth], ts: float) -> Truth | None:
    return next((t for t in truth if t.ts_start <= ts < t.ts_end), None)


def score(
    graph: Graph, windows: list[Window], vertices: list[str | None], truth: list[Truth]
) -> dict:
    """vertices[i] is the predicted vertex id for windows[i] (room:<id> for the baseline)."""

    def room_of(place: str | None) -> str | None:
        v = graph.vertices.get(place) if place else None
        return v.room_id if v else place  # an unknown place is a room id (or away/None)

    room_hits, room_n, lm_hits, lm_n = 0, 0, 0, 0
    for w, pred in zip(windows, vertices):
        t = _truth_at(truth, w.t_end)
        if t is None:
            continue
        room_n += 1
        room_hits += room_of(pred) == room_of(t.place)
        if t.place.startswith("lm:"):
            lm_n += 1
            lm_hits += pred == t.place

    # visits (>= 30 s) that overlap ground truth but put the pet in the wrong room
    tracker, visits, open_ = VisitTracker(), [], None
    for w, pred in zip(windows, vertices):
        v = graph.vertices.get(pred) if pred else None
        for ev in tracker.update(Estimate(w.t_end, pred or "away", 1.0, None), v):
            if ev.op == "open":
                open_ = ev
            elif ev.op == "close":
                visits.append((ev.place_id, ev.start, ev.end))
                open_ = None
    if open_ and windows:
        visits.append((open_.place_id, open_.start, windows[-1].t_end))
    judged = false = 0
    for place, start, end in visits:
        overlap = [t for t in truth if t.ts_start < end and start < t.ts_end]
        if overlap:
            judged += 1
            false += all(room_of(place) != room_of(t.place) for t in overlap)
    return {
        "room_acc": room_hits / room_n if room_n else None,
        "landmark_acc": lm_hits / lm_n if lm_n else None,
        "transit_false_visit_rate": false / judged if judged else 0.0,
        "windows": room_n,
    }


def evaluate(bundle_path: str, truth_csv: str | None = None, **physics_kw) -> dict:
    """physics_kw are PhysicsEmission knobs (tx_power_dbm, floor_db, ...) for tuning."""
    b = load_bundle(bundle_path)
    truth = b.truth
    if truth_csv:
        with open(truth_csv, newline="") as fh:
            truth = read_truth(list(csv.DictReader(fh)), b.ids)
    if not b.readings or not truth:
        raise ValueError("bundle has no readings for the pet, or there is no ground truth")
    rooms = detect_rooms(b.home)
    graph = build_graph(b.home, rooms)
    t0 = math.floor(b.readings[0][0])
    windows = make_windows(
        0, b.readings, b.motion, {n.id for n in b.home.nodes}, t0, b.readings[-1][0] + 2.0
    )
    physics = PhysicsEmission(b.home, graph, **physics_kw)
    phys = score(graph, windows, hmm_vertices(graph, physics, b.home, windows), truth)
    base_rooms = nearest_node_rooms(b.home, rooms, windows)
    base = score(graph, windows, [f"room:{r}" if r else None for r in base_rooms], truth)
    out = {
        **phys,
        "baseline_room_acc": base["room_acc"],
        "baseline_transit_false_visit_rate": base["transit_false_visit_rate"],
    }
    fps = build_fingerprints(label_samples(b, windows))
    if fps:  # ponytail: labels may overlap the truth spans; hold some out if numbers look too good
        blended = BlendedEmission(physics, fps)
        out |= score(graph, windows, hmm_vertices(graph, blended, b.home, windows), truth)
        out |= {
            "physics_room_acc": phys["room_acc"],
            "physics_landmark_acc": phys["landmark_acc"],
            "physics_transit_false_visit_rate": phys["transit_false_visit_rate"],
            "fingerprinted_vertices": sorted(v for v in fps if blended.weight(v) > 0),
        }
    return out


def label_samples(b: Bundle, windows: list[Window]) -> dict[str, list[Window]]:
    """The bundle's labels -> training windows (the windows whose end falls in a label span)."""
    out: dict[str, list[Window]] = {}
    for start, end, vid in b.labels:
        out.setdefault(vid, []).extend(w for w in windows if start < w.t_end <= end)
    return out
```

**Step 4: Run test, verify pass**
Run: `uv run pytest tests/estimator -q`
Expected: all pass

**Step 5: Commit**
```bash
git add src/wheres_allie/estimator/eval.py tests/estimator/test_eval_bundle.py
git commit -m "feat: eval trains fingerprints from bundle labels and shows the gain

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 17: `/api/calibrate/label` + `/api/calibrate/stats`

**Files:**
- Create: `box/src/wheres_allie/api/routes/calibrate.py`
- Modify: `box/src/wheres_allie/api/app.py` (include the router)
- Test: `box/tests/api/test_calibrate.py`

**Step 1: Write failing test**
```python
from fastapi import FastAPI
from fastapi.testclient import TestClient

from wheres_allie import db
from wheres_allie.api.routes import calibrate
from wheres_allie.bus import Bus
from wheres_allie.home.model import Floor, Home, Landmark, RoomLabel, Wall
from wheres_allie.home.store import save_home


def _app():
    conn = db.connect(":memory:")
    db.migrate(conn)
    conn.execute("INSERT INTO pets (id, name) VALUES (1, 'Allie')")
    conn.execute("INSERT INTO tags (id, pet_id, ibeacon_id) VALUES (1, 1, 'ib')")
    conn.execute("INSERT INTO nodes (id, online) VALUES ('a', 1)")
    conn.executemany(
        "INSERT INTO readings (ts, tag_id, node_id, rssi) VALUES (?, 1, 'a', -70)",
        [(100.0 + k,) for k in range(30)],
    )
    pts = [(0, 0), (6, 0), (6, 4), (0, 4)]
    save_home(conn, Home(
        floors=[Floor(id="f", name="Main", elevation_m=0)],
        walls=[Wall(id=f"w{i}", floor_id="f", a=pts[i], b=pts[(i + 1) % 4]) for i in range(4)],
        room_labels=[RoomLabel(id="den", floor_id="f", name="Den", seed=(3, 2))],
        landmarks=[Landmark(id="bed", floor_id="f", x=1, y=1, type="bed", name="Bed")],
    ))
    app = FastAPI()
    app.include_router(calibrate.router, prefix="/api")
    app.state.conn, app.state.bus = conn, Bus()
    return app


def test_label_then_stats():
    app = _app()
    c = TestClient(app)
    r = c.post("/api/calibrate/label",
               json={"pet": "Allie", "vertex_id": "lm:bed", "ts_end": 130, "source": "walk"})
    assert r.status_code == 200, r.text
    assert r.json()["samples"] == 30 and r.json()["ts_start"] == 100
    s = c.get("/api/calibrate/stats", params={"pet": "Allie"}).json()
    assert s["vertices"] == [{"vertex_id": "lm:bed", "labels": 1, "samples": 30, "weight": 0.6}]
    assert s["eval"] is None


def test_label_publishes_on_bus():
    app = _app()
    seen = []
    app.state.bus.publish = lambda topic, data: seen.append(topic)
    TestClient(app).post("/api/calibrate/label", json={"pet": 1, "vertex_id": "lm:bed", "ts_end": 130})
    assert seen == ["label"]


def test_label_rejects_unknowns():
    c = TestClient(_app())
    assert c.post("/api/calibrate/label", json={"pet": "Rex", "vertex_id": "lm:bed"}).status_code == 404
    assert c.post("/api/calibrate/label", json={"pet": "Allie", "vertex_id": "lm:nope"}).status_code == 422
    bad = {"pet": "Allie", "vertex_id": "lm:bed", "ts_start": 200, "ts_end": 100}
    assert c.post("/api/calibrate/label", json=bad).status_code == 422
```

**Step 2: Run test, verify failure**
Run: `uv run pytest tests/api/test_calibrate.py -q`
Expected: FAIL with `ImportError: cannot import name 'calibrate'`

**Step 3: Implement**
`box/src/wheres_allie/api/routes/calibrate.py`:
```python
"""POST /api/calibrate/label, GET /api/calibrate/stats (conventions §10)."""

import asyncio
import sqlite3
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from wheres_allie.api.deps import get_bus, get_conn
from wheres_allie.bus import Bus
from wheres_allie.calibration.fingerprints import blend_weight, build_fingerprints
from wheres_allie.calibration.labels import create_label, load_samples
from wheres_allie.home.geometry import detect_rooms
from wheres_allie.home.graph import build_graph
from wheres_allie.home.store import load_home

router = APIRouter()


class LabelIn(BaseModel):
    pet: str | int  # pet name or id
    vertex_id: str
    ts_start: float | None = None
    ts_end: float | None = None
    source: Literal["walk", "tap", "voice", "import"] = "tap"


def _pet(conn: sqlite3.Connection, pet: str | int) -> tuple[int, str]:
    row = conn.execute(
        "SELECT t.id, p.name FROM tags t JOIN pets p ON p.id = t.pet_id"
        " WHERE p.name = ? OR p.id = ? ORDER BY t.id LIMIT 1",
        (str(pet), pet),
    ).fetchone()
    if row is None:
        raise HTTPException(404, f"no tagged pet {pet!r}")
    return row[0], row[1]


@router.post("/calibrate/label")
async def post_label(
    body: LabelIn, conn: sqlite3.Connection = Depends(get_conn), bus: Bus = Depends(get_bus)
) -> dict:
    tag_id, name = _pet(conn, body.pet)
    home = load_home(conn)
    if body.vertex_id not in build_graph(home, detect_rooms(home)).vertices:
        raise HTTPException(422, f"unknown vertex {body.vertex_id!r}")
    try:
        label = await asyncio.to_thread(
            create_label, conn, tag_id, body.vertex_id, body.source, body.ts_start, body.ts_end
        )
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    label["pet"] = name
    bus.publish("label", label)
    return label


@router.get("/calibrate/stats")
def get_stats(pet: str, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    tag_id, name = _pet(conn, pet)
    counts = dict(
        conn.execute(
            "SELECT vertex_id, count(*) FROM labels WHERE tag_id = ? GROUP BY vertex_id", (tag_id,)
        ).fetchall()
    )
    fps = build_fingerprints(load_samples(conn))
    vertices = [
        {
            "vertex_id": vid,
            "labels": counts.get(vid, 0),
            "samples": fp.n,
            "weight": blend_weight(fp.n),
        }
        for vid, fp in sorted(fps.items())
    ]
    # ponytail: no ground truth lives in the db; accuracy comes from `wheres-allie eval`
    return {"pet": name, "vertices": vertices, "eval": None}
```
In `api/app.py`, next to the other routers, add:
```python
from wheres_allie.api.routes import calibrate
app.include_router(calibrate.router, prefix="/api")
```

**Step 4: Run test, verify pass**
Run: `uv run pytest tests/api -q`
Expected: all pass (`3 passed` in `test_calibrate.py`)

**Step 5: Commit**
```bash
git add src/wheres_allie/api/routes/calibrate.py src/wheres_allie/api/app.py tests/api/test_calibrate.py
git commit -m "feat: calibrate API (label + stats)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 18: GUI step logic (`calibrateSteps.ts`) + vitest

This logic is pure, so it can be tested without a DOM. `GET /api/home` returns `graph.vertices` as either an object or an array, and `Object.values` handles both.

**Files:**
- Create: `box/web/src/pages/calibrateSteps.ts`
- Test: `box/web/src/pages/calibrateSteps.test.ts`

**Step 1: Write failing test**
```ts
import { describe, expect, it } from "vitest";
import { buildSteps, progress, tapLabel, walkLabel, type HomeResponseLite } from "./calibrateSteps";

const resp: HomeResponseLite = {
  home: {
    floors: [
      { id: "m", name: "Main", elevation_m: 2.7 },
      { id: "b", name: "Basement", elevation_m: 0 },
    ],
  },
  graph: {
    vertices: {
      "room:kitchen": { id: "room:kitchen", kind: "room", floor_id: "m", name: "Kitchen" },
      "lm:bowl": { id: "lm:bowl", kind: "landmark", floor_id: "m", name: "Water bowl" },
      "door:d1": { id: "door:d1", kind: "door", floor_id: "m", name: "Door" },
      "room:office": { id: "room:office", kind: "room", floor_id: "b", name: "Office" },
      "lm:bed": { id: "lm:bed", kind: "landmark", floor_id: "b", name: "Allie's bed" },
      "stairs:s:a": { id: "stairs:s:a", kind: "stairs", floor_id: "b", name: "Stairs" },
    },
  },
};

describe("buildSteps", () => {
  it("lists landmarks then rooms, basement up, skipping doors and stairs", () => {
    expect(buildSteps(resp).map((s) => s.vertexId)).toEqual([
      "lm:bed", "lm:bowl", "room:office", "room:kitchen",
    ]);
    expect(buildSteps(resp)[0]).toEqual({ vertexId: "lm:bed", name: "Allie's bed", floor: "Basement", kind: "landmark" });
  });
  it("accepts vertices as an array too", () => {
    const arr = { ...resp, graph: { vertices: Object.values(resp.graph.vertices) } };
    expect(buildSteps(arr)).toHaveLength(4);
  });
});

describe("progress", () => {
  it("runs 0 -> 1 over 30 s and clamps", () => {
    expect(progress(null, 5000)).toBe(0);
    expect(progress(1000, 16000)).toBe(0.5);
    expect(progress(1000, 99000)).toBe(1);
    expect(progress(1000, 0)).toBe(0);
  });
});

describe("labels", () => {
  const step = buildSteps(resp)[0];
  it("walk label covers the timed span in unix seconds", () => {
    expect(walkLabel("Allie", step, 1_000_000, 1_030_000)).toEqual({
      pet: "Allie", vertex_id: "lm:bed", ts_start: 1000, ts_end: 1030, source: "walk",
    });
  });
  it("tap label leaves the span to the server", () => {
    expect(tapLabel("Allie", step)).toEqual({ pet: "Allie", vertex_id: "lm:bed", source: "tap" });
  });
});
```

**Step 2: Run test, verify failure**
Run (from `box/web/`): `pnpm vitest run src/pages/calibrateSteps.test.ts`
Expected: FAIL with `Failed to resolve import "./calibrateSteps"`

**Step 3: Implement**
```ts
// Pure logic for the Calibrate page: which spots to walk, the 30 s timer, label bodies.

export const STEP_SECONDS = 30;

// Minimal structural views of GET /api/home (conventions §6, §10).
export interface VertexLite {
  id: string;
  kind: "room" | "landmark" | "door" | "stairs";
  floor_id: string;
  name: string;
}
export interface HomeResponseLite {
  home: { floors: { id: string; name: string; elevation_m: number }[] };
  graph: { vertices: Record<string, VertexLite> | VertexLite[] };
}

export interface Step {
  vertexId: string;
  name: string;
  floor: string;
  kind: "landmark" | "room";
}

/** Landmarks first (they matter most: bed, bowls), then rooms; each group by floor, then name. */
export function buildSteps(r: HomeResponseLite): Step[] {
  const floors = [...r.home.floors].sort((a, b) => a.elevation_m - b.elevation_m);
  const floorIdx = new Map(floors.map((f, i) => [f.id, i]));
  const floorName = new Map(floors.map((f) => [f.id, f.name]));
  const rank = (v: VertexLite) => (v.kind === "landmark" ? 0 : 1);
  return Object.values(r.graph.vertices)
    .filter((v) => v.kind === "landmark" || v.kind === "room")
    .sort(
      (a, b) =>
        rank(a) - rank(b) ||
        (floorIdx.get(a.floor_id) ?? 0) - (floorIdx.get(b.floor_id) ?? 0) ||
        a.name.localeCompare(b.name),
    )
    .map((v) => ({
      vertexId: v.id,
      name: v.name,
      floor: floorName.get(v.floor_id) ?? v.floor_id,
      kind: v.kind as "landmark" | "room",
    }));
}

/** 0..1 progress of a step started at startedAtMs (null = not started). */
export function progress(startedAtMs: number | null, nowMs: number): number {
  if (startedAtMs === null) return 0;
  return Math.min(1, Math.max(0, (nowMs - startedAtMs) / (STEP_SECONDS * 1000)));
}

export interface LabelBody {
  pet: string;
  vertex_id: string;
  ts_start?: number;
  ts_end?: number;
  source: "walk" | "tap";
}

/** Guided-walk label: exactly the timed span. */
export function walkLabel(pet: string, step: Step, startedAtMs: number, endMs: number): LabelBody {
  return { pet, vertex_id: step.vertexId, ts_start: startedAtMs / 1000, ts_end: endMs / 1000, source: "walk" };
}

/** "Allie is here now": the server labels the 30 s before now. */
export function tapLabel(pet: string, step: Step): LabelBody {
  return { pet, vertex_id: step.vertexId, source: "tap" };
}
```

**Step 4: Run test, verify pass**
Run (from `box/web/`): `pnpm vitest run src/pages/calibrateSteps.test.ts`
Expected: `5 passed`

**Step 5: Commit**
```bash
git add web/src/pages/calibrateSteps.ts web/src/pages/calibrateSteps.test.ts
git commit -m "feat: calibrate guided-walk step logic

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 19: `Calibrate.tsx`: guided walk + "Allie is here now"

The page has two parts:
- **Guided walk.** It lists landmarks and then rooms. The user presses "I'm there, start" and a 30 s ring counts down. At 100%, the page POSTs `{source:"walk", ts_start, ts_end}` and moves to the next step. There is also a Skip button.
- **"<Pet> is here now".** One button per spot POSTs `{source:"tap"}`. The server then labels the 30 s before now.

Sample counts come from `/api/calibrate/stats`. The page uses `fetch` directly, so the only things it relies on are `/api/home`, `/api/pets` (`[{id, name, …}]`) and `tokens.css` variables.

**Files:**
- Modify (replace plan 01's stub): `box/web/src/pages/Calibrate.tsx`
- Modify if needed: `box/web/src/App.tsx` (route `/calibrate`)

**Step 1: Write failing check**
Run (from `box/web/`): `grep -c "buildSteps" src/pages/Calibrate.tsx`
Expected: `0` (it's the stub)

**Step 2: Verify the route exists**
Run: `grep -n "Calibrate" src/App.tsx`
Expected: a `<Route path="/calibrate" …>` line. If it's missing, add `import Calibrate from "./pages/Calibrate";` and `<Route path="/calibrate" element={<Calibrate />} />` next to the other page routes, plus a "Calibrate" entry in the left rail, following plan 01's pattern.

**Step 3: Implement**
`box/web/src/pages/Calibrate.tsx`:
```tsx
import { useEffect, useState } from "react";
import {
  STEP_SECONDS, buildSteps, progress, tapLabel, walkLabel,
  type HomeResponseLite, type LabelBody, type Step,
} from "./calibrateSteps";

interface Pet { id: number; name: string }
interface VertexStat { vertex_id: string; labels: number; samples: number; weight: number }

async function json<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, init);
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json() as Promise<T>;
}

const postLabel = (b: LabelBody) =>
  json("/api/calibrate/label", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(b),
  });

function Ring({ p }: { p: number }) {
  const r = 52, c = 2 * Math.PI * r;
  return (
    <svg width="128" height="128" viewBox="0 0 128 128" role="img"
         aria-label={`${Math.round(p * 100)} percent`}>
      <circle cx="64" cy="64" r={r} fill="none" stroke="var(--line)" strokeWidth="8" />
      <circle cx="64" cy="64" r={r} fill="none" stroke="var(--accent)" strokeWidth="8"
              strokeDasharray={c} strokeDashoffset={c * (1 - p)} strokeLinecap="round"
              transform="rotate(-90 64 64)" />
      <text x="64" y="70" textAnchor="middle" fontSize="20" fill="var(--text)">
        {Math.ceil(STEP_SECONDS * (1 - p))}s
      </text>
    </svg>
  );
}

export default function Calibrate() {
  const [steps, setSteps] = useState<Step[]>([]);
  const [pets, setPets] = useState<Pet[]>([]);
  const [pet, setPet] = useState("");
  const [stats, setStats] = useState<Record<string, VertexStat>>({});
  const [i, setI] = useState(0);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [now, setNow] = useState(Date.now());
  const [msg, setMsg] = useState("");

  useEffect(() => {
    json<HomeResponseLite>("/api/home").then((r) => setSteps(buildSteps(r))).catch((e) => setMsg(String(e)));
    json<Pet[]>("/api/pets").then((p) => { setPets(p); setPet(p[0]?.name ?? ""); }).catch((e) => setMsg(String(e)));
  }, []);

  const loadStats = () => {
    if (!pet) return;
    json<{ vertices: VertexStat[] }>(`/api/calibrate/stats?pet=${encodeURIComponent(pet)}`)
      .then((s) => setStats(Object.fromEntries(s.vertices.map((v) => [v.vertex_id, v]))))
      .catch(() => {});
  };
  useEffect(loadStats, [pet]);

  useEffect(() => {
    if (startedAt === null) return;
    const t = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(t);
  }, [startedAt]);

  const step = steps[i];
  const p = progress(startedAt, now);
  useEffect(() => {
    if (startedAt === null || p < 1 || !step) return;
    const end = Date.now();
    setStartedAt(null);
    postLabel(walkLabel(pet, step, startedAt, end))
      .then(() => { setMsg(`Saved ${step.name}.`); setI((k) => k + 1); loadStats(); })
      .catch((e) => setMsg(`Could not save ${step.name}: ${e}`));
  }, [p]);

  const tap = (s: Step) =>
    postLabel(tapLabel(pet, s))
      .then(() => { setMsg(`Marked ${pet} at ${s.name}.`); loadStats(); })
      .catch((e) => setMsg(`Could not save: ${e}`));

  const done = (s: Step) => (stats[s.vertexId]?.weight ?? 0) > 0;

  return (
    <div className="page calibrate" style={{ display: "grid", gap: 24, padding: 24, maxWidth: 960 }}>
      <header style={{ display: "flex", gap: 12, alignItems: "center" }}>
        <h1 style={{ margin: 0, fontSize: 20 }}>Calibrate</h1>
        <select value={pet} onChange={(e) => setPet(e.target.value)} aria-label="Pet">
          {pets.map((x) => <option key={x.id} value={x.name}>{x.name}</option>)}
        </select>
        <span style={{ color: "var(--muted)" }} role="status">{msg}</span>
      </header>

      <section style={{ background: "var(--panel)", border: "1px solid var(--line)", borderRadius: "var(--radius)", padding: 16 }}>
        <h2 style={{ marginTop: 0, fontSize: 16 }}>Guided walk</h2>
        {step ? (
          <div style={{ display: "flex", gap: 24, alignItems: "center" }}>
            <Ring p={p} />
            <div>
              <p>Step {i + 1} of {steps.length}: take the tag to <b>{step.name}</b> ({step.floor}),
                 put it where {pet || "your pet"} usually is, and wait {STEP_SECONDS} s.</p>
              <button disabled={!pet || startedAt !== null} onClick={() => { setNow(Date.now()); setStartedAt(Date.now()); }}>
                {startedAt === null ? "I'm there, start" : "Hold still…"}
              </button>{" "}
              <button onClick={() => { setStartedAt(null); setI((k) => k + 1); }}>Skip</button>
            </div>
          </div>
        ) : (
          <p>{steps.length ? "Walk complete." : "Draw rooms and landmarks in the editor first."}{" "}
            {steps.length > 0 && <button onClick={() => setI(0)}>Walk again</button>}</p>
        )}
      </section>

      <section style={{ background: "var(--panel)", border: "1px solid var(--line)", borderRadius: "var(--radius)", padding: 16 }}>
        <h2 style={{ marginTop: 0, fontSize: 16 }}>{pet || "Pet"} is here now</h2>
        <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "grid", gap: 6 }}>
          {steps.map((s) => (
            <li key={s.vertexId} style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <button disabled={!pet} onClick={() => tap(s)}>{s.name}</button>
              <span style={{ color: "var(--muted)" }}>{s.floor}</span>
              <span style={{ color: done(s) ? "var(--accent-2)" : "var(--muted)" }}>
                {stats[s.vertexId] ? `${stats[s.vertexId].samples} samples` : "not calibrated"}
              </span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
```

**Step 4: Verify**
Run (from `box/web/`): `pnpm test && pnpm build`
Expected: vitest passes and `tsc` + vite build succeed with no type errors. Manual check: run `uv run wheres-allie serve` (from `box/`) with a home that has landmarks, open `/calibrate`, tap "Allie's bed", and confirm the status line reads "Marked Allie at …" and the samples column updates.

**Step 5: Commit**
```bash
git add web/src/pages/Calibrate.tsx web/src/App.tsx
git commit -m "feat: Calibrate page (guided walk + here-now taps)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 20: Real-data calibration gain

**Step 1:** Label spots on the real data. Either run the guided walk on the live box (bed, water bowl, food bowl, couch, each room), or add the owner's known spans to the bundle's `labels.csv`. Only use spans the owner confirms. A label that overlaps a truth span inflates the score (see the `ponytail:` note in `evaluate`), so prefer label spans from a different time than the truth spans.
**Step 2:** Export a bundle that includes the labels (`POST /api/data/export` or plan 01's tool), then run:
`uv run wheres-allie eval --bundle <bundle> --truth tests/fixtures/allie-truth.csv`
Expected: the output includes `physics_room_acc` and `fingerprinted_vertices`, and `room_acc >= physics_room_acc`. Success criterion 1 is `room_acc > baseline_room_acc` with the master-bed span correct (`landmark_acc` > 0.5).
**Step 3:** If criterion 1 isn't met, record the numbers and report back to the lead. Don't loosen the tests to hide it.
**Step 4:** Commit any new truth or label fixtures, with the eval JSON in the commit body:
```bash
git add tests/fixtures
git commit -m "test: calibrated eval on Allie's recorded data

<paste eval JSON>

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 21: Phase 4 exit

**Step 1:** Run `uv run pytest -q && uv run ruff check . && uv run ruff format --check .` from `box/`, then `pnpm test && pnpm build` from `box/web/`. Expected: all green.
**Step 2:** Update the Status table (Tasks 12–21 → done / yes), then commit and push:
```bash
git add docs/plans/2026-09-28-wheres-allie-plan-03-estimator.md
git commit -m "docs: phase 4 calibration complete

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push origin main
```

## Phase exit criteria

**Phase 3**
- `uv run pytest -q` is green. That includes: convergence on synthetic homes, floor bleed where the HMM is right and nearest-node is wrong, a still tag holding its state, silence turning into `away`, Viterbi removing a blip, a 14 s loft pass recorded as a transit and not a visit, and the end-to-end bundle eval.
- A running box writes one `positions` row per tag every 2 s and emits `position` and `visit` on the bus. Readings backfilled with past timestamps are processed from each tag's persisted cursor (unit test: 3 h of history gives 5400 positions and one visit, and a restart writes no duplicates).
- `wheres-allie eval` runs on the real bundle and prints room, landmark and false-visit numbers for the HMM and the baseline. The numbers are recorded in the Task 10 commit.

**Phase 4**
- Labels created from the GUI, the API, or bundle `labels.csv` feed fingerprints. The snapshots survive readings retention.
- The unit test shows the under-bed readings (-89 / -81) flipping from the basement (physics) to `lm:bed` (blended) after one 30 s label.
- `wheres-allie eval` on a labelled bundle reports `physics_*` next to the blended numbers. The Calibrate page walks the steps and posts labels.
- Success criterion 1 (beat the baseline, under-bed correct) is either met on real data or reported to the lead with numbers.
