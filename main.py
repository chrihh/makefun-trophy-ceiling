"""GTA VI trophy earn-rate forecaster, v2: every trophy bends to a ceiling.

Written for the make.fun bounty gta6-trophy-rarity-forecast-01.

The modelling bet in this version is about shape. An earn rate does not
travel in a straight line on any clock: it climbs quickly while the launch
cohort is fresh, then bends over as the players who will ever earn that
trophy run out and the remaining tracked pool is topped up by newcomers
who have barely started. So this program fits each trophy's rate a
saturating curve with two numbers of its own:

    rate(u) = ceiling * (1 - exp(-speed * u ** 1.2))

where u is log-time since release, u = ln(1 + age in days), the ceiling is
the rate the trophy is heading for (never above 100), and the speed says
how fast it gets there. For any candidate speed the best ceiling is a
one-line least-squares solve, so the program scans a grid of speeds,
keeps the one whose curve hugs the observed rates closest, and shrinks
that speed toward the typical speed across all 55 trophies: a trophy with
a handful of earners has no business claiming a speed entirely its own.

The fitted curve is not trusted outright. Its median is blended with
simple persistence -- the last printed rate -- because a curve fitted to
two days of launch data can overshoot in either direction, and the blend
weight follows how well the curve actually fitted. Uncertainty is
measured, not assumed: the curve's own residuals in logit space, the
counting noise implied by the trophy's earner count, the horizon, and a
leave-the-last-refresh-out rehearsal (refit one refresh early, predict
the last refresh, compare) that sets a global band width and a small
bias correction for the whole field.

Histories are first collapsed to distinct page states: Exophase refreshes
in jumps, and a read that repeats the previous one word for word carries
no new information. With fewer than three distinct states (the launch
night practice cases are one frozen page) no curve is identifiable, and
the program holds the last rate with a deliberately wide band that prices
in the refresh nobody has seen yet.

Deterministic, standard library only, no network, no clock reading.
"""

import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

IN_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

QUANTILES = [0.05, 0.25, 0.5, 0.75, 0.95]
ZVALS = [-1.644854, -0.674490, 0.0, 0.674490, 1.644854]
LAUNCH = datetime(2026, 11, 19, tzinfo=timezone.utc).timestamp()
CURVE_POWER = 1.2
SPEED_GRID = [0.05 * (1.20 ** i) for i in range(36)]  # roughly 0.05 .. 6.3


