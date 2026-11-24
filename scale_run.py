import os
import sys
import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from capture import SYSTEM, tool_result, fetch_pricing, _send

TURNS = int(os.environ.get("SCALE_TURNS", "40"))
AGENTS = int(os.environ.get("SCALE_AGENTS", "1"))

BACKLOG = [
    "Find the root cause of the intermittent 500s under load on /checkout and /refund. Read the code and run the tests before concluding.",
    "Write the minimal fix for that root cause and show the updated file.",
    "Add a regression test that would have caught it, and say where it goes.",
    "Check whether /orders and /health share the same problem. Cite the files.",
    "Review auth.py and config.py for anything that would bite under load.",
    "Sketch a connection pooling approach for db.py and the tradeoffs.",
    "Write a short on-call runbook: the symptom, how to confirm it, the fix.",
    "List the remaining risks in the service and how you would test each.",
]


def run_session(key, model):
    session = f"scale-{uuid.uuid4().hex[:8]}"
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": BACKLOG[0]},
    ]
    task_i = 1
    rows = []
    for step in range(1, TURNS + 1):
        content, tool_calls, finish, ttft_ms, total_ms, usage = _send(key, model, session, messages)
        details = (usage or {}).get("prompt_tokens_details", {}) or {}
        out = (usage or {}).get("completion_tokens")
        rows.append({
            "turn": step,
            "input": (usage or {}).get("prompt_tokens"),
            "cached": details.get("cached_tokens"),
            "output": out,
            "cache_write": (usage or {}).get("cache_write_tokens"),
            "cost": (usage or {}).get("cost"),
            "ttft_ms": ttft_ms,
        })
        assistant = {"role": "assistant", "content": content or None}
        if tool_calls:
            assistant["tool_calls"] = [
                {"id": c["id"], "type": "function",
                 "function": {"name": c["name"], "arguments": c["arguments"]}}
                for c in tool_calls
            ]
        messages.append(assistant)
        if tool_calls:
            for c in tool_calls:
                try:
                    args = json.loads(c["arguments"] or "{}")
                except json.JSONDecodeError:
                    args = {}
                messages.append({"role": "tool", "tool_call_id": c["id"],
                                 "content": tool_result(c["name"], args)})
        else:
            # finished a task, give it the next one
            messages.append({"role": "user", "content": BACKLOG[task_i % len(BACKLOG)]})
            task_i += 1
        time.sleep(0.5)
    return session, rows


def main():
    key = os.environ.get("CORAL_KEY")
    if not key:
        sys.exit("set CORAL_KEY")
    model = os.environ.get("CORAL_MODEL", "deepseek-v4.1-flash-fast")
    pricing = fetch_pricing(key, model)
    os.makedirs("runs_scale", exist_ok=True)

    def worker(_):
        session, rows = run_session(key, model)
        path = os.path.join("runs_scale", f"{session}.json")
        with open(path, "w") as f:
            json.dump({"session": session, "model": model, "pricing": pricing, "turns": rows}, f, indent=2)
        hits = [r["cached"] / r["input"] * 100 for r in rows if r["input"]]
        cost = sum((r["cost"] or 0) for r in rows)
        last = sum(hits[-5:]) / len(hits[-5:]) if hits else 0
        print(f"{model}  {session}: {len(rows)} turns, last-5 hit {last:.0f}%, cost ${cost:.4f}")
        return session

    start = time.time()
    with ThreadPoolExecutor(max_workers=AGENTS) as ex:
        list(ex.map(worker, range(AGENTS)))
    print(f"done, {AGENTS} agents x {TURNS} turns in {time.time() - start:.0f}s")


if __name__ == "__main__":
    main()
