/* ==========================================================================
   22/33 kV Automatic Pole Placement - front end
   Canvas renderer + AutoCAD style PLINE picking + server communication.
   ========================================================================== */
(function () {
  "use strict";

  const DEFAULTS = window.APP_DEFAULTS || { offset: 5, useBreakPoles: true, roadWidth: 16, sample: [] };
  const STORAGE_KEY = "pole-project-v1";
  const LEGACY_STORAGE_KEY = "pea-pole-project-v1";

  const canvas = document.getElementById("canvas");
  const ctx = canvas.getContext("2d");

  const el = {
    status: document.getElementById("status-pill"),
    cursor: document.getElementById("cursor-readout"),
    pointCount: document.getElementById("point-count"),
    pointBody: document.getElementById("point-tbody"),
    poleBody: document.getElementById("pole-tbody"),
    checkBody: document.getElementById("check-tbody"),
    countRow: document.getElementById("count-row"),
    errorBox: document.getElementById("error-box"),
    warnBox: document.getElementById("warning-box"),
    statLength: document.getElementById("stat-length"),
    statPoles: document.getElementById("stat-poles"),
    statMaxSpan: document.getElementById("stat-maxspan"),
    statGy: document.getElementById("stat-gy"),
    statCurve: document.getElementById("stat-curve"),
    statLimit: document.getElementById("stat-limit"),
    offset: document.getElementById("input-offset"),
    useBreak: document.getElementById("input-break"),
    showLabels: document.getElementById("input-labels"),
    showSpans: document.getElementById("input-spans"),
    showGrid: document.getElementById("input-grid"),
    roadWidth: document.getElementById("input-road"),
    filterCode: document.getElementById("filter-code"),
    stdBody: document.querySelector("#std-table tbody"),
    helpDialog: document.getElementById("help-dialog")
  };

  const state = {
    points: [],
    design: null,
    mode: "draw",
    view: { scale: 4, tx: 0, ty: 0 },
    dragging: false,
    dragLast: null,
    showPoles: true,
    finished: false
  };

  /* --------------------------------------------------------------- utils */
  function fmt(n, digits) {
    return Number(n).toFixed(digits === undefined ? 2 : digits);
  }

  function setStatus(text, kind) {
    el.status.textContent = text;
    el.status.className = "pill " + (kind || "pill-idle");
  }

  function showError(message) {
    el.errorBox.textContent = message;
    el.errorBox.hidden = false;
  }

  function clearError() {
    el.errorBox.hidden = true;
    el.errorBox.textContent = "";
  }

  /* --------------------------------------------------------- coordinates */
  function worldToScreen(p) {
    return {
      x: p[0] * state.view.scale + state.view.tx,
      y: -p[1] * state.view.scale + state.view.ty
    };
  }

  function screenToWorld(sx, sy) {
    return [(sx - state.view.tx) / state.view.scale, (state.view.ty - sy) / state.view.scale];
  }

  function resizeCanvas() {
    const ratio = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width = Math.max(1, Math.floor(rect.width * ratio));
    canvas.height = Math.max(1, Math.floor(rect.height * ratio));
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    draw();
  }

  function fitView() {
    const rect = canvas.getBoundingClientRect();
    const pts = state.points.length ? state.points : (state.design ? state.design.centerline : DEFAULTS.sample);
    const list = pts && pts.length ? pts : [[0, 0], [1, 1]];
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    list.forEach(function (p) {
      minX = Math.min(minX, p[0]); maxX = Math.max(maxX, p[0]);
      minY = Math.min(minY, p[1]); maxY = Math.max(maxY, p[1]);
    });
    const pad = 60;
    const w = Math.max(maxX - minX, 1e-6);
    const h = Math.max(maxY - minY, 1e-6);
    const scale = Math.min((rect.width - pad * 2) / w, (rect.height - pad * 2) / h);
    state.view.scale = Math.max(0.05, Math.min(scale, 400));
    state.view.tx = rect.width / 2 - ((minX + maxX) / 2) * state.view.scale;
    state.view.ty = rect.height / 2 + ((minY + maxY) / 2) * state.view.scale;
    draw();
  }

  function zoomAt(factor, cx, cy) {
    const before = screenToWorld(cx, cy);
    state.view.scale = Math.max(0.05, Math.min(state.view.scale * factor, 4000));
    const after = screenToWorld(cx, cy);
    state.view.tx += (after[0] - before[0]) * state.view.scale;
    state.view.ty -= (after[1] - before[1]) * state.view.scale;
    draw();
  }

  /* ------------------------------------------------------------- drawing */
  function strokeWorld(pts, style) {
    if (!pts || pts.length === 0) return;
    ctx.beginPath();
    const first = worldToScreen(pts[0]);
    ctx.moveTo(first.x, first.y);
    for (let i = 1; i < pts.length; i++) {
      const s = worldToScreen(pts[i]);
      ctx.lineTo(s.x, s.y);
    }
    ctx.lineWidth = style.width;
    ctx.strokeStyle = style.color;
    ctx.setLineDash(style.dash || []);
    ctx.lineJoin = "round";
    ctx.lineCap = style.cap || "round";
    ctx.stroke();
    ctx.setLineDash([]);
  }

  function drawGrid() {
    const rect = canvas.getBoundingClientRect();
    const stepCandidates = [1, 2, 5, 10, 20, 50, 100, 200, 500];
    let step = stepCandidates[stepCandidates.length - 1];
    for (let i = 0; i < stepCandidates.length; i++) {
      if (stepCandidates[i] * state.view.scale >= 40) { step = stepCandidates[i]; break; }
    }
    const tl = screenToWorld(0, 0);
    const br = screenToWorld(rect.width, rect.height);
    ctx.strokeStyle = "rgba(120,140,175,0.13)";
    ctx.lineWidth = 1;
    for (let x = Math.floor(tl[0] / step) * step; x <= br[0]; x += step) {
      const a = worldToScreen([x, 0]), b = worldToScreen([x, 0]);
      ctx.beginPath(); ctx.moveTo(a.x, 0); ctx.lineTo(a.x, rect.height); ctx.stroke();
    }
    for (let y = Math.floor(br[1] / step) * step; y <= tl[1]; y += step) {
      const s = worldToScreen([0, y]);
      ctx.beginPath(); ctx.moveTo(0, s.y); ctx.lineTo(rect.width, s.y); ctx.stroke();
    }
    const origin = worldToScreen([0, 0]);
    ctx.strokeStyle = "rgba(150,175,210,0.35)";
    ctx.beginPath(); ctx.moveTo(origin.x, 0); ctx.lineTo(origin.x, rect.height); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(0, origin.y); ctx.lineTo(rect.width, origin.y); ctx.stroke();
  }

  function drawRoad() {
    if (state.points.length < 2) return;
    const width = parseFloat(el.roadWidth.value);
    const roadW = width > 0 ? width : 16;
    const half = roadW / 2;
    const left = state.points.map(function (p, i, arr) { return offsetPoint(p, arr, i, half); });
    const right = state.points.map(function (p, i, arr) { return offsetPoint(p, arr, i, -half); });
    const polygon = left.concat(right.slice().reverse());
    ctx.beginPath();
    polygon.forEach(function (p, i) {
      const s = worldToScreen(p);
      if (i === 0) ctx.moveTo(s.x, s.y); else ctx.lineTo(s.x, s.y);
    });
    ctx.closePath();
    ctx.fillStyle = "#39424f";
    ctx.fill();
    ctx.strokeStyle = "#5b6675";
    ctx.lineWidth = 1;
    ctx.stroke();

    // R.O.W. right-of-way lines: the two offset lines the pole line may sit on.
    // Drawn at the offset the design actually used (fallback to what the input
    // asks for) so the user can see the pole line sits outside the carriageway.
    const offset = designOffset();
    if (!(offset > 0)) return;
    const rowLeft = state.points.map(function (p, i, arr) { return offsetPoint(p, arr, i, offset); });
    const rowRight = state.points.map(function (p, i, arr) { return offsetPoint(p, arr, i, -offset); });
    strokeWorld(rowLeft, { color: "rgba(90,200,140,0.75)", width: 1, dash: [8, 6], cap: "butt" });
    strokeWorld(rowRight, { color: "rgba(90,200,140,0.75)", width: 1, dash: [8, 6], cap: "butt" });

    // shaded road corridor band (edge to edge) so the clearance is visible
    const minClear = roadClearance();
    if (minClear > 0 && offset > half + 1e-9) {
      const clearL = state.points.map(function (p, i, arr) { return offsetPoint(p, arr, i, half + minClear); });
      const clearR = state.points.map(function (p, i, arr) { return offsetPoint(p, arr, i, -(half + minClear)); });
      ctx.beginPath();
      const band = clearL.concat(clearR.slice().reverse());
      band.forEach(function (p, i) {
        const s = worldToScreen(p);
        if (i === 0) ctx.moveTo(s.x, s.y); else ctx.lineTo(s.x, s.y);
      });
      ctx.closePath();
      ctx.fillStyle = "rgba(90,200,140,0.07)";
      ctx.fill();
    }
  }

  function designOffset() {
    // the offset the server actually used; falls back to the input value
    if (state.design && typeof state.design.offset_m === "number") return state.design.offset_m;
    const v = parseFloat(el.offset.value);
    return v > 0 ? v : 0;
  }

  function roadClearance() {
    if (state.design && typeof state.design.road_clearance_m === "number") return state.design.road_clearance_m;
    return 2.0;
  }

  function offsetPoint(p, arr, i, dist) {
    const prev = arr[Math.max(i - 1, 0)];
    const next = arr[Math.min(i + 1, arr.length - 1)];
    let dx = next[0] - prev[0];
    let dy = next[1] - prev[1];
    const len = Math.hypot(dx, dy) || 1;
    dx /= len; dy /= len;
    return [p[0] - dy * dist, p[1] + dx * dist];
  }

  function drawMarker(pole) {
    const s = worldToScreen([pole.x, pole.y]);
    ctx.beginPath();
    ctx.lineWidth = 1.4;
    ctx.strokeStyle = "#0b0f18";
    ctx.fillStyle = pole.color;
    const r = 6;
    switch (pole.marker) {
      case "square":
        ctx.rect(s.x - r, s.y - r, r * 2, r * 2);
        break;
      case "hexagon":
        for (let i = 0; i < 6; i++) {
          const a = (Math.PI / 3) * i - Math.PI / 6;
          const px = s.x + r * Math.cos(a), py = s.y + r * Math.sin(a);
          if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
        }
        ctx.closePath();
        break;
      case "diamond":
        ctx.moveTo(s.x, s.y - r - 1);
        ctx.lineTo(s.x + r + 1, s.y);
        ctx.lineTo(s.x, s.y + r + 1);
        ctx.lineTo(s.x - r - 1, s.y);
        ctx.closePath();
        break;
      default:
        ctx.arc(s.x, s.y, r, 0, Math.PI * 2);
    }
    ctx.fill();
    ctx.stroke();
    if (pole.gy) {
      // Guy line runs from the pole to the anchor block. The engine supplies the
      // true anchor coordinates (opposing the resultant wire pull), so draw the
      // line to that point rather than a fixed screen length in the stored angle.
      let ax, ay;
      if (pole.gy_anchor_x !== null && pole.gy_anchor_x !== undefined &&
          pole.gy_anchor_y !== null && pole.gy_anchor_y !== undefined) {
        const a = worldToScreen([pole.gy_anchor_x, pole.gy_anchor_y]);
        ax = a.x; ay = a.y;
      } else {
        const back = pole.gy_angle * Math.PI / 180;
        ax = s.x + Math.cos(back) * 16;
        ay = s.y - Math.sin(back) * 16;
      }
      ctx.beginPath();
      ctx.strokeStyle = "rgba(215,58,73,0.85)";
      ctx.lineWidth = 1;
      ctx.moveTo(s.x, s.y); ctx.lineTo(ax, ay);
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(ax, ay, 2.6, 0, Math.PI * 2);
      ctx.fillStyle = "rgba(215,58,73,0.85)";
      ctx.fill();
    }
  }

  function drawPoleLabel(pole, index) {
    const s = worldToScreen([pole.x, pole.y]);
    const up = index % 2 === 0;
    const dy = up ? -16 : 20;
    ctx.font = "600 11px Consolas, monospace";
    ctx.textAlign = "center";
    const line1 = "#" + pole.id + " " + pole.code.toUpperCase();
    const line2 = pole.bracket + (pole.angle > 0 ? " " + fmt(pole.angle, 1) + "°" : "");
    ctx.fillStyle = pole.color;
    ctx.fillText(line1, s.x, s.y + dy);
    ctx.fillStyle = "#a8b7cc";
    ctx.font = "10px Consolas, monospace";
    ctx.fillText(line2, s.x, s.y + dy + (up ? 11 : -11));
  }

  function draw() {
    const rect = canvas.getBoundingClientRect();
    ctx.clearRect(0, 0, rect.width, rect.height);
    ctx.fillStyle = "#0b0f18";
    ctx.fillRect(0, 0, rect.width, rect.height);

    if (el.showGrid.checked) drawGrid();

    const design = state.design;
    const center = design ? design.centerline : state.points;
    const poles = design ? design.poles : [];

    if (center && center.length >= 2) {
      drawRoad();
      strokeWorld(center, { color: "rgba(210,190,90,0.9)", width: 1.2, dash: [7, 5] });
      const wire = poles.length ? poles.map(function (p) { return [p.x, p.y]; }) : center;
      strokeWorld(wire, { color: "#0d47a1", width: 3 });
      strokeWorld(wire, { color: "rgba(120,175,255,0.45)", width: 1, dash: [3, 4] });
    } else if (center && center.length === 1) {
      strokeWorld(center, { color: "#2f81f7", width: 2 });
    }

    if (state.points.length >= 2 && !design) {
      state.points.forEach(function (p, i) {
        const s = worldToScreen(p);
        ctx.beginPath();
        ctx.arc(s.x, s.y, 4, 0, Math.PI * 2);
        ctx.fillStyle = "#7ee787";
        ctx.fill();
        ctx.font = "10px Consolas, monospace";
        ctx.fillStyle = "#93a4bd";
        ctx.textAlign = "left";
        ctx.fillText(String(i + 1), s.x + 7, s.y - 6);
      });
    }

    if (design && state.showPoles) {
      poles.forEach(drawMarker);
      if (el.showSpans.checked && design.spans) {
        design.spans.forEach(function (span) {
          const s = worldToScreen([span.mid_x, span.mid_y]);
          const text = fmt(span.length, 1) + " m";
          ctx.font = "10px Consolas, monospace";
          const w = ctx.measureText(text).width + 8;
          ctx.fillStyle = "rgba(10,16,28,0.8)";
          ctx.fillRect(s.x - w / 2, s.y + 6, w, 13);
          ctx.fillStyle = "#79c0ff";
          ctx.textAlign = "center";
          ctx.fillText(text, s.x, s.y + 16);
        });
      }
      if (el.showLabels.checked) poles.forEach(drawPoleLabel);
    }
  }

  /* ------------------------------------------------------------ UI tables */
  function renderPoints() {
    el.pointCount.textContent = state.points.length;
    if (!state.points.length) {
      el.pointBody.innerHTML = '<tr class="empty"><td colspan="3">ยังไม่มีจุด คลิกบนผืนภาพเพื่อปัก</td></tr>';
      return;
    }
    el.pointBody.innerHTML = state.points.map(function (p, i) {
      return "<tr><td>" + (i + 1) + "</td><td>" + fmt(p[0], 2) + "</td><td>" + fmt(p[1], 2) + "</td></tr>";
    }).join("");
  }

  function renderPoleTable() {
    const design = state.design;
    if (!design || !design.poles.length) {
      el.poleBody.innerHTML = '<tr class="empty"><td colspan="6">ยังไม่มีผลออกแบบ</td></tr>';
      return;
    }
    const filter = el.filterCode.value.trim().toLowerCase();
    const rows = design.poles.filter(function (p) {
      return !filter || p.code.indexOf(filter) !== -1 || String(p.id) === filter;
    });
    if (!rows.length) {
      el.poleBody.innerHTML = '<tr class="empty"><td colspan="6">ไม่พบเสาที่ตรงกับคำค้น</td></tr>';
      return;
    }
    el.poleBody.innerHTML = rows.map(function (p) {
      return "<tr>" +
        "<td>" + p.id + "</td>" +
        '<td><span class="tag" style="background:' + p.color + '">' + p.code.toUpperCase() + "</span></td>" +
        "<td>" + fmt(p.x, 2) + "</td>" +
        "<td>" + fmt(p.y, 2) + "</td>" +
        "<td>" + fmt(p.station, 2) + "</td>" +
        "<td>" + (p.span_to_next === null ? "-" : fmt(p.span_to_next, 2)) + "</td>" +
        "</tr>";
    }).join("");
  }

  function renderChecks() {
    const design = state.design;
    if (!design) {
      el.checkBody.innerHTML = '<tr class="empty"><td colspan="3">ยังไม่มีผลตรวจสอบ</td></tr>';
      return;
    }
    el.checkBody.innerHTML = design.validation.map(function (row) {
      const cls = row.status === "PASS" ? "status-ok" : "status-fail";
      return "<tr><td>" + row.label + "</td><td>" + row.value + "</td>" +
        '<td class="' + cls + '">' + row.status + "</td></tr>";
    }).join("");

    if (design.warnings && design.warnings.length) {
      el.warnBox.hidden = false;
      el.warnBox.innerHTML = "<strong>ข้อควรทราบ</strong><ul>" +
        design.warnings.map(function (w) { return "<li>" + w + "</li>"; }).join("") + "</ul>";
    } else {
      el.warnBox.hidden = true;
      el.warnBox.innerHTML = "";
    }
  }

  function renderStats() {
    const design = state.design;
    if (!design) {
      el.statLength.textContent = "-";
      el.statPoles.textContent = "-";
      el.statMaxSpan.textContent = "-";
      el.statGy.textContent = "-";
      el.statCurve.textContent = "-";
      el.countRow.textContent = "";
      return;
    }
    const s = design.summary;
    el.statLength.textContent = fmt(s.length_m, 2) + " m";
    el.statPoles.textContent = s.pole_count + " ต้น";
    el.statMaxSpan.textContent = fmt(s.max_span_used_m, 2) + " m";
    el.statGy.textContent = s.guy_pole_count + " ต้น";
    el.statCurve.textContent = s.curve_pole_count + " ต้น";
    el.countRow.textContent = s.count_label;
    el.statLimit.textContent = s.tangent_max_span_m + " m";
    setStatus(design.ok ? "ผ่านทุกเกณฑ์" : "มีบางเกณฑ์ไม่ผ่าน", design.ok ? "pill-ok" : "pill-fail");
  }

  /* --------------------------------------------------------- server calls */
  function requestBody() {
    return {
      points: state.points,
      offset: parseFloat(el.offset.value),
      use_break_poles: el.useBreak.checked,
      road_width: parseFloat(el.roadWidth.value)
    };
  }

  async function runDesign() {
    if (state.points.length < 2) {
      showError("ต้องปักจุดบนแนวถนนอย่างน้อย 2 จุดก่อนออกแบบ");
      return;
    }
    clearError();
    setStatus("กำลังคำนวณ...", "pill-busy");
    try {
      const response = await fetch("/api/design", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(requestBody())
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "เซิร์ฟเวอร์ตอบกลับผิดพลาด");
      state.design = data;
      state.finished = true;
      renderStats();
      renderPoleTable();
      renderChecks();
      draw();
      saveProject();
    } catch (err) {
      showError(err.message);
      setStatus("เกิดข้อผิดพลาด", "pill-fail");
    }
  }

  function download(filename, content, mime) {
    const blob = new Blob(["\ufeff" + content], { type: (mime || "text/plain") + ";charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
  }

  async function exportCsv() {
    if (!state.design) { showError("ยังไม่มีผลออกแบบ กดออกแบบก่อน"); return; }
    clearError();
    try {
      const response = await fetch("/api/export/csv", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(requestBody())
      });
      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.error || "ส่งออก CSV ไม่สำเร็จ");
      }
      download("poles.csv", await response.text(), "text/csv");
    } catch (err) {
      showError(err.message);
    }
  }

  function exportJson() {
    if (!state.design) { showError("ยังไม่มีผลออกแบบ กดออกแบบก่อน"); return; }
    download("poles.json", JSON.stringify({
      centerline: state.points,
      offset_m: parseFloat(el.offset.value),
      used_offset_m: state.design.offset_m,
      road_width_m: parseFloat(el.roadWidth.value),
      road_clearance_m: state.design.road_clearance_m,
      min_edge_clearance_m: state.design.min_edge_clearance_m,
      use_break_poles: el.useBreak.checked,
      design: state.design
    }, null, 2), "application/json");
  }

  function exportPng() {
    const link = document.createElement("a");
    link.download = "pole_layout.png";
    link.href = canvas.toDataURL("image/png");
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  }

  function exportReport() {
    if (!state.design) { showError("ยังไม่มีผลออกแบบ กดออกแบบก่อน"); return; }
    const d = state.design;
    const lines = [];
    lines.push("22/33 kV POLE PLACEMENT - DESIGN REPORT (SAC 50 sq.mm.)");
    lines.push("=".repeat(92));
    lines.push("ความยาวแนวถนน " + fmt(d.summary.length_m, 2) + " m | Offset " +
      fmt(d.offset_m, 2) + " m | เสา " + d.summary.pole_count + " ต้น");
    if (d.requested_offset_m !== undefined && d.requested_offset_m !== null &&
        Math.abs(d.requested_offset_m - d.offset_m) > 0.001) {
      lines.push(" Offset ที่ขอ " + fmt(d.requested_offset_m, 2) +
        " m ถูกถอยออกเป็น " + fmt(d.offset_m, 2) +
        " m (เขตทางกว้าง " + fmt(d.road_width_m, 1) + " m + เว้นว่าง " +
        fmt(d.road_clearance_m, 1) + " m)");
    }
    lines.push("เขตทางกว้าง " + fmt(d.road_width_m, 1) + " m | ริมทางห่างเสา " +
      fmt(d.min_edge_clearance_m, 2) + " m | เว้นว่างขั้นต่ำ " +
      fmt(d.road_clearance_m, 1) + " m");
    lines.push("");
    lines.push(pad("#", 5) + pad("ประเภท", 14) + pad("วงเล็บ", 11) + pad("มุม(องศา)", 12) +
      pad("X(m)", 12) + pad("Y(m)", 12) + pad("Station", 12) + pad("Span(m)", 11) + "อุปกรณ์");
    lines.push("-".repeat(92));
    d.poles.forEach(function (p) {
      lines.push(
        pad("#" + p.id, 5) + pad(p.code, 14) + pad(p.bracket, 11) + pad(fmt(p.angle, 1), 12) +
        pad(fmt(p.x, 2), 12) + pad(fmt(p.y, 2), 12) + pad(fmt(p.station, 2), 12) +
        pad(p.span_to_next === null ? "-" : fmt(p.span_to_next, 2), 11) +
        (p.gy ? "GY-21 + สมอบก" : "-")
      );
    });
    lines.push("-".repeat(92));
    lines.push("การตรวจสอบมาตรฐาน");
    d.validation.forEach(function (row) {
      lines.push("  " + pad(row.label, 34) + pad(row.value, 26) + row.status);
    });
    if (d.warnings && d.warnings.length) {
      lines.push("");
      lines.push("ข้อควรทราบ");
      d.warnings.forEach(function (w) { lines.push("  - " + w); });
    }
    lines.push("");
    lines.push("ผลรวม: " + (d.ok ? "PASS" : "FAIL"));
    download("pole_report.txt", lines.join("\n"), "text/plain");
  }

  function pad(text, width) {
    let out = String(text);
    while (out.length < width) out += " ";
    return out;
  }

  /* ------------------------------------------------------------- project */
  function saveProject() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({
        points: state.points,
        offset: parseFloat(el.offset.value),
        useBreak: el.useBreak.checked,
        roadWidth: parseFloat(el.roadWidth.value)
      }));
      setStatus((state.design && state.design.ok ? "ผ่านทุกเกณฑ์" : "บันทึกโปรเจกต์แล้ว"),
        state.design && state.design.ok ? "pill-ok" : "pill-idle");
    } catch (err) {
      console.warn("บันทึกโปรเจกต์ไม่สำเร็จ", err);
    }
  }

  function loadProject(silent) {
    let data = null;
    try {
      let raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) raw = localStorage.getItem(LEGACY_STORAGE_KEY);
      if (raw) data = JSON.parse(raw);
    } catch (err) {
      console.warn("อ่านโปรเจกต์ไม่สำเร็จ", err);
    }
    if (!data || !Array.isArray(data.points) || data.points.length < 2) {
      if (!silent) showError("ไม่พบโปรเจกต์ที่บันทึกไว้ในเบราว์เซอร์นี้");
      return false;
    }
    state.points = data.points.map(function (p) { return [p[0], p[1]]; });
    el.offset.value = data.offset || DEFAULTS.offset;
    el.useBreak.checked = data.useBreak !== false;
    if (data.roadWidth > 0) el.roadWidth.value = data.roadWidth;
    state.design = null;
    renderPoints();
    renderStats();
    renderPoleTable();
    renderChecks();
    fitView();
    runDesign();
    return true;
  }

  /* -------------------------------------------------------- interaction */
  function pointerPosition(event) {
    const rect = canvas.getBoundingClientRect();
    return { x: event.clientX - rect.left, y: event.clientY - rect.top };
  }

  canvas.addEventListener("contextmenu", function (e) { e.preventDefault(); });

  canvas.addEventListener("mousedown", function (event) {
    const pos = pointerPosition(event);
    if (event.button === 2) {
      state.finished = true;
      setStatus("จบแนวทางแล้ว (" + state.points.length + " จุด)", "pill-idle");
      return;
    }
    if (state.mode === "pan" || event.button === 1) {
      state.dragging = true;
      state.dragLast = pos;
      canvas.classList.add("dragging");
      return;
    }
    if (state.finished) {
      showError("แนวทางถูกปิดแล้ว กด 'ล้างทั้งหมด' หรือ 'ตัวอย่าง 200 m' เพื่อเริ่มใหม่");
      return;
    }
    const world = screenToWorld(pos.x, pos.y);
    state.points.push([world[0], world[1]]);
    renderPoints();
    clearError();
    draw();
  });

  window.addEventListener("mousemove", function (event) {
    const pos = pointerPosition(event);
    const world = screenToWorld(pos.x, pos.y);
    el.cursor.textContent = "X: " + fmt(world[0], 2) + " m   Y: " + fmt(world[1], 2) + " m";
    if (state.dragging && state.dragLast) {
      state.view.tx += pos.x - state.dragLast.x;
      state.view.ty += pos.y - state.dragLast.y;
      state.dragLast = pos;
      draw();
    }
  });

  window.addEventListener("mouseup", function () {
    state.dragging = false;
    state.dragLast = null;
    canvas.classList.remove("dragging");
  });

  canvas.addEventListener("wheel", function (event) {
    event.preventDefault();
    const pos = pointerPosition(event);
    zoomAt(event.deltaY < 0 ? 1.12 : 1 / 1.12, pos.x, pos.y);
  }, { passive: false });

  document.addEventListener("keydown", function (event) {
    if (event.target.tagName === "INPUT" || event.target.tagName === "TEXTAREA") return;
    if (event.key === "Enter") {
      state.finished = true;
      if (state.points.length >= 2) runDesign();
    } else if (event.key === "Backspace" || ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z")) {
      event.preventDefault();
      state.points.pop();
      state.finished = false;
      state.design = null;
      renderPoints();
      renderStats();
      renderPoleTable();
      renderChecks();
      draw();
    } else if (event.key === "Escape") {
      state.points = [];
      state.design = null;
      state.finished = false;
      renderPoints();
      renderStats();
      renderPoleTable();
      renderChecks();
      draw();
      fitView();
    } else if (event.key === "Delete") {
      clearAll();
    } else if (event.key === "+" || event.key === "=") {
      zoomAt(1.2, canvas.getBoundingClientRect().width / 2, canvas.getBoundingClientRect().height / 2);
    } else if (event.key === "-") {
      zoomAt(1 / 1.2, canvas.getBoundingClientRect().width / 2, canvas.getBoundingClientRect().height / 2);
    }
  });

  function clearAll() {
    state.points = [];
    state.design = null;
    state.finished = false;
    clearError();
    renderPoints();
    renderStats();
    renderPoleTable();
    renderChecks();
    setStatus("ยังไม่ได้ออกแบบ", "pill-idle");
    draw();
  }

  function loadSample() {
    state.points = DEFAULTS.sample.map(function (p) { return [p[0], p[1]]; });
    state.finished = false;
    renderPoints();
    clearError();
    fitView();
    runDesign();
  }

  /* ---------------------------------------------------------- init/ wiring */
  document.querySelectorAll(".btn-mode").forEach(function (button) {
    button.addEventListener("click", function () {
      document.querySelectorAll(".btn-mode").forEach(function (b) { b.classList.remove("active"); });
      button.classList.add("active");
      state.mode = button.dataset.mode;
      canvas.classList.toggle("mode-pan", state.mode === "pan");
    });
  });

  document.getElementById("btn-undo").addEventListener("click", function () {
    state.points.pop();
    state.finished = false;
    state.design = null;
    renderPoints(); renderStats(); renderPoleTable(); renderChecks(); draw();
  });
  document.getElementById("btn-clear").addEventListener("click", clearAll);
  document.getElementById("btn-finish").addEventListener("click", function () {
    state.finished = true;
    runDesign();
  });
  document.getElementById("btn-sample").addEventListener("click", loadSample);
  document.getElementById("btn-design").addEventListener("click", runDesign);
  document.getElementById("btn-csv").addEventListener("click", exportCsv);
  document.getElementById("btn-json").addEventListener("click", exportJson);
  document.getElementById("btn-png").addEventListener("click", exportPng);
  document.getElementById("btn-report").addEventListener("click", exportReport);
  document.getElementById("btn-save").addEventListener("click", function () {
    saveProject();
    setStatus("บันทึกโปรเจกต์แล้ว", "pill-ok");
  });
  document.getElementById("btn-load").addEventListener("click", function () { loadProject(false); });
  document.getElementById("btn-help").addEventListener("click", function () { el.helpDialog.showModal(); });
  document.getElementById("btn-copy").addEventListener("click", function () {
    if (!state.points.length) { showError("ยังไม่มีจุดพิกัดให้คัดลอก"); return; }
    const text = state.points.map(function (p) { return fmt(p[0], 3) + ", " + fmt(p[1], 3); }).join("\n");
    navigator.clipboard.writeText(text).then(function () {
      setStatus("คัดลอกพิกัดแล้ว", "pill-ok");
    }, function () {
      showError("เบราว์เซอร์ไม่อนุญาตให้คัดลอกอัตโนมัติ");
    });
  });
  document.getElementById("btn-zoom-in").addEventListener("click", function () {
    zoomAt(1.25, canvas.getBoundingClientRect().width / 2, canvas.getBoundingClientRect().height / 2);
  });
  document.getElementById("btn-zoom-out").addEventListener("click", function () {
    zoomAt(1 / 1.25, canvas.getBoundingClientRect().width / 2, canvas.getBoundingClientRect().height / 2);
  });
  document.getElementById("btn-fit").addEventListener("click", fitView);
  document.getElementById("btn-toggle-poles").addEventListener("click", function (event) {
    state.showPoles = !state.showPoles;
    event.target.textContent = state.showPoles ? "ซ่อนเสา" : "แสดงเสา";
    draw();
  });

  [el.showLabels, el.showSpans, el.showGrid].forEach(function (input) {
    input.addEventListener("change", draw);
  });
  el.roadWidth.addEventListener("change", function () {
    // road width feeds the server design now (auto offset raise), so a
    // change invalidates the current result just like the offset field does.
    if (state.design) {
      state.design = null;
      renderStats(); renderPoleTable(); renderChecks();
    }
    draw();
    saveProject();
    if (state.points.length >= 2 && state.finished) runDesign();
  });
  el.filterCode.addEventListener("input", renderPoleTable);
  el.offset.addEventListener("change", function () {
    state.design = null;
    renderStats(); renderPoleTable(); renderChecks();
    draw();
    saveProject();
    if (state.points.length >= 2 && state.finished) runDesign();
  });

  window.addEventListener("resize", resizeCanvas);

  fetch("/api/standards")
    .then(function (r) { return r.json(); })
    .then(function (data) {
      el.stdBody.innerHTML = data.span_table.map(function (row) {
        return "<tr><td>" + row.condition + "</td><td>" + row.code + "</td><td>" +
          row.max_span_m + " m</td></tr>";
      }).join("");
      el.statLimit.textContent = data.tangent_max_span_m + " m";
    })
    .catch(function () {
      el.stdBody.innerHTML = '<tr class="empty"><td colspan="3">โหลดตารางมาตรฐานไม่สำเร็จ</td></tr>';
    });

  el.offset.value = DEFAULTS.offset;
  el.useBreak.checked = DEFAULTS.useBreakPoles;
  if (DEFAULTS.roadWidth > 0) el.roadWidth.value = DEFAULTS.roadWidth;
  renderPoints();
  renderStats();
  renderPoleTable();
  renderChecks();
  resizeCanvas();
  fitView();
  loadProject(true);
})();