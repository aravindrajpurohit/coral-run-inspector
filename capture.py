import os
import sys
import json
import time
import uuid
import httpx

BASE = os.environ.get("CORAL_BASE_URL", "https://inference.coralbricks.ai/v1")
MODEL = os.environ.get("CORAL_MODEL", "deepseek-v4.1-flash-fast")
MAX_STEPS = int(os.environ.get("CORAL_MAX_STEPS", "24"))

SYSTEM = """You are a software engineer agent working inside a code repository.
Work methodically: list the files, read the ones that matter, search for patterns, and run
the tests before you conclude — don't guess from file names alone. Call tools when you need
to see something. When you have enough, give the root cause, the minimal fix, whether other
endpoints share the problem, and a regression test, citing the files and lines you used.
"""

TASK = ("Users report intermittent HTTP 500s under load on POST /checkout and POST /refund. "
        "Audit the service with the tools, find the root cause, propose the smallest fix, say "
        "whether other endpoints share the problem, and sketch a regression test that would "
        "catch it. Read the relevant files and run the tests before you conclude.")

REPO = {
    "app.py": """import logging
from flask import Flask, request, jsonify
from auth import require_key
from orders import create_order, get_order
from payments import charge, refund
from inventory import reserve, release, check_stock
from db import get_connection

app = Flask(__name__)
log = logging.getLogger("store")


@app.get("/health")
def health():
    conn = get_connection()
    conn.execute("SELECT 1")
    return jsonify({"ok": True})


@app.post("/checkout")
@require_key
def checkout():
    body = request.get_json()
    if not check_stock(body["sku"], body["qty"]):
        return jsonify({"ok": False, "error": "out_of_stock"}), 409
    reserve(body["sku"], body["qty"])
    order_id = create_order(body["sku"], body["qty"])
    result = charge(body["amount"])
    log.info("checkout order=%s charge=%s", order_id, result)
    return jsonify({"ok": True, "order": order_id, "charge": result})


@app.post("/refund")
@require_key
def refund_order():
    body = request.get_json()
    order = get_order(body["order_id"])
    if order is None:
        return jsonify({"ok": False, "error": "not_found"}), 404
    release(order["sku"], order["qty"])
    result = refund(body["charge_id"])
    return jsonify({"ok": True, "refund": result})


@app.get("/orders/<int:order_id>")
@require_key
def order_status(order_id):
    order = get_order(order_id)
    if order is None:
        return jsonify({"ok": False, "error": "not_found"}), 404
    return jsonify({"ok": True, "order": order})
""",
    "db.py": """import sqlite3
from config import DB_PATH

# Every caller gets a brand-new connection and none of them close it. sqlite
# serializes writers behind a single lock, so once enough handlers are mid-write
# the next INSERT/UPDATE blocks and eventually raises "database is locked".
# There is no pool and no busy timeout wired in (see config.LOCK_TIMEOUT).
def get_connection():
    return sqlite3.connect(DB_PATH)


def init_db():
    from models import SCHEMA
    conn = get_connection()
    conn.executescript(SCHEMA)
    conn.commit()
""",
    "payments.py": """from db import get_connection


def charge(amount):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO charges (amount, status) VALUES (?, 'captured')", (amount,))
    conn.commit()
    return {"id": cur.lastrowid, "amount": amount, "status": "captured"}


def refund(charge_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE charges SET status = 'refunded' WHERE id = ?", (charge_id,))
    conn.commit()
    if cur.rowcount == 0:
        raise ValueError(f"no charge {charge_id}")
    return {"charge_id": charge_id, "status": "refunded"}


def charge_status(charge_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT status FROM charges WHERE id = ?", (charge_id,))
    row = cur.fetchone()
    return row[0] if row else None
""",
    "inventory.py": """from db import get_connection


def check_stock(sku, qty):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT available FROM stock WHERE sku = ?", (sku,))
    row = cur.fetchone()
    return bool(row) and row[0] >= qty


def reserve(sku, qty):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE stock SET available = available - ? WHERE sku = ?", (qty, sku))
    conn.commit()


def release(sku, qty):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE stock SET available = available + ? WHERE sku = ?", (qty, sku))
    conn.commit()
""",
    "orders.py": """from db import get_connection


def create_order(sku, qty):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO orders (sku, qty) VALUES (?, ?)", (sku, qty))
    conn.commit()
    return cur.lastrowid


def get_order(order_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, sku, qty FROM orders WHERE id = ?", (order_id,))
    row = cur.fetchone()
    if row is None:
        return None
    return {"id": row[0], "sku": row[1], "qty": row[2]}
""",
    "auth.py": """import functools
from flask import request, jsonify
from config import API_KEYS


def require_key(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        key = request.headers.get("X-API-Key")
        if key not in API_KEYS:
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        return fn(*args, **kwargs)
    return wrapper
""",
    "config.py": """import os

DB_PATH = os.environ.get("STORE_DB", "store.db")
API_KEYS = set(os.environ.get("API_KEYS", "dev-key").split(","))
LOCK_TIMEOUT = 5          # seconds; intended for get_connection, not wired in yet
MAX_CONNECTIONS = 20      # advisory; nothing enforces it today
""",
    "models.py": """SCHEMA = '''
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY, sku TEXT NOT NULL, qty INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS charges (
    id INTEGER PRIMARY KEY, amount REAL NOT NULL, status TEXT DEFAULT 'captured'
);
CREATE TABLE IF NOT EXISTS stock (
    sku TEXT PRIMARY KEY, available INTEGER NOT NULL DEFAULT 0
);
'''
""",
    "tests/test_checkout.py": """import threading
from app import app

HEADERS = {"X-API-Key": "dev-key"}


def test_checkout_ok():
    client = app.test_client()
    r = client.post("/checkout", json={"sku": "A1", "qty": 1, "amount": 9.99}, headers=HEADERS)
    assert r.status_code == 200


def test_checkout_rejects_without_key():
    client = app.test_client()
    r = client.post("/checkout", json={"sku": "A1", "qty": 1, "amount": 9.99})
    assert r.status_code == 401


def test_checkout_under_load():
    client = app.test_client()
    errors = []

    def hit():
        r = client.post("/checkout", json={"sku": "A1", "qty": 1, "amount": 9.99}, headers=HEADERS)
        if r.status_code != 200:
            errors.append(r.status_code)

    threads = [threading.Thread(target=hit) for _ in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
""",
    "tests/test_refund.py": """from app import app

HEADERS = {"X-API-Key": "dev-key"}


def test_refund_unknown_order():
    client = app.test_client()
    r = client.post("/refund", json={"order_id": 999, "charge_id": 1}, headers=HEADERS)
    assert r.status_code == 404
""",
    "tests/test_inventory.py": """from inventory import check_stock, reserve, release


def test_check_stock_reflects_reserve():
    # assumes stock seeded with sku X1 at 10
    start = check_stock("X1", 1)
    reserve("X1", 1)
    release("X1", 1)
    assert start is True
""",
    "README.md": """# store

Checkout / refund / inventory service backed by SQLite.

- app.py        HTTP routes
- auth.py       X-API-Key check
- orders.py     order rows
- payments.py   charges and refunds
- inventory.py  stock levels
- db.py         connection handling
- models.py     schema
- config.py     settings

Run the suite with `pytest`. test_checkout_under_load reproduces the production issue.
""",
}

