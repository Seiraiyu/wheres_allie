# Candidate 006 — Pet Check-in ("How was Max's day?")

**One-line pitch:** Ask Alexa+ how your dog did while you were away. ESP32 BLE room sensors plus bark and feeding signals feed a self-hosted MCP server that answers with where the dog spent its time, how fast it settled compared with its own baseline, barking, and whether it's been fed.

**Buyer persona:** Pet owner (dog first, cat second) in an Alexa household who leaves the pet home alone.

> Template adapted for the hackathon: "revenue" means the judging criteria (Impact, Idea, Tech, Design). Competitors are pet-tech products and other hackathon entrants.

## TAM model

| Buyer persona | Spend per | Adoption rate | Annual TAM |
|---|---|---|---|
| Dog households with Alexa (71M × 27% ≈ 19.2M) | $60/yr (≈$40 kit amortized + optional sub) | 1% | $11.5M |
| Cat households with Alexa (49M × 27% ≈ 13.2M) | $60/yr | 0.5% | $4.0M |
| DIY / Home Assistant homelab | $0 (open source) | n/a | $0 (Open Source mini-challenge credibility) |
| **Total** | | | **≈ $15.5M/yr** |

Notes:
- Anchors: 71M US dog households (53%) and 49M cat households, from [APPA 2025](https://americanpetproducts.org/news/the-american-pet-products-association-appa-releases-2025-dog-cat-report). About 27% of US households have an Alexa smart speaker ([grabon](https://grabon.com/blog/alexa-statistics/)). Alexa+ reached all US customers in Feb 2026. The pet-camera market is $1.1–3.1B (2025, estimates vary widely; [Grand View](https://www.grandviewresearch.com/industry-analysis/pet-monitoring-camera-market)).
- Adoption rates and spend are assumptions, not sourced.
- For judging, reach matters more than dollars: tens of millions of households, a daily emotional pain point, and "is my dog okay?" guilt.

## Time-to-first-revenue (hackathon: time to a winning demo)

- **Winning shape:** 3-minute video showing a real dog, 3D-printed ESP32 sensors, "Alexa, how was Max's day?" and a grounded answer, followed by a judge running the replay harness in one command.
- **Weeks from green light to demo-ready:** about 3 (deadline 2026-10-23, 4 weeks out).
- **Critical path:**
  - BLE collar tag plus ESP32 room presence (ESPresense firmware) feeding an event log.
  - MCP server (Streamable HTTP, spec 2025-11-25) with tools: `pet_day_summary`, `where_is_pet`, `time_in_rooms`, `settle_time_vs_baseline`, `bark_log`, `feeding_status`.
  - Replay/sim harness plus CI, then the video.

## Comp-kill matrix

| Competitor | Can ship in 6mo? | In 18mo? | Architectural cost to them |
|---|---|---|---|
| Petcube (Alexa skill: manual "has X been fed?", treats, laser) | yes (summary via their cam) | yes | Single camera, single room. No room-level location. Business model pushes paid cloud plans. |
| Furbo (Alexa skill: treats, bark alert triggers calming music) | yes (bark log) | yes | Same single-camera limit. Room time needs new hardware. |
| Fi / Tractive / Halo collars | partial (activity, sleep) | yes | GPS/outdoor focus. Indoor room-level needs in-home beacons (unverified whether any do). No Alexa+ day summary. |
| Amazon (Ring + Alexa+ native) | yes, biggest threat | yes | Could summarize Ring video natively. No per-room presence unless every room has a Ring cam. |
| Home Assistant DIY (ESPresense/Bermuda) | already exists (pieces) | — | Presence exists, but no pet "day story", baseline, or voice summary. Our voice layer sits on top of it. |
| Other hackathon entrants | no one found (as of 2026-09-25) | — | — |

## Build estimate

- **Engineering weeks to MVP:** about 3 (one person plus Claude).
- **Dependencies:** ESP32 boards per room, BLE tag on the collar, a Pi or small server, a 3D printer, an Alexa+ account (US) with the MCP Toolkit and web simulator, optional mic for barking, optional sensor on the food bin.
- **Risk:**
  1. BLE room accuracy through walls or with the dog lying on the tag. Needs per-room calibration (an RSSI threshold knob).
  2. The Alexa+ MCP Toolkit connection and auth path hasn't been proven yet. Spike it in week 1.

## Score (1-5 each)

| Axis | Score | Reasoning |
|---|---|---|
| TAM | 4 | 71M dog households; strong emotional pain (guilt, eviction risk, double-feeding). |
| Velocity | 4 | Room presence is a solved open-source component. MCP server is simple. Demo within about 3 weeks. |
| Wedge | 4 | No hackathon competitor. Petcube/Furbo don't do room time or baseline. Amazon native is the risk. |
| Build | 2 | EFFORT/cost: (1 = <=4 wks; 5 = >=26 wks). About 3 weeks, but hardware + firmware + enclosures + sim harness push it above a pure-software 1. |

**Composite:** (TAM x Velocity x Wedge) / Build = (4 × 4 × 4) / 2 = **32**
(Build is a cost denominator: a cheaper build gives a higher composite.)

## Verdict

**keep** (scores confirmed by user 2026-09-25; demo pet: dog). The idea is voice-native, differentiated, and demoable with real hardware, with a CI-backed judge path. Week-1 spikes: (1) the Alexa+ MCP Toolkit connection, (2) BLE room accuracy with a real dog.
