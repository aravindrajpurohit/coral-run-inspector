const usd = (v, dp = 4) => "$" + Number(v).toFixed(dp);
const ktok = n => n >= 1000 ? (n / 1000).toFixed(n >= 10000 ? 0 : 1) + "K" : String(n);

const charts = {};
let live = null;

function tiles(t) {
  const items = [
    ["Run cost", usd(t.cost), t.turns + " turns"],
    ["Served from cache", t.hit + "%", ktok(t.cached) + " of " + ktok(t.input) + " input"],
    ["Without caching", "~" + usd(t.nocache, 3), (t.saved_x ?? "-") + "x more"],
    ["New vs re-read", ktok(t.new), ktok(t.cached) + " re-read free"],
  ];
  document.getElementById("tiles").innerHTML = items.map(
    ([l, v, s]) => `<div class="tile"><div class="label">${l}</div><div class="value">${v}</div><div class="sub">${s}</div></div>`
  ).join("");
}

function ledger(turns) {
  document.querySelector("#ledger tbody").innerHTML = turns.map(r => `<tr>
    <td>${r.turn}</td><td>${r.input.toLocaleString()}</td><td>${r.cached.toLocaleString()}</td>
    <td>${r.new.toLocaleString()}</td><td>${r.output}</td><td>${r.hit}%</td>
    <td>${usd(r.cost, 6)}</td><td>${r.ttft_ms ?? "-"} ms</td></tr>`).join("");
}

function draw(id, config) {
  if (charts[id]) charts[id].destroy();
  charts[id] = new Chart(document.getElementById(id), config);
}

function render(run) {
  const labels = run.turns.map(r => r.turn);
  tiles(run.totals);
  ledger(run.turns);

  draw("costChart", {
    type: "line",
    data: {
      labels,
      datasets: [
        { label: "With caching", data: run.turns.map(r => r.cum_cost), borderColor: "#e05a3f", pointStyle: "line", tension: 0.2, pointRadius: 0 },
        { label: "Without caching", data: run.turns.map(r => r.cum_nocache), borderColor: "#a39c91", borderDash: [5, 4], pointStyle: "line", tension: 0.2, pointRadius: 0 },
      ],
    },
    options: {
      animation: false,
      scales: { x: { title: { display: true, text: "turn" } }, y: { ticks: { callback: v => "$" + v.toFixed(3) } } },
      plugins: { legend: { position: "bottom", labels: { usePointStyle: true } } },
    },
  });

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
    data: { labels, datasets: [{ label: "Hit rate", data: run.turns.map(r => r.hit), borderColor: "#e05a3f", tension: 0.2, pointRadius: 2 }] },
    options: {
      animation: false,
      scales: { x: { title: { display: true, text: "turn" } }, y: { min: 0, max: 100, ticks: { callback: v => v + "%" } } },
      plugins: { legend: { display: false } },
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
    cost: last.cum_cost,
    nocache: last.cum_nocache,
    saved_x: last.cum_cost ? +(last.cum_nocache / last.cum_cost).toFixed(1) : null,
  };
}

async function loadRun(session) {
  const run = await (await fetch("/api/run/" + session)).json();
  render(run);
}

function setStatus(msg) {
  document.getElementById("status").textContent = msg || "";
}

function runLive() {
  const btn = document.getElementById("live");
  btn.disabled = true;
  setStatus("running...");
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
      setStatus("turn " + msg.turn.turn + " of 20");
      render({ turns, totals: totalsFrom(turns) });
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
  const select = document.getElementById("run");
  select.innerHTML = runs.map(r => `<option value="${r.session}">${r.session} (${r.turns} turns)</option>`).join("");
  if (selected) select.value = selected;
}

async function init() {
  await refreshRuns();
  const select = document.getElementById("run");
  select.addEventListener("change", () => loadRun(select.value));
  document.getElementById("live").addEventListener("click", runLive);
  if (select.value) loadRun(select.value);
}

init();
