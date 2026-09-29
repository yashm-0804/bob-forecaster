# Where the model is weak, and the plan to fix it

The README's verification table is the evidence: rain is the strongest
pathway, the flood layer has negative skill for both replayed storms, and the
outage score missed Fani's area-wide blackout and raised seven false alarms
for Montha. Nothing below is a result. Each item is a change with the test it
must pass before its output is shown as a forecast rather than a screen.

## Rules for every change

- **Montha 2025 and Fani 2019 are not the test set.** Every change below was
  motivated by them, so tuning against them would only fit two storms. The
  held-out set is the Andhra and Odisha landfalls with Sentinel-1 and VIIRS
  coverage: Hudhud 2014, Titli 2018, Gulab 2021, Asani 2022 and Michaung
  2023. They are scored once, after a change is frozen, with the checks
  already in `verify/`.
- **A layer that fails its test stays labelled a screen** in the console and
  in the advisories' ensemble note, as the surge layer is today.
- **Results are recorded as they come**, including failures, in the README's
  verification table.

## Flooding

**Diagnosis.** The ponding term in `hazard/rainfall.py` weights low ground near
the coast. The flooding Sentinel-1 saw sat a median 17 to 23 km inland and 9
to 22 m up, which the term cannot reach. The radar's after-pass also came 1
to 3 days after landfall.

1. **Replace coastal proximity with drainage position.** Use height above
   nearest drainage (the `hnd` band of MERIT Hydro, `MERIT/Hydro/v1_0_1` on
   Earth Engine) and upstream area, so that water collects along rivers and
   in depressions wherever they are. Rain accumulation stays the driver.
2. **Score only where the radar could see.** Record the lag of each
   Sentinel-1 pass after landfall, and report flood skill only for passes
   within 2 days. Report the others as unscored, with the lag.
3. **Test.** On the held-out storms, the Brier skill against climatology
   must be above zero for at least three of five, and the median distance
   inland of predicted flooding must fall within a factor of two of the
   observed.

## Power outages

**Diagnosis.** Only substations are scored. Fani's lights went out because
lines and poles failed around the substations. Montha's seven predicted
outages were all at substations whose surroundings stayed lit.

1. **Score service areas, not points.** Assign each lit area to its nearest
   substation, and give each area the failure probability of the lines that
   feed it (OSM `power=line` and `minor_line`, with the gridfinder density
   where OSM is thin), combined with the substation's own.
2. **Calibrate line fragility on recorded damage**, not on these scores: the
   pole counts in the dossier's damage records (about 156,000 poles for
   Fani, 27,041 for Hudhud).
3. **Test.** On the held-out storms, probability of detection of at least
   0.5 with a false-alarm ratio of at most 0.5, against the VIIRS night-light
   drop.

## Rain

**Diagnosis.** GFS forecast less than half of Montha's rain at T−72 h and
T−24 h. R-CLIPER placed Fani's rain well but made it 67% too heavy.

1. **Bias-correct GFS by lead time** with a quantile mapping fitted on IMERG
   for the Bay of Bengal storms of 2021 to 2024, excluding Montha.
2. **Use WeatherNext rainfall when access is granted**, scored with the same
   checks.
3. **Test.** On the held-out storms from 2021 on (GFS is archived from
   2021), the correlation with IMERG must not fall and the bias must move
   towards 1.

## What this does not fix

The low-voltage grid is still unmapped, so outages caused below the feeder
level stay out of reach until the building-footprint density surface is
built. Two storms, or seven, remain a small sample: the checks exist so
that every new storm adds to it automatically.
