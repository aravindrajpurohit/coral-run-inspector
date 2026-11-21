import json
import glob

TIER = {
    "deepseek-v4.1-flash-fast": "Fast",
    "deepseek-v4.1-flash": "Standard",
    "deepseek-v4.1-flash-value": "Value",
}
ORDER = ["deepseek-v4.1-flash-fast", "deepseek-v4.1-flash", "deepseek-v4.1-flash-value"]

# Coral's published per-model figures from /v1/models (1-day window), pulled 2026-11-21
SPEED = {
    "deepseek-v4.1-flash-fast":  {"decode": 449.0, "latency": 0.38},
    "deepseek-v4.1-flash":       {"decode": 129.7, "latency": 0.77},
    "deepseek-v4.1-flash-value": {"decode": 120.9, "latency": 0.69},
}


def load_runs():
    runs = {}
    for path in glob.glob("runs/*.json"):
        d = json.load(open(path))
        runs[d["model"]] = d
    return runs


def cost(turns, p):
    # new (uncached) tokens pay input + cache-write; cached reads pay the cached rate
    total = 0.0
    for t in turns:
        new = t["input"] - t["cached"]
        total += (new * (p["input_per_m"] + p["cache_write_per_m"])
                  + t["cached"] * p["cached_input_per_m"]
                  + t["output"] * p["output_per_m"]) / 1e6
    return total


def totals(turns):
    return (sum(t["input"] for t in turns),
            sum(t["cached"] for t in turns),
            sum(t["output"] for t in turns))


def build_html(rows, hits):
    labels = [TIER[m] for m in ORDER]
    mult = [round(c / rows[ORDER[-1]], 2) for c in (rows[m] for m in ORDER)]
    f, s, v = SPEED["deepseek-v4.1-flash-fast"], SPEED["deepseek-v4.1-flash"], SPEED["deepseek-v4.1-flash-value"]
    speed_ratio = round(f["decode"] / v["decode"], 1)
    tr = "".join(
        f"<tr><td>{TIER[m]}</td><td>${rows[m]:.4f}</td><td>{rows[m] / rows[ORDER[-1]]:.2f}x</td>"
        f"<td>{SPEED[m]['decode']:.0f}</td><td>{SPEED[m]['latency']}s</td></tr>"
        for m in ORDER)
    hit_lo, hit_hi = min(hits), max(hits)
    html = TEMPLATE
    html = html.replace("__ROWS__", tr)
    html = html.replace("__LABELS__", json.dumps(labels))
    html = html.replace("__MULT__", json.dumps(mult))
    html = html.replace("__FASTM__", f"{rows['deepseek-v4.1-flash-fast'] / rows[ORDER[-1]]:.2f}")
    html = html.replace("__STDM__", f"{rows['deepseek-v4.1-flash'] / rows[ORDER[-1]]:.2f}")
    html = html.replace("__SPEEDR__", str(speed_ratio))
    html = html.replace("__FD__", f"{f['decode']:.0f}")
    html = html.replace("__VD__", f"{v['decode']:.0f}")
    html = html.replace("__SD__", f"{s['decode']:.0f}")
    html = html.replace("__HITLO__", str(hit_lo))
    html = html.replace("__HITHI__", str(hit_hi))
    with open("tier_report.html", "w") as fh:
        fh.write(html)


