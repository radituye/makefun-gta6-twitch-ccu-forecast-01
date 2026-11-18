[![make.fun · gta6-twitch-ccu-forecast-01](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/radituye/makefun-gta6-twitch-ccu-forecast-01/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/radituye/makefun-gta6-twitch-ccu-forecast-01/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)

# GTA VI launch-day Twitch forecaster

Forecasts how many people watch Grand Theft Auto VI live on Twitch in each
hour of its release day, 2026-11-19 (UTC), after the first hour's print.
Entry for the make.fun bounty:
https://make.fun/bounty/gta6-twitch-ccu-forecast-01

## What it does

`main.py` (Python 3.13, standard library only, no network) reads one case
file (`/input/<id>.in`) and writes one forecast (`/output/<id>.out`): for
each of hours 2–24, five quantiles (5%, 25%, 50%, 75%, 95%) of that hour's
Twitch viewer count for the "Grand Theft Auto VI" category. It runs in
~0.3 s, well inside the 8 s limit, and is byte-deterministic across runs.

## Model

Launch-day Twitch viewership for a big console launch follows a shape mostly
pinned down by the hour-1 print — but not by persistence. The count dips in
the small hours after midnight UTC, jumps when the US east coast unlocks
(05:00Z), then climbs toward an evening-UTC prime-time peak and eases off
late. How far it climbs depends strongly on how much of the launch had
already happened by hour 1: launches whose hour-1 print is already huge
barely rise further, while launches with a tiny hour-1 print rise many-fold.
That is a log-log relationship, so for each hour `h` the program fits, over
the case's own comparable launches,

```
log(viewers_h) = a_h + b_h * log(hour-1 print)
```

and reads the forecast quantiles off the fit's residuals. The fit is
Theil–Sen (the median pairwise slope), which the few extreme launches in
the set cannot drag around the way least squares would, and the residual
quantiles are shrunk by 0.85, which the practice cases show calibrates the
5%–95% band without over-covering.

Only comparables that look like this launch are used: the research notes
carry a "Tier" (comparable / early-access-contaminated / weak /
target-history). Early-access launches are left out because early access
inflates the hour-1 print and compresses the shape; weak tiers and the
target game's own pre-release history are left out too. Launches with a
single later global unlock (flat until one unlock hour, then a spike) are
also left out: their shape is a different animal from a rolling
midnight-local unlock. If too few launches survive, the filter relaxes in
steps; with fewer than eight it falls back to the house baseline.

## Validation

Scored locally on the kit's four practice cases with the contest's own
pinball loss on the log scale, against SullyGnome's published hourly
averages for those launches (the practice answers are not in the kit; they
were read once from SullyGnome's public chart data for those four games):

| case | this model | house baseline |
|---|---|---|
| Marvel's Wolverine (2026-09-15) | 0.175 | 0.744 |
| Red Dead Redemption 2 (2018-10-26) | 0.165 | 0.287 |
| God of War Ragnarök (2022-11-09) | 0.130 | 0.215 |
| Marvel's Spider-Man 2 (2023-10-20) | 0.205 | 0.303 |
| **mean** | **0.169** | **0.387** |

The model beats the baseline on every practice case and on nearly every
comparable launch in leave-one-out. The practice cases are console-only,
midnight-local rolling launches — the same kind of launch as Grand Theft
Auto VI — so they are the closest guide to the final. Coverage of the
5%–95% band on the practice cases is 0.87–1.00 (an honest forecast covers
about 0.9).

## Run it

```sh
mkdir -p out
MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

## License

MIT — see [LICENSE](LICENSE).
