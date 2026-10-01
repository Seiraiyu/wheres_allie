# Friction log

Raw notes as we hit them. Curate before submission (Devpost bonus up to 10%).

## 2026-09-27: ESPresense PoC
- Web flasher (espresense.com/firmware) left the factory AT bootloader and partition table in place, and ota_0 failed its checksum. The board wouldn't boot until the flash was fully erased first.
- ESPresense ships with MQTT host `mqtt.z13.org` as a placeholder default. It's easy to miss, and the node just loops on "Reconnecting to MQTT...".
- Mosquitto 2.x listens on localhost only by default, so LAN nodes can't connect without a `listener 1883 0.0.0.0` config.

## 2026-09-27: HAOS on Proxmox
- The community-scripts haos-vm helper is interactive, which is awkward to automate; we imported the qcow2 image by hand.
- In HA 2026.9, a fresh install serves on :80, and :8123 only returns a 307 redirect. API clients that don't follow redirects must use http://<ip>/api/.
- The serial console root login drops into a Linux shell, not the `ha >` CLI, so every command needs the `ha` prefix.

## 2026-09-28: Mosquitto + companion apps
- In ESPresense v4.0.6 the MQTT client ID comes from the room name (`espresense-office`), not the MAC suffix. HA's device ID still uses the MAC suffix (`espresense_e0b6fe`).
- Saving the ESPresense settings page overwrites every field: a field left out is blanked, and any checkbox included counts as on. Saving does not reboot the node; restarting is a separate step.
- ESPresense-companion's default config is a whole example house with 10 nodes. Our "office" node matched it only by coincidence, and the example logs warnings until you replace the floorplan.
- The companion starts tracking random BLE devices by default (e.g. a Wahoo KICKR) and creates device_trackers for them.
- The companion example config anchors GPS at the White House (38.897957, -77.036560), so its map places your home there until you edit `gps:`.
- A fresh HA install defaults its home location to Amsterdam unless you set it during onboarding.
- The companion has no visual floorplan editor. You edit YAML by hand, with Ctrl-C on the map to copy coordinates.
- **Companion bug (v2.2.2):** its HA discovery sets `availability_topic: espresense/companion/status`, but the companion never publishes there. The device_tracker stays `unavailable` forever and History is blank. Workaround: `mosquitto_pub -r -t espresense/companion/status -m online`. Candidate for an upstream issue or PR.
- The walk test showed the companion ignores nodes missing from its config: the beacon in `master_bedroom` was reported as `not_home`.
- Cloning a working node with esptool (read-flash of the whole chip, settings region blanked, write-flash at 0x0) gave a "Hash of data verified" write, yet 3 of 3 boards then boot-looped in ROM (RTCWDT_RTC_RESET, garbled bootloader segment `load:0xff001cff,len:267327`). The same boards work when flashed from the browser. Root cause: these AITRIP boards can't reliably read their flash memory at boot at the default DIO/40 MHz. **Fix:** write with `--flash-mode dout --flash-freq 20m`, which rewrites the bootloader header, and the board then boots. The ESPresense web installer has no option for this.

## Home Assistant MCP / Alexa+
- The HA MCP Server only supports resources with the Assist API and has no MCP Apps support (docs, 2026-09).

## 2026-10-01: esptool-js flash spike
- esptool-js 0.7.0 patches the bootloader header itself when given `flashMode: "dout"`, `flashFreq: "20m"` (`Flash params set to 322`), and the board boots. A pre-patched bootloader isn't needed, which the ESPresense web installer could also use.
- After a full erase the node joins nothing: it only shows up as its own `espresense-<mac>` AP, not in the router's client list. A phone took a minute or two to list the AP; the serial console (`SSID: 'espresense-00dcfe'`) was the quicker check.
- The same flash took 28 s twice and 47 s once, with no error either way.

## 2026-10-01: Alexa+ MCP Toolkit spike
- The Alexa AI CLI is not on public npm: `npm install -g @alexa-ai/cli` returns 404. It lives in a private AWS CodeArtifact registry, so installing it first needs an IAM user, an assumed role in Amazon's account (`AddOn3PDeveloperToolsRead`), two AWS profiles and `aws codeartifact login` (token lasts 12 h). The quickstart and CLI reference don't mention or link this; it is only on the "Set Up Your Development Environment" page.
- cloudflared under Docker Desktop on WSL2: `--network host` is the Docker VM's network, so `--url http://localhost:8765` gets "connection refused" and every call returns 502. `--url http://host.docker.internal:8765` works.
- The 500 ms latency limit is tight if Alexa opens a new connection per call: through a trycloudflare tunnel a cold call took ~550 ms (390 ms of it TLS setup) against ~135 ms on a reused connection.
- addon.json needs far more media than "an icon": six icon sizes plus a 600×900 carousel image, and 3–4 example phrases.
- **Access is gated (2026-10-01).** With the IAM user and the documented inline policy in place, `sts:AssumeRole` on `arn:aws:iam::372468808636:role/AddOn3PDeveloperToolsRead` returns AccessDenied. The role only trusts AWS accounts Amazon has allowlisted ("the AWS account that you provided to the Alexa Solutions Architect"), and the docs don't say how to get an account added. The error is identical to a missing policy, so it looks like a setup mistake.
- **Add-ons console shows only "Coming Soon" (2026-10-01).** With a registered developer account, the dashboard's "Alexa+ Developer Console" link opens `developer.amazon.com/alexa/console/ask/addons`, which renders a blank page reading "Coming Soon": no explanation, no access-request link. The developer registration link (`/settings/console/registration?return_to=/settings/console/home`) also returned a 404.
- **The gating is stated in one place only.** The docs home page (`/docs/alexaplus/add-ons/home`, last updated 2026-07-10) opens with "At this time, Category SDK and MCP Toolkit are available to select partners only." The quickstart, the setup page and the CLI reference don't repeat it and none links to a way to apply, so a developer finds out by hitting AccessDenied and "Coming Soon".
- **The hackathon's Alexa+ track gives no Alexa+ access.** The landing page says Alexa+ is "open to outside developers", but the resources page links only the generic MCP spec and MCP Apps docs and says to "simulate an Alexa+ experience ... via a web app". Nothing says up front that the real toolkit, simulator and devices are out of reach, so we spent a spike finding out.
