/* ECONOMICS · renderer del presentador. Estilo fijo: los colores salen de theme.css; no se personaliza por reporte. */
(function () {
  "use strict";

  var DATA = JSON.parse(document.getElementById("econ-data").textContent);
  var css = getComputedStyle(document.documentElement);
  function tok(name) { return css.getPropertyValue("--" + name).trim(); }
  var C = {
    panel: tok("panel"), raised: tok("raised"), border: tok("border"), grid: tok("grid"),
    fg: tok("fg"), fg2: tok("fg-2"), muted: tok("muted"), amber: tok("amber"),
    up: tok("up"), down: tok("down"), mono: tok("font-mono"),
    series: [1, 2, 3, 4, 5, 6].map(function (i) { return tok("s" + i); }),
  };
  var REDUCED = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];

  function alpha(hex, a) {
    var h = hex.replace("#", "");
    if (h.length === 3) h = h.split("").map(function (c) { return c + c; }).join("");
    var n = parseInt(h, 16);
    return "rgba(" + ((n >> 16) & 255) + "," + ((n >> 8) & 255) + "," + (n & 255) + "," + a + ")";
  }
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined && text !== null) e.textContent = text;
    return e;
  }

  /* ---------- Formato (mismo criterio que econ/present/build.py) ---------- */
  var NF = {};
  function nf(d) {
    if (!NF[d]) NF[d] = new Intl.NumberFormat("es-MX", { minimumFractionDigits: d, maximumFractionDigits: d });
    return NF[d];
  }
  function compact(v) {
    var a = Math.abs(v);
    if (a >= 1e12) return nf(2).format(v / 1e12) + " B";
    if (a >= 1e9) return nf(2).format(v / 1e9) + " MM";
    if (a >= 1e6) return nf(2).format(v / 1e6) + " M";
    if (a >= 1e3) return nf(1).format(v / 1e3) + " K";
    return nf(0).format(v);
  }
  var DEC = { pct: 2, pp: 2, mxn: 2, usd: 2, fx: 4, num: 2 };
  function fmt(v, unit, dec) {
    if (v === null || v === undefined || typeof v !== "number" || !isFinite(v)) return "—";
    var d = dec === null || dec === undefined ? (DEC[unit] === undefined ? 2 : DEC[unit]) : dec;
    var sign = v < 0 ? "-" : "";
    var a = Math.abs(v);
    switch (unit) {
      case "pct": return sign + nf(d).format(a) + "%";
      case "pp": return sign + nf(d).format(a) + " pp";
      case "mxn": return sign + "$" + nf(d).format(a);
      case "usd": return sign + "US$" + nf(d).format(a);
      case "compact": return compact(v);
      default: return sign + nf(d).format(a);
    }
  }
  function signed(v, unit, dec) { return (v > 0 ? "+" : "") + fmt(v, unit, dec); }
  function dirClass(v) { return v > 0 ? "up" : v < 0 ? "down" : ""; }

  /* ---------- Fechas ---------- */
  function parts(t) {
    if (typeof t === "string") { var p = t.split("-").map(Number); return { y: p[0], m: p[1], d: p[2] }; }
    if (typeof t === "number") { var dt = new Date(t * 1000); return { y: dt.getUTCFullYear(), m: dt.getUTCMonth() + 1, d: dt.getUTCDate() }; }
    return { y: t.year, m: t.month, d: t.day };
  }
  function fmtDate(t, freq) {
    var p = parts(t);
    if (freq === "M") return MESES[p.m - 1] + " " + p.y;
    if (freq === "Q") return "T" + Math.ceil(p.m / 3) + " " + p.y;
    if (freq === "S") return "S" + (p.m <= 6 ? 1 : 2) + " " + p.y;
    if (freq === "A") return String(p.y);
    return p.d + " " + MESES[p.m - 1] + " " + p.y;
  }
  function tickFmt(t, type) {
    var p = parts(t);
    if (type === 0) return String(p.y);
    if (type === 1) return MESES[p.m - 1];
    return p.d + " " + MESES[p.m - 1];
  }
  function iso(y, m, d) {
    var dt = new Date(Date.UTC(y, m - 1, d));
    return dt.toISOString().slice(0, 10);
  }
  function rangeStart(last, code) {
    var p = parts(last);
    var back = { "1M": [0, 1], "3M": [0, 3], "6M": [0, 6], "1A": [1, 0], "3A": [3, 0], "5A": [5, 0], "10A": [10, 0] }[code];
    if (code === "YTD") return iso(p.y, 1, 1);
    if (!back) return null;
    return iso(p.y - back[0], p.m - back[1], p.d);
  }

  /* ---------- Vista de tabla (gemela accesible de cada gráfica) ---------- */
  function buildTable(headers, rows, numeric) {
    var table = el("table", "data");
    var thead = el("thead");
    var tr = el("tr");
    headers.forEach(function (h, i) {
      var th = el("th", numeric[i] ? "num" : "");
      th.appendChild(el("span", "th-l", h));
      tr.appendChild(th);
    });
    thead.appendChild(tr);
    table.appendChild(thead);
    var tbody = el("tbody");
    rows.forEach(function (r) {
      var row = el("tr");
      r.forEach(function (c, i) {
        var td = el("td", numeric[i] ? "num" : "txt");
        if (c && typeof c === "object") { td.textContent = c.text; if (c.cls) td.classList.add(c.cls); }
        else td.textContent = c;
        row.appendChild(td);
      });
      tbody.appendChild(row);
    });
    table.appendChild(tbody);
    return table;
  }
  function tableForTime(cfg) {
    if (cfg.kind === "candles") {
      var s = cfg.series[0];
      var vol = {};
      (s.volume || []).forEach(function (v) { vol[v[0]] = v[1]; });
      var rows = s.ohlc.slice().reverse().map(function (b) {
        return [fmtDate(b[0], cfg.freq), fmt(b[1], cfg.unit, cfg.decimals), fmt(b[2], cfg.unit, cfg.decimals),
          fmt(b[3], cfg.unit, cfg.decimals), fmt(b[4], cfg.unit, cfg.decimals), vol[b[0]] === undefined ? "—" : compact(vol[b[0]])];
      });
      return buildTable(["Fecha", "Apertura", "Máximo", "Mínimo", "Cierre", "Volumen"], rows, [false, true, true, true, true, true]);
    }
    var all = cfg.series.concat(cfg.overlays || []);
    var byDate = {};
    all.forEach(function (s, i) {
      s.points.forEach(function (p) { (byDate[p[0]] = byDate[p[0]] || {})[i] = p[1]; });
    });
    var dates = Object.keys(byDate).sort().reverse();
    var rows2 = dates.map(function (d) {
      return [fmtDate(d, cfg.freq)].concat(all.map(function (s, i) { return fmt(byDate[d][i], s.unit || cfg.unit, cfg.decimals); }));
    });
    return buildTable(["Fecha"].concat(all.map(function (s) { return s.label; })), rows2, [false].concat(all.map(function () { return true; })));
  }
  function tableForCat(cfg) {
    var rows = cfg.categories.map(function (c, i) {
      return [c].concat(cfg.series.map(function (s) { return fmt(s.values[i], cfg.unit, cfg.decimals); }));
    });
    return buildTable([cfg.category_label || "Categoría"].concat(cfg.series.map(function (s) { return s.label; })), rows,
      [false].concat(cfg.series.map(function () { return true; })));
  }
  function toggleTable(card, cfg, force) {
    var view = card.querySelector(".tableview");
    var btn = card.querySelector('[data-act="table"]');
    var open = force === undefined ? view.hidden : force;
    if (open && !view.firstChild) view.appendChild(cfg.time ? tableForTime(cfg) : tableForCat(cfg));
    view.hidden = !open;
    if (btn) btn.setAttribute("aria-pressed", open ? "true" : "false");
  }

  /* ---------- Series de tiempo (Lightweight Charts, de TradingView) ---------- */
  function priceFormat(unit, dec) {
    return { type: "custom", minMove: 0.0001, formatter: function (p) { return fmt(p, unit, dec); } };
  }
  function mountTime(card, cfg) {
    var box = card.querySelector(".chart");
    var LW = window.LightweightCharts;
    var single = cfg.series.length === 1 && !(cfg.overlays && cfg.overlays.length);
    var chart = LW.createChart(box, {
      autoSize: true,
      layout: { background: { type: "solid", color: C.panel }, textColor: C.muted, fontFamily: C.mono, fontSize: 11 },
      grid: { vertLines: { color: C.grid }, horzLines: { color: C.grid } },
      rightPriceScale: { borderColor: C.border, mode: cfg.compare ? 2 : 0 },
      timeScale: { borderColor: C.border, rightOffset: 3, minBarSpacing: 0.3, tickMarkFormatter: tickFmt },
      crosshair: {
        mode: 0,
        vertLine: { color: C.muted, width: 1, style: 3, labelBackgroundColor: C.raised },
        horzLine: { color: C.muted, width: 1, style: 3, labelBackgroundColor: C.raised },
      },
      localization: {
        locale: "es-MX",
        timeFormatter: function (t) { return fmtDate(t, cfg.freq); },
        priceFormatter: function (p) { return fmt(p, cfg.unit, cfg.decimals); },
      },
      watermark: single && cfg.watermark
        ? { visible: true, text: cfg.watermark, color: alpha(C.fg, 0.06), fontSize: 40, fontFamily: C.mono, horzAlign: "center", vertAlign: "center" }
        : { visible: false },
      handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false },
      handleScale: { mouseWheel: true, pinch: true, axisPressedMouseMove: true, axisDoubleClickReset: true },
    });

    var entries = [];  // {api, label, color, unit, kind}
    cfg.series.forEach(function (s) {
      var color = s.slot === null || s.slot === undefined ? C.series[0] : C.series[s.slot];
      var api;
      var common = {
        priceFormat: priceFormat(s.unit || cfg.unit, cfg.decimals), lastValueVisible: true, priceLineVisible: single,
        baseLineColor: C.muted, baseLineWidth: 1, baseLineStyle: 0,
      };
      if (cfg.kind === "candles") {
        api = chart.addCandlestickSeries(Object.assign({}, common, {
          upColor: C.up, downColor: C.down, wickUpColor: C.up, wickDownColor: C.down, borderVisible: false, priceLineVisible: true,
        }));
        api.setData(s.ohlc.map(function (b) { return { time: b[0], open: b[1], high: b[2], low: b[3], close: b[4] }; }));
        if (s.volume) {
          var vol = chart.addHistogramSeries({ priceScaleId: "", priceFormat: { type: "volume" }, lastValueVisible: false, priceLineVisible: false });
          vol.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
          var dir = {};
          s.ohlc.forEach(function (b) { dir[b[0]] = b[4] >= b[1]; });
          vol.setData(s.volume.map(function (v) { return { time: v[0], value: v[1], color: alpha(dir[v[0]] ? C.up : C.down, 0.35) }; }));
        }
        entries.push({ api: api, label: s.label, color: C.up, unit: cfg.unit, kind: "candles" });
        return;
      }
      if (cfg.kind === "area") {
        api = chart.addAreaSeries(Object.assign({}, common, {
          lineColor: color, topColor: alpha(color, 0.22), bottomColor: alpha(color, 0), lineWidth: 2,
          crosshairMarkerRadius: 4, crosshairMarkerBorderColor: C.panel, crosshairMarkerBorderWidth: 2,
        }));
      } else if (cfg.kind === "baseline") {
        api = chart.addBaselineSeries(Object.assign({}, common, {
          baseValue: { type: "price", price: cfg.base || 0 }, lineWidth: 2,
          topLineColor: C.up, topFillColor1: alpha(C.up, 0.22), topFillColor2: alpha(C.up, 0.02),
          bottomLineColor: C.down, bottomFillColor1: alpha(C.down, 0.02), bottomFillColor2: alpha(C.down, 0.22),
          crosshairMarkerRadius: 4, crosshairMarkerBorderColor: C.panel, crosshairMarkerBorderWidth: 2,
        }));
        color = C.fg2;
      } else if (cfg.kind === "histogram") {
        api = chart.addHistogramSeries(Object.assign({}, common, { color: color }));
      } else {
        api = chart.addLineSeries(Object.assign({}, common, {
          color: color, lineWidth: 2, crosshairMarkerRadius: 4, crosshairMarkerBorderColor: C.panel, crosshairMarkerBorderWidth: 2,
        }));
      }
      api.setData(s.points.map(function (p) {
        var d = { time: p[0], value: p[1] };
        if (cfg.kind === "histogram" && cfg.polarity) d.color = p[1] >= 0 ? C.up : C.down;
        return d;
      }));
      entries.push({ api: api, label: s.label, color: cfg.kind === "histogram" && cfg.polarity ? C.fg2 : color, unit: s.unit || cfg.unit, kind: cfg.kind });
    });
    (cfg.overlays || []).forEach(function (o) {
      var color = C.series[o.slot || 0];
      var api = chart.addLineSeries({
        color: color, lineWidth: 1, priceFormat: priceFormat(cfg.unit, cfg.decimals), lastValueVisible: false, priceLineVisible: false,
        crosshairMarkerVisible: false,
      });
      api.setData(o.points.map(function (p) { return { time: p[0], value: p[1] }; }));
      entries.push({ api: api, label: o.label, color: color, unit: cfg.unit, kind: "overlay" });
    });

    var main = entries[0].api;
    if (cfg.markers && cfg.markers.length) {
      main.setMarkers(cfg.markers.map(function (m) {
        return { time: m.date, position: m.position === "below" ? "belowBar" : "aboveBar", color: C.amber, shape: m.position === "below" ? "arrowUp" : "arrowDown", text: m.text };
      }));
    }
    (cfg.hlines || []).forEach(function (h) {
      main.createPriceLine({ price: h.value, color: C.amber, lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: h.label || "" });
    });

    /* Leyenda con lectura de valores (estilo TradingView) */
    var legend = el("div", "legend");
    legend.setAttribute("aria-live", "off");
    var dateEl = el("span", "lg-date");
    legend.appendChild(dateEl);
    var multi = entries.length > 1;
    entries.forEach(function (e) {
      var item = el(multi ? "button" : "span", "lg-item" + (multi ? "" : " lg-static"));
      if (multi) {
        item.type = "button";
        item.setAttribute("aria-pressed", "true");
        item.title = "Mostrar u ocultar " + e.label;
        item.addEventListener("click", function () {
          var on = item.getAttribute("aria-pressed") !== "true";
          item.setAttribute("aria-pressed", on ? "true" : "false");
          e.api.applyOptions({ visible: on });
        });
      }
      if (e.kind !== "candles") {
        var key = el("span", "key");
        key.style.background = e.color;
        item.appendChild(key);
      }
      item.appendChild(el("span", "lg-name", e.label));
      e.valEl = el("span", "lg-val");
      item.appendChild(e.valEl);
      legend.appendChild(item);
    });
    box.appendChild(legend);

    /* Deja espacio arriba para la leyenda aunque ocupe varias líneas (teléfono, varias series). */
    var bottomMargin = cfg.kind === "candles" && cfg.series[0].volume ? 0.24 : 0.08;
    function fitLegend() {
      var h = box.clientHeight || 1;
      var top = Math.min(0.5, Math.max(0.1, (legend.offsetHeight + 12) / h));
      chart.priceScale("right").applyOptions({ scaleMargins: { top: top, bottom: bottomMargin } });
    }
    if (window.ResizeObserver) new ResizeObserver(fitLegend).observe(box);

    function lastPoint(e) {
      var d = e.api.data();
      return d.length ? d[d.length - 1] : null;
    }
    var bases = [];
    function refreshBases() {
      if (!cfg.compare) return;
      var r = chart.timeScale().getVisibleLogicalRange();
      bases = entries.map(function (e) {
        var b = r ? e.api.dataByIndex(Math.max(0, Math.ceil(r.from)), 1) : null;
        return b ? (b.value !== undefined ? b.value : b.close) : null;
      });
    }
    function show(point, e, i) {
      if (!point) { e.valEl.textContent = "—"; e.valEl.className = "lg-val"; return; }
      if (e.kind === "candles") {
        var chg = point.open ? (point.close / point.open - 1) * 100 : null;
        var close = "Cie " + fmt(point.close, e.unit, cfg.decimals) + (chg === null ? "" : "  " + signed(chg, "pct"));
        e.valEl.textContent = box.clientWidth < 560 ? close
          : "Ap " + fmt(point.open, e.unit, cfg.decimals) + "  Máx " + fmt(point.high, e.unit, cfg.decimals) +
            "  Mín " + fmt(point.low, e.unit, cfg.decimals) + "  " + close;
        e.valEl.className = "lg-val " + dirClass(point.close - point.open);
        return;
      }
      var v = point.value;
      if (cfg.compare && bases[i]) {
        var pct = (v / bases[i] - 1) * 100;
        e.valEl.textContent = signed(pct, "pct");
        e.valEl.className = "lg-val " + dirClass(pct);
      } else {
        e.valEl.textContent = fmt(v, e.unit, cfg.decimals);
        e.valEl.className = "lg-val" + ((cfg.kind === "baseline" || (cfg.kind === "histogram" && cfg.polarity)) ? " " + dirClass(v - (cfg.base || 0)) : "");
      }
    }
    function showLast() {
      var lp = lastPoint(entries[0]);
      dateEl.textContent = lp ? fmtDate(lp.time, cfg.freq) : "";
      entries.forEach(function (e, i) { show(lastPoint(e), e, i); });
    }
    chart.subscribeCrosshairMove(function (param) {
      if (!param || param.time === undefined || !param.point) { showLast(); return; }
      dateEl.textContent = fmtDate(param.time, cfg.freq);
      entries.forEach(function (e, i) { show(param.seriesData.get(e.api) || null, e, i); });
    });
    chart.timeScale().subscribeVisibleLogicalRangeChange(function () { refreshBases(); showLast(); });

    /* Rango visible (botones tipo TradingView) */
    var lastTime = (lastPoint(entries[0]) || {}).time;
    function setRange(code) {
      card.querySelectorAll("[data-range]").forEach(function (b) { b.setAttribute("aria-pressed", b.dataset.range === code ? "true" : "false"); });
      var from = code === "MAX" ? null : rangeStart(lastTime, code);
      if (!from) chart.timeScale().fitContent();
      else chart.timeScale().setVisibleRange({ from: from, to: lastTime });
      refreshBases();
      showLast();
    }
    card.querySelectorAll("[data-range]").forEach(function (b) {
      b.addEventListener("click", function () { setRange(b.dataset.range); });
    });
    var fit = card.querySelector('[data-act="fit"]');
    if (fit) fit.addEventListener("click", function () { setRange("MAX"); });
    setRange(cfg.range || "MAX");
    fitLegend();
  }

  /* ---------- Categóricas (ECharts, con los mismos tokens) ---------- */
  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; });
  }
  function mountCat(card, cfg) {
    var box = card.querySelector(".chart");
    var ec = window.echarts.init(box, null, { renderer: "canvas" });
    var horizontal = cfg.kind === "hbar";
    var curve = cfg.kind === "curve";
    var multi = cfg.series.length > 1;
    function radius(v) {
      if (horizontal) return v >= 0 ? [0, 4, 4, 0] : [4, 0, 0, 4];
      return v >= 0 ? [4, 4, 0, 0] : [0, 0, 4, 4];
    }
    var series = cfg.series.map(function (s) {
      var color = C.series[s.slot || 0];
      if (curve) {
        return {
          type: "line", name: s.label, data: s.values, symbol: "circle", symbolSize: 8, connectNulls: true,
          lineStyle: { width: 2, color: color }, itemStyle: { color: color, borderColor: C.panel, borderWidth: 2 },
          emphasis: { focus: "series" },
        };
      }
      return {
        type: "bar", name: s.label, barMaxWidth: 24, barGap: "12%", barCategoryGap: "35%",
        itemStyle: { color: color },
        data: s.values.map(function (v) {
          var fill = cfg.polarity ? (v >= 0 ? C.up : C.down) : color;
          return {
            value: v,
            itemStyle: { color: fill, borderRadius: radius(v) },
            label: { position: horizontal ? (v >= 0 ? "right" : "left") : (v >= 0 ? "top" : "bottom") },
          };
        }),
        label: {
          show: !!cfg.labels, color: C.fg2, fontFamily: C.mono, fontSize: 11, distance: 6,
          formatter: function (p) { return fmt(p.value, cfg.unit, cfg.decimals); },
        },
        emphasis: { itemStyle: { opacity: 0.85 } },
      };
    });
    var narrow = box.clientWidth < 560;
    var valueAxis = {
      type: "value", scale: curve, splitNumber: narrow ? 3 : 5, axisLine: { show: false }, axisTick: { show: false },
      splitLine: { lineStyle: { color: C.grid, width: 1, type: "solid" } },
      axisLabel: { color: C.muted, fontFamily: C.mono, fontSize: 11, formatter: function (v) { return fmt(v, cfg.unit, cfg.axis_decimals); } },
    };
    var catAxis = {
      type: "category", data: cfg.categories, inverse: horizontal, boundaryGap: !curve,
      axisLine: { lineStyle: { color: C.border } }, axisTick: { show: false },
      axisLabel: { color: C.fg2, fontFamily: C.mono, fontSize: 11, hideOverlap: true },
    };
    ec.setOption({
      backgroundColor: C.panel,
      animation: !REDUCED,
      textStyle: { fontFamily: C.mono },
      grid: { left: 12, right: horizontal ? 56 : 20, top: multi ? 40 : 18, bottom: 10, containLabel: true },
      legend: multi ? {
        top: 8, left: 12, itemWidth: 14, itemHeight: curve ? 3 : 8, icon: "rect", itemGap: 16,
        textStyle: { color: C.fg2, fontFamily: C.mono, fontSize: 12 }, inactiveColor: C.muted,
      } : { show: false },
      tooltip: {
        trigger: "axis", confine: true,
        axisPointer: { type: curve ? "line" : "shadow", lineStyle: { color: C.muted, type: "dashed" }, shadowStyle: { color: alpha(C.fg, 0.04) } },
        backgroundColor: C.raised, borderColor: C.border, borderWidth: 1, padding: [8, 10],
        textStyle: { color: C.fg, fontFamily: C.mono, fontSize: 12 },
        formatter: function (ps) {
          var rows = ps.map(function (p) {
            var color = cfg.polarity && !curve ? (p.value >= 0 ? C.up : C.down) : C.series[cfg.series[p.seriesIndex].slot || 0];
            return '<div class="tt-r"><span class="key" style="background:' + color + '"></span><b>' +
              esc(fmt(p.value, cfg.unit, cfg.decimals)) + "</b><span>" + esc(p.seriesName) + "</span></div>";
          });
          return '<div class="tt-h">' + esc(ps[0].axisValueLabel) + "</div>" + rows.join("");
        },
      },
      xAxis: horizontal ? valueAxis : catAxis,
      yAxis: horizontal ? catAxis : valueAxis,
      series: series,
    });
    if (window.ResizeObserver) new ResizeObserver(function () { ec.resize(); }).observe(box);
    else window.addEventListener("resize", function () { ec.resize(); });
  }

  /* ---------- Montaje ---------- */
  function fail(card, cfg, lib) {
    var box = card.querySelector(".chart");
    box.classList.add("chart-fail");
    box.textContent = "No se pudo cargar " + lib + ". Los datos están en la tabla.";
    toggleTable(card, cfg, true);
  }
  Object.keys(DATA.charts).forEach(function (id) {
    var cfg = DATA.charts[id];
    var card = document.getElementById(id);
    if (!card) return;
    var tbtn = card.querySelector('[data-act="table"]');
    if (tbtn) tbtn.addEventListener("click", function () { toggleTable(card, cfg); });
    try {
      if (cfg.time) {
        if (!window.LightweightCharts) return fail(card, cfg, "la librería de gráficas de TradingView");
        mountTime(card, cfg);
      } else {
        if (!window.echarts) return fail(card, cfg, "la librería de gráficas");
        mountCat(card, cfg);
      }
    } catch (err) {
      fail(card, cfg, "la gráfica (" + err.message + ")");
    }
  });

  /* ---------- Tablas ordenables ---------- */
  document.querySelectorAll("table.data[data-sortable]").forEach(function (table) {
    table.querySelectorAll("thead th button").forEach(function (btn, idx) {
      btn.addEventListener("click", function () {
        var th = btn.parentElement;
        var dir = th.getAttribute("aria-sort") === "descending" ? "ascending" : "descending";
        table.querySelectorAll("thead th").forEach(function (t) { t.removeAttribute("aria-sort"); });
        th.setAttribute("aria-sort", dir);
        var body = table.tBodies[0];
        var rows = Array.prototype.slice.call(body.rows);
        rows.sort(function (a, b) {
          var x = a.cells[idx].getAttribute("data-v"), y = b.cells[idx].getAttribute("data-v");
          if (x === "" && y === "") return 0;
          if (x === "") return 1;
          if (y === "") return -1;
          var nx = parseFloat(x), ny = parseFloat(y);
          var r = !isNaN(nx) && !isNaN(ny) ? nx - ny : String(x).localeCompare(String(y), "es");
          return dir === "ascending" ? r : -r;
        });
        rows.forEach(function (r) { body.appendChild(r); });
      });
    });
  });
})();