TOOLS = [
    {"type": "function", "function": {
        "name": "list_dir",
        "description": "List the files in the repository.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    }},
    {"type": "function", "function": {
        "name": "read_file",
        "description": "Return the contents of a file.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
    }},
    {"type": "function", "function": {
        "name": "grep",
        "description": "Search the repository for a substring and return matching lines.",
        "parameters": {"type": "object", "properties": {"pattern": {"type": "string"}}, "required": ["pattern"]},
    }},
    {"type": "function", "function": {
        "name": "run_tests",
        "description": "Run the test suite and return its output.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    }},
]


def tool_result(name, args):
    if name == "list_dir":
        return "\n".join(sorted(REPO))
    if name == "read_file":
        path = args.get("path", "")
        return REPO.get(path, f"no such file: {path}")
    if name == "grep":
        pat = args.get("pattern", "")
        hits = [f"{fn}:{i}: {ln.strip()}"
                for fn, body in REPO.items()
                for i, ln in enumerate(body.splitlines(), 1) if pat in ln]
        return "\n".join(hits) or f"no matches for {pat!r}"
    if name == "run_tests":
        return ("tests/test_checkout.py::test_checkout_ok PASSED\n"
                "tests/test_checkout.py::test_checkout_rejects_without_key PASSED\n"
                "tests/test_checkout.py::test_checkout_under_load FAILED\n"
                "tests/test_refund.py::test_refund_unknown_order PASSED\n"
                "tests/test_inventory.py::test_check_stock_reflects_reserve PASSED\n"
                "E   sqlite3.OperationalError: database is locked")
    return f"unknown tool: {name}"


def fetch_pricing(key, model):
    headers = {"Authorization": f"Bearer {key}"}
    with httpx.Client(timeout=30) as client:
        r = client.get(f"{BASE}/models", headers=headers)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
        for m in r.json().get("data", []):
            if m.get("id") == model:
                return m.get("pricing", {})
    raise RuntimeError(f"{model} not in /models")


def _send(key, model, session, messages):
    body = {
        "model": model,
        "stream": True,
        "stream_options": {"include_usage": True},
        "prompt_cache_key": session,
        "messages": messages,
        "tools": TOOLS,
    }
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    start = time.perf_counter()
    ttft = None
    content = ""
    calls = {}
    finish = None
    usage = None
    with httpx.Client(timeout=httpx.Timeout(300.0, connect=15.0)) as client:
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
                for ch in chunk.get("choices", []):
                    delta = ch.get("delta", {})
                    if delta.get("content"):
                        ttft = ttft or time.perf_counter() - start
                        content += delta["content"]
                    for tc in delta.get("tool_calls") or []:
                        ttft = ttft or time.perf_counter() - start
                        slot = calls.setdefault(tc.get("index", 0), {"id": None, "name": "", "arguments": ""})
                        if tc.get("id"):
                            slot["id"] = tc["id"]
                        fn = tc.get("function") or {}
                        slot["name"] += fn.get("name") or ""
                        slot["arguments"] += fn.get("arguments") or ""
                    if ch.get("finish_reason"):
                        finish = ch["finish_reason"]
                if chunk.get("usage"):
                    usage = chunk["usage"]
    tool_calls = [calls[i] for i in sorted(calls)]
    ttft_ms = round(ttft * 1000) if ttft else None
    return content, tool_calls, finish, ttft_ms, usage


def run_live(key, model=MODEL, delay=1.0):
    session = f"run-{uuid.uuid4().hex[:8]}"
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": TASK},
    ]
    for step in range(1, MAX_STEPS + 1):
        content, tool_calls, finish, ttft_ms, usage = _send(key, model, session, messages)
        details = (usage or {}).get("prompt_tokens_details", {}) or {}
        yield {
            "session": session,
            "turn": step,
            "input": (usage or {}).get("prompt_tokens"),
            "cached": details.get("cached_tokens"),
            "output": (usage or {}).get("completion_tokens"),
            "cache_write": (usage or {}).get("cache_write_tokens"),
            "cost": (usage or {}).get("cost"),
            "ttft_ms": ttft_ms,
            "tools": [c["name"] for c in tool_calls],
        }
        assistant = {"role": "assistant", "content": content or None}
        if tool_calls:
            assistant["tool_calls"] = [
                {"id": c["id"], "type": "function",
                 "function": {"name": c["name"], "arguments": c["arguments"]}}
                for c in tool_calls
            ]
        messages.append(assistant)
        if not tool_calls:
            break
        for c in tool_calls:
            try:
                args = json.loads(c["arguments"] or "{}")
            except json.JSONDecodeError:
                args = {}
            messages.append({"role": "tool", "tool_call_id": c["id"],
                             "content": tool_result(c["name"], args)})
        time.sleep(delay)


def main():
    key = os.environ.get("CORAL_KEY")
    if not key:
        sys.exit("set CORAL_KEY")
    model = os.environ.get("CORAL_MODEL", MODEL)
    pricing = fetch_pricing(key, model)
    rows = []
    session = None
    for row in run_live(key, model):
        session = row["session"]
        rows.append({k: row[k] for k in ("turn", "input", "cached", "output", "cache_write", "cost", "ttft_ms", "tools")})
        tools = ",".join(row["tools"]) or "answer"
        print(f"turn {row['turn']:>2}: input={row['input']:>6} cached={row['cached']:>6} cost=${(row['cost'] or 0):.6f}  {tools}")
    os.makedirs("runs", exist_ok=True)
    path = os.path.join("runs", f"{session}.json")
    with open(path, "w") as f:
        json.dump({"session": session, "model": model, "pricing": pricing, "turns": rows}, f, indent=2)
    print(f"\nwrote {path}")


if __name__ == "__main__":
    main()
