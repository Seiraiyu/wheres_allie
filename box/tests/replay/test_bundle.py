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
