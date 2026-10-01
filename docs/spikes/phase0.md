# Phase 0 spike results

## A. Alexa+ MCP Toolkit hello-world (date: 2026-10-01, in progress)
| Check | Result | Notes |
|---|---|---|
| Local tool call | pass | 200 in 8 ms, mcp 2.2 |
| CLI install + configure | blocked 2026-10-01 | `@alexa-ai/cli` is not on public npm (404); it installs from Amazon's private CodeArtifact registry. IAM user + policy done, but AssumeRole on `AddOn3PDeveloperToolsRead` is denied: AWS account not allowlisted by Amazon |
| Tunnel round-trip time | 132–143 ms warm, ~550 ms cold | limit 500 ms. Cold = new TLS connection per call (~390 ms handshake); warm = connection reused. From WSL via Cloudflare lax07 |
| Deploy | | |
| Web simulator calls tool | | phrases that worked: |
| Real device speaks answer | | device model: |
| Account linking = OAuth 2.1 + PKCE + resource | | |
| 401 without WWW-Authenticate | | |
| MCP Apps: devices, mime type, _meta key | | docs: MCP spec 2025-11-25 and the MCP Apps extension are supported |
| Other limits (timeouts, payload size) | | docs: round trip under 500 ms; addon.json needs 6 icon sizes (72, 64, 88, 126, 180, 241 px) and a 600×900 carousel image; `examplePhrases` needs 3–4 items |

**Finding (2026-10-01):** real Alexa+ is not reachable for this hackathon. The Alexa+ docs home says the MCP Toolkit is "available to select partners only", the add-ons console shows "Coming Soon", and the hackathon resources and rules give no access path. The track requirement is a self-hosted MCP server (spec 2025-11-25+, Streamable HTTP) or an Agent Skill; a simulated Alexa+ experience in a web app is the offered way to demo it. No device, simulator or account linking is required.

**Decision:** pending owner. Affects design success criterion 2 (real Alexa+ device through the relay) and plan 06 (LWA account linking, Alexa add-on registration, tasks 15 and 18-20).

## B. BC021 motion trigger (date: 2026-10-01)

Done on a new spare tag (BC021 Pro, `BCPro_220767`, MAC `dd88000035fd`), not Allie's. Watched on the HA broker through the `office` (192.168.5.233) and `loft` nodes, ESPresense v4.0.6.

