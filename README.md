# Coral Run Inspector

A small Flask tool that reads one Coral Bricks agent run and shows, turn by turn, what it
cost, how much of each turn's input was served from cache, where genuine cache misses are, and
how time to first token moves across the run.

The Coral console shows usage at the account level. This is the same data scoped to a single
run, where you can see the re-read curve and where the cost actually goes.

## Quick start

    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    python app.py

Open http://127.0.0.1:5001. It loads with a captured run in the dropdown, so you can see the
full view without a key or a live call.

## The workload

`capture.py` runs a real tool-using agent, not a canned script. The agent is given a debugging
task against a small repo and a set of tools (`list_dir`, `read_file`, `grep`, `run_tests`). It
decides which tools to call, the results are fed back, and it works until it reaches a fix.
There is no output-token cap, and context grows as it reads files, so the run looks like an
actual agent session rather than a fixed prompt replayed.

## Run live

With a key set on the server, the "Run live" button runs the agent against your account and
fills the charts in as each turn completes.

    export CORAL_KEY=cb_...
    python app.py

Then click Run live. When it finishes, the run is saved to `runs/<session>.json` and selected
in the Run dropdown. Live mode is live for runs this tool makes; it reads the usage each call
returns, and does not stream account-wide traffic, which the public API does not expose.

## Pricing

Prices are not hardcoded. `capture.py` reads them from `/v1/models` when a run starts and
stores a snapshot in the run file, so each run is priced at the rates it actually ran under and
a saved run opens without a key. The billed line is the `cost` the API returns on each call;
only the "no caching" line is computed, pricing every input token at the model's current input
rate.

What this shows depends on the model. At current `deepseek-v4.1-flash-fast` rates input is cheap
and output dominates the bill, so caching is close to a wash on cost there; it's a larger saving
on `deepseek-v4.1-flash`. The tool shows where a run's cost actually goes rather than claiming a
fixed multiple.

## Compare two models

Capture the same task on each model, then pick one in each dropdown (Run and vs) to overlay
them: cumulative cost, per-turn cost, TTFT, and hit rate side by side.

    export CORAL_KEY=cb_...
    CORAL_MODEL=deepseek-v4.1-flash-fast python capture.py
    CORAL_MODEL=deepseek-v4.1-flash python capture.py

## What to look for

- Cost across the run: the billed line vs the same run with no caching. The gap is what cached
  reads saved at the current rates.
- Input per turn: each bar is the full re-sent context; the cached part is billed at the
  cached-read rate, the sliver on top is new.
- Cache hit rate and genuine misses: turn 1 is a cold start. Caching works in 256-token blocks,
  so the tool computes the expected cached amount for each turn (the previous turn's context,
  floored to a 256-token block). When actual cached falls more than one block below expected,
  that's a genuine miss rather than block rounding — those turns are flagged in the table and
  marked on the hit-rate chart. The API doesn't report which replica served a request, so the
  cause of a miss isn't visible from the run alone.
- TTFT per turn: time to first token. A cache miss and a slow turn don't always line up, which
  is why both are plotted.

## Capture without the UI

    export CORAL_KEY=cb_...
    python capture.py

Runs the agent and writes `runs/<session>.json`. Refresh and pick it.

## How it works

- `capture.py` runs the tool-using agent and records per-turn usage straight from the API:
  prompt tokens, cached tokens, cache-write tokens, output tokens, and `cost`. It also snapshots
  model pricing from `/v1/models`. Used by both the CLI and the live endpoint.
- `app.py` reads a run and builds the per-turn series: the new-vs-cached split, cumulative
  billed cost, hit rate, the expected-vs-actual cached comparison, and the no-caching
  counterfactual from the run's stored rates.
- The page renders those with Chart.js.