def to_epoch(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()


def age_days(epoch):
    return max((epoch - LAUNCH) / 86400.0, 0.0)


def log_clock(days):
    return math.log1p(days)


def logit_of(pct):
    p = min(99.99, max(0.01, pct)) / 100.0
    return math.log(p / (1.0 - p))


def pct_of_logit(value):
    if value >= 0:
        return 100.0 / (1.0 + math.exp(-value))
    e = math.exp(value)
    return 100.0 * e / (1.0 + e)


def middle(values):
    ordered = sorted(values)
    n = len(ordered)
    if n == 0:
        return 0.0
    if n % 2 == 1:
        return ordered[n // 2]
    return (ordered[n // 2 - 1] + ordered[n // 2]) / 2.0


def distinct_states(case):
    """History collapsed to the reads where the printed page changed."""
    states = []
    for read in case["history"]:
        marker = (read["players_tracked"], tuple(read["rates"]))
        if states and states[-1]["marker"] == marker:
            continue
        when = to_epoch(read.get("slot") or read["at"])
        states.append(
            {
                "marker": marker,
                "days": age_days(when),
                "players": float(read["players_tracked"]),
                "rates": read["rates"],
            }
        )
    return states


def fit_rate_curve(us, rates):
    """Best (speed, ceiling, rmse) for one trophy's printed rates.

    rmse is measured in logit space, since that is the scale the contest
    scores on: a curve that misses a 1% trophy by a point is far worse
    than one that misses a 50% trophy by a point, and the residuals
    should say so.
    """
    best = None
    for speed in SPEED_GRID:
        basis = [1.0 - math.exp(-speed * (u ** CURVE_POWER)) for u in us]
        denom = sum(b * b for b in basis)
        if denom < 1e-12:
            continue
        ceiling = sum(r * b for r, b in zip(rates, basis)) / denom
        if ceiling <= 0:
            continue
        ceiling = min(ceiling, 100.0)
        sse = 0.0
        for r, b in zip(rates, basis):
            pred = max(ceiling * b, 0.01)
            sse += (logit_of(r) - logit_of(pred)) ** 2
        if best is None or sse < best[0]:
            best = (sse, speed, ceiling)
    if best is None:
        return None
    sse, speed, ceiling = best
    return speed, ceiling, math.sqrt(sse / max(len(us), 1))


def curve_forecasts(states, target_days):
    """Per-trophy curve predictions at the target, with fit quality.

    Returns a list whose entries are either None (too few points) or a
    dict with the predicted rate, the last rate, the earner count behind
    the last rate, and the curve's logit rmse.
    """
    u_tgt = log_clock(target_days)
    n = len(states[0]["rates"])
    raw = []
    for idx in range(n):
        pts = []
        for s in states:
            if idx < len(s["rates"]) and s["rates"][idx] is not None:
                pts.append((log_clock(s["days"]), float(s["rates"][idx]), s["players"]))
        if len(pts) < 3:
            raw.append(None)
            continue
        got = fit_rate_curve([p[0] for p in pts], [p[1] for p in pts])
        if got is None:
            raw.append(None)
            continue
        speed, ceiling, rmse = got
        raw.append(
            {
                "speed": speed,
                "ceiling": ceiling,
                "rmse": rmse,
                "pts": pts,
                "r_last": pts[-1][1],
                "e_last": pts[-1][1] * pts[-1][2] / 100.0,
            }
        )
    speeds = [f["speed"] for f in raw if f and f["e_last"] >= 20.0]
    typical = middle(speeds) if speeds else (
        middle([f["speed"] for f in raw if f]) if any(raw) else 0.5
    )
    out = []
    for f in raw:
        if f is None:
            out.append(None)
            continue
        # Shrink the speed toward the field's typical speed, trusting a
        # trophy's own value in proportion to the earners behind it, then
        # refit its ceiling at the shrunk speed.
        trust = f["e_last"] / (f["e_last"] + 45.0)
        speed = math.exp(trust * math.log(f["speed"]) + (1.0 - trust) * math.log(typical))
        us = [p[0] for p in f["pts"]]
        rs = [p[1] for p in f["pts"]]
        basis = [1.0 - math.exp(-speed * (u ** CURVE_POWER)) for u in us]
        denom = sum(b * b for b in basis)
        ceiling = sum(r * b for r, b in zip(rs, basis)) / denom if denom > 1e-12 else f["ceiling"]
        ceiling = min(max(ceiling, f["r_last"]), 100.0)
        pred = ceiling * (1.0 - math.exp(-speed * (u_tgt ** CURVE_POWER)))
        # A rate can fall when a refresh dilutes it, but earners never
        # vanish: keep the prediction within a generous corridor of the
        # last printed rate.
        pred = min(max(pred, 0.30 * f["r_last"]), 99.5)
        out.append(
            {"pred": pred, "r_last": f["r_last"], "e_last": f["e_last"], "rmse": f["rmse"]}
        )
    return out


def rehearsal(states):
    """Fit one refresh early, predict the last one, measure the miss.

    Returns (bias, widen): the median signed logit error of the blended
    forecast in the rehearsal, and how wide the bands should have been
    relative to a nominal half-logit, both clamped to sane limits.
    """
    if len(states) < 5:
        return 0.0, 1.0
    head = states[:-1]
    truth = states[-1]
    fits = curve_forecasts(head, truth["days"])
    signed, absolute = [], []
    for idx, f in enumerate(fits):
        if f is None or idx >= len(truth["rates"]) or truth["rates"][idx] is None:
            continue
        blended = 0.72 * logit_of(f["pred"]) + 0.28 * logit_of(f["r_last"])
        err = logit_of(float(truth["rates"][idx])) - blended
        signed.append(err)
        absolute.append(abs(err))
    if len(signed) < 12:
        return 0.0, 1.0
    bias = min(max(0.55 * middle(signed), -0.30), 0.30)
    widen = min(max(middle(absolute) / 0.5, 0.75), 1.9)
    return bias, widen


def tidy4(value):
    rounded = round(float(value) + 1e-12, 4)
    return int(rounded) if float(rounded).is_integer() else rounded


def forecast_one(case):
    if case["levels"] != QUANTILES:
        raise ValueError("unexpected quantile levels")
    states = distinct_states(case)
    if not states:
        raise ValueError("empty history")
    target_days = age_days(to_epoch(case["target"]))
    last = states[-1]
    horizon_days = max(target_days - last["days"], 0.0)

    if len(states) < 3:
        # One frozen page: no curve is identifiable. Hold the last rate
        # and pay for the unseen refresh with width instead of movement.
        sigma = 0.70 * math.sqrt(horizon_days) + 0.55
        rows = []
        for idx, trophy in enumerate(case["trophies"]):
            rate = last["rates"][idx] if idx < len(last["rates"]) else None
            centre = logit_of(float(rate)) if rate is not None else logit_of(0.4)
            qs = [tidy4(pct_of_logit(centre + z * sigma)) for z in ZVALS]
            rows.append({"id": trophy["id"], "q": qs})
        return {"trophies": rows}

    fits = curve_forecasts(states, target_days)
    bias, widen = rehearsal(states)

    rows = []
    for idx, trophy in enumerate(case["trophies"]):
        rate_last = last["rates"][idx] if idx < len(last["rates"]) else None
        r_last = float(rate_last) if rate_last is not None else 0.4
        f = fits[idx]
        if f is None:
            centre = logit_of(r_last)
            sigma = 0.9
        else:
            # Blend the curve with persistence; a curve that fitted its
            # own history badly earns less of the blend.
            curve_weight = 0.72 if f["rmse"] < 0.45 else 0.55
            centre = curve_weight * logit_of(f["pred"]) + (1.0 - curve_weight) * logit_of(r_last)
            centre += bias
            counting = 1.05 / math.sqrt(f["e_last"] + 3.0)
            # When the curve wants to move the rate a long way from where
            # it was last printed, that ambition is itself uncertainty:
            # the further the prediction sits from persistence, the wider
            # the band around it should be.
            ambition = abs(logit_of(f["pred"]) - logit_of(r_last))
            sigma = math.sqrt(
                (0.26 * math.sqrt(horizon_days)) ** 2
                + (0.85 * f["rmse"]) ** 2
                + counting ** 2
                + (0.30 * ambition) ** 2
                + 0.09 ** 2
            )
            sigma = min(max(sigma * widen, 0.32), 1.65)
        qs = [tidy4(pct_of_logit(centre + z * sigma)) for z in ZVALS]
        for k in range(1, len(qs)):
            if qs[k] < qs[k - 1]:
                qs[k] = qs[k - 1]
        rows.append({"id": trophy["id"], "q": qs})
    return {"trophies": rows}


def run():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(IN_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        result = forecast_one(case)
        (OUT_DIR / (path.stem + ".out")).write_text(
            json.dumps(result, separators=(",", ":")) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    run()
