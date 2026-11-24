import json
import glob
from collections import defaultdict

TIER = {
    "deepseek-v4.1-flash-fast": "Fast",
    "deepseek-v4.1-flash": "Standard",
    "deepseek-v4.1-flash-value": "Value",
}
ORDER = ["deepseek-v4.1-flash-fast", "deepseek-v4.1-flash", "deepseek-v4.1-flash-value"]


def cost(turns, p):
    total = 0.0
    for t in turns:
        new = t["input"] - t["cached"]
        total += (new * (p["input_per_m"] + p["cache_write_per_m"])
                  + t["cached"] * p["cached_input_per_m"]
                  + t["output"] * p["output_per_m"]) / 1e6
    return total


def load():
    runs = defaultdict(list)
    for path in glob.glob("runs_scale/*.json"):
        d = json.load(open(path))
        runs[d["model"]].append(d)
    return runs


def main():
    runs = load()
    missing = [m for m in ORDER if not runs[m]]
    if missing:
        print("missing:", ", ".join(TIER[m] for m in missing))
        return

    pricing = {m: runs[m][0]["pricing"] for m in ORDER}

    print("cost model check:")
    for m in ORDER:
        for d in runs[m]:
            computed = cost(d["turns"], pricing[m])
            billed = sum((t["cost"] or 0) for t in d["turns"])
            off = abs(computed - billed) / billed * 100 if billed else 0
            print(f"  {TIER[m]:<9} {d['session']}  {off:.1f}% off")

    rep = max(runs[ORDER[0]], key=lambda d: len(d["turns"]))
    print(f"\ncache hit over turns ({rep['session']}):")
    for t in rep["turns"]:
        if t["turn"] in (1, 5, 10, 20, 30, 40):
            hit = t["cached"] / t["input"] * 100 if t["input"] else 0
            print(f"  turn {t['turn']:>2}: {hit:.0f}%")

    warm = [t for t in rep["turns"] if t["input"] and t["cached"] / t["input"] >= 0.90]
    priced = {m: cost(warm, pricing[m]) for m in ORDER}
    cheap = min(priced.values())
    print(f"\nsteady-state workload ({len(warm)} warm turns, hit >=90%) priced at each tier:")
    for m in ORDER:
        print(f"  {TIER[m]:<9} ${priced[m]:.6f}   {priced[m] / cheap:.2f}x")

    print("\nactual aggregate per tier (3 agents, work differs):")
    for m in ORDER:
        c = sum(sum((t["cost"] or 0) for t in d["turns"]) for d in runs[m])
        ti = sum(sum(t["input"] for t in d["turns"]) for d in runs[m])
        tc = sum(sum(t["cached"] for t in d["turns"]) for d in runs[m])
        out = sum(sum(t["output"] for t in d["turns"]) for d in runs[m])
        hit = tc / ti * 100 if ti else 0
        print(f"  {TIER[m]:<9} ${c:.4f}  hit {hit:.0f}%  out {out}")


if __name__ == "__main__":
    main()
