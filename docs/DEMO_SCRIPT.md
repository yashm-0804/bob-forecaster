# Walkthrough video script: about three and a half minutes

Written for whoever records the submission video. Every console shot is a
URL, so a retake starts from exactly the same screen. Shots marked
*optional* can be cut to bring the video to three minutes.

## Before recording

### 1. Prepare the console

```bash
./run.sh                                  # console at http://localhost:8077
```

- **Check the Telugu.** Open
  `http://localhost:8077/?storm=montha&lead=48#advisories`. Each advisory
  should say **Drafted by gemini-3.7-flash** and offer an `te-IN` button. If
  it says *Drafted by template*, regenerate with a Gemini key in `.env`:
  `.venv/bin/python -m agent.watch --replay MONTHA 2025 --region andhra`.
- **Check sign-in.** The top bar shows **Sign in with Google**. Sign in once
  with an account listed in `BOB_OPERATORS`, so the take does not stop at
  "not on the officer list". Allow pop-ups for `localhost` if Chrome blocks
  the Google window.
- **Reset the approval.** Approvals are kept in BigQuery and can never be
  deleted. If the power utility's advisory on Montha T−48h is already
  approved from a rehearsal, click **Withdraw** before the take: it returns
  to unapproved and can be approved again.
- **Your email will show** in the Google sign-in window and in the dispatch
  receipt ("approved by Name <email>"). Either accept that, since it is your
  own account, or blur those two moments when editing.

### 2. Prepare the screen

- Chrome, full screen, 1920×1080, browser zoom 100%, bookmarks bar hidden.
- Turn on Do Not Disturb, and close every other tab and app.
- Tab 1: the console. Tab 2: the pitch deck in presentation mode, on the
  cover slide.
- Network on, so the real basemap loads. Without it the console draws its
  own offline map, which also works; say so if it appears.

### 3. Record

- **macOS:** press `Cmd + Shift + 5`, choose *Record Entire Screen*, and under
  *Options* pick your microphone. Press the stop button in the menu bar
  when done. QuickTime (*File → New Screen Recording*) and OBS also work.
- Speak slowly and move the cursor slowly; pause a beat after each click.
- If a line trips, pause for two seconds and say it again from the start of
  the sentence. The pause makes the cut easy in editing.
- Rehearse once with the script open on a second screen or a phone.

## Shots

