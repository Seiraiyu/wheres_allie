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
