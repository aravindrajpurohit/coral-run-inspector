# Coral Run Inspector

A small Flask tool that reads one Coral Bricks agent run and shows, turn by turn, what it
cost, how much of each turn's input was served from cache, and what the same run would cost
without free cached reads.

The Coral console shows usage at the account level. This is the same data scoped to a single
run, where you can see the re-read curve, where caching kicked in, and whether the run held
cache locality.

## start

    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    python app.py

Open http://127.0.0.1:5001. It loads with a sample run already in the dropdown, so you can see
the full view without a key or a live call.

## Run live

With a key set on the server, the "Run live" button executes a real 20-turn conversation
against your account and fills the charts in as each turn completes.

    export CORAL_KEY=cb_...
    python app.py

Then click Run live. The status shows "turn N of 20", and the tiles, charts, and table update
per turn. When it finishes, the run is saved to `runs/<session>.json` and selected in the Run
dropdown, so every run you do stays available to re-open and compare.

Live mode is live for runs this tool makes; it reads the usage each call returns. It does not
stream arbitrary account traffic, which the public API does not expose.

## Noticed:

- Cost across the run: the billed line stays nearly flat while the no-cache line climbs, the
  gap is what the free cached reads saved.
- Input per turn: each bar is the full re-sent context; the cached part (billed $0) carries
  almost all of it, only the sliver on top is new.
- Cache hit rate: turn 1 is a cold start. If a run bounces to a replica that does not hold its
  prefix, the hit rate drops for that turn and the cost ticks up. One of the example runs in
  `runs/` shows this mid-run.

## Capture without the UI

    export CORAL_KEY=cb_...
    python capture.py

Runs the same 20-turn conversation and writes `runs/<session>.json`. Refresh the page and pick
it from the dropdown.

## How it works

- `capture.py` records per-turn usage straight from the API: prompt tokens, cached tokens,
  output tokens, and `usage.cost`. It is used both by the CLI and by the live endpoint.
- `app.py` reads a run and computes the per-turn series: the new-vs-cached split, cumulative
  billed cost, cache hit rate, and a "without caching" figure that prices every input token at
  the standard input rate.
- The page renders those with Chart.js.

Billed cost comes straight from `usage.cost`. Only the "without caching" counterfactual is
computed, from the rates in `PRICES` (app.py), which come from coralbricks.ai/pricing.