def main():
    runs = load_runs()
    missing = [m for m in ORDER if m not in runs]
    if missing:
        print("missing runs for:", ", ".join(TIER[m] for m in missing))
        return

    print("cost model check (recomputed from tokens vs billed usage.cost):")
    for m in ORDER:
        r = runs[m]
        computed = cost(r["turns"], r["pricing"])
        billed = sum((t["cost"] or 0) for t in r["turns"])
        off = abs(computed - billed) / billed * 100 if billed else 0
        print(f"  {TIER[m]:<9} computed ${computed:.6f}  billed ${billed:.6f}  ({off:.1f}% off)")

    canon = runs["deepseek-v4.1-flash-fast"]["turns"]
    priced = {m: cost(canon, runs[m]["pricing"]) for m in ORDER}
    cheapest = min(priced.values())
    print(f"\nsame workload priced at each tier ({len(canon)}-turn Fast run token profile):")
    for m in ORDER:
        print(f"  {TIER[m]:<9} ${priced[m]:.6f}   {priced[m] / cheapest:.2f}x")

    hits = []
    print("\nactual run per tier (each tier ran it itself, so lengths differ):")
    for m in ORDER:
        r = runs[m]
        ti, tc, to = totals(r["turns"])
        billed = sum((t["cost"] or 0) for t in r["turns"])
        hit = round(tc / ti * 100) if ti else 0
        hits.append(hit)
        print(f"  {TIER[m]:<9} {len(r['turns']):>2} turns  ${billed:.6f}  out {to:>5}  hit {hit}%")

    print("\nspeed, Coral published (/v1/models, 1d):")
    for m in ORDER:
        s = SPEED[m]
        print(f"  {TIER[m]:<9} {s['decode']:>5.0f} tok/s   {s['latency']}s latency")

    build_html(priced, hits)
    print("\nwrote tier_report.html")


TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tier comparison</title>
<style>
  :root { --ink:#1c1b19; --muted:#6c675f; --line:#e4e0d9; --bg:#faf9f7; --card:#fff; --coral:#e05a3f; --teal:#0e9b8e; }
  body { margin:0; background:var(--bg); color:var(--ink); font-family:-apple-system,"Segoe UI",system-ui,sans-serif; line-height:1.5; }
  main { max-width:760px; margin:0 auto; padding:2rem 1.25rem; }
  h1 { font-size:1.4rem; margin:0 0 .3rem; }
  h2 { font-size:1rem; margin:1.6rem 0 .5rem; }
  .meta { color:var(--muted); font-size:.9rem; margin:0 0 1rem; }
  table { border-collapse:collapse; width:100%; font-size:.92rem; font-variant-numeric:tabular-nums; }
  th,td { text-align:right; padding:.45rem .7rem; border-bottom:1px solid var(--line); }
  th:first-child,td:first-child { text-align:left; }
  th { color:var(--muted); font-weight:600; }
  .panel { background:var(--card); border:1px solid var(--line); border-radius:8px; padding:1rem 1.1rem; margin-top:1rem; }
  ul { padding-left:1.1rem; }
  li { margin:.3rem 0; }
  .note { color:var(--muted); font-size:.9rem; }
</style>
</head>
<body>
<main>
  <h1>Fast / Standard / Value on an agent workload</h1>
  <p class="meta">Same tool-using coding-agent workload, one token profile priced at each tier so run length doesn't skew it. Cost recomputed from tokens matches billed usage.cost to 0%. Decode and latency are Coral's published /v1/models figures. Cache hit ran __HITLO__ to __HITHI__% across the three runs.</p>

  <table>
    <thead><tr><th>Tier</th><th>Cost</th><th>vs Value</th><th>Decode tok/s</th><th>Latency</th></tr></thead>
    <tbody>__ROWS__</tbody>
  </table>

  <div class="panel">
    <h2>Relative cost, Value = 1</h2>
    <canvas id="costChart" height="90"></canvas>
  </div>

  <h2>Read</h2>
  <ul>
    <li>Fast costs __FASTM__x Value and runs about __SPEEDR__x faster (__FD__ vs __VD__ tok/s). Worth it when a user is waiting on the agent.</li>
    <li>Standard costs __STDM__x Value but runs at Value's speed (__SD__ tok/s). Its cheaper output is offset by $0.19/M input and charged cache reads, which hurt when most of the input is cache.</li>
    <li>Fast for interactive, Value for background. Standard rarely wins this workload shape.</li>
  </ul>
  <p class="note">Workload-specific: on a low-cache or output-light workload the input and cache penalties shrink and the ranking shifts.</p>
</main>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js"></script>
<script>
new Chart(document.getElementById("costChart"), {
  type: "bar",
  data: { labels: __LABELS__, datasets: [{ data: __MULT__, backgroundColor: ["#e05a3f", "#2f6de0", "#0e9b8e"] }] },
  options: {
    plugins: { legend: { display: false } },
    scales: { y: { ticks: { callback: v => v + "x" } } },
  },
});
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
