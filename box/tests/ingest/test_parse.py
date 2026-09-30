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
