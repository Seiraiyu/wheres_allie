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

## B. BC021 motion trigger (date: )

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
