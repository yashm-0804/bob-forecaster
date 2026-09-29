# Demo video script — three minutes

Written for whoever records the submission video. Every shot is a URL, so a
retake starts from exactly the same screen.

## Before recording

```bash
# once, with the Gemini key in .env: drafts every cycle (8 requests, then cached)
.venv/bin/python -m agent.watch --replay MONTHA 2025 --region andhra
.venv/bin/python -m agent.watch --replay FANI 2019 --region odisha

./run.sh                                  # console at http://localhost:8077
```

Check the *Advisories* tab says **Drafted by gemini-3.7-flash** before recording.
The free tier allows 20 Gemini requests a day; if it says the quota was
reached, re-run the two replays the next day.

- Use Chrome with network access, so the real basemap loads. Without it the
  console draws its offline map, which also works — just say so if it appears.
- Full screen at 1920×1080, browser zoom 100%.
- Have the pitch deck open in another tab for the first and last shots.
- Approvals are recorded in `data/audit.sqlite3`. Delete it before a take if
  you want the advisory to start unapproved.

## Shots

| Time | Screen | Do | Say |
|---|---|---|---|
| 0:00 | Deck, cover | — | "India forecasts where cyclones go. This is about what they break." |
| 0:10 | Deck, *problem* slide | — | "Deaths from Odisha's cyclones fell from nearly ten thousand to sixty-four. But Fani still took down 156,000 power poles, and parts of Odisha waited two months for electricity." |
| 0:25 | `/?storm=montha&lead=48` | Point at the first three rows of the asset list | "This is Cyclone Montha, 48 hours before landfall, replayed from IMD's record. Not a district in orange — named substations and hospitals, ranked by what would be lost." |
| 0:45 | same | Point at the *Forecast source* row in the sidebar | "The forecast is the ensemble Google's WeatherNext 3 actually issued before this storm hit." |
| 0:55 | Click **Fani**, then **Montha**, in the sidebar | Point at *Wind-driven assets*: 792, then 0 | "Fani was an extremely severe storm: 792 assets at risk from wind. Montha was only severe — zero from wind. But its damage was real, and all of it came from flooding. A wind rating misses that." |
| 1:20 | `/?storm=fani&lead=72`, then click **T−48h** | Point at the *Since T−72h* box | "An agent re-runs everything on every bulletin. Between these two cycles, 78 assets turned red. That delta is what an officer needs." |
| 1:40 | `/?storm=fani&lead=48#advisories` | Click **Dispatch** first | "Each department gets its own advisory — this one addressed to Odisha's utilities. Dispatch is refused until someone approves." |
| 1:55 | same | Click **Approve**, type a full name, then **Dispatch** again; point at the Odia text | "A named officer approves, and it's logged. Even then nothing is sent — every alert is an exercise. Gemini wrote the Odia, and every number in it was checked against the model's own figures before it was let through." |
| 2:15 | `/?storm=montha&lead=48#triggers` | Point at *Loss without payout* | "For insurers: a policy triggered on wind would pay nothing for Montha — while each zone has assets in red. The platform shows that gap before landfall." |
| 2:30 | `/?storm=montha&lead=48#verify` | Scroll to *Against what actually happened*; point at the rain verdict, then the flood verdict | "Afterwards, every forecast is scored against satellites. The real GFS rain forecast beat the simple model. Our flood layer missed: the radar saw water inland, we predicted it at the coast. The console says so in red." |
| 2:45 | same | Scroll up to *Sensor network (simulated)* | "A simulated sensor network, with faults injected, runs through the same quality checks real hardware would." |
| 2:53 | Deck, *status* slide | — | "Know what breaks, 48 hours before it does." |

## If something goes wrong

- **Blank middle column:** reload once; if the basemap is blocked, the offline
  map appears within six seconds.
- **"No runs available":** run the replays in `DEPLOY.md` step 1.
- **Approve button greyed out:** the advisory is already approved — delete
  `data/audit.sqlite3` and restart `./run.sh`.

## Claims to keep accurate

Say these exactly as written, or not at all:

- Montha's track forecast is **WeatherNext 3** and its rainfall is the **GFS**
  forecast, both issued before landfall. Fani predates both archives: its
  ensemble is a perturbed best track and its rain is parametric (R-CLIPER).
- The surge output is a **screening estimate**, not a simulation.
- Trigger zones and tiers are **illustrative**, not real policies.
- The sensor network is **simulated**.
- The satellite checks cover **two storms**. Say "scored", never "validated".
  The flood layer **missed** on both; say so if flooding comes up.
- Gemini drafting needs the key in `.env`. If an advisory says *Drafted by
  template* and Odia shows as pending, say instead: "Odia is marked pending:
  we never fake a translation." Do not show it as translated.
