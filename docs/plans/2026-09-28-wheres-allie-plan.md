# wheres_allie Implementation Plan (index)

**Goal:** Build the standalone pet-presence box, GUI, estimator, MCP server and AWS relay described in the approved design, and submit it by 2026-10-23.
**Architecture:** A docker compose deployment of mosquitto plus the `wheres_allie` FastAPI box (ingest → HMM estimator on a walkable graph → brain → MCP server + React GUI), and an outbound WebSocket to an AWS Fargate relay that Alexa+ calls through Login with Amazon account linking. A replay bundle of real recorded data serves as the judge mode.
**Tech Stack:** Python 3.12 (FastAPI, mcp 2.2 SDK, aiomqtt, numpy, shapely, SQLite), React 18 + TypeScript (Vite 8, vitest 5, Playwright), esptool-js, AWS CDK (Python), ECS Fargate, DynamoDB, GitHub Actions and Pages.

**Status:** approved 2026-09-29

**Design:** `2026-09-28-wheres-allie-design.md` · **Contract:** `2026-09-28-wheres-allie-conventions.md`. Every plan follows the contract, and cross-plan details are resolved in each plan's "Interface additions" section.

Each plan was written by a parallel agent. Its code was extracted and run in a scratch environment against stand-ins for earlier plans. Some parts are not yet verified: the Docker image builds, `cdk synth` and deploy (no daemon or credentials were available), and anything that needs hardware or Alexa.

| Task | Description | Status | Tested | Pushed |
|------|-------------|--------|--------|--------|
| 1 | Plan 01: foundation (phase 0 spikes + phase 1 box skeleton): 32 tasks | pending | no | no |
| 2 | Plan 02: home model + plan editor (phase 2, timeboxed 5 days): 16 tasks | pending | no | no |
| 3 | Plan 03: estimator + eval + calibration (phases 3–4): 21 tasks | pending | no | no |
| 4 | Plan 04: live + history GUI + MCP App (phases 5, 8): 23 tasks | pending | no | no |
| 5 | Plan 05: brain + MCP tools (phase 6): 14 tasks | pending | no | no |
| 6 | Plan 06: AWS relay + account linking + box link (phase 7): 22 tasks | pending | no | no |
| 7 | Plan 07: node flasher + judge mode + submission + stretch (phases 9–11): 28 tasks | pending | no | no |

**Execution order:** 01 → 02 → 03 → (04, 05) → 06 → 07. Plan 05 Task 6 needs plan 04 Task 4 done first. Milestones follow design §10: phases 0–1 by 10/01, 2–4 by 10/09, 5–7 by 10/15, 8–10 by 10/21.

## Plan files
- `2026-09-28-wheres-allie-plan-01-foundation.md`
- `2026-09-28-wheres-allie-plan-02-home-editor.md`
- `2026-09-28-wheres-allie-plan-03-estimator.md`
- `2026-09-28-wheres-allie-plan-04-live-history-mcpapp.md`
- `2026-09-28-wheres-allie-plan-05-brain-mcp.md`
- `2026-09-28-wheres-allie-plan-06-relay.md`
- `2026-09-28-wheres-allie-plan-07-flasher-judge.md`

## Key decisions made while planning (beyond the design)
1. **MCP SDK 2.x** (`mcp>=2.2,<3`, `MCPServer` + the built-in Apps extension). `/mcp` is stateless and returns JSON responses (no SSE), so the relay forwards exactly one body.
2. **MCP App payload:** `where_is`, `day_summary` and `timeline` return `structuredContent.app` (`AppView`: a position or path view with `{home, rooms}`). It is rendered by the same `PlanCanvas` as the GUI, which works from props alone.
3. **Estimator catch-up:** a per-tag cursor in `settings` (`estimator.last_ts.<tag>`). Backfilled and live readings take the same path, which lets judge mode backfill history.
4. **Calibration:** one reading is one sample. Label windows are copied into settings so they survive the 30-day retention. Blend weight is n/(n+20).
5. **Web Serial needs a secure context.** The flasher is published on GitHub Pages (`seiraiyu.github.io/wheres_allie/flash.html`) and hands the node's IP back to the LAN GUI by a top-level redirect, allowed only to private or `.local` addresses. It runs inline when the GUI is opened on `localhost`. The Wi-Fi password only travels over USB.
6. **ESPresense Improv has no Wi-Fi scan,** so the wizard asks for the SSID as text. The node reboots after receiving credentials, so the wizard polls its state until the node reports its URL.
7. **Alexa+ requirements** (from the docs, still to be confirmed in spike A):
   - OAuth 2.1 authorization code + PKCE S256 + an RFC 8707 `resource` bound to `https://<relay>/mcp`;
   - an unauthenticated `/mcp` gets a bare 401 with **no** `WWW-Authenticate` header;
   - p95 round trip under 500 ms, measured by `relay.bench` and CloudWatch;
   - the `@alexa-ai/cli` flow.
8. **Settings are pushed to nodes** via ESPresense `GET/POST /wifi/main`, which uses masked secrets (`***###***` keeps the stored value). Saving doesn't restart the node, so a separate `POST /restart` follows.
9. **ESPresense-companion bug root cause:** the connect message `online` is published without retain while the last-will `offline` is retained. The fix is one line at `MqttCoordinator.cs:169`. It's an optional upstream PR (plan 07 Task 26) and needs your OK before opening.

## Known risks carried into execution
- **Ground truth mostly predates the raw log** (the log runs 22:34–23:39 on 9/28). Keep recording `data/ground-truth.md` entries so the under-bed case can be scored on real data.
- **The real tag reads quieter than the physics default** (-80 to -91 dBm). Plan 03 Task 10 sweeps `--tx-power` and `--floor-db` before changing defaults.
- **The eval uses the fixture floorplan** until the real house is drawn in the editor, so accuracy numbers are only meaningful after that.
- **The web toolchain** (vite 8, vitest 5, TS 7) was checked against the later plans' dependencies, but not against their full test suites.
