const usd = (v, dp = 4) => "$" + Number(v).toFixed(dp);
const ktok = n => n >= 1000 ? (n / 1000).toFixed(n >= 10000 ? 0 : 1) + "K" : String(n);
const modelShort = id => (id || "").replace("deepseek-v4.1-", "");
const lbl = r => modelShort(r.model) + " · " + r.session.slice(-4);
const avgTtft = run => {
  const xs = run.turns.map(r => r.ttft_ms).filter(x => x != null);
  return xs.length ? Math.round(xs.reduce((s, x) => s + x, 0) / xs.length) : null;
};

const charts = {};

function setMid(title, hint) {
  document.getElementById("midTitle").textContent = title;
  document.getElementById("midHint").textContent = hint;
}

function draw(id, config) {
  if (charts[id]) charts[id].destroy();
  charts[id] = new Chart(document.getElementById(id), config);
}

function tiles(t) {
  const nocache = t.nocache == null ? "n/a" : "~" + usd(t.nocache, 3);
  const savedsub = t.saved_x == null ? "no price data" : t.saved_x + "× the billed cost";
  const hitsub = ktok(t.cached) + " of " + ktok(t.input) + (t.misses ? " · " + t.misses + " miss" + (t.misses > 1 ? "es" : "") : "");
  const items = [
    ["Run cost", usd(t.cost), t.turns + " turns"],
    ["Served from cache", t.hit + "%", hitsub],
    ["Without caching", nocache, savedsub],
    ["New vs re-read", ktok(t.new), ktok(t.cached) + " re-read"],
  ];
  document.getElementById("tiles").innerHTML = items.map(
    ([l, v, s]) => `<div class="tile"><div class="label">${l}</div><div class="value">${v}</div><div class="sub">${s}</div></div>`
  ).join("");
}

function compareTiles(a, b) {
  const row = r => {
    const t = r.totals;
    const saved = t.saved_x == null ? "n/a" : t.saved_x + "×";
    return `<div class="cmp-row">
      <span class="cmp-model">${modelShort(r.model)}</span>
      <span>cost ${usd(t.cost)}</span>
      <span>no caching ${t.nocache == null ? "n/a" : "~" + usd(t.nocache, 3)}</span>
      <span>${saved}</span>
      <span>hit ${t.hit}%</span>
      <span>out ${ktok(t.output)}</span>
    </div>`;
  };
  document.getElementById("tiles").innerHTML = `<div class="cmp">${row(a)}${row(b)}</div>`;
}

function comparisonTable(a, b) {
  const rows = [
    ["Run cost", r => usd(r.totals.cost)],
    ["Without caching", r => r.totals.nocache == null ? "n/a" : "~" + usd(r.totals.nocache, 3)],
    ["vs no caching", r => r.totals.saved_x == null ? "n/a" : r.totals.saved_x + "×"],
    ["Cache hit", r => r.totals.hit + "%"],
    ["Genuine misses", r => r.totals.misses],
    ["Turns", r => r.totals.turns],
    ["Output tokens", r => r.totals.output.toLocaleString()],
    ["Input re-read", r => r.totals.input.toLocaleString()],
    ["Avg TTFT", r => avgTtft(r) == null ? "-" : avgTtft(r) + " ms"],
  ];
  const head = `<thead><tr><th>Metric</th><th>${lbl(a)}</th><th>${lbl(b)}</th></tr></thead>`;
  const body = "<tbody>" + rows.map(([label, f]) =>
    `<tr><td>${label}</td><td>${f(a)}</td><td>${f(b)}</td></tr>`).join("") + "</tbody>";
  document.getElementById("cmpTable").innerHTML = head + body;
}

function ledger(turns) {
  document.querySelector("#ledger tbody").innerHTML = turns.map(r => `<tr class="${r.miss ? "miss" : ""}">
    <td>${r.turn}</td><td>${r.input.toLocaleString()}</td><td>${r.cached.toLocaleString()}</td>
    <td>${(r.expected ?? 0).toLocaleString()}</td><td>${r.new.toLocaleString()}</td><td>${r.output}</td>
    <td>${r.hit}%</td><td>${usd(r.cost, 6)}</td><td>${r.ttft_ms ?? "-"} ms</td></tr>`).join("");
}

