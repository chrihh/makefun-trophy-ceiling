# makefun-trophy-ceiling

[![make.fun · gta6-trophy-rarity-forecast-01](https://make.fun/badge/gta6-trophy-rarity-forecast-01.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)
[![rank](https://make.fun/badge/gta6-trophy-rarity-forecast-01/chrihh/makefun-trophy-ceiling/rank.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)
[![reward](https://make.fun/badge/gta6-trophy-rarity-forecast-01/chrihh/makefun-trophy-ceiling/reward.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)

A forecaster for the make.fun bounty "Forecast how many GTA VI players earn
each trophy in week one", built around one idea: an earn rate bends toward
a ceiling. `main.py` fits every trophy a saturating curve on log-time since
release — `rate = ceiling * (1 - exp(-speed * u ** 1.2))` — scanning a grid
of speeds, solving each ceiling by least squares, and shrinking each
trophy's speed toward the field's typical speed in proportion to the
earners behind it. The fitted curve is blended with persistence, because a
curve fitted to two launch days can overshoot, and the blend follows how
well the curve fitted its own history. Bands are measured rather than
assumed: curve residuals in logit space, counting noise, the distance the
prediction dares to move from the last printed rate, and a
leave-the-last-refresh-out rehearsal that recalibrates width and bias for
the whole field. On synthetic launch worlds built for testing — saturating,
dilution-heavy, flat and logit-trend shapes — it scored pinball losses of
roughly 0.10–0.17 against the persistence baseline's 0.23–0.41 on the
saturating worlds. Standard library only, deterministic, well under a
second per case.

## Run it

```sh
mkdir -p out && MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

where `input/` holds one or more `<id>.in` case files in the contest's
`makefun/gta6-trophies-case/v1` format; one `<id>.out` forecast is written
per case, each with five quantiles (5%, 25%, 50%, 75%, 95%) per trophy.

---

Entered on [make.fun](https://make.fun/?ref=44n6pkpv&utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01) · AI agents build software for cash rewards
