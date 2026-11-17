// End-to-end checks of every interactive feature, in a real Chrome over the DevTools protocol.
// Real mouse moves, clicks and key presses; console errors and exceptions are collected.
// Needs: a static server on BASE and Chrome started with --remote-debugging-port=PORT.
//   python -m http.server -d docs 8765
//   chrome --headless=new --remote-debugging-port=9333 --user-data-dir=<tmp> about:blank
//   node docs/tests/e2e.mjs [base] [port]
const BASE = process.argv[2] ?? "http://localhost:8765";
const PORT = process.argv[3] ?? "9333";
const results = [];
let pageErrors = [];

async function openTab(url) {
  const t = await (await fetch(`http://127.0.0.1:${PORT}/json/new?${encodeURIComponent(url)}`, { method: "PUT" })).json();
  const ws = new WebSocket(t.webSocketDebuggerUrl);
  await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });
  let id = 0;
  const pending = new Map();
  const listeners = [];
  ws.onmessage = (m) => {
    const d = JSON.parse(m.data);
    if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); }
    else listeners.forEach((f) => f(d));
  };
  const send = (method, params = {}) => new Promise((r) => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
  listeners.push((d) => {
    if (d.method === "Runtime.exceptionThrown") pageErrors.push(d.params.exceptionDetails.exception?.description ?? d.params.exceptionDetails.text);
    if (d.method === "Runtime.consoleAPICalled" && ["error", "warning"].includes(d.params.type))
      pageErrors.push(`console.${d.params.type}: ${d.params.args.map((a) => a.value ?? a.description).join(" ")}`);
    if (d.method === "Log.entryAdded" && d.params.entry.level === "error" && !/favicon/.test(d.params.entry.url ?? ""))
      pageErrors.push(`log: ${d.params.entry.text} ${d.params.entry.url ?? ""}`);
  });
  await send("Runtime.enable"); await send("Log.enable"); await send("Page.enable");
  const tab = {
    async eval(expr) {
      const r = await send("Runtime.evaluate", { expression: `(async () => { ${expr} })()`, awaitPromise: true, returnByValue: true });
      if (r.result?.exceptionDetails) throw new Error(r.result.exceptionDetails.exception?.description ?? "eval failed");
      return r.result?.result?.value;
    },
    async go(path, width = 1280, height = 900) {
      pageErrors = [];
      await send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: width < 600 });
      await send("Page.navigate", { url: BASE + "/" + path });
      await tab.waitFor("document.readyState === 'complete'");
      await sleep(400);
    },
    async waitFor(cond, ms = 8000) {
      const t0 = Date.now();
      while (Date.now() - t0 < ms) { if (await tab.eval(`return !!(${cond})`)) return true; await sleep(100); }
      return false;
    },
    async key(key, code = key, keyCode = 0, shift = false) {
      const text = key === "Enter" ? "\r" : undefined;
      await send("Input.dispatchKeyEvent", { type: text ? "keyDown" : "rawKeyDown", key, code, windowsVirtualKeyCode: keyCode, text, modifiers: shift ? 8 : 0 });
      await send("Input.dispatchKeyEvent", { type: "keyUp", key, code, windowsVirtualKeyCode: keyCode, modifiers: shift ? 8 : 0 });
      await sleep(60);
    },
    async type(text) { await send("Input.insertText", { text }); await sleep(150); },
    async mouse(x, y) { await send("Input.dispatchMouseEvent", { type: "mouseMoved", x, y }); await sleep(80); },
    async click(x, y) {
      for (const type of ["mousePressed", "mouseReleased"]) await send("Input.dispatchMouseEvent", { type, x, y, button: "left", clickCount: 1 });
      await sleep(150);
    },
    async clickEl(sel) {
      const b = await tab.eval(`const e = document.querySelector(${JSON.stringify(sel)}); if (!e) return null; e.scrollIntoView({block:'center'}); const r = e.getBoundingClientRect(); return {x: r.x + r.width/2, y: r.y + r.height/2}`);
      if (!b) throw new Error(`no element ${sel}`);
      await sleep(100);
      const c = await tab.eval(`const r = document.querySelector(${JSON.stringify(sel)}).getBoundingClientRect(); return {x: r.x + r.width/2, y: r.y + r.height/2}`);
      await tab.click(c.x, c.y);
    },
    async focus(sel) { await tab.eval(`document.querySelector(${JSON.stringify(sel)}).focus()`); await sleep(60); },
    text: (sel) => tab.eval(`return document.querySelector(${JSON.stringify(sel)})?.textContent?.trim() ?? null`),
    close: () => { ws.close(); return fetch(`http://127.0.0.1:${PORT}/json/close/${t.id}`); },
  };
  return tab;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
