import os
import sys
import json
import time
import uuid
import httpx

BASE = os.environ.get("CORAL_BASE_URL", "https://inference.coralbricks.ai/v1")
MODEL = os.environ.get("CORAL_MODEL", "deepseek-v4.1-flash-fast")

SYSTEM = """You are a senior software engineer agent operating inside a code repository.
You plan before you act, you call tools, and you reason over large context.

Rules:
- Read before you write. Never edit a file you have not opened.
- Prefer small, reversible changes. Explain the why.
- On a failing test, find the root cause, not the symptom.
- Keep secrets out of code. Flag any hardcoded credential.
- When unsure, say so and propose how you would verify.

Tools:
- read_file(path), write_file(path, content), list_dir(path, recursive)
- grep(pattern, path), run_tests(target), run_shell(command)
- git_diff(), open_pr(title, body)

End each turn by stating the single next action you would take.
""" * 6

TURNS = [
    "Our /checkout endpoint intermittently returns 500s under load. Outline how you'd investigate.",
    "list_dir shows a Flask app: app.py, payments.py, db.py, tests/. What do you read first and why?",
    "payments.py opens a new DB connection per request and never closes it. Hypothesis for the 500s?",
    "Walk through how an unclosed connection pool causes intermittent failures under load.",
    "Propose the minimal, reversible fix.",
    "Write the corrected connection handling and describe the change.",
    "What test proves the leak is fixed without a load test?",
    "The new test passes but two older tests now fail with 'database is locked'. What changed?",
    "Diagnose 'database is locked' given your change. Root cause.",
    "Give the corrected approach that fixes the leak without serializing every request.",
    "Summarize the final diff, file by file.",
    "Risk of shipping this on a Friday afternoon?",
    "Draft a PR title and a three-line body.",
    "A reviewer asks why you didn't just raise the connection timeout. Answer them.",
    "What monitoring catches this regression automatically next time?",
    "If the same pattern exists in db.py, how do you confirm it quickly?",
    "Estimate the blast radius if this had been in production for a week.",
    "What generalizes from this to other endpoints?",
    "Your single most important takeaway, one sentence.",
    "State the next action you'd take given the repo right now.",
]


def _send(key, model, session, messages):
    body = {
        "model": model,
        "stream": True,
        "stream_options": {"include_usage": True},
        "prompt_cache_key": session,
        "messages": messages,
        "max_tokens": 400,
    }
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    start = time.perf_counter()
    ttft = None
    text = ""
    usage = None
    with httpx.Client(timeout=httpx.Timeout(180.0, connect=15.0)) as client:
        with client.stream("POST", f"{BASE}/chat/completions", headers=headers, json=body) as r:
            if r.status_code != 200:
                raise RuntimeError(f"HTTP {r.status_code}: {r.read()[:300]!r}")
            for line in r.iter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if chunk.get("choices"):
                    delta = chunk["choices"][0].get("delta", {})
                    if delta.get("content"):
                        ttft = ttft or time.perf_counter() - start
                        text += delta["content"]
                if chunk.get("usage"):
                    usage = chunk["usage"]
    ttft_ms = round(ttft * 1000) if ttft else None
    return text, ttft_ms, usage


def run_live(key, model=MODEL, delay=1.5):
    session = f"run-{uuid.uuid4().hex[:8]}"
    messages = [{"role": "system", "content": SYSTEM}]
    for i, prompt in enumerate(TURNS, 1):
        messages.append({"role": "user", "content": prompt})
        text, ttft_ms, usage = _send(key, model, session, messages)
        messages.append({"role": "assistant", "content": text})
        details = (usage or {}).get("prompt_tokens_details", {}) or {}
        yield {
            "session": session,
            "turn": i,
            "input": (usage or {}).get("prompt_tokens"),
            "cached": details.get("cached_tokens"),
            "output": (usage or {}).get("completion_tokens"),
            "cost": (usage or {}).get("cost"),
            "ttft_ms": ttft_ms,
        }
        time.sleep(delay)


def main():
    key = os.environ.get("CORAL_KEY")
    if not key:
        sys.exit("set CORAL_KEY")
    model = os.environ.get("CORAL_MODEL", MODEL)
    rows = []
    session = None
    for row in run_live(key, model):
        session = row["session"]
        rows.append({k: row[k] for k in ("turn", "input", "cached", "output", "cost", "ttft_ms")})
        print(f"turn {row['turn']:>2}: input={row['input']:>6} cached={row['cached']:>6} cost=${row['cost']:.6f}")
    os.makedirs("runs", exist_ok=True)
    path = os.path.join("runs", f"{session}.json")
    with open(path, "w") as f:
        json.dump({"session": session, "model": model, "turns": rows}, f, indent=2)
    print(f"\nwrote {path}")


if __name__ == "__main__":
    main()
