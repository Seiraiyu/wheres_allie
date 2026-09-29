# 001 — Standalone app on ESPresense firmware, not Home Assistant + ESPresense-companion

**Date:** 2026-09-28 · **Status:** decided

## Decision
Keep the **ESPresense firmware** on the room nodes. Replace **Home Assistant + ESPresense-companion** with our own standalone server: MQTT broker, room/landmark logic, event log, floorplan editor and MCP server, shipped as one `docker compose`. Home Assistant can stay an optional integration later (for example, one MQTT discovery message) and is not a dependency.

## What we tried (2026-09-27/28, real hardware)
HAOS 18.3 in a Proxmox VM, with the Mosquitto and ESPresense-companion 2.2.2 apps, 5 ESP32 nodes across 3 floors, and one BLE tag on a dog (Allie).

## Why not HA + companion
- **Setup is an enthusiast project.** It needed a dedicated VM or box, a static IP, two apps, a user for MQTT, and a floorplan hand-written in YAML through a file-browser app. Every layer came with a wrong default: HA's home location set to Amsterdam, the companion's GPS anchored at the White House, and an example 10-node house as its config.
- **Things broke silently.** A companion bug (its availability topic was never published) left Allie's tracker "unavailable" and HA History blank, with no error anywhere.
- **The data model doesn't fit pets.** Positions are room-level only, the raw per-node readings are thrown away, and history is a stream of state changes that is thinned out after 10 days. A dog under the master bed was placed in the basement room below, and there's no way to teach it "this signal pattern means her bed".
- **Extending it is the wrong experience.** A custom HA integration plus a forked MCP server could expose our tools, but the user would still be setting up and running Home Assistant. Our target user wants to know where their pet is, not to run a home-automation platform.

## Why keep the ESPresense firmware
Once flashed, it's solid: BLE scanning, distance estimates, per-node calibration, MQTT output and Wi-Fi setup over USB (Improv). Nodes stayed online and reported consistently across 3 floors.

(Flashing is its weak spot: the web installer is unreliable on cheap boards; we flash with esptool using `--flash-mode dout --flash-freq 20m`. See `docs/friction-log.md`.)

## What we gain
- We own the raw readings, which enables **learned spots** (RSSI fingerprints such as "under the master bed") and transit-aware room logic (a 14 s pass by the stairs node is transit, not a visit).
- We own the MCP server, with our own auth and MCP Apps (a floorplan view on Echo Show), and no HA OAuth dependency.
- The experience is one product: flash the nodes, `docker compose up`, place nodes and landmarks on a floorplan, ask Alexa.

## What we give up
HA's free history, dashboards and automations, plus reach into the HA community. The first is small, since we need our own event log anyway. For the rest, an optional HA bridge can come later.

## Still worth contributing upstream
The companion availability-topic bug fix is a small, clean PR, and it qualifies for the Open Source mini-challenge regardless of this decision.
