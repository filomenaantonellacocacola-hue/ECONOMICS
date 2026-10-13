// Mapa del proyecto: lee el modelo de #mapa-data (lo genera econ/mapa/build.py) y dibuja el lienzo.
(() => {
  "use strict";
  const DATA = JSON.parse(document.getElementById("mapa-data").textContent);
  const { groups: GROUPS, nodes: N, edges: E, flows: FLOWS } = DATA;

  const ICONS = {
    clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
    play: '<circle cx="12" cy="12" r="8.5"/><path d="M10 8.8v6.4l5.2-3.2z"/>',
    branch: '<circle cx="6" cy="6" r="2.2"/><circle cx="6" cy="18" r="2.2"/><circle cx="18" cy="9" r="2.2"/><path d="M6 8.2v7.6M18 11.2c0 4-6 3-11 5"/>',
    gear: '<circle cx="12" cy="12" r="3"/><path d="M12 3v2.5M12 18.5V21M3 12h2.5M18.5 12H21M5.6 5.6l1.8 1.8M16.6 16.6l1.8 1.8M5.6 18.4l1.8-1.8M16.6 7.4l1.8-1.8"/>',
    switch: '<path d="M4 7h10M4 12h16M4 17h7"/><circle cx="17" cy="7" r="2"/><circle cx="14" cy="17" r="2"/>',
    check: '<rect x="4" y="4" width="16" height="16" rx="3"/><path d="M8 12.5l2.6 2.5L16 9.5"/>',
    file: '<path d="M7 3.5h7l4 4V20a.5.5 0 0 1-.5.5h-10A.5.5 0 0 1 7 20z"/><path d="M14 3.5V8h4M9.5 12h6M9.5 15.5h6"/>',
    cloud: '<path d="M7 18h10a4 4 0 0 0 .6-7.95A5.5 5.5 0 0 0 7 10.5 3.75 3.75 0 0 0 7 18z"/>',
    bank: '<path d="M4 9.5L12 5l8 4.5M5.5 10v7M10 10v7M14 10v7M18.5 10v7M4 19h16"/>',
    chartUp: '<path d="M4 19h16M6 15l4-4 3 3 5-6"/><path d="M15 8h3v3"/>',
    wrench: '<path d="M14.5 6.5a4 4 0 0 0-5 5L4 17l3 3 5.5-5.5a4 4 0 0 0 5-5l-2.5 2.5-2.5-.5-.5-2.5z"/>',
    db: '<ellipse cx="12" cy="6" rx="7" ry="2.6"/><path d="M5 6v12c0 1.4 3.1 2.6 7 2.6s7-1.2 7-2.6V6M5 12c0 1.4 3.1 2.6 7 2.6s7-1.2 7-2.6"/>',
    cpu: '<rect x="7" y="7" width="10" height="10" rx="2"/><path d="M10 3.5V7M14 3.5V7M10 17v3.5M14 17v3.5M3.5 10H7M3.5 14H7M17 10h3.5M17 14h3.5"/>',
    sigma: '<path d="M17 5H7l5 7-5 7h10"/>',
    doc: '<path d="M6 4h12v16H6z"/><path d="M9 8h6M9 11.5h6M9 15h4"/>',
    terminal: '<rect x="3.5" y="5" width="17" height="14" rx="2"/><path d="M7 10l3 2.5L7 15M12.5 15H17"/>',
    user: '<circle cx="12" cy="8.5" r="3.5"/><path d="M5 20c.8-3.6 3.6-5.5 7-5.5s6.2 1.9 7 5.5"/>',
    anchor: '<circle cx="12" cy="5.5" r="2"/><path d="M12 7.5V20M8 10.5h8M5 13.5c0 3.8 3.1 6.5 7 6.5s7-2.7 7-6.5"/>',
    crown: '<path d="M4 17l1.5-9 4.5 4 2-6 2 6 4.5-4L20 17z"/><path d="M4.5 20h15"/>',
    globe: '<circle cx="12" cy="12" r="8.5"/><path d="M3.5 12h17M12 3.5c2.5 2.6 3.5 5.4 3.5 8.5S14.5 17.9 12 20.5M12 3.5C9.5 6.1 8.5 8.9 8.5 12s1 5.9 3.5 8.5"/>',
    flag: '<path d="M6 21V4M6 5h11l-2 3.5L17 12H6"/>',
    lens: '<circle cx="10.5" cy="10.5" r="5.5"/><path d="M15 15l5 5M8 10.5h5"/>',
    pulse: '<path d="M3 12h4l2.5-6 4 12 2.5-6H21"/>',
    brush: '<path d="M14 4l6 6-8 8-6-6z"/><path d="M6 12l-2.5 6.5L10 16"/>',
    bubble: '<path d="M4 6.5A2.5 2.5 0 0 1 6.5 4h11A2.5 2.5 0 0 1 20 6.5v7a2.5 2.5 0 0 1-2.5 2.5H10l-4.5 4V16H6.5A2.5 2.5 0 0 1 4 13.5z"/><path d="M8 8.5h8M8 12h5"/>',
    gavel: '<path d="M13 5l6 6M10 8l6 6M11.5 6.5l-3.5 3.5 6 6 3.5-3.5M8 13l-4.5 4.5 2 2L10 15M4 21h8"/>',
    pr: '<circle cx="6" cy="6" r="2.2"/><circle cx="6" cy="18" r="2.2"/><circle cx="18" cy="18" r="2.2"/><path d="M6 8.2v7.6M18 15.8V10a3 3 0 0 0-3-3h-4M12.5 5 10.5 7l2 2"/>',
    image: '<rect x="3.5" y="5" width="17" height="14" rx="2"/><path d="M7 15l3.5-4 3 3 2-2 2.5 3"/>',
  };
  const CATS = {
    trigger: ["Disparador", "--c-trigger"], config: ["Configuración", "--c-config"], orch: ["Orquestación", "--c-orch"],
    source: ["Fuente externa", "--c-source"], storage: ["Almacenamiento", "--c-storage"], process: ["Procesamiento", "--c-process"],
    snap: ["Resumen para agentes", "--c-snap"], tool: ["Herramienta", "--c-tool"], user: ["Usuario", "--c-user"],
    head: ["Head", "--c-head"], macro: ["Mesa macro", "--c-macro"], fin: ["Mesa financiera", "--c-fin"],
    staff: ["Staff", "--c-staff"], out: ["Entregable", "--c-out"],
  };

  const $ = (s) => document.querySelector(s);
  const world = $("#world"), svg = $("#edges"), stage = $("#stage"), dots = $("#dots");
  const drawer = $("#drawer"), dbody = $("#dbody");
  const svgNS = "http://www.w3.org/2000/svg";
  const byId = Object.fromEntries(N.map((n) => [n.id, n]));
  const icon = (k) => `<svg viewBox="0 0 24 24">${ICONS[k] || ICONS.gear}</svg>`;
  const nodeEl = {};
  const geo = {};  // posicion y tamano de cada nodo en el lienzo (se mide una vez)
  const adj = {};  // vecinos y conexiones por nodo
  const W = Math.max(...GROUPS.map((g) => g.x + g.w), ...N.map((n) => n.x + 230)) + 20;
  const H = Math.max(...GROUPS.map((g) => g.y + g.h), ...N.map((n) => n.y + 80)) + 20;
  world.style.width = W + "px"; world.style.height = H + "px";
  svg.style.width = W + "px"; svg.style.height = H + "px";

  // ---------------------------------------------------------------- construccion (una sola vez)
  const frag = document.createDocumentFragment();
  for (const g of GROUPS) {
    const el = document.createElement("div");
    el.className = "group";
    el.style.cssText = `left:${g.x}px;top:${g.y}px;width:${g.w}px;height:${g.h}px`;
    el.innerHTML = `<b><em>${g.n}</em>${g.t}</b>`;
    frag.appendChild(el);
  }
  for (const n of N) {
    const el = document.createElement("div");
    el.className = "node" + (n.big ? " big" : "");
    el.tabIndex = 0;
    el.dataset.id = n.id;
    el.setAttribute("role", "button");
    el.setAttribute("aria-label", `${n.t}: ${n.s}`);
    el.style.cssText = `left:${n.x}px;top:${n.y}px;--k:var(${CATS[n.c][1]})`;
    el.innerHTML = `${n.tag ? `<span class="tag">${n.tag}</span>` : ""}<div class="ic">${icon(n.ic)}</div>` +
      `<div class="tx"><b>${n.t}</b><span>${n.s}</span></div><i class="port l"></i><i class="port r"></i>`;
    frag.appendChild(el);
    nodeEl[n.id] = el;
    adj[n.id] = { nb: new Set(), edges: [] };
  }
  world.appendChild(frag);

  const legend = $("#legend");
  for (const [k, [label, v]] of Object.entries(CATS)) {
    if (k === "user" || k === "out") continue;
    const s = document.createElement("span");
    s.style.setProperty("--k", `var(${v})`);
    s.innerHTML = `<i></i>${label}`;
    legend.appendChild(s);
  }

  const DIR = { r: [1, 0], l: [-1, 0], t: [0, -1], b: [0, 1] };
  function port(id, side) {
    const { x, y, w, h } = geo[id];
    return { r: [x + w, y + h / 2], l: [x, y + h / 2], t: [x + w / 2, y], b: [x + w / 2, y + h] }[side];
  }
  const bez = (p, t) => { const u = 1 - t;
    return [0, 1].map((i) => u * u * u * p[0][i] + 3 * u * u * t * p[1][i] + 3 * u * t * t * p[2][i] + t * t * t * p[3][i]); };

  const edgeEls = [];
  function drawEdges() {
    clearHi();
    for (const n of N) { const el = nodeEl[n.id]; geo[n.id] = { x: el.offsetLeft, y: el.offsetTop, w: el.offsetWidth, h: el.offsetHeight }; }
    edgeEls.length = 0;
    for (const id in adj) { adj[id].nb.clear(); adj[id].edges.length = 0; }
    let base = "", flows = "", labels = "";
    E.forEach(([a, b, sa, sb, label, dash], i) => {
      if (!geo[a] || !geo[b]) return;
      const [x1, y1] = port(a, sa), [x2, y2] = port(b, sb);
      const k = Math.max(60, Math.min(220, Math.hypot(x2 - x1, y2 - y1) * 0.45));
      const c1 = [x1 + DIR[sa][0] * k, y1 + DIR[sa][1] * k], c2 = [x2 + DIR[sb][0] * k, y2 + DIR[sb][1] * k];
      const d = `M${x1},${y1} C${c1} ${c2} ${x2},${y2}`;
      base += `<path class="e${dash ? " dash" : ""}" data-i="${i}" d="${d}" marker-end="url(#arr)"/>`;
      flows += `<path class="flow" data-i="${i}" d="${d}"/>`;
      if (label) {
        const [mx, my] = bez([[x1, y1], c1, c2, [x2, y2]], 0.5);
        labels += `<text class="elabel" data-i="${i}" x="${mx.toFixed(1)}" y="${(my - 6).toFixed(1)}" text-anchor="middle">${label}</text>`;
      }
    });
    svg.innerHTML = `<defs><marker id="arr" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">` +
      `<path d="M0,1 L9,5 L0,9 z" fill="#4a5568"/></marker></defs>${base}<g>${flows}</g>${labels}`;
    E.forEach(([a, b], i) => {
      if (!geo[a] || !geo[b]) return;
      const e = { a, b, path: svg.querySelector(`path.e[data-i="${i}"]`), flow: svg.querySelector(`path.flow[data-i="${i}"]`),
        text: svg.querySelector(`text[data-i="${i}"]`) };
      edgeEls.push(e);
      adj[a].nb.add(b); adj[b].nb.add(a); adj[a].edges.push(e); adj[b].edges.push(e);
    });
  }

  // ---------------------------------------------------------------- resaltado (solo toca lo que cambia)
  const state = { flow: null, sel: null, lit: new Set(), litEdges: new Set() };
  function clearHi() {
    world.classList.remove("dim");
    for (const id of state.lit) nodeEl[id].classList.remove("on", "sel");
    for (const e of state.litEdges) { e.path.classList.remove("on"); e.flow.classList.remove("on"); if (e.text) e.text.classList.remove("on"); }
    state.lit.clear(); state.litEdges.clear();
  }
  function highlight(ids, color, focus) {
    clearHi();
    world.classList.add("dim");
    for (const id of ids) { nodeEl[id].classList.add("on"); state.lit.add(id); }
    const list = focus ? adj[focus].edges : edgeEls.filter((e) => ids.has(e.a) && ids.has(e.b));
    const c = color || `var(${CATS[byId[focus].c][1]})`;
    for (const e of list) {
      e.path.classList.add("on"); e.path.style.setProperty("--hc", c);
      if (color) { e.flow.classList.add("on"); e.flow.style.setProperty("--hc", c); }
      if (e.text) e.text.classList.add("on");
      state.litEdges.add(e);
    }
  }

  // ---------------------------------------------------------------- panel de detalle
  const links = (ids) => `<div class="links">${ids.map((i) => `<button data-go="${i}">${byId[i].t}</button>`).join("")}</div>`;
  function openNode(id, center) {
    const n = byId[id];
    setFlow(null, true);
    state.sel = id;
    highlight(new Set([id, ...adj[id].nb]), null, id);
    nodeEl[id].classList.add("sel");
    const [cat, v] = CATS[n.c];
    const ins = E.filter((e) => e[1] === id).map((e) => e[0]);
    const outs = E.filter((e) => e[0] === id).map((e) => e[1]);
    dbody.innerHTML = `<div class="k" style="--k: var(${v})"><div class="ic">${icon(n.ic)}</div>` +
      `<div><div class="cat">${cat}</div><h2>${n.t}</h2></div></div><p>${n.d}</p>` +
      (n.l && n.l.length ? `<h3>Detalle</h3><ul>${n.l.map((x) => `<li>${x}</li>`).join("")}</ul>` : "") +
      (ins.length ? `<h3>Recibe de</h3>${links(ins)}` : "") + (outs.length ? `<h3>Envía a</h3>${links(outs)}` : "");
    drawer.classList.add("open");
    if (center) focusOn(id);
  }
  function openFlow(f) {
    dbody.innerHTML = `<div class="k" style="--k: var(${f.c})"><div class="ic">${icon("play")}</div>` +
      `<div><div class="cat">Recorrido</div><h2>${f.t}</h2></div></div>` +
      `<h3>Paso a paso</h3><ol>${f.steps.map((s) => `<li>${s}</li>`).join("")}</ol>` +
      `<h3>Nodos que participan</h3>${links(f.n.filter((i) => byId[i]))}`;
    drawer.classList.add("open");
  }
  dbody.addEventListener("click", (e) => { const b = e.target.closest("[data-go]"); if (b) openNode(b.dataset.go, true); });
  function closeDrawer() { drawer.classList.remove("open"); state.sel = null; setFlow(null); clearHi(); }
  $("#close").addEventListener("click", closeDrawer);

  const chipEls = {};
  const flowsBar = $("#flows");
  for (const f of FLOWS) {
    const b = document.createElement("button");
    b.className = "chip"; b.textContent = f.t; b.setAttribute("aria-pressed", "false");
    b.addEventListener("click", () => setFlow(state.flow === f.k ? null : f.k));
    flowsBar.appendChild(b);
    chipEls[f.k] = b;
  }
  function setFlow(k, keepDrawer) {
    state.flow = k;
    for (const [key, b] of Object.entries(chipEls)) b.setAttribute("aria-pressed", String(key === k));
    if (!k) { if (!keepDrawer) { clearHi(); drawer.classList.remove("open"); } return; }
    state.sel = null;
    const f = FLOWS.find((x) => x.k === k);
    highlight(new Set(f.n.filter((i) => byId[i])), `var(${f.c})`);
    openFlow(f);
  }

  // Delegacion: un solo listener para todos los nodos.
  world.addEventListener("click", (e) => { const el = e.target.closest(".node"); if (el && moved < 4) { e.stopPropagation(); openNode(el.dataset.id); } });
  world.addEventListener("keydown", (e) => {
    const el = e.target.closest(".node");
    if (el && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); openNode(el.dataset.id); }
  });
  world.addEventListener("pointerover", (e) => {
    const el = e.target.closest(".node");
    if (!el || dragging || state.flow || state.sel || el === hovered) return;
    hovered = el; highlight(new Set([el.dataset.id, ...adj[el.dataset.id].nb]), null, el.dataset.id);
  });
  world.addEventListener("pointerout", (e) => {
    const el = e.target.closest(".node");
    if (!el || el.contains(e.relatedTarget) || dragging || state.flow || state.sel) return;
    hovered = null; clearHi();
  });
  let hovered = null;

  // ---------------------------------------------------------------- paneo y zoom (un repintado por cuadro)
  const view = { x: 0, y: 0, s: 1 };
  let raf = 0, idle = 0;
  function render() {
    raf = 0;
    world.style.transform = `translate3d(${view.x}px,${view.y}px,0) scale(${view.s})`;
    let cell = 22 * view.s;
    while (cell < 11) cell *= 2;
    const ox = ((view.x % cell) + cell) % cell, oy = ((view.y % cell) + cell) % cell;
    dots.style.backgroundSize = `${cell}px ${cell}px`;
    dots.style.transform = `translate3d(${ox - cell}px,${oy - cell}px,0)`;
  }
  function apply(interactive) {
    if (interactive) {
      stage.classList.add("moving");
      clearTimeout(idle);
      idle = setTimeout(() => stage.classList.remove("moving"), 160);  // al soltar, se vuelve a dibujar nitido
    }
    if (!raf) raf = requestAnimationFrame(render);
  }
  function zoomAt(f, cx, cy) {
    const s = Math.min(2.2, Math.max(0.15, view.s * f));
    view.x = cx - (cx - view.x) * (s / view.s);
    view.y = cy - (cy - view.y) * (s / view.s);
    view.s = s; apply(true);
  }
  const wide = () => stage.clientWidth > 640;
  function fit() {
    const w = stage.clientWidth, h = stage.clientHeight, top = wide() ? 60 : 8, pad = 20;
    view.s = Math.max(0.15, Math.min((w - pad * 2) / W, (h - top - pad) / H));
    view.x = (w - W * view.s) / 2;
    view.y = top + (h - top - H * view.s) / 2;
    apply();
  }
  function start() {
    if (wide()) return fit();
    view.s = 0.62; view.x = -4; view.y = 0; apply();  // en telefono empieza legible en los disparadores
  }
  function focusOn(id) {
    const g = geo[id], w = stage.clientWidth, h = stage.clientHeight;
    view.s = Math.max(view.s, 0.8);
    view.x = (w - (wide() ? 380 : 0)) / 2 - (g.x + g.w / 2) * view.s;
    view.y = (wide() ? h / 2 : h * 0.22) - (g.y + g.h / 2) * view.s;
    apply();
  }
  $("#zin").addEventListener("click", () => zoomAt(1.2, stage.clientWidth / 2, stage.clientHeight / 2));
  $("#zout").addEventListener("click", () => zoomAt(1 / 1.2, stage.clientWidth / 2, stage.clientHeight / 2));
  $("#zfit").addEventListener("click", fit);

  let rect = stage.getBoundingClientRect();
  stage.addEventListener("wheel", (e) => {
    e.preventDefault();
    if (e.ctrlKey || Math.abs(e.deltaX) < 1 || e.deltaMode) {
      zoomAt(Math.exp(-e.deltaY * (e.ctrlKey ? 0.01 : 0.0015)), e.clientX - rect.left, e.clientY - rect.top);
    } else {  // panel tactil de laptop: dos dedos mueven el lienzo
      view.x -= e.deltaX; view.y -= e.deltaY; apply(true);
    }
  }, { passive: false });

  const pts = new Map();
  let last = null, moved = 0, pinch = null, dragging = false;
  stage.addEventListener("pointerdown", (e) => {
    if (e.target.closest(".drawer, .zoom, .legend")) return;
    rect = stage.getBoundingClientRect();
    pts.set(e.pointerId, [e.clientX, e.clientY]);
    if (pts.size === 1) { last = [e.clientX, e.clientY]; moved = 0; }
    if (pts.size === 2) { const [a, b] = [...pts.values()]; pinch = Math.hypot(a[0] - b[0], a[1] - b[1]); }
  });
  stage.addEventListener("pointermove", (e) => {
    if (!pts.has(e.pointerId)) return;
    pts.set(e.pointerId, [e.clientX, e.clientY]);
    if (pts.size === 2 && pinch) {
      const [a, b] = [...pts.values()], d = Math.hypot(a[0] - b[0], a[1] - b[1]);
      zoomAt(d / pinch, (a[0] + b[0]) / 2 - rect.left, (a[1] + b[1]) / 2 - rect.top);
      pinch = d; return;
    }
    if (!last) return;
    const dx = e.clientX - last[0], dy = e.clientY - last[1];
    moved += Math.abs(dx) + Math.abs(dy);
    if (!dragging && moved > 4) {
      dragging = true; stage.classList.add("dragging");
      try { stage.setPointerCapture(e.pointerId); } catch (_) { /* sin captura */ }
    }
    if (dragging) { view.x += dx; view.y += dy; last = [e.clientX, e.clientY]; apply(true); }
  });
  const up = (e) => {
    pts.delete(e.pointerId);
    if (pts.size < 2) pinch = null;
    if (pts.size) return;
    const wasClick = moved < 4;
    dragging = false; stage.classList.remove("dragging"); last = null;
    if (wasClick && !e.target.closest(".node, .drawer, .zoom, .legend")) closeDrawer();
  };
  stage.addEventListener("pointerup", up);
  stage.addEventListener("pointercancel", up);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDrawer(); });

  let ready = false;
  function init() { drawEdges(); if (!ready) { ready = true; start(); } }
  init();
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(drawEdges);  // re-mide con la fuente final
  let rz = 0;
  window.addEventListener("resize", () => { clearTimeout(rz); rz = setTimeout(() => { rect = stage.getBoundingClientRect(); start(); }, 120); });
})();
