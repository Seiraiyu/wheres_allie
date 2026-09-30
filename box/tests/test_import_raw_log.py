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
