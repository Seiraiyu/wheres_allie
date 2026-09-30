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