| Time | Screen | Do | Say |
|---|---|---|---|
| 0:00 | Deck, slide 1 (cover) | — | "India can forecast where a cyclone will go. This is about what it will break." |
| 0:10 | Deck, slide 2 (problem) | — | "Deaths from Odisha's cyclones fell from nearly ten thousand to sixty-four. But Cyclone Fani still brought down about 156,000 power poles, and parts of Odisha waited two months for electricity. And the costliest storms of 2025 were weak, rainy ones that a wind rating calls minor." |
| 0:30 | Console: `/?storm=montha&lead=48` | Point slowly at the first three rows of the asset list | "This is Cyclone Montha, 48 hours before landfall, replayed from the record. Every dot is a real asset from OpenStreetMap. Not a district shaded orange: named hospitals and substations, ranked by what would be lost." |
| 0:48 | same | Click the third row, **Konaseema CCPP** | "This is a gas power plant's 400 kV switchyard. It is only 22 percent likely to fail, but it ranks third, because so much depends on it." |
| 1:00 | same | Point at *Forecast source* in the left panel | "The storm track is the 64-member ensemble that Google DeepMind's WeatherNext issued before this storm, and the terrain comes through Google Earth Engine." |
| 1:10 | same | Click **Fani**, point at *Wind-driven assets* (792); click **Montha**, point again (0) | "Fani was an extremely severe storm: 792 assets threatened mainly by wind. Montha was only severe: zero from wind. A wind rating would have stood down. But 2,314 assets were exposed to flooding, and that is the pathway we model." |
| 1:30 | Deck, slide 9 (impact model) | — | "Each of the 64 tracks drives wind, a surge estimate and rain on a two-kilometre grid, and every asset goes through its own damage curve." |
| 1:40 | Console: `/?storm=montha&lead=48#advisories` | Point at the power utility's advisory; click **te-IN**, then **en-IN** | "Each department gets its own advisory, naming its own assets. Gemini 3.7 Flash rewords it and writes the Telugu, and a guardrail rejects any number Gemini did not get from the model." |
| 1:55 | same | Hover over **Dispatch** until its tooltip shows | "Dispatch stays locked until an officer approves." |
| 2:00 | same | Click **Sign in with Google** in the top bar and pick the account; click **Approve**, then confirm; wait through *Recording…* | "Officers sign in with Google. Only listed accounts can approve, and every decision is written to BigQuery, where it can never be edited or deleted." |
| 2:15 | same | Click **Dispatch**; point at the receipt | "Even now nothing is sent. It is an exercise, in the Common Alerting Protocol format that SACHET, India's national alert system, uses." |
| 2:25 | *Optional.* Console: `/?storm=fani&lead=72`, then click **T−48h** | Point at the *Since T−72h* box | "An agent re-runs everything on each forecast cycle. Between these two, 78 assets turned red. That change is what an officer needs to see." |
| 2:37 | *Optional.* Console: `/?storm=montha&lead=48#triggers` | Point at *Loss without payout* | "For insurers and disaster funds: every zone has high-risk assets, yet no payout trigger fires. The console shows that gap before landfall." |
| 2:47 | Console: `/?storm=montha&lead=48#verify` | Scroll to *Against what actually happened*; point at the rain result, then the flood result | "After landfall, every forecast is scored against satellites, through Earth Engine. The rain totals were close." |
| 2:57 | Deck, slide 12 (flood map) | — | "Our flood screen missed. It put the water on the coast; the radar saw it twenty-three kilometres inland, along rivers. We publish that, with the fix: route the rain through rivers." |
| 3:12 | *Optional.* Deck, slide 15 (sensor pathway) | — | "Phase two is a low-cost sensor network. The software to receive and check its readings is built, and tested on 83 simulated nodes with faults injected on purpose." |
| 3:24 | Deck, slide 17 (close) | — | "Which asset fails, and who acts on it: 48 hours before landfall. The code, and how to run it, are on GitHub." |

Without the optional shots the video runs about three minutes.

## If something goes wrong

- **Blank middle column:** reload once. If the basemap is blocked, the
  offline map appears within six seconds.
- **"No runs available":** run the replays in `DEPLOY.md`, step 1.
- **The Google window does not open:** allow pop-ups for `localhost` in
  Chrome, then click **Sign in with Google** again.
- **"Not on the officer list":** the account you picked is not in
  `BOB_OPERATORS` in `.env`. Sign out, and sign in with the listed one.
- **Approve is missing and Withdraw is showing:** the advisory is already
  approved. Click **Withdraw**, confirm, then approve again.
- **"Recording…" takes a few seconds:** normal. BigQuery takes 2 to 3
  seconds per write. Keep talking.
- **No `te-IN` button:** that cycle was not drafted by Gemini. Regenerate as
  in step 1, or say "Telugu is marked pending: we never fake a translation."

## Claims to keep accurate

Say these exactly as written, or not at all:

- Montha's track forecast is **WeatherNext 3** and its rain is the **GFS**
  forecast, both issued before landfall. Fani predates both archives: its
  ensemble is perturbed from the best track, and its rain is parametric.
- **Konaseema CCPP** is a gas power plant's 400 kV switchyard, mapped in
  OpenStreetMap as a substation.
- The surge output is a **screening estimate**, not a simulation.
- Trigger zones and thresholds are **illustrative**, not real policies.
- The sensor network is **simulated**, and the hardware is a **proposed
  design**.
- The satellite checks cover **two storms**. Say "scored", never
  "validated". The flood layer **missed** on both.
- **Nothing is ever sent.** Every alert is an exercise; IMD is the
  statutory warning authority.

## After recording

- Upload to YouTube as **Unlisted** (or as the portal asks). Suggested
  title: *Bay of Bengal Cyclone Impact Forecaster: Build with AI, Track 5,
  Team SPECODERS*.
- Suggested description: "Which substation, road and hospital fails 48 hours
  before a Bay of Bengal cyclone, and what each department should do.
  Built on Gemini 3.7 Flash, Google Earth Engine, WeatherNext, BigQuery and
  Firebase. Code and setup: https://github.com/yashm-0804/bob-forecaster"
- Put the link in the README and the deck's closing slide.
