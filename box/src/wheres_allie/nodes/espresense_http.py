"""Push settings to ESPresense v4.0.6 nodes over HTTP (HeadlessWiFiSettings v1.1.4).

GET /wifi/main returns {"values": {...}, "defaults": {...}}; passwords come back as MASK.
POST /wifi/main (form-encoded) overwrites EVERY field of the endpoint: a missing field is
blanked, a present checkbox is on. So we always resend the full current values. Sending MASK
for a password leaves it unchanged. Saving does not reboot; POST /restart does.
"""

import httpx

MASK = "***###***"
SECRET_KEYS = {"wifi-password", "mqtt_user", "mqtt_pass"}


async def get_main(client: httpx.AsyncClient, ip: str) -> dict:
    r = await client.get(f"http://{ip}/wifi/main", timeout=10)
    r.raise_for_status()
    return r.json()["values"]


def build_form(values: dict, overrides: dict) -> dict[str, str]:
    form = {}
    for k, v in (values | overrides).items():
        if v is None or v is False:
            continue  # absent field = blank / unchecked
        form[k] = "1" if v is True else str(v)
    return form


async def push_settings(client: httpx.AsyncClient, ip: str, overrides: dict,
                        expect_room: str | None = None, dry_run: bool = False) -> dict:
    """Merge overrides into the node's current settings and save. Returns {key: (old, new)}."""
    values = await get_main(client, ip)
    if expect_room is not None and values.get("room") != expect_room:
        raise ValueError(f"{ip} is room {values.get('room')!r}, expected {expect_room!r}")
    if not values.get("wifi-ssid"):
        raise ValueError(f"{ip}: no wifi-ssid in current settings; refusing to overwrite")
    changes = {k: (values.get(k), MASK if k in SECRET_KEYS else v)
               for k, v in overrides.items() if values.get(k) != v}
    if dry_run:
        return changes
    r = await client.post(f"http://{ip}/wifi/main", data=build_form(values, overrides), timeout=10)
    r.raise_for_status()
    after = await get_main(client, ip)
    lost = sorted(k for k in values if k not in overrides and after.get(k) != values[k])
    if lost:
        raise RuntimeError(f"{ip}: fields changed unexpectedly after save: {lost}")
    return changes


async def restart(client: httpx.AsyncClient, ip: str) -> None:
    try:
        await client.post(f"http://{ip}/restart", timeout=5)
    except httpx.TransportError:
        pass  # the node may drop the connection while rebooting