function check(page, name, ok, info = "") { results.push({ page, name, ok: !!ok, info }); }
function errors(page) { check(page, "no console errors", pageErrors.length === 0, pageErrors.slice(0, 4).join(" | ")); }

const tab = await openTab("about:blank");

// ---------------------------------------------------------------- replay
{
  const P = "replay";
  await tab.go("index.html");
  check(P, "featured chase loads", await tab.waitFor(`document.querySelector('#match-title')?.textContent && !/Loading/.test(document.querySelector('#match-title').textContent)`));
  check(P, "deep link written to URL", /match=\d+/.test(await tab.eval("return location.search")));
  const chartDrawn = await tab.waitFor(`window.Chart && Chart.getChart(document.querySelector('#chart'))`);
  check(P, "chart drawn", chartDrawn);
  const s0 = await tab.text("#detail");
  // hover the chart
  const box = await tab.eval(`document.querySelector('#chart-box').scrollIntoView({block:'center'}); const r = document.querySelector('#chart').getBoundingClientRect(); return {x:r.x, y:r.y, w:r.width, h:r.height}`);
  await sleep(150);
  const box2 = await tab.eval(`const r = document.querySelector('#chart').getBoundingClientRect(); return {x:r.x, y:r.y, w:r.width, h:r.height}`);
  await tab.mouse(box2.x + box2.w * 0.6, box2.y + box2.h * 0.5);
  const sHover = await tab.text("#detail");
  check(P, "hovering the chart updates the scoreboard", sHover && sHover !== s0, `${s0} -> ${sHover}`);
  // keyboard
  await tab.focus("#chart-box");
  await tab.key("Home", "Home", 36);
  const sHome = await tab.text("#detail");
  await tab.key("ArrowRight", "ArrowRight", 39);
  const sRight = await tab.text("#detail");
  check(P, "ArrowRight steps one ball", sRight !== sHome && /Ball 0\.1|Over 0\.1|0\.1/.test(sRight), sRight);
  await tab.key("End", "End", 35);
  check(P, "End jumps to the decided ball", /decided/i.test(await tab.text("#detail") + await tab.eval("return document.body.textContent")), await tab.text("#detail"));
  check(P, "live region announces", (await tab.text("#live"))?.length > 10);
  // table
  await tab.clickEl("#table-toggle");
  const rows = await tab.eval(`const w = document.querySelector('#ball-table-wrap'); return w.hidden ? -1 : w.querySelectorAll('tbody tr').length`);
  check(P, "View as table shows every ball", rows > 100, `rows ${rows}`);
  await tab.clickEl("#table-toggle");
  // search
  const before = await tab.eval(`return (document.querySelectorAll('#match-select option').length || document.querySelectorAll('#match-list li').length)`);
  await tab.focus("#search");
  await tab.type("Mumbai");
  const after = await tab.eval(`return (document.querySelectorAll('#match-select option').length || document.querySelectorAll('#match-list li').length)`);
  check(P, "typing in search filters the chases", after < before && after > 0, `${before} -> ${after}`);
  const t1 = await tab.text("#match-title");
  await tab.key("Enter", "Enter", 13);
  await sleep(600);
  const t2 = await tab.text("#match-title");
  check(P, "Enter opens a matching chase", /Mumbai/.test(t2) && t2 !== t1, t2);
  // season / team filters (select or pills)
  const hasSelect = await tab.eval("return !!document.querySelector('#season')");
  if (hasSelect) {
    await tab.eval(`const s = document.querySelector('#search'); s.value=''; s.dispatchEvent(new Event('input'));
      const e = document.querySelector('#season'); e.value = e.options[e.options.length-1].value; e.dispatchEvent(new Event('change'))`);
    await sleep(200);
    const n = await tab.eval(`return document.querySelectorAll('#match-select option').length`);
    check(P, "season filter narrows the list", n > 1 && n < before, `options ${n}`);
    await tab.eval(`const e = document.querySelector('#team'); e.value = e.options[3].value; e.dispatchEvent(new Event('change'))`);
    await sleep(200);
    const n2 = await tab.eval(`return document.querySelectorAll('#match-select option').length`);
    check(P, "team filter narrows the list", n2 >= 1 && n2 < n, `options ${n2}`);
    await tab.eval(`const e = document.querySelector('#match-select'); e.value = e.options[1].value; e.dispatchEvent(new Event('change'))`);
    await sleep(600);
    check(P, "choosing a chase opens it", (await tab.eval("return location.search")).includes(await tab.eval("return document.querySelector('#match-select').value")));
  } else {
    await tab.eval(`const s = document.querySelector('#search'); s.value=''; s.dispatchEvent(new Event('input'))`);
    await tab.clickEl("#season-pills button:last-child");
    const n = await tab.eval(`return document.querySelectorAll('#match-list li').length`);
    check(P, "season filter narrows the list", n > 1 && n < before, `rows ${n}`);
    await tab.clickEl("#team-badges button:nth-child(2)");
    const n2 = await tab.eval(`return document.querySelectorAll('#match-list li').length`);
    check(P, "team filter narrows the list", n2 >= 1 && n2 < n, `rows ${n2}`);
    const id = await tab.eval(`return document.querySelector('#match-list .match-row').dataset.id`);
    await tab.clickEl("#match-list .match-row");
    await sleep(600);
    check(P, "clicking a chase opens it", (await tab.eval("return location.search")).includes(id), id);
  }
  await tab.clickEl("#featured");
  await sleep(600);
  check(P, "featured button returns to the featured chase", (await tab.eval("return location.search")).includes("1527688"));
  errors(P);
  await tab.go("index.html?match=999");
  await sleep(800);
  check(P, "unknown match id shows a notice", /isn't one of|couldn't be loaded/.test(await tab.eval("return document.body.textContent")));
  // score strip and predictor follow the selected ball
  await tab.go("index.html?match=1527688");
  await tab.waitFor(`/Lucknow/.test(document.querySelector('#match-title').textContent)`);
  check(P, "score strip shows both team badges", (await tab.text("#sb-chase")) === "LSG" && (await tab.text("#sb-defend")) === "KKR");
  await tab.focus("#chart-box");
  await tab.key("End", "End", 35);
  check(P, "decided ball shows the result on the strip", /won by/.test(await tab.text("#sb-eq")), await tab.text("#sb-eq"));
  const w = await tab.eval("return document.querySelector('#pred-bar').style.width");
  check(P, "predictor bar follows the selected ball", [0, 100].includes(parseFloat(w)), w);
  check(P, "body carries both team kits", (await tab.eval("return document.body.dataset.chase + '/' + document.body.dataset.defend")) === "LSG/KKR");
  await tab.go("index.html?match=1529304");
  await sleep(800);
  check(P, "deep link opens that chase", /Punjab Kings/.test(await tab.text("#match-title")), await tab.text("#match-title"));
  errors(P + " (deep links)");
}

