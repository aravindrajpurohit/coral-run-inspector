import os
import json
import glob
from flask import Flask, jsonify, abort, render_template, Response
from capture import run_live, fetch_pricing

app = Flask(__name__)

RUNS_DIR = os.path.join(os.path.dirname(__file__), "runs")


def load_raw(session):
    path = os.path.join(RUNS_DIR, f"{session}.json")
    if not os.path.exists(path):
        abort(404, f"no run {session}")
    with open(path) as f:
        return json.load(f)


def analyze(raw):
    pricing = raw.get("pricing") or {}
    priced = bool(pricing)
    in_rate = pricing.get("input_per_m", 0) / 1e6
    out_rate = pricing.get("output_per_m", 0) / 1e6

    cum_cost = 0.0
    cum_nocache = 0.0
    turns = []
    prev = None
    for t in raw["turns"]:
        cum_cost += t["cost"] or 0
        cum_nocache += t["input"] * in_rate + t["output"] * out_rate
        # what was already sent and cacheable before this turn, rounded to the 256-token block
        expected = ((prev["input"] + prev["output"]) // 256) * 256 if prev else 0
        # a genuine miss, not block rounding: actual falls more than one block below expected
        miss = expected > 0 and t["cached"] < expected - 256
        turns.append({
            "turn": t["turn"],
            "input": t["input"],
            "cached": t["cached"],
            "new": t["input"] - t["cached"],
            "output": t["output"],
            "cost": t["cost"],
            "ttft_ms": t.get("ttft_ms"),
            "tools": t.get("tools", []),
            "expected": expected,
            "miss": miss,
            "hit": round(t["cached"] / t["input"] * 100, 1) if t["input"] else 0.0,
            "cum_cost": round(cum_cost, 6),
            "cum_nocache": round(cum_nocache, 6) if priced else None,
        })
        prev = t

    tot_input = sum(t["input"] for t in raw["turns"])
    tot_cached = sum(t["cached"] for t in raw["turns"])
    totals = {
        "turns": len(turns),
        "input": tot_input,
        "cached": tot_cached,
        "new": tot_input - tot_cached,
        "output": sum(t["output"] for t in raw["turns"]),
        "hit": round(tot_cached / tot_input * 100, 1) if tot_input else 0.0,
        "misses": sum(1 for x in turns if x["miss"]),
        "cost": round(cum_cost, 6),
        "nocache": round(cum_nocache, 6) if priced else None,
        "saved_x": round(cum_nocache / cum_cost, 2) if priced and cum_cost else None,
        "cached_rate": pricing.get("cached_input_per_m"),
        "input_rate": pricing.get("input_per_m"),
        "output_rate": pricing.get("output_per_m"),
    }
    return {"session": raw["session"], "model": raw["model"], "turns": turns, "totals": totals}


@app.get("/api/runs")
def list_runs():
    out = []
    for path in sorted(glob.glob(os.path.join(RUNS_DIR, "*.json"))):
        with open(path) as f:
            raw = json.load(f)
        a = analyze(raw)
        out.append({"session": a["session"], "model": a["model"],
                    "turns": a["totals"]["turns"], "cost": a["totals"]["cost"],
                    "hit": a["totals"]["hit"]})
    return jsonify(out)


@app.get("/api/run/<session>")
def get_run(session):
    return jsonify(analyze(load_raw(session)))


def sse(obj):
    return f"data: {json.dumps(obj)}\n\n"


@app.get("/api/live")
def live():
    key = os.environ.get("CORAL_KEY")
    model = os.environ.get("CORAL_MODEL", "deepseek-v4.1-flash-fast")

    def stream():
        if not key:
            yield sse({"error": "CORAL_KEY is not set on the server. Stop the app, run: export CORAL_KEY=cb_..., then start it again."})
            return
        try:
            pricing = fetch_pricing(key, model)
        except Exception as e:
            yield sse({"error": f"could not read pricing from /models: {e}"})
            return
        in_rate = pricing.get("input_per_m", 0) / 1e6
        out_rate = pricing.get("output_per_m", 0) / 1e6
        cum_cost = 0.0
        cum_nocache = 0.0
        rows = []
        session = None
        prev = None
        try:
            for raw in run_live(key, model):
                session = raw["session"]
                cum_cost += raw["cost"] or 0
                cum_nocache += raw["input"] * in_rate + raw["output"] * out_rate
                expected = ((prev["input"] + prev["output"]) // 256) * 256 if prev else 0
                rows.append({k: raw[k] for k in ("turn", "input", "cached", "output", "cache_write", "cost", "ttft_ms", "tools")})
                yield sse({"turn": {
                    "turn": raw["turn"],
                    "input": raw["input"],
                    "cached": raw["cached"],
                    "new": raw["input"] - raw["cached"],
                    "output": raw["output"],
                    "cost": raw["cost"],
                    "ttft_ms": raw["ttft_ms"],
                    "tools": raw["tools"],
                    "expected": expected,
                    "miss": expected > 0 and raw["cached"] < expected - 256,
                    "hit": round(raw["cached"] / raw["input"] * 100, 1) if raw["input"] else 0.0,
                    "cum_cost": round(cum_cost, 6),
                    "cum_nocache": round(cum_nocache, 6),
                }})
                prev = raw
            if session:
                os.makedirs(RUNS_DIR, exist_ok=True)
                with open(os.path.join(RUNS_DIR, f"{session}.json"), "w") as f:
                    json.dump({"session": session, "model": model, "pricing": pricing, "turns": rows}, f, indent=2)
                yield sse({"done": session})
        except Exception as e:
            yield sse({"error": str(e)})

    return Response(stream(), mimetype="text/event-stream")


@app.get("/")
def index():
    return render_template("index.html")


if __name__ == "__main__":
    app.run(debug=True, port=5001, threaded=True)
