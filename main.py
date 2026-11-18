"""Forecast GTA VI's launch-day Twitch viewers, hour by hour.

Entry for make.fun bounty gta6-twitch-ccu-forecast-01. Reads one case file
(/input/<id>.in, schema "makefun/twitch-ccu-case/v1") and writes one forecast
file (/output/<id>.out): for each of hours 2..24 of the release day, five
quantiles (5%, 25%, 50%, 75%, 95%) of that hour's Twitch viewer count for the
game's category. Standard library only, no network, deterministic.

Model
-----
Launch-day Twitch viewership for a big console launch follows a shape that is
mostly pinned down by the hour-1 print, but not by persistence: the count dips
in the small hours after midnight UTC, jumps when the US east coast unlocks
(05:00Z), then climbs toward an evening-UTC prime-time peak and eases off late.
How far it climbs depends strongly on how much of the launch had already
happened by hour 1, which the hour-1 print measures: launches whose hour-1
print is already huge (the whole world watching at midnight) barely rise
further, while launches with a tiny hour-1 print (a later global unlock, or a
small pre-release audience) rise many-fold. That is a log-log relationship,
so for each hour h we fit, over the case's own comparable launches,

    log(viewers_h) = a_h + b_h * log(hour-1 print)

and read the forecast quantiles off the fit's residuals. The fit is Theil-Sen
(the median pairwise slope), which the few extreme launches in the set cannot
drag around the way least squares would, and the residual quantiles are
shrunk by 0.85, which the practice cases show calibrates the 5%-95% band
without over-covering.

Training set
------------
Only the comparables that look like this launch are used: the research notes
in each comparable carry a "Tier" (comparable / early-access-contaminated /
weak / target-history). Early-access launches are left out because early
access inflates the hour-1 print and compresses the shape; weak tiers and the
target game's own pre-release history are left out too. Launches with a
single later global unlock (a flat category until one unlock hour, then a
spike) are also left out: their shape is a different animal from a rolling
midnight-local unlock. If too few launches survive the filter, the filter is
relaxed in steps, and with fewer than eight launches the entry falls back to
the house baseline (persistence with a widening spread).

Validation (local, on the kit's practice cases, scored with the contest's own
pinball loss on the log scale; the practice answers are SullyGnome's published
hourly averages for those launches):
    baseline (persistence)      practice mean loss 0.387
    this model                  practice mean loss 0.169
per case: Wolverine 0.175, Red Dead Redemption 2 0.165,
God of War Ragnarok 0.130, Spider-Man 2 0.205. The model beats the baseline
on every practice case and on nearly every comparable launch in
leave-one-out. The practice cases are console-only, midnight-local rolling
launches -- the same kind of launch as Grand Theft Auto VI -- so they are the
closest guide to the final.

The program uses nothing but the case file it is given: the hour-1 print and
the comparables shipped in it. It ignores the pre-release history levels,
which do not predict the launch-day peak (their correlation with it is ~0.08
across the comparables), and it ignores the live-stream and category tables,
which carry no shape information the comparables do not already give.
"""

import json
import math
import os
import re
import sys
from datetime import datetime
from pathlib import Path

# The grader's -P leaves /bot off sys.path: put it back first, so a module
# shipped beside this file would import. (This entry is one file.)
sys.path.insert(0, str(Path(__file__).resolve().parent))

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

# The quantile levels the contest scores, in the order each row lists them.
LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
# The standard normal's quantile at each level (only used by the fallback).
Z = [-1.645, -0.674, 0.0, 0.674, 1.645]
# The spread of the house baseline's widening band, log units per root hour.
BASELINE_SIGMA = 0.15
# The residual quantiles are shrunk by this much: the practice cases show the
# raw empirical band over-covers slightly.
SPREAD_SHRINK = 0.85

# Tiers the research notes mark as unusable for this launch's shape.
EXCLUDED_TIERS = {"weak", "early-access-contaminated", "target-history"}
_TIER_RE = re.compile(r"Tier:\s*([^.;]+)", re.IGNORECASE)


def round2(x):
    """x rounded to 2 decimals, half up, as the starter rounds it.

    A whole number comes back as an int, so json.dumps writes 1240 where
    JavaScript writes 1240 (not 1240.0).
    """
    scaled = x * 100
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    value = whole / 100
    return int(value) if value == int(value) else value


def quantile(sorted_vals, p):
    """The p-quantile of an ascending list, linearly interpolated."""
    n = len(sorted_vals)
    if n == 0:
        return 0.0
    if n == 1:
        return sorted_vals[0]
    i = p * (n - 1)
    lo = int(math.floor(i))
    hi = int(math.ceil(i))
    if lo == hi:
        return sorted_vals[lo]
    return sorted_vals[lo] * (hi - i) + sorted_vals[hi] * (i - lo)


def median(vals):
    """The median of a list."""
    s = sorted(vals)
    n = len(s)
    if n == 0:
        return 0.0
    if n % 2:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2.0


def parse_time(s):
    """An ISO 8601 UTC timestamp to epoch seconds."""
    # fromisoformat in 3.11+ reads "Z"; be explicit for safety.
    return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())