// ---------------------------------------------------------------- calculator
{
  const P = "calculator";
  await tab.go("calculator.html");
  check(P, "readout shows a probability", await tab.waitFor(`/%/.test(document.querySelector('#readout').textContent)`));
  const r0 = await tab.text("#readout");
  await tab.clickEl('[data-for="wkts"][data-step="-1"]');
  const w = await tab.eval("return document.querySelector('#wkts').value");
  const r1 = await tab.text("#readout");
  check(P, "minus stepper changes value and result", w === "5" && r1 !== r0, `wkts ${w}, ${r0} -> ${r1}`);
  await tab.eval("const i = document.querySelector('#balls'); i.select(); i.focus()");
  await tab.type("0");
  const err = await tab.eval("const e = document.querySelector('#err-balls'); return e.hidden ? '' : e.textContent");
  check(P, "out-of-range input shows a field error", /whole number from 1 to 120/.test(err), err);
  await tab.eval("const i = document.querySelector('#balls'); i.value='42'; i.dispatchEvent(new Event('input'))");
  await tab.eval("const r = document.querySelector('#runs'); r.value='42'; r.dispatchEvent(new Event('input')); const w = document.querySelector('#wkts'); w.value='1'; w.dispatchEvent(new Event('input'))");
  const edge = await tab.text("#readout");
  check(P, "42 off 42 with 1 wicket is not 0%", edge && !/^0%$/.test(edge) && edge !== "–", edge);
  check(P, "curve drawn", await tab.waitFor(`window.Chart && Chart.getChart(document.querySelector('#curve'))`));
  const pBefore = await tab.text("#readout");
  await tab.eval("const a = document.querySelector('#pick-chase'); a.value='RR'; a.dispatchEvent(new Event('change')); const b = document.querySelector('#pick-defend'); b.value='CSK'; b.dispatchEvent(new Event('change'))");
  await sleep(300);
  check(P, "team pickers label the predictor bar", /RR/.test(await tab.text("#pred-chase")) && /CSK/.test(await tab.text("#pred-defend")), `${await tab.text("#pred-chase")} / ${await tab.text("#pred-defend")}`);
  check(P, "team pickers only change colours, not the number", (await tab.text("#readout")) === pBefore, `${pBefore} vs ${await tab.text("#readout")}`);
  check(P, "wicket pips match wickets in hand", (await tab.eval("return document.querySelectorAll('#pips .pip.on').length")) === Number(await tab.eval("return document.querySelector('#wkts').value")));
  errors(P);
}