function costChart(run) {
  const data = [
    { label: "With caching", data: run.turns.map(r => r.cum_cost), borderColor: "#e05a3f", pointStyle: "line", tension: 0.2, pointRadius: 0 },
  ];
  if (run.totals.nocache != null) {
    data.push({ label: "Without caching", data: run.turns.map(r => r.cum_nocache), borderColor: "#a39c91", pointStyle: "line", tension: 0.2, pointRadius: 0 });
  }
  draw("costChart", {
    type: "line",
    data: { labels: run.turns.map(r => r.turn), datasets: data },
    options: {
      animation: false,
      scales: { x: { title: { display: true, text: "turn" } }, y: { ticks: { callback: v => "$" + v.toFixed(3) } } },
      plugins: { legend: { position: "bottom", labels: { usePointStyle: true } } },
    },
  });
}

function render(run) {
  const labels = run.turns.map(r => r.turn);
  document.getElementById("ledgerTitle").textContent = "Per turn";
  document.getElementById("perTurnWrap").style.display = "";
  document.getElementById("comparisonWrap").style.display = "none";
  tiles(run.totals);
  ledger(run.turns);
  costChart(run);
  setMid("Input per turn", "Each turn re-sends the whole conversation. The cached part is billed at the model's cached-read rate.");

  draw("inputChart", {
    type: "bar",
    data: {
      labels,
      datasets: [
        { label: "Cached", data: run.turns.map(r => r.cached), backgroundColor: "#0e9b8e" },
        { label: "New", data: run.turns.map(r => r.new), backgroundColor: "#2f6de0" },
      ],
    },
    options: {
      animation: false,
      scales: { x: { stacked: true, title: { display: true, text: "turn" } }, y: { stacked: true, ticks: { callback: v => ktok(v) } } },
      plugins: { legend: { position: "bottom" } },
    },
  });

  draw("hitChart", {
    type: "line",
    data: {
      labels,
      datasets: [{
        label: "Hit rate",
        data: run.turns.map(r => r.hit),
        borderColor: "#e05a3f",
        tension: 0.2,
        pointRadius: run.turns.map(r => r.miss ? 5 : 2),
        pointBackgroundColor: run.turns.map(r => r.miss ? "#b3341f" : "#e05a3f"),
      }],
    },
    options: {
      animation: false,
      scales: { x: { title: { display: true, text: "turn" } }, y: { min: 0, max: 100, ticks: { callback: v => v + "%" } } },
      plugins: { legend: { display: false } },
    },
  });

  draw("ttftChart", {
    type: "bar",
    data: { labels, datasets: [{ label: "TTFT", data: run.turns.map(r => r.ttft_ms), backgroundColor: "#2f6de0" }] },
    options: {
      animation: false,
      scales: { x: { title: { display: true, text: "turn" } }, y: { title: { display: true, text: "ms" } } },
      plugins: { legend: { display: false } },
    },
  });
}