Tag settings (KBeaconPro app; the BC021 Pro, MAC `DD88…`, does not use the "KBeacon" app):
- Slot 0: iBeacon, UUID `426c7565-4368-6172-6d42-6561636f6e73`, major 3838, minor 4951 (changed from the factory 4949, which is the same as Allie's), interval 1022.5 ms, always on.
- Slot 1: iBeacon, same UUID, major 3838, minor 4952, Trigger Only Adv = Yes.
- Trigger: Motion, action Advertise, Advertisement Change = No, Trigger Adv Slot 1, Trigger Adv Time 10 s, Trigger Adv Interval 400 ms then 100 ms. Sensitivity not recorded.

| Check | Result |
|---|---|
| Tag switches on the motion id when moved, off when still (KBeaconPro scan screen) | pass |
| (a) motion-id messages from a node within 5 s of shaking | **fail** |
| (b) motion-id messages stop within 20 s of stillness | **fail** |
| (c) no motion-id messages while still | **fail** |

Why it fails: an ESPresense node reports one id per hardware address, the first one it hears, and keeps it until it forgets the device.
- With the trigger at 400 ms (about 25 motion broadcasts per 10 s window), the nodes reported only `…-4951` through repeated shaking.
- After the tag was unheard for 3 minutes and reappeared while moving, both nodes reported only `…-4952`, and kept doing so for minutes while the tag sat still and the app showed 4951.
- Same cause: after the minor was changed from 4949 to 4951, the node reported 4949 for 7 minutes; restarting the node fixed it.

So the id a node reports says nothing about motion, and it can differ between nodes.

What does track motion: the `int` field in each device message (the node's measured interval between broadcasts from that MAC), with the trigger slot at 100 ms. On `office` at about -75 dBm:

| State | `int` |
|---|---|
| Still, before | about 1650 ms |
| Moving | 50–265 ms, within about 1 s of the first broadcast |
| Still, after | climbs slowly: 304 ms at +5 s, 624 at +60 s, 869 at +130 s, 1022 at +180 s |

On `loft` at about -89 dBm: 457–971 ms moving, 1400–2500 ms still. At 400 ms the drop was too small to use (about 2000 to 1930 ms at -90 dBm).

Not measured: exact onset and release delays against timed shakes, battery cost of 100 ms bursts, behaviour on a collar.

Root cause, from the ESPresense v4.0.6 source (`src/BleFingerprint.cpp`, `BleFingerprint::setId`):

```cpp
if (idType > 0 && newIdType <= idType) return false;
```

A device that already has an iBeacon id rejects any later iBeacon id, because it is the same id type. It is only re-identified after `forget_ms` (default 150 s) without being heard, or a node restart.

A 3-line change that lets one iBeacon id replace another on the same device is in `spikes/espresense/ibeacon-id-change.patch` (applies to tag v4.0.6). With it, a moving tag should be reported under the motion id and a still one under the normal id, which is the behaviour plan 01's ingest already implements. **Not built or tested yet**: a build was started but not flashed. Open question for the test: while both slots broadcast, the id may flip between messages.

**Owner's call (2026-10-01):** motion is a stretch goal. It could be very useful, but nothing else waits on it.

**Decision (proposed, owner to confirm):** fail as designed on stock ESPresense; two routes to a pass, both stretch.
- Either route: register both ids for a tag (`ibeacon_id` and `motion_ibeacon_id`); on stock firmware readings arrive under either. Unchanged from conventions §5.
- Route 1, forked firmware: run ESPresense with the patch above. No ingest change. Costs: we own a firmware build, auto-update must stay off, the flasher (plan 07) ships our build, and design non-goal "ESPresense firmware v4.0.6 is used unmodified" changes. Counts for the Open Source mini-challenge as a fork or upstream PR. Test on the spare board first.
- Route 2, stock firmware: replace plan 01's motion rule (Interface additions 7, "a motion-id message means moving") with one based on `int`: a sharp drop means moving, and still is declared when `int` has risen again. Ingest already parses the payload, so this is a change to `Ingestor.handle` and its tests (plan 01 tasks 10 and 11, already complete).
- Until either route is done: register tags with `motion_ibeacon_id` NULL and use the estimator's movement-variance fallback (design §4.1), as plan 01 Task 2 step 8 says for a fail.
- Every new BC021 ships as 3838-4949. Setup must give each tag its own minor, and a node must be restarted (or the tag kept away for about 3 minutes) before it reports a changed id.

Also seen: during this test no node reported Allie's own tag at all (the only `…-4949` messages came from the new tag before its minor was changed), though she was upstairs. Not investigated.

## C. esptool-js browser flash (date: 2026-10-01)

Done on a new spare board instead of `loft`, so no node was erased or re-provisioned (plan steps 1's backup and 7 skipped).

- Board: ESP32-D0WD-V3 rev 3, 40 MHz crystal, flash ID `1640a1` (4 MB), CP210x USB serial (VID 0x10c4 / PID 0xea60), MAC `ec:c9:ff:fe:dc:00`. Board model not yet confirmed as the AITRIP D1 mini.
- Browser: Chrome 154.0.8037.59 on Windows 11 25H2, page served from WSL at `http://localhost:8000`.
- esptool-js 0.7.0, 460800 baud, full erase, ESPresense v4.0.6.

| Run | Bootloader | esptool-js header handling | (a) `DONE in N s` | (b) boots, AP up |
|---|---|---|---|---|
| 1 | pre-patched dout/20m, `flashMode: keep` | `Not changing the image` | 28 s | yes |
| 2 | pre-patched dout/20m, `flashMode: keep` | `Not changing the image` | 47 s | yes |
| 3 | stock, `flashMode: dout`, `flashFreq: 20m` | `Flash params set to 322` | 28 s | yes |

- (a) pass, (b) pass, (c) pass (run 2 repeats run 1).
- Boot was checked on the serial console after every run: ROM prints `mode:DOUT, clock div:4`, no reset loop, then `Starting access point for configuration portal`, `SSID: 'espresense-00dcfe'`, `IP: 192.168.4.1`. A phone also saw the AP after run 1.
- Flash time is dominated by the 1.3 MB app image: 23 s in runs 1 and 3, 42 s in run 2. Cause of the slow run unknown.
- **Stock bootloader result:** esptool-js rewrites the header to DOUT / 20 MHz itself and the board boots, so the pre-patched bootloader is optional on this board.
- Not tested: whether this board boot-loops at the default DIO/40 MHz, so the runs show the dout/20m paths work, not that the patch is required here.

**Decision:** pass. Plan 07 phase 9 goes ahead as designed. Plan 07 may drop the pre-patched bootloader and pass `flashMode: "dout"`, `flashFreq: "20m"` to esptool-js instead; confirm on a second board type first.
