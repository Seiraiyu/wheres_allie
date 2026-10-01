# Phase 0 spike results

## A. Alexa+ MCP Toolkit hello-world (date: )

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
