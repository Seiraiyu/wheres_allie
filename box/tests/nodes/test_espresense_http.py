from urllib.parse import parse_qs

import httpx
import pytest
import respx

from wheres_allie.nodes.espresense_http import MASK, build_form, push_settings, restart

IP = "192.168.5.232"
URL = f"http://{IP}/wifi/main"
CURRENT = {"room": "office", "wifi-ssid": "HomeNet", "wifi-password": MASK,
           "wifi_timeout": 30, "mqtt_host": "192.168.5.132", "mqtt_port": 1883,
           "mqtt_user": MASK, "mqtt_pass": MASK, "discovery": True, "pub_tele": True,
           "pub_devices": True, "auto_update": True, "prerelease": False, "arduino_ota": True}
NEW = {"mqtt_host": "192.168.5.254", "mqtt_user": "wheres_allie", "mqtt_pass": "pw",
       "auto_update": False}


def test_build_form_resends_everything():
    form = build_form(CURRENT, NEW)
    assert form["wifi-password"] == MASK  # unchanged on the node
    assert form["mqtt_host"] == "192.168.5.254" and form["mqtt_port"] == "1883"
    assert form["discovery"] == "1"
    assert "auto_update" not in form and "prerelease" not in form  # unchecked = absent


@respx.mock
async def test_push_settings_posts_full_form_and_verifies():
    after = CURRENT | {"mqtt_host": "192.168.5.254", "auto_update": False}
    respx.get(URL).mock(side_effect=[httpx.Response(200, json={"values": CURRENT, "defaults": {}}),
                                     httpx.Response(200, json={"values": after, "defaults": {}})])
    post = respx.post(URL).mock(return_value=httpx.Response(200))
    async with httpx.AsyncClient() as client:
        changes = await push_settings(client, IP, NEW, expect_room="office")
    sent = {k: v[0] for k, v in parse_qs(post.calls.last.request.content.decode()).items()}
    assert sent == build_form(CURRENT, NEW)
    assert changes["mqtt_pass"] == (MASK, MASK)  # never echo secrets
    assert changes["mqtt_host"] == ("192.168.5.132", "192.168.5.254")


@respx.mock
async def test_dry_run_does_not_post():
    respx.get(URL).mock(return_value=httpx.Response(200, json={"values": CURRENT}))
    post = respx.post(URL)
    async with httpx.AsyncClient() as client:
        changes = await push_settings(client, IP, NEW, dry_run=True)
    assert not post.called and "mqtt_host" in changes


@respx.mock
async def test_wrong_room_or_missing_wifi_aborts():
    respx.get(URL).mock(return_value=httpx.Response(200, json={"values": CURRENT}))
    async with httpx.AsyncClient() as client:
        with pytest.raises(ValueError, match="expected 'loft'"):
            await push_settings(client, IP, NEW, expect_room="loft")
    respx.get(URL).mock(return_value=httpx.Response(200, json={"values": {"room": "office"}}))
    async with httpx.AsyncClient() as client:
        with pytest.raises(ValueError, match="wifi-ssid"):
            await push_settings(client, IP, NEW)


@respx.mock
async def test_unexpected_change_after_save_raises():
    broken = CURRENT | {"wifi_timeout": 0}
    respx.get(URL).mock(side_effect=[httpx.Response(200, json={"values": CURRENT}),
                                     httpx.Response(200, json={"values": broken})])
    respx.post(URL).mock(return_value=httpx.Response(200))
    async with httpx.AsyncClient() as client:
        with pytest.raises(RuntimeError, match="wifi_timeout"):
            await push_settings(client, IP, NEW)


@respx.mock
async def test_restart_tolerates_dropped_connection():
    respx.post(f"http://{IP}/restart").mock(side_effect=httpx.ReadError("reset"))
    async with httpx.AsyncClient() as client:
        await restart(client, IP)
