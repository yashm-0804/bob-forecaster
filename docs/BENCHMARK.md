# Benchmark

Produced by `python scripts/benchmark.py`, copied here unedited. Earth Engine
off and no Gemini calls, so only the model and the API are timed. The
pipeline row needs a warm data cache; the API rows use temporary stores. The
script lifts the per-client write budget for its own process, since timing
thousands of posts a minute from one client is what that budget refuses.

Measured 2026-09-28 on macOS-27.0-arm64-arm-64bit-Mach-O, Python 3.14.6, arm.

| What | Samples | Median | 90th percentile |
|---|---:|---:|---:|
| Pipeline: one Montha forecast cycle, 6,418 assets | 3 | 2.7 s | 2.7 s |
| API: GET a run (about 260 KB) | 50 | 3.4 ms | 3.6 ms |
| API: approve an advisory | 50 | 1.8 ms | 2.1 ms |
| API: ingest one reading, 80 reporting nodes | 400 | 2.6 ms | 2.9 ms |
| API: ingest one reading, 500 reporting nodes | 1000 | 2.2 ms | 2.4 ms |
| API: ingest one reading, 2,000 reporting nodes | 4000 | 2.6 ms | 3.0 ms |

One laptop, one run of the script. The larger networks are spread over the
Andhra-Odisha coast (15.5-20.5 N, 80.5-86.5 E), each node reporting every 15
minutes; readings are timed until every node has reported twice.

## What changed these figures

The same script, same machine, earlier the same day, before two changes:

| What | Samples | Median | 90th percentile |
|---|---:|---:|---:|
| Pipeline: one Montha forecast cycle, 6,418 assets | 3 | 2.9 s | 2.9 s |
| API: GET a run (about 260 KB) | 50 | 5.6 ms | 5.8 ms |
| API: approve an advisory | 50 | 1.9 ms | 2.1 ms |
| API: ingest one reading, 80 reporting nodes | 400 | 2.7 ms | 2.9 ms |
| API: ingest one reading, 500 reporting nodes | 1000 | 2.5 ms | 2.8 ms |
| API: ingest one reading, 2,000 reporting nodes | 4000 | 3.5 ms | 4.6 ms |

- **Ingest at 2,000 nodes: 3.5 ms to 2.6 ms median (4.6 to 3.0 ms at the
  90th percentile).** The neighbour query read every reading in the network
  from the last 20 minutes and discarded the distant ones in Python. It now
  asks SQLite for a box around the node (`telemetry.ingest.neighbour_box`),
  and the exact distance is still checked after. The QC verdicts of the
  simulated Montha network are byte-identical either way.
- **GET a run: 1.4 ms before compression (this page's previous version),
  5.6 ms with gzip at level 9 (the table just above), 3.4 ms at level 5.**
  Responses over 1 KB are now gzip-compressed, and the run's 264 KB goes as
  33 KB. Compressing that file alone takes 1.4 ms at level 5 and 6.1 ms at
  level 9, for 32.9 KB against 30.5 KB. The test client decompresses too,
  so part of each figure is the client's.

## How much it varies

Two later runs of the same script on the same laptop, with the machine
busier (load average about 5.5 during the second):

| What | Run 3 median | Run 4 median | Run 4, 90th percentile |
|---|---:|---:|---:|
| Pipeline: one Montha forecast cycle | 4.1 s | 3.6 s | 3.6 s |
| API: GET a run | 4.4 ms | 3.7 ms | 3.8 ms |
| API: approve an advisory | 2.2 ms | 2.0 ms | 2.3 ms |
| API: ingest, 80 nodes | 3.3 ms | 4.7 ms | 7.7 ms |
| API: ingest, 500 nodes | 2.7 ms | 3.0 ms | 5.2 ms |
| API: ingest, 2,000 nodes | 3.2 ms | 3.4 ms | 5.9 ms |

Across the four runs a forecast cycle took 2.7 to 4.1 s. Read the figures
as orders of magnitude on one laptop, not as a service level.

## Under concurrent load

`scripts/benchmark.py` also starts a real server (uvicorn, one worker, as
deployed) and sends 1,000 requests from 50 concurrent clients, first reading
a run (gzip accepted) and then approving an advisory with the access code.
The write budget is lifted for the measurement, as above. One run, load
average about 2.3:

| What | Samples | Median | 90th percentile |
|---|---:|---:|---:|
| Server, 50 concurrent clients: GET a run (858/s; not 200: none) | 1000 | 57.1 ms | 65.3 ms |
| Server, 50 concurrent clients: approve an advisory (962/s; not 200: none) | 1000 | 47.3 ms | 51.7 ms |

Every answer was a 200. The medians are mostly queueing: 50 callers share one
process, so each waits for the others. What this does not show is more than
one instance: the audit log and the rate limit are per process, which is why
the deploy command caps instances at one.