function renderCompare(a, b) {
  compareTiles(a, b);
  comparisonTable(a, b);
  document.getElementById("ledgerTitle").textContent = "Comparison";
  document.getElementById("perTurnWrap").style.display = "none";
  document.getElementById("comparisonWrap").style.display = "";
  setMid("Cost per turn", "Billed cost each turn for each model on the same task.");

  const labels = (a.turns.length >= b.turns.length ? a : b).turns.map(r => r.turn);

  const line = (run, color, nocache) => ({
    label: (nocache ? "no cache " : "") + lbl(run),
    data: run.turns.map(r => nocache ? r.cum_nocache : r.cum_cost),
    borderColor: color, pointStyle: "line", tension: 0.2, pointRadius: 0,
  });
  const costSets = [line(a, "#e05a3f", false), line(b, "#2f6de0", false)];
  if (a.totals.nocache != null) costSets.push(line(a, "#f0a58f", true));
  if (b.totals.nocache != null) costSets.push(line(b, "#93b4f0", true));
  draw("costChart", {
    type: "line",
    data: { labels, datasets: costSets },
    options: {
      animation: false,
      scales: { x: { title: { display: true, text: "turn" } }, y: { ticks: { callback: v => "$" + v.toFixed(3) } } },
      plugins: { legend: { position: "bottom", labels: { usePointStyle: true } } },
    },
  });

  const perTurn = (run, color, key) => ({ label: lbl(run), data: run.turns.map(r => r[key]), backgroundColor: color });
  draw("inputChart", {
    type: "bar",
    data: { labels, datasets: [perTurn(a, "#e05a3f", "cost"), perTurn(b, "#2f6de0", "cost")] },
    options: {
      animation: false,
      scales: { x: { title: { display: true, text: "turn" } }, y: { ticks: { callback: v => "$" + v.toFixed(4) } } },
      plugins: { legend: { position: "bottom" } },
    },
  });

  draw("hitChart", {
    type: "line",
    data: {
      labels,
      datasets: [
        { label: lbl(a), data: a.turns.map(r => r.hit), borderColor: "#e05a3f", tension: 0.2, pointRadius: 2 },
        { label: lbl(b), data: b.turns.map(r => r.hit), borderColor: "#2f6de0", tension: 0.2, pointRadius: 2 },
      ],
    },
    options: {
      animation: false,
      scales: { x: { title: { display: true, text: "turn" } }, y: { min: 0, max: 100, ticks: { callback: v => v + "%" } } },
      plugins: { legend: { position: "bottom" } },
    },
  });

  draw("ttftChart", {
    type: "bar",
    data: { labels, datasets: [perTurn(a, "#e05a3f", "ttft_ms"), perTurn(b, "#2f6de0", "ttft_ms")] },
    options: {
      animation: false,
      scales: { x: { title: { display: true, text: "turn" } }, y: { title: { display: true, text: "ms" } } },
      plugins: { legend: { position: "bottom" } },
    },
  });
}

function totalsFrom(turns) {
  const input = turns.reduce((s, r) => s + r.input, 0);
  const cached = turns.reduce((s, r) => s + r.cached, 0);
  const output = turns.reduce((s, r) => s + r.output, 0);
  const last = turns[turns.length - 1];
  return {
    turns: turns.length,
    input, cached, new: input - cached, output,
    hit: input ? +(cached / input * 100).toFixed(1) : 0,
    misses: turns.filter(r => r.miss).length,
    cost: last.cum_cost,
    nocache: last.cum_nocache,
    saved_x: last.cum_cost ? +(last.cum_nocache / last.cum_cost).toFixed(2) : null,
  };
}

const getRun = s => fetch("/api/run/" + s).then(r => r.json());

async function refresh() {
  const a = document.getElementById("run").value;
  const b = document.getElementById("run2").value;
  if (!a) return;
  if (b && b !== a) {
    const [ra, rb] = await Promise.all([getRun(a), getRun(b)]);
    renderCompare(ra, rb);
  } else {
    render(await getRun(a));
  }
}

function setStatus(msg) {
  document.getElementById("status").textContent = msg || "";
}

function runLive() {
  const btn = document.getElementById("live");
  btn.disabled = true;
  setStatus("running...");
  document.getElementById("run2").value = "";
  const turns = [];
  const es = new EventSource("/api/live");
  es.onmessage = ev => {
    const msg = JSON.parse(ev.data);
    if (msg.error) {
      setStatus(msg.error);
      es.close();
      btn.disabled = false;
      return;
    }
    if (msg.turn) {
      turns.push(msg.turn);
      setStatus("turn " + msg.turn.turn);
      render({ model: "live", turns, totals: totalsFrom(turns) });
    }
    if (msg.done) {
      es.close();
      btn.disabled = false;
      setStatus("done");
      refreshRuns(msg.done);
    }
  };
  es.onerror = () => {
    es.close();
    btn.disabled = false;
    setStatus("connection closed");
  };
}

async function refreshRuns(selected) {
  const runs = await (await fetch("/api/runs")).json();
  const opts = runs.map(r => `<option value="${r.session}">${modelShort(r.model)} · ${r.session}</option>`).join("");
  const sel = document.getElementById("run");
  sel.innerHTML = opts;
  if (selected) sel.value = selected;
  document.getElementById("run2").innerHTML = `<option value="">none</option>` + opts;
}

async function init() {
  await refreshRuns();
  document.getElementById("run").addEventListener("change", refresh);
  document.getElementById("run2").addEventListener("change", refresh);
  document.getElementById("live").addEventListener("click", runLive);
  refresh();
}

init();
