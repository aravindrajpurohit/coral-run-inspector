import os
import json
import glob
from flask import Flask, jsonify, abort, render_template, Response
from capture import run_live

app = Flask(__name__)

RUNS_DIR = os.path.join(os.path.dirname(__file__), "runs")

PRICES = {
    "deepseek-v4.1-flash-fast": {"input": 0.30e-6, "cache_write": 0.09e-6, "output": 1.20e-6},
    "glm-5.3-fast":             {"input": 1.12e-6, "cache_write": 1.68e-6, "output": 4.40e-6},
}


def price_for(model):
    return PRICES.get(model, PRICES["deepseek-v4.1-flash-fast"])


def load_raw(session):
    path = os.path.join(RUNS_DIR, f"{session}.json")
    if not os.path.exists(path):
        abort(404, f"no run {session}")
    with open(path) as f:
        return json.load(f)


def analyze(raw):
    price = price_for(raw["model"])
    cum_cost = 0.0
    cum_nocache = 0.0
    turns = []
    for t in raw["turns"]:
        new = t["input"] - t["cached"]
        cum_cost += t["cost"]
        cum_nocache += t["input"] * price["input"] + t["output"] * price["output"]
        turns.append({
            "turn": t["turn"],
            "input": t["input"],
            "cached": t["cached"],
            "new": new,
            "output": t["output"],
            "cost": t["cost"],
            "ttft_ms": t.get("ttft_ms"),
            "hit": round(t["cached"] / t["input"] * 100, 1) if t["input"] else 0.0,
            "cum_cost": round(cum_cost, 6),
            "cum_nocache": round(cum_nocache, 6),
        })
    tot_input = sum(t["input"] for t in raw["turns"])
    tot_cached = sum(t["cached"] for t in raw["turns"])
    totals = {
        "turns": len(turns),
        "input": tot_input,
        "cached": tot_cached,
        "new": tot_input - tot_cached,
        "output": sum(t["output"] for t in raw["turns"]),
        "hit": round(tot_cached / tot_input * 100, 1) if tot_input else 0.0,
        "cost": round(cum_cost, 6),
        "nocache": round(cum_nocache, 6),
        "saved_x": round(cum_nocache / cum_cost, 1) if cum_cost else None,
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
        price = price_for(model)
        cum_cost = 0.0
        cum_nocache = 0.0
        rows = []
        session = None
        try:
            for raw in run_live(key, model):
                session = raw["session"]
                new = raw["input"] - raw["cached"]
                cum_cost += raw["cost"]
                cum_nocache += raw["input"] * price["input"] + raw["output"] * price["output"]
                rows.append({k: raw[k] for k in ("turn", "input", "cached", "output", "cost", "ttft_ms")})
                yield sse({"turn": {
                    "turn": raw["turn"],
                    "input": raw["input"],
                    "cached": raw["cached"],
                    "new": new,
                    "output": raw["output"],
                    "cost": raw["cost"],
                    "ttft_ms": raw["ttft_ms"],
                    "hit": round(raw["cached"] / raw["input"] * 100, 1) if raw["input"] else 0.0,
                    "cum_cost": round(cum_cost, 6),
                    "cum_nocache": round(cum_nocache, 6),
                }})
            if session:
                os.makedirs(RUNS_DIR, exist_ok=True)
                with open(os.path.join(RUNS_DIR, f"{session}.json"), "w") as f:
                    json.dump({"session": session, "model": model, "turns": rows}, f, indent=2)
                yield sse({"done": session})
        except Exception as e:
            yield sse({"error": str(e)})

    return Response(stream(), mimetype="text/event-stream")


@app.get("/")
def index():
    return render_template("index.html")


if __name__ == "__main__":
    app.run(debug=True, port=5001, threaded=True)
