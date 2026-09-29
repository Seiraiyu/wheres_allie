# Research notes (2026-09-25)

## Hackathon (Alexa+ track)
- Due 2026-10-23 12:00 PDT. Self-hosted MCP server (spec >= 2025-11-25, Streamable HTTP) or Agent Skill; simulated Alexa+ also allowed.
- Alexa+ MCP Toolkit: US only, request/response (no documented server push), supports auth + MCP Apps (interactive UI on Echo Show), has web simulator.
  https://developer.amazon.com/docs/alexaplus/add-ons/mcp-toolkit-overview.html
- Open question: does Alexa+ pass Voice ID speaker identity to MCP?
- Taken by other entrants: home-ops/tasks (northbridge, provendone, asaya), scam checker (scamshield), energy (homeops-guardian).

## Cross-cutting ideas (not yet a backlog row)
- Merge 004+005+006 into one "home guardian" server (shared Pi, cameras, sensors).
- Shared backbone: verify -> tell the truth -> speak up (Pi speaker + Voice ID + one-time PIN, or virtual sensor + announce routine).
- Use MCP Apps on Echo Show for snapshots / device lists / pet timeline.

## Reddit: Alexa+ complaints (r/alexa, r/amazonecho)
1. Broken reliability: failed alarms, routines drop actions, "I'm going to bed" -> sleep lecture, specific skill/station replaced. (-> idea 007)
2. Too chatty / personality / "just answer".
3. Hallucinates, gaslights.
4. Ads, unprompted/creepy speech.
Users fleeing to Home Assistant.

## Reddit: pets (r/dogs, r/Dogtraining, r/puppy101, r/homeassistant)
- Owners want "did they settle / stressed longer than usual vs baseline" over live video; cams add anxiety w/o context (Harvard researcher thread 1rfxpud).
- Barking -> noise complaints -> eviction; owners don't know how much dog barks (1pin95m, 1q7eisw).
- Double-feeding / forgot-to-feed coordination; popular HA builds with sensor on food bin (1s1fimj, 1rerg9i).
- RTO forcing alone-time training (1steuip).
- Petcube motion detection degraded, pushed to pricier plan (1vbo5ku).
- Competitors w/ Alexa skills: Petcube (manual fed/walk log, treats, laser), Furbo (treats, bark alert -> calming music).