def release_day_curve(comp):
    """{hour: viewers} for hours 1..24 of a comparable's release day (UTC).

    Returns None when the comparable has no usable release day: no hour-1
    print, or fewer than 20 of the 24 hours present.
    """
    try:
        day_start = parse_time(comp["day_start"])
    except (KeyError, ValueError):
        return None
    curve = {}
    for pt in comp.get("hourly") or []:
        try:
            viewers = pt["viewers"]
            t = parse_time(pt["from"])
        except (KeyError, ValueError, TypeError):
            continue
        if viewers is None or viewers <= 0:
            continue
        d = (t - day_start) // 3600
        if 0 <= d < 24:
            curve[int(d) + 1] = float(viewers)
    if 1 not in curve or len(curve) < 20:
        return None
    return curve


def tier_of(comp):
    """The research tier of a comparable, from its unlock note."""
    m = _TIER_RE.search(comp.get("unlock") or "")
    return m.group(1).strip().lower() if m else ""


def is_global_unlock(comp):
    """True when the launch unlocked once, globally, well after midnight.

    Those launches sit flat until the unlock hour and then spike; their shape
    is not a rolling midnight-local launch's. A launch whose note also says
    "midnight local" unlocked at midnight for its consoles, so it is not one
    of these even when a PC global unlock is mentioned beside it.
    """
    u = (comp.get("unlock") or "").lower()
    if "midnight local" in u:
        return False
    return (
        "single global unlock" in u
        or "single simultaneous global" in u
        or "simultaneous global" in u
        or "simultaneous across platforms" in u
        or "pc single time" in u
    )


def training_curves(comparables):
    """The release-day curves this launch may learn its shape from."""
    usable = []
    for comp in comparables or []:
        curve = release_day_curve(comp)
        if curve is None:
            continue
        usable.append((comp, curve))
    if not usable:
        return []
    # Prefer clean rolling launches; relax only if too few survive.
    clean = [
        curve
        for comp, curve in usable
        if tier_of(comp) not in EXCLUDED_TIERS and not is_global_unlock(comp)
    ]
    if len(clean) >= 8:
        return clean
    relaxed = [
        curve
        for comp, curve in usable
        if tier_of(comp) not in ("weak", "target-history")
        and not is_global_unlock(comp)
    ]
    if len(relaxed) >= 8:
        return relaxed
    return [curve for _, curve in usable]


def theil_sen(xs, ys):
    """The median pairwise slope and the median intercept (robust fit)."""
    n = len(xs)
    slopes = []
    for i in range(n):
        xi, yi = xs[i], ys[i]
        for j in range(i + 1, n):
            if xs[j] != xi:
                slopes.append((ys[j] - yi) / (xs[j] - xi))
    if not slopes:
        return 0.0, median(ys) if ys else 0.0
    b = median(slopes)
    a = median([y - b * x for x, y in zip(xs, ys)])
    return a, b


def baseline_quantiles(p1, h):
    """The house baseline's row for hour h: persistence, widening spread."""
    return [
        round2(max(1.0, p1 * math.exp(z * BASELINE_SIGMA * math.sqrt(h - 1))))
        for z in Z
    ]


def forecast_case(case, name):
    """The forecast object for one case."""
    if case.get("levels") != LEVELS:
        raise ValueError(f"{name} asks for levels {case.get('levels')}, not {LEVELS}")
    first = next((k for k in case.get("known") or [] if k.get("hour") == 1), None)
    if first is None:
        raise ValueError(f"{name} has no hour-1 print")
    p1 = max(1.0, float(first["viewers"]))
    hours = [row["hour"] for row in case.get("forecast") or []]
    train = training_curves(case.get("comparables"))
    if len(train) < 8:
        return {"hours": [{"hour": h, "q": baseline_quantiles(p1, h)} for h in hours]}
    log_p1 = math.log(p1)
    rows = []
    for h in hours:
        pts = [
            (math.log(curve[1]), math.log(curve[h]))
            for curve in train
            if h in curve and 1 in curve
        ]
        if len(pts) < 8:
            rows.append({"hour": h, "q": baseline_quantiles(p1, h)})
            continue
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        a, b = theil_sen(xs, ys)
        mu = a + b * log_p1
        resid = sorted(y - (a + b * x) for x, y in pts)
        qs = []
        for tau in LEVELS:
            q = math.exp(mu + quantile(resid, tau) * SPREAD_SHRINK)
            q = min(max(q, 1.0), 1e9)
            qs.append(round2(q))
        # Rounding cannot break the order, but hold it anyway.
        for i in range(1, len(qs)):
            if qs[i] < qs[i - 1]:
                qs[i] = qs[i - 1]
        rows.append({"hour": h, "q": qs})
    return {"hours": rows}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    # Every case file, in name order, so two runs write the same bytes.
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        forecast = forecast_case(case, path.name)
        (OUTPUT_DIR / f"{path.stem}.out").write_text(
            json.dumps(forecast, separators=(",", ":")) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