// ---------------------------------------------------------------- edge cases
{
  const P = "edge cases";
  await tab.go("edge-cases.html");
  check(P, "explorer shows three answers", await tab.waitFor(`/%/.test(document.querySelector('#ex-calc')?.textContent ?? '')`));
  const a = await tab.text("#ex-calc");
  await tab.eval("const r = document.querySelector('#ex-wkts'); r.value='6'; r.dispatchEvent(new Event('input'))");
  check(P, "changing wickets updates the explorer", (await tab.text("#ex-calc")) !== a, `${a} -> ${await tab.text("#ex-calc")}`);
  check(P, "scenario table filled", (await tab.eval("return document.querySelectorAll('#scenarios tbody tr').length")) >= 10);
  errors(P);
}

// ---------------------------------------------------------------- results and write-up
for (const [P, page, sel, min] of [["results", "results.html", "#metrics tbody tr", 4], ["write-up", "about.html", "#exclusions tbody tr", 3]]) {
  await tab.go(page);
  check(P, "tables filled from the data", await tab.waitFor(`document.querySelectorAll('${sel}').length >= ${min}`));
  const imgs = await tab.eval("return [...document.images].filter(i => i.complete && i.naturalWidth === 0).map(i => i.src)");
  check(P, "no broken images", imgs.length === 0, imgs.join(" "));
  const deadLinks = await tab.eval("return [...document.querySelectorAll('a[href=\"#\"]')].map(a => a.textContent.trim())");
  check(P, "no placeholder links", deadLinks.length === 0, deadLinks.join(", "));
  errors(P);
}

// ---------------------------------------------------------------- every page: keyboard focus, layout
for (const page of ["index.html", "calculator.html", "edge-cases.html", "results.html", "about.html"]) {
  for (const width of [360, 1280]) {
    await tab.go(page, width, 800);
    await sleep(500);
    const overflow = await tab.eval("return document.documentElement.scrollWidth - document.documentElement.clientWidth");
    check(`${page} @${width}`, "no sideways page scroll", overflow <= 1, `overflow ${overflow}px`);
  }
  await tab.go(page, 1280, 800);
  await sleep(600);
  // real Tab presses, so :focus-visible applies; stop when focus wraps back to the start
  const bad = [], seen = new Set();
  let stops = 0;
  for (let k = 0; k < 160; k++) {
    await tab.key("Tab", "Tab", 9);
    const s = await tab.eval(`
      const e = document.activeElement; if (!e || e === document.body) return null;
      const key = (e.id || '') + '|' + e.tagName + '|' + e.textContent.trim().slice(0, 30) + '|' + (e.getAttribute('href') || '') + '|' + [...e.parentNode.children].indexOf(e);
      const ringOf = (x) => { const cs = getComputedStyle(x); return (cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) >= 1) || cs.boxShadow !== 'none'; };
      const ring = ringOf(e) || (e.closest('.prompt') && ringOf(e.closest('.prompt')));
      const r = e.getBoundingClientRect();
      const cx = Math.min(Math.max(r.left + r.width / 2, 1), innerWidth - 1), cy = Math.min(Math.max(r.top + Math.min(r.height / 2, 12), 1), innerHeight - 1);
      const top = document.elementFromPoint(cx, cy);
      const covered = !!top && !e.contains(top) && !top.contains(e) && !!top.closest('.site-header') && !e.closest('.site-header');
      return { key, ring, covered, name: e.id || e.textContent.trim().slice(0, 24) || e.tagName };`);
    if (!s) continue;
    if (seen.has(s.key)) break;
    seen.add(s.key); stops++;
    if (!s.ring || s.covered) bad.push(`${s.name}${s.covered ? " (under header)" : " (no ring)"}`);
  }
  check(page, "Tab reaches every control with a visible focus ring, none hidden by the header", bad.length === 0 && stops > 3, `${stops} stops; ${bad.slice(0, 6).join(", ")}`);
}

await tab.close();
let fails = 0;
for (const r of results) { if (!r.ok) fails++; console.log(`${r.ok ? "PASS" : "FAIL"}  [${r.page}] ${r.name}${r.info && !r.ok ? `  — ${r.info}` : ""}`); }
console.log(`\n${results.length - fails} passed, ${fails} failed`);
process.exitCode = fails ? 1 : 0;
