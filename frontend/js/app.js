/**
 * app.js — MRI QC Analyzer
 * Full interactive analysis: editable ROIs, zoom, WW/WL, dynamic re-analysis, SNR multi-method
 */
"use strict";

(async function main() {
  // ═══════════════════════════════════════════════════════════════════════════
  // THEME
  // ═══════════════════════════════════════════════════════════════════════════
  const themeBtn = document.getElementById("btn-theme-toggle");
  let darkMode = localStorage.getItem("mri_qc_theme") !== "light";
  applyTheme(darkMode);
  themeBtn?.addEventListener("click", () => { darkMode = !darkMode; applyTheme(darkMode); localStorage.setItem("mri_qc_theme", darkMode ? "dark" : "light"); });
  function applyTheme(d) { if (d) { document.body.classList.remove("theme-light"); themeBtn.textContent = "🌙"; } else { document.body.classList.add("theme-light"); themeBtn.textContent = "☀️"; } }

  // Step navigation
  document.querySelectorAll(".step-btn").forEach(btn => { btn.addEventListener("click", () => { const s = parseInt(btn.dataset.step); if (s <= AppState.currentStep) UI.showStep(s); }); });

  // ═══════════════════════════════════════════════════════════════════════════
  // STEP 1: Load DICOM
  // ═══════════════════════════════════════════════════════════════════════════
  const inputDir = document.getElementById("input-dir");
  const btnLoad = document.getElementById("btn-load");
  const savedPath = localStorage.getItem("mri_qc_input_dir");
  if (savedPath) { inputDir.value = savedPath; btnLoad.disabled = false; }
  inputDir.addEventListener("input", () => { btnLoad.disabled = !inputDir.value.trim(); });
  inputDir.addEventListener("keydown", (e) => { if (e.key === "Enter") btnLoad.click(); });

  btnLoad.addEventListener("click", async () => {
    const dir = inputDir.value.trim(); if (!dir) return;
    localStorage.setItem("mri_qc_input_dir", dir);
    UI.show("load-progress"); UI.setStatus("Caricamento DICOM MRI…");
    try {
      const resp = await API.loadDicom(dir);
      AppState.inputDir = dir; AppState.slices = resp.slices;
      UI.setStatus(`✓ ${resp.n_slices} slice MRI caricate`);
      UI.hide("load-progress");
      try { AppState.dicomMeta = await API.getDicomMeta(); } catch (e) {}
      setupStep2(); UI.showStep(2);
    } catch (err) { UI.hide("load-progress"); UI.setStatus(`✗ ${err.message}`); alert(err.message); }
  });

  // ═══════════════════════════════════════════════════════════════════════════
  // STEP 2: Slice Selection — Grid S/M/L/XL, WW/WL, Auto-assign
  // ═══════════════════════════════════════════════════════════════════════════
  async function setupStep2() { buildModuleLegend(); applyGridSize(); await refreshThumbnails(); autoAssign(); }

  function buildModuleLegend() {
    const legend = document.getElementById("module-legend"); legend.innerHTML = "";
    AppState.moduleOrder.forEach((mod, i) => {
      const color = AppState.moduleColors[mod], label = AppState.moduleLabels[mod];
      const chip = document.createElement("div");
      chip.className = `module-chip ${i === 0 ? "active" : ""}`;
      chip.style.cssText = `background:${color}22;color:${color};`;
      chip.innerHTML = `<span class="dot" style="background:${color}"></span><span>${label}</span><span class="assigned-badge" id="chip-${mod}">—</span>`;
      chip.addEventListener("click", () => { document.querySelectorAll(".module-chip").forEach(c => c.classList.remove("active")); chip.classList.add("active"); AppState.activeModule = mod; });
      legend.appendChild(chip);
    });
    AppState.activeModule = AppState.moduleOrder[0];
  }

  function autoAssign() {
    const n = AppState.slices.length; if (n === 0) return;
    for (const mod of AppState.moduleOrder) { const d = AppState.defaultSlices[mod]; if (d !== undefined && d < n) AppState.assignments[mod] = d; }
    updateAllBadges(); renderSliceGrid(); updateConfirmBtn();
    UI.setStatus(`Auto-assign: ${Object.keys(AppState.assignments).length} moduli`);
  }
  function updateAllBadges() { for (const mod of AppState.moduleOrder) { const b = document.getElementById(`chip-${mod}`); if (b) b.textContent = (mod in AppState.assignments) ? `#${AppState.assignments[mod]}` : "—"; } }

  async function refreshThumbnails() {
    const wl = parseFloat(document.getElementById("wl-val").value) || null;
    const ww = parseFloat(document.getElementById("ww-val").value) || null;
    AppState.wl = wl; AppState.ww = ww;
    try { const r = await API.getThumbnails(wl, ww, 128); AppState.thumbnails = r.thumbnails; renderSliceGrid(); } catch (e) { UI.setStatus(`Errore: ${e.message}`); }
  }

  function renderSliceGrid() {
    const grid = document.getElementById("slice-grid"); grid.innerHTML = "";
    AppState.thumbnails.forEach(thumb => {
      const card = document.createElement("div"); card.className = "slice-card";
      const mods = Object.entries(AppState.assignments).filter(([,idx]) => idx === thumb.idx).map(([m]) => m);
      if (mods.length > 0) {
        card.style.borderColor = AppState.moduleColors[mods[0]]; card.classList.add("assigned");
        const tags = mods.map(m => `<span class="module-tag-mini" style="background:${AppState.moduleColors[m]}">${m.replace("_","").substring(0,4)}</span>`).join("");
        card.innerHTML = `<img src="data:image/png;base64,${thumb.image}"/><div class="module-tags-wrap">${tags}</div><div class="slice-info"><span>#${thumb.idx}</span><span>z=${thumb.z}</span></div>`;
      } else {
        card.innerHTML = `<img src="data:image/png;base64,${thumb.image}"/><div class="slice-info"><span>#${thumb.idx}</span><span>z=${thumb.z}</span></div>`;
      }
      card.addEventListener("click", () => { if (AppState.activeModule) { AppState.assignments[AppState.activeModule] = thumb.idx; updateAllBadges(); renderSliceGrid(); updateConfirmBtn(); } });
      card.addEventListener("contextmenu", (e) => { e.preventDefault(); mods.forEach(m => delete AppState.assignments[m]); updateAllBadges(); renderSliceGrid(); updateConfirmBtn(); });
      grid.appendChild(card);
    });
  }

  function applyGridSize() { const px = AppState.gridSizes[AppState.gridSize] || 120; const g = document.getElementById("slice-grid"); if (g) g.style.gridTemplateColumns = `repeat(auto-fill, minmax(${px}px, 1fr))`; }
  function updateConfirmBtn() { const btn = document.getElementById("btn-confirm-slices"); const n = Object.keys(AppState.assignments).length; btn.disabled = n === 0; btn.textContent = `Conferma (${n}/${AppState.moduleOrder.length}) ›`; }

  document.querySelectorAll(".size-btn").forEach(btn => { btn.addEventListener("click", () => { document.querySelectorAll(".size-btn").forEach(b => b.classList.remove("active")); btn.classList.add("active"); AppState.gridSize = btn.dataset.size; applyGridSize(); }); });
  document.querySelectorAll(".preset-btn").forEach(btn => { btn.addEventListener("click", () => { document.querySelectorAll(".preset-btn").forEach(b => b.classList.remove("active")); btn.classList.add("active"); document.getElementById("wl-val").value = btn.dataset.wl; document.getElementById("ww-val").value = btn.dataset.ww; refreshThumbnails(); }); });
  document.getElementById("wl-val").addEventListener("change", refreshThumbnails);
  document.getElementById("ww-val").addEventListener("change", refreshThumbnails);
  document.getElementById("btn-refresh-thumbs").addEventListener("click", refreshThumbnails);
  document.getElementById("btn-auto-assign").addEventListener("click", () => { AppState.assignments = {}; autoAssign(); });
  document.getElementById("btn-confirm-slices").addEventListener("click", () => { setupStep3(); UI.showStep(3); });

  // ═══════════════════════════════════════════════════════════════════════════
  // STEP 3: Info QC
  // ═══════════════════════════════════════════════════════════════════════════
  function setupStep3() {
    const d = document.getElementById("info-date"); if (d && !d.value) d.value = new Date().toISOString().split("T")[0];
    const card = document.getElementById("dicom-meta-card"), m = AppState.dicomMeta;
    if (!m) { card.innerHTML = ""; return; }
    const it = (l,v) => `<div class="meta-item"><span class="meta-label">${l}</span><span class="meta-value">${v||"–"}</span></div>`;
    card.innerHTML = `<h3>Metadati DICOM MRI</h3><div class="meta-grid">${it("Produttore",m.manufacturer)}${it("Modello",m.model)}${it("Campo B₀",m.magnetic_field_T+" T")}${it("TR/TE",m.tr_ms+"/"+m.te_ms+" ms")}${it("Pixel Spacing",m.pixel_spacing_mm+" mm")}${it("Spessore",m.slice_thickness_mm+" mm")}${it("FOV",m.fov_mm+" mm")}${it("Matrice",m.matrix_size)}${it("N. Averages",m.n_averages)}${it("Data",m.study_date)}${it("N. Slice",m.n_slices)}</div>`;
  }
  document.getElementById("btn-start-analysis").addEventListener("click", () => {
    AppState.metaInfo = { data_controllo: document.getElementById("info-date").value, tipo_controllo: document.getElementById("info-type").value, presidio: document.getElementById("info-presidio").value, sala: document.getElementById("info-sala").value, operatori: document.getElementById("info-operatori").value, note: document.getElementById("info-note").value };
    API.setMetaInfo(AppState.metaInfo).catch(() => {});
    API.assignSlices(AppState.assignments).catch(() => {});
    setupStep4(); UI.showStep(4);
  });

  // ═══════════════════════════════════════════════════════════════════════════
  // STEP 4: Interactive Analysis with editable ROIs, zoom, WW/WL, live update
  // ═══════════════════════════════════════════════════════════════════════════
  let _zoom = 1, _autoTimer = null;

  function setupStep4() { buildAnalysisTabs(); const mods = AppState.moduleOrder.filter(m => m in AppState.assignments); if (mods.length > 0) showModule(mods[0]); }

  function buildAnalysisTabs() {
    const bar = document.getElementById("module-tabs"); bar.innerHTML = "";
    AppState.moduleOrder.filter(m => m in AppState.assignments).forEach((mod, i) => {
      const btn = document.createElement("button"); btn.className = `tab-btn ${i===0?"active":""}`;
      btn.dataset.module = mod; btn.innerHTML = `${AppState.moduleLabels[mod]} <span class="tab-status pending" id="ts-${mod}"></span>`;
      btn.addEventListener("click", () => { document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active")); btn.classList.add("active"); showModule(mod); });
      bar.appendChild(btn);
    });
  }

  async function showModule(mod) {
    _zoom = 1;
    const idx = AppState.assignments[mod];
    const content = document.getElementById("module-content");
    // SNR method selector (only for snr module)
    const snrMethodHtml = mod === "snr" ? `
      <div style="margin-bottom:10px;padding:8px;background:var(--bg-surface);border-radius:var(--radius);border:1px solid var(--border);">
        <label style="font-size:11px;font-weight:600;color:var(--accent-cyan);">Metodo SNR (da articolo Epistatou et al.):</label>
        <select id="snr-method" style="margin-top:4px;width:100%;font-size:12px;">
          <option value="single_lr">A) Singola immagine — σ(L+R) — Eq.7</option>
          <option value="single_ud">A) Singola immagine — σ(U+D)</option>
          <option value="single_all">A) Singola immagine — σ(L+R+U+D)</option>
          <option value="two_image">C) Due immagini subtraction — Eq.6</option>
        </select>
        <div id="snr-second-slice-wrap" class="hidden" style="margin-top:6px;">
          <label style="font-size:11px;">Indice seconda slice: <input type="number" id="snr-second-idx" value="${Math.min(idx+1, AppState.slices.length-1)}" min="0" max="${AppState.slices.length-1}" style="width:50px;font-size:11px;" /></label>
        </div>
      </div>` : "";

    content.innerHTML = `<div class="module-layout">
      <div class="module-image-panel">
        <div class="canvas-wrap" id="canvas-wrap"><canvas id="mod-canvas"></canvas><canvas id="mod-overlay"></canvas></div>
        <div class="hu-readout" id="hu-readout">—</div>
        <div class="canvas-controls">
          <label>WL <input type="range" id="mod-wl" min="0" max="2000" value="500" step="10"/><span id="lbl-wl">500</span></label>
          <label>WW <input type="range" id="mod-ww" min="1" max="3000" value="1000" step="10"/><span id="lbl-ww">1000</span></label>
          <label>Zoom <input type="range" id="mod-zoom" min="1" max="6" step="0.5" value="1"/><span id="lbl-zoom">1×</span></label>
        </div>
      </div>
      <div class="module-results-panel">
        <div class="result-section">
          <h4>${AppState.moduleLabels[mod]}</h4>
          ${snrMethodHtml}
          <p style="font-size:10px;color:var(--text-muted);margin-bottom:8px;">Tutte le ROI sono modificabili: <b>drag</b> per spostare, <b>dblclick</b> per aggiungere, <b>right-click</b> per rimuovere. L'analisi si aggiorna automaticamente.</p>
          <button class="btn btn-primary" id="btn-run">⚡ Analizza</button>
          <button class="btn btn-xs btn-secondary" id="btn-reset-roi" style="margin-left:6px;">↺ Reset ROI</button>
        </div>
        <div id="mod-results-area"></div>
      </div>
    </div>`;

    await loadBaseImage(idx, 500, 1000);
    if (AppState.results[mod]) {
      renderResults(mod, AppState.results[mod]);
      // Draw ROIs client-side on overlay
      drawRoisOnOverlay(AppState.results[mod].results);
      const runBtn = document.getElementById("btn-run");
      if (runBtn) {
        runBtn.textContent = "Fatto";
        runBtn.className = "btn btn-secondary";
        runBtn.dataset.mode = "done";
      }
    }

    // Bind controls
    bindWlWwZoom(idx);
    bindRoiInteraction(mod, idx);

    // SNR method toggle
    if (mod === "snr") {
      const sel = document.getElementById("snr-method");
      sel.addEventListener("change", () => { document.getElementById("snr-second-slice-wrap").classList.toggle("hidden", sel.value !== "two_image"); });
    }

    document.getElementById("btn-run").addEventListener("click", () => {
      const btn = document.getElementById("btn-run");
      if (btn?.dataset.mode === "done") {
        const ts = document.getElementById(`ts-${mod}`);
        const passed = AppState.results[mod]?.results?.passed;
        if (ts) ts.className = `tab-status ${passed === false ? "fail" : "pass"}`;
        UI.setStatus(`${AppState.moduleLabels[mod]} confermato`);
        return;
      }
      runAnalysis(mod);
    });
    document.getElementById("btn-reset-roi").addEventListener("click", () => { showModule(mod); });
  }

  function bindWlWwZoom(idx) {
    let t = null;
    const wl = document.getElementById("mod-wl"), ww = document.getElementById("mod-ww"), zm = document.getElementById("mod-zoom");
    const reload = () => { clearTimeout(t); t = setTimeout(() => loadBaseImage(idx, +wl.value, +ww.value), 200); };
    wl.addEventListener("input", () => { document.getElementById("lbl-wl").textContent = wl.value; reload(); });
    ww.addEventListener("input", () => { document.getElementById("lbl-ww").textContent = ww.value; reload(); });
    zm.addEventListener("input", () => { _zoom = +zm.value; document.getElementById("lbl-zoom").textContent = `${_zoom}×`; applyZoom(); });
    document.getElementById("canvas-wrap").addEventListener("wheel", (e) => { e.preventDefault(); _zoom = Math.max(1, Math.min(6, _zoom + (e.deltaY < 0 ? 0.5 : -0.5))); zm.value = _zoom; document.getElementById("lbl-zoom").textContent = `${_zoom}×`; applyZoom(); });
  }

  function applyZoom() {
    const c = document.getElementById("mod-canvas"), o = document.getElementById("mod-overlay");
    if (!c) return;
    if (_zoom <= 1) { c.style.width = "100%"; c.style.height = "auto"; if (o) { o.style.width = "100%"; o.style.height = "auto"; } }
    else { const w = `${c.width*_zoom}px`, h = `${c.height*_zoom}px`; c.style.width = w; c.style.height = h; if (o) { o.style.width = w; o.style.height = h; } }
  }

  async function loadBaseImage(idx, wl, ww) {
    try {
      const r = await API.getSliceImage(idx, wl, ww, 0);
      const canvas = document.getElementById("mod-canvas"); if (!canvas) return;
      const ctx = canvas.getContext("2d"), img = new Image();
      img.onload = () => {
        canvas.width = img.width; canvas.height = img.height; ctx.drawImage(img, 0, 0);
        const o = document.getElementById("mod-overlay"); if (o) { o.width = img.width; o.height = img.height; }
        applyZoom();
        // Redraw ROIs on overlay if we have results for the current module
        const activeMod = document.querySelector(".tab-btn.active")?.dataset?.module;
        if (activeMod && AppState.results[activeMod]) {
          drawRoisOnOverlay(AppState.results[activeMod].results);
        }
      };
      img.src = `data:image/png;base64,${r.image}`;
    } catch (e) {}
  }

  // ── Elegant ROI drawing on overlay canvas ──────────────────────────────────
  function drawServerOverlay(resp) {
    // Instead of showing the server PNG overlay, we draw ROIs CLIENT-SIDE
    // on the transparent overlay canvas. This makes them interactive.
    const r = resp.results;
    if (!r) return;
    drawRoisOnOverlay(r);
  }

  /**
   * Draw all ROIs from analysis results on the overlay canvas.
   * Style: medical imaging — colored strokes, text with dark outline for contrast.
   */
  function drawRoisOnOverlay(r) {
    const overlay = document.getElementById("mod-overlay");
    const base = document.getElementById("mod-canvas");
    if (!overlay || !base) return;
    overlay.width = base.width;
    overlay.height = base.height;
    const ctx = overlay.getContext("2d");
    ctx.clearRect(0, 0, overlay.width, overlay.height);

    // Helper: text with dark outline
    function strokeText(text, x, y, color, font = "bold 10px sans-serif", align = "center", baseline = "bottom") {
      if (typeof text === "string" && (text.startsWith("Rampa") || text.startsWith("FWHM="))) return;
      ctx.save();
      ctx.font = font; ctx.textAlign = align; ctx.textBaseline = baseline;
      ctx.strokeStyle = "#000"; ctx.lineWidth = 3; ctx.lineJoin = "round";
      ctx.strokeText(text, x, y);
      ctx.fillStyle = color; ctx.fillText(text, x, y);
      ctx.restore();
    }

    function labelBox(text, x, y, color, font = "bold 10px sans-serif", align = "center") {
      ctx.save();
      ctx.font = font;
      const metrics = ctx.measureText(text);
      const padX = 4, padY = 3;
      const boxW = metrics.width + padX * 2;
      const boxH = 20;
      let bx = align === "left" ? x : align === "right" ? x - boxW : x - boxW / 2;
      let by = y - boxH / 2;
      bx = Math.max(2, Math.min(overlay.width - boxW - 2, bx));
      by = Math.max(2, Math.min(overlay.height - boxH - 2, by));
      ctx.fillStyle = "rgba(15,23,42,0.82)";
      ctx.strokeStyle = "rgba(255,255,255,0.25)";
      ctx.lineWidth = 1;
      ctx.fillRect(bx, by, boxW, boxH);
      ctx.strokeRect(bx, by, boxW, boxH);
      ctx.fillStyle = color;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(text, bx + boxW / 2, by + boxH / 2);
      ctx.restore();
    }

    // Helper: dashed circle
    function dashedCircle(cx, cy, radius, color, lineWidth = 1.5, dash = [6, 4]) {
      ctx.beginPath(); ctx.arc(cx, cy, radius, 0, 2 * Math.PI);
      ctx.strokeStyle = color; ctx.lineWidth = lineWidth; ctx.setLineDash(dash);
      ctx.stroke(); ctx.setLineDash([]);
    }

    // Helper: solid circle
    function solidCircle(cx, cy, radius, color, lineWidth = 2) {
      ctx.beginPath(); ctx.arc(cx, cy, radius, 0, 2 * Math.PI);
      ctx.strokeStyle = color; ctx.lineWidth = lineWidth; ctx.stroke();
    }

    // Helper: rectangle
    function drawRect(y, x, h, w, color, lineWidth = 2, dash = []) {
      ctx.strokeStyle = color; ctx.lineWidth = lineWidth; ctx.setLineDash(dash);
      ctx.strokeRect(x, y, w, h); ctx.setLineDash([]);
    }

    // Helper: center cross
    function drawCross(cx, cy, size, color) {
      ctx.strokeStyle = color; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.moveTo(cx - size, cy); ctx.lineTo(cx + size, cy);
      ctx.moveTo(cx, cy - size); ctx.lineTo(cx, cy + size); ctx.stroke();
    }

    // ── Draw phantom outline + center ──
    const cr = r.center_rc ? r.center_rc[0] : null;
    const cc = r.center_rc ? r.center_rc[1] : null;
    const r0 = r.radius_px || 0;

    if (cr !== null && cc !== null && r0 > 0) {
      dashedCircle(cc, cr, r0, "rgba(34, 211, 238, 0.4)");
      drawCross(cc, cr, 10, "#22d3ee");
    }

    // ── UFOV circle ──
    const rUfov = r.ufov_radius_px || 0;
    if (rUfov > 0 && cc !== null) {
      dashedCircle(cc, cr, rUfov, "#22c55e", 1.5, [4, 3]);
      strokeText("UFOV", cc, cr - rUfov - 4, "#22c55e", "9px sans-serif");
    }

    // ── PSG: 4 background rectangular ROIs ──
    if (r.rois && typeof r.rois === "object" && !Array.isArray(r.rois)) {
      const roiColors = { right: "#fb923c", left: "#fb923c", up: "#60a5fa", down: "#60a5fa" };
      for (const [name, roi] of Object.entries(r.rois)) {
        if (!roi.rect) continue;
        const [ry, rx, rh, rw] = roi.rect;
        const color = roiColors[name] || "#ffffff";
        drawRect(ry, rx, rh, rw, color, 2);
        const cx = rx + rw / 2, cy = ry + rh / 2;
        strokeText(`${name[0].toUpperCase()}`, cx, cy - 6, color, "bold 11px sans-serif");
        strokeText(`${roi.mean.toFixed(0)}`, cx, cy + 8, color, "9px monospace", "center", "top");
      }
    }

    // ── PSG signal label ──
    if (r.psg_percent !== undefined && cc !== null) {
      const passed = r.passed;
      const color = passed ? "#22c55e" : "#ef4444";
      strokeText(`PSG = ${r.psg_percent.toFixed(3)}%`, cc, 14, color, "bold 12px sans-serif", "center", "top");
    }

    // ── PIU: max and min positions ──
    if (r.max_position_rc && r.min_position_rc) {
      const [maxR, maxC] = r.max_position_rc;
      const [minR, minC] = r.min_position_rc;
      const maskR = r.mask_radius_px || 5;
      solidCircle(maxC, maxR, maskR, "#ef4444");
      strokeText(`MAX ${r.s_max.toFixed(0)}`, maxC, maxR - maskR - 3, "#ef4444", "bold 9px sans-serif");
      solidCircle(minC, minR, maskR, "#3b82f6");
      strokeText(`MIN ${r.s_min.toFixed(0)}`, minC, minR - maskR - 3, "#3b82f6", "bold 9px sans-serif");
      if (r.piu_percent !== undefined) {
        const color = r.passed ? "#22c55e" : "#ef4444";
        strokeText(`PIU = ${r.piu_percent.toFixed(1)}%`, cc || overlay.width/2, 14, color, "bold 12px sans-serif", "center", "top");
      }
    }

    // ── SNR: UFOV + background ROIs ──
    if (r.snr !== undefined && r.std_left !== undefined && cc !== null) {
      // The UFOV is already drawn above. Add SNR label.
      const color = "#eab308";
      strokeText(`SNR = ${(r.snr_lr || r.snr).toFixed(1)}`, cc, cr, color, "bold 14px sans-serif");
    }

    // ── SNRU: 5 circular ROIs ──
    if (r.rois && Array.isArray(r.rois) && r.rois.length > 0 && r.rois[0].center_rc) {
      for (const roi of r.rois) {
        const [ry, rx] = roi.center_rc;
        const rpx = roi.radius_px || 10;
        solidCircle(rx, ry, rpx, "#60a5fa");
        strokeText(`${roi.snr.toFixed(0)}`, rx, ry, "#60a5fa", "bold 10px monospace", "center", "middle");
      }
      if (r.snru_percent !== undefined) {
        const color = r.passed ? "#22c55e" : "#ef4444";
        strokeText(`SNRU = ${r.snru_percent.toFixed(2)}%`, overlay.width / 2, 14, color, "bold 12px sans-serif", "center", "top");
      }
    }

    // ── Geometric: diameter measurement lines with endpoints ──
    if (r.h_line_row !== undefined && r.h_line_endpoints && r.v_line_col !== undefined && r.v_line_endpoints) {
      const hRow = r.h_line_row;
      const [hLeft, hRight] = r.h_line_endpoints;
      const vCol = r.v_line_col;
      const [vTop, vBottom] = r.v_line_endpoints;

      // Horizontal measurement line
      ctx.strokeStyle = "#f97316"; ctx.lineWidth = 2; ctx.setLineDash([]);
      ctx.beginPath(); ctx.moveTo(hLeft, hRow); ctx.lineTo(hRight, hRow); ctx.stroke();
      // Endpoint markers
      ctx.fillStyle = "#f97316";
      ctx.fillRect(hLeft - 1, hRow - 5, 3, 10);
      ctx.fillRect(hRight - 1, hRow - 5, 3, 10);
      strokeText(`H = ${r.diameter_h_mm.toFixed(1)} mm`, (hLeft + hRight) / 2, hRow + 16, "#f97316", "bold 11px sans-serif");

      // Vertical measurement line
      ctx.strokeStyle = "#3b82f6"; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.moveTo(vCol, vTop); ctx.lineTo(vCol, vBottom); ctx.stroke();
      // Endpoint markers
      ctx.fillStyle = "#3b82f6";
      ctx.fillRect(vCol - 5, vTop - 1, 10, 3);
      ctx.fillRect(vCol - 5, vBottom - 1, 10, 3);
      strokeText(`V = ${r.diameter_v_mm.toFixed(1)} mm`, vCol + 12, (vTop + vBottom) / 2, "#3b82f6", "bold 11px sans-serif", "left", "middle");

      if (Array.isArray(r.oblique_lines)) {
        ctx.setLineDash([4, 4]);
        ctx.lineWidth = 1.5;
        for (const line of r.oblique_lines.filter(Boolean)) {
          const p1 = line.endpoints_rc?.[0];
          const p2 = line.endpoints_rc?.[1];
          if (!p1 || !p2) continue;
          ctx.strokeStyle = line.name === "45" ? "#a855f7" : "#14b8a6";
          ctx.beginPath();
          ctx.moveTo(p1[1], p1[0]);
          ctx.lineTo(p2[1], p2[0]);
          ctx.stroke();
          strokeText(`${line.name} deg ${line.diameter_mm.toFixed(1)} mm`, (p1[1] + p2[1]) / 2, (p1[0] + p2[0]) / 2 - 8, ctx.strokeStyle, "bold 10px sans-serif");
        }
        ctx.setLineDash([]);
      }

      // Pass/fail title
      const color = r.passed ? "#22c55e" : "#ef4444";
      strokeText(`Geometria: ${r.passed ? "PASS" : "FAIL"} (lim ±${r.limit_mm}mm)`, overlay.width / 2, 14, color, "bold 11px sans-serif", "center", "top");
    } else if (r.diameter_h_mm !== undefined && cr !== null && r0 > 0) {
      // Fallback: draw lines from center ± radius
      ctx.strokeStyle = "#f97316"; ctx.lineWidth = 2; ctx.setLineDash([]);
      ctx.beginPath(); ctx.moveTo(cc - r0, cr); ctx.lineTo(cc + r0, cr); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(cc, cr - r0); ctx.lineTo(cc, cr + r0); ctx.stroke();
      strokeText(`H=${r.diameter_h_mm.toFixed(1)}mm`, cc, cr + r0 + 14, "#f97316", "bold 10px sans-serif");
      strokeText(`V=${r.diameter_v_mm.toFixed(1)}mm`, cc + r0 + 4, cr, "#f97316", "bold 10px sans-serif", "left", "middle");
    }

    // ── Slice thickness: ramp ROI rectangles ──
    if (r.top_ramp_rect && r.bot_ramp_rect) {
      const [ty, tx, th, tw] = r.top_ramp_rect;
      const [by, bx, bh, bw] = r.bot_ramp_rect;
      drawRect(ty, tx, th, tw, "#22d3ee", 2, [4, 3]);
      strokeText("Rampa ↑", tx + tw/2, ty - 4, "#22d3ee", "bold 9px sans-serif");
      drawRect(by, bx, bh, bw, "#fb923c", 2, [4, 3]);
      strokeText("Rampa ↓", bx + bw/2, by - 4, "#fb923c", "bold 9px sans-serif");
      // Show FWHM values
      if (r.top_ramp_length_mm !== undefined) {
        strokeText(`FWHM=${r.top_ramp_length_mm.toFixed(1)}mm`, tx + tw/2, ty + th + 12, "#22d3ee", "9px monospace");
        strokeText(`FWHM=${r.bottom_ramp_length_mm.toFixed(1)}mm`, bx + bw/2, by + bh + 12, "#fb923c", "9px monospace");
        labelBox(`Top ${r.top_ramp_length_mm.toFixed(1)} mm`, tx + tw/2, ty - 12, "#22d3ee", "bold 10px sans-serif");
        labelBox(`Bottom ${r.bottom_ramp_length_mm.toFixed(1)} mm`, bx + bw/2, by + bh + 14, "#fb923c", "bold 10px sans-serif");
      }
      const profs = r.slice_thickness_profiles;
      if (profs) {
        for (const [key, prof] of Object.entries(profs)) {
          const color = key === "top" ? "#22d3ee" : "#fb923c";
          const l = prof.left_rc;
          const rr = prof.right_rc;
          if (!l || !rr) continue;
          ctx.strokeStyle = color;
          ctx.lineWidth = 2.5;
          ctx.setLineDash([]);
          ctx.beginPath();
          ctx.moveTo(l[1], l[0]);
          ctx.lineTo(rr[1], rr[0]);
          ctx.stroke();
          ctx.fillStyle = "#ef4444";
          for (const p of [l, rr]) {
            ctx.beginPath();
            ctx.arc(p[1], p[0], 3.2, 0, Math.PI * 2);
            ctx.fill();
          }
        }
      }
      // Title
      const color = r.passed ? "#22c55e" : "#ef4444";
      strokeText(`Spessore = ${r.measured_thickness_mm.toFixed(2)} mm (nom. ${r.nominal_thickness_mm} mm)`, overlay.width/2, 14, color, "bold 11px sans-serif", "center", "top");
    } else if (r.top_ramp_length_mm !== undefined && cr !== null) {
      // Fallback: just show text
      strokeText(`Ramp ↑${r.top_ramp_length_mm.toFixed(1)}mm ↓${r.bottom_ramp_length_mm.toFixed(1)}mm`, cc || overlay.width/2, 14, "#06b6d4", "bold 10px sans-serif", "center", "top");
    }

    // ── Resolution: grid ROI rectangles ──
    if (r.grid_rects && r.grid_rects.length > 0) {
      const labels = ["1.1mm", "1.0mm", "0.9mm"];
      const mods = [r.modulation_1_1mm, r.modulation_1_0mm, r.modulation_0_9mm];
      const resolved = [r.resolved_1_1mm, r.resolved_1_0mm, r.resolved_0_9mm];
      for (let i = 0; i < r.grid_rects.length; i++) {
        const [gy, gx, gh, gw] = r.grid_rects[i];
        const color = resolved[i] ? "#22c55e" : "#ef4444";
        drawRect(gy, gx, gh, gw, color, 2);
        labelBox(labels[i], gx + gw/2, gy - 12, color, "bold 9px sans-serif");
        labelBox(`m=${(mods[i]||0).toFixed(2)}`, gx + gw/2, gy + gh + 14, color, "8px monospace");
        const mip = r.resolution_mip?.[i];
        if (mip) {
          ctx.fillStyle = "#ef4444";
          ctx.strokeStyle = "#ffffff";
          ctx.lineWidth = 1;
          const peaks = [
            ...(mip.horizontal?.peaks || []),
            ...(mip.vertical?.peaks || []),
          ];
          for (const peak of peaks) {
            if (peak.row === undefined || peak.col === undefined) continue;
            ctx.beginPath();
            ctx.arc(peak.col, peak.row, 2.8, 0, Math.PI * 2);
            ctx.fill();
            ctx.stroke();
          }
        }
      }
      const resColor = r.passed ? "#22c55e" : "#ef4444";
      const resText = r.resolved_mm === null || r.resolved_mm === undefined ? "Risoluzione assistita" : `Risoluzione = ${r.resolved_mm} mm`;
      strokeText(resText, overlay.width/2, 14, resColor, "bold 11px sans-serif", "center", "top");
    }

    // ── Low contrast: visible count + spoke positions ──
    if (r.n_visible !== undefined && r.n_total !== undefined) {
      const color = r.passed ? "#22c55e" : "#ef4444";
      strokeText(`${r.n_visible}/${r.n_total} visibili`, overlay.width/2, 14, color, "bold 12px sans-serif", "center", "top");
      // Draw spoke positions if available
      if (r.spokes && r.spokes.length > 0) {
        for (const spoke of r.spokes) {
          if (spoke.center_rc) {
            const [sr, sc] = spoke.center_rc;
            const spokeColor = spoke.visible ? "#22c55e" : "#ef444480";
            solidCircle(sc, sr, 4, spokeColor);
          }
        }
      }
    }

    // ── Slice position: vertical profile lines ──
    if (r.bar_length_1_mm !== undefined && cr !== null) {
      const color = r.passed ? "#22c55e" : "#ef4444";
      strokeText(`Pos. err = ${r.slice_position_error_mm.toFixed(2)} mm`, overlay.width/2, 14, color, "bold 11px sans-serif", "center", "top");
      strokeText(`Bar1=${r.bar_length_1_mm.toFixed(1)} Bar2=${r.bar_length_2_mm.toFixed(1)} mm`, overlay.width/2, 28, "#84cc16", "9px sans-serif", "center", "top");
    }
  }

  // ── ROI Interaction: drag ROIs, live re-analysis ─────────────────────────────
  let _dragState = null; // { type, index, startX, startY, origRect }

  function bindRoiInteraction(mod, idx) {
    const overlay = document.getElementById("mod-overlay"); if (!overlay) return;
    overlay.addEventListener("contextmenu", e => e.preventDefault());

    // HU readout + cursor change on mousemove
    let ht = null;
    overlay.addEventListener("mousemove", (e) => {
      // If dragging, move the ROI
      if (_dragState) {
        handleDrag(e, mod);
        overlay.style.cursor = "grabbing";
        return;
      }
      // Check if hovering over a draggable ROI → change cursor
      const [row, col] = eventToPixel(e, overlay);
      const hit = hitTestRoi(row, col, mod);
      overlay.style.cursor = hit ? "grab" : "crosshair";

      // HU readout (debounced)
      clearTimeout(ht); ht = setTimeout(() => {
        API.getPixelValue(idx, row, col).then(r => { document.getElementById("hu-readout").textContent = `(${r.row},${r.col}) = ${r.value}`; }).catch(() => {});
      }, 80);
    });

    // Mousedown: check if clicking on a ROI rect to start drag
    overlay.addEventListener("mousedown", (e) => {
      if (e.button !== 0) return;
      const [row, col] = eventToPixel(e, overlay);
      const hit = hitTestRoi(row, col, mod);
      if (hit) {
        _dragState = { ...hit, startRow: row, startCol: col };
        overlay.style.cursor = "grabbing";
        e.preventDefault();
      }
    });

    // Mouseup: end drag, trigger re-analysis with new positions
    overlay.addEventListener("mouseup", (e) => {
      if (_dragState) {
        overlay.style.cursor = "crosshair";
        _dragState = null;
        // Re-analyze with updated ROI positions
        scheduleAutoAnalysis(mod);
      }
    });

    // Mouseleave: cancel drag if mouse leaves overlay
    overlay.addEventListener("mouseleave", () => {
      if (_dragState) {
        _dragState = null;
        overlay.style.cursor = "crosshair";
        scheduleAutoAnalysis(mod);
      }
    });

    // Double-click: trigger re-analysis
    overlay.addEventListener("dblclick", () => { scheduleAutoAnalysis(mod); });
  }

  function eventToPixel(e, overlay) {
    const rect = overlay.getBoundingClientRect();
    const col = Math.round((e.clientX - rect.left) / rect.width * (overlay.width || 256));
    const row = Math.round((e.clientY - rect.top) / rect.height * (overlay.height || 256));
    return [row, col];
  }

  function hitTestRoi(row, col, mod) {
    const r = AppState.results[mod]?.results;
    if (!r) return null;

    // Test phantom center cross (drag to move all ROIs)
    if (r.center_rc) {
      const [cr, cc] = r.center_rc;
      if (Math.hypot(col - cc, row - cr) <= 12) {
        return { type: "center" };
      }
    }

    // Test geometric measurement lines (drag to move the line row/col)
    if (r.h_line_row !== undefined) {
      const [hL, hR] = r.h_line_endpoints || [0, 0];
      if (Math.abs(row - r.h_line_row) <= 6 && col >= hL - 10 && col <= hR + 10) {
        return { type: "h_line", origRow: r.h_line_row };
      }
    }
    if (r.v_line_col !== undefined) {
      const [vT, vB] = r.v_line_endpoints || [0, 0];
      if (Math.abs(col - r.v_line_col) <= 6 && row >= vT - 10 && row <= vB + 10) {
        return { type: "v_line", origCol: r.v_line_col };
      }
    }

    // Test slice_thickness ramp rects
    if (r.top_ramp_rect) {
      const [ty, tx, th, tw] = r.top_ramp_rect;
      if (row >= ty && row <= ty + th && col >= tx && col <= tx + tw) {
        return { type: "top_ramp_rect", rect: r.top_ramp_rect };
      }
    }
    if (r.bot_ramp_rect) {
      const [by, bx, bh, bw] = r.bot_ramp_rect;
      if (row >= by && row <= by + bh && col >= bx && col <= bx + bw) {
        return { type: "bot_ramp_rect", rect: r.bot_ramp_rect };
      }
    }

    // Test resolution grid rects
    if (r.grid_rects) {
      for (let i = 0; i < r.grid_rects.length; i++) {
        const [gy, gx, gh, gw] = r.grid_rects[i];
        if (row >= gy && row <= gy + gh && col >= gx && col <= gx + gw) {
          return { type: "grid_rect", index: i, rect: r.grid_rects[i] };
        }
      }
    }

    // Test PSG background rects
    if (r.rois && typeof r.rois === "object" && !Array.isArray(r.rois)) {
      for (const [name, roi] of Object.entries(r.rois)) {
        if (!roi.rect) continue;
        const [ry, rx, rh, rw] = roi.rect;
        if (row >= ry && row <= ry + rh && col >= rx && col <= rx + rw) {
          return { type: "psg_roi", name, rect: roi.rect };
        }
      }
    }

    // Test SNRU circular ROIs
    if (r.rois && Array.isArray(r.rois) && r.rois[0]?.center_rc) {
      for (let i = 0; i < r.rois.length; i++) {
        const [ry, rx] = r.rois[i].center_rc;
        const rpx = r.rois[i].radius_px || 10;
        const dist = Math.hypot(col - rx, row - ry);
        if (dist <= rpx + 5) {
          return { type: "snru_roi", index: i, center: [ry, rx] };
        }
      }
    }

    return null;
  }

  function handleDrag(e, mod) {
    if (!_dragState) return;
    const overlay = document.getElementById("mod-overlay");
    const [row, col] = eventToPixel(e, overlay);
    const dr = row - _dragState.startRow;
    const dc = col - _dragState.startCol;
    _dragState.startRow = row;
    _dragState.startCol = col;

    const r = AppState.results[mod]?.results;
    if (!r) return;

    // Move the ROI based on type
    if (_dragState.type === "center") {
      // Move phantom center → affects all ROIs
      if (r.center_rc) {
        r.center_rc = [r.center_rc[0] + dr, r.center_rc[1] + dc];
      }
    } else if (_dragState.type === "h_line") {
      // Move horizontal measurement line up/down
      r.h_line_row += dr;
    } else if (_dragState.type === "v_line") {
      // Move vertical measurement line left/right
      r.v_line_col += dc;
    } else if (_dragState.type === "top_ramp_rect" && r.top_ramp_rect) {
      r.top_ramp_rect[0] += dr;
      r.top_ramp_rect[1] += dc;
    } else if (_dragState.type === "bot_ramp_rect" && r.bot_ramp_rect) {
      r.bot_ramp_rect[0] += dr;
      r.bot_ramp_rect[1] += dc;
    } else if (_dragState.type === "grid_rect" && r.grid_rects) {
      r.grid_rects[_dragState.index][0] += dr;
      r.grid_rects[_dragState.index][1] += dc;
    } else if (_dragState.type === "snru_roi" && Array.isArray(r.rois)) {
      r.rois[_dragState.index].center_rc[0] += dr;
      r.rois[_dragState.index].center_rc[1] += dc;
    } else if (_dragState.type === "psg_roi" && r.rois && typeof r.rois === "object") {
      const roi = r.rois[_dragState.name];
      if (roi && roi.rect) {
        roi.rect[0] += dr;
        roi.rect[1] += dc;
      }
    }

    // Redraw overlay with updated positions (immediate visual feedback)
    drawRoisOnOverlay(r);
  }

  function scheduleAutoAnalysis(mod) {
    clearTimeout(_autoTimer);
    _autoTimer = setTimeout(() => {
      // Build kwargs from current ROI positions
      const r = AppState.results[mod]?.results;
      let kwargs = null;
      if (r) {
        kwargs = {};
        // Geometric: pass line positions
        if (r.h_line_row !== undefined) kwargs.h_line_row = r.h_line_row;
        if (r.v_line_col !== undefined) kwargs.v_line_col = r.v_line_col;
        // Slice thickness: pass ramp rects
        if (r.top_ramp_rect) kwargs.top_ramp_rect = r.top_ramp_rect;
        if (r.bot_ramp_rect) kwargs.bot_ramp_rect = r.bot_ramp_rect;
        // Resolution: pass grid rects
        if (r.grid_rects) kwargs.grid_rects = r.grid_rects;
        // Common: center and radius
        if (r.center_rc) kwargs.center_rc = r.center_rc;
        if (r.radius_px) kwargs.radius_px = r.radius_px;
        if (Object.keys(kwargs).length === 0) kwargs = null;
      }
      // For SNR, add method
      if (mod === "snr") {
        const method = document.getElementById("snr-method")?.value || "single_lr";
        kwargs = kwargs || {};
        kwargs.snr_method = method;
        if (method === "two_image") {
          const idx2 = parseInt(document.getElementById("snr-second-idx")?.value);
          if (!isNaN(idx2) && idx2 >= 0) kwargs.second_slice_idx = idx2;
        }
      }
      runAnalysis(mod, kwargs);
    }, 600);
  }

  // ── Run Analysis with SNR multi-method support ─────────────────────────────
  async function runAnalysis(mod, extraKwargs = null) {
    const btn = document.getElementById("btn-run");
    if (btn) { btn.disabled = true; btn.textContent = "⏳…"; }
    UI.setStatus(`Analisi ${AppState.moduleLabels[mod]}…`);
    try {
      let kwargs = extraKwargs;
      // SNR: pass method and optional second slice (if not already in extraKwargs)
      if (mod === "snr" && (!kwargs || !kwargs.snr_method)) {
        const method = document.getElementById("snr-method")?.value || "single_lr";
        kwargs = kwargs || {};
        kwargs.snr_method = method;
        if (method === "two_image") {
          const idx2 = parseInt(document.getElementById("snr-second-idx")?.value);
          if (!isNaN(idx2) && idx2 >= 0) kwargs.second_slice_idx = idx2;
        }
      }
      const resp = await API.analyzeModule(mod, kwargs);
      AppState.results[mod] = resp;
      renderResults(mod, resp);
      // Draw ROIs client-side on overlay (NOT the server PNG)
      drawRoisOnOverlay(resp.results);
      const passed = resp.results?.passed;
      const ts = document.getElementById(`ts-${mod}`);
      if (ts) ts.className = `tab-status ${passed === false ? "fail" : "pass"}`;
      if (btn) {
        btn.textContent = "Fatto";
        btn.className = "btn btn-secondary";
        btn.disabled = false;
        btn.dataset.mode = "done";
      }
      UI.setStatus(`✓ ${AppState.moduleLabels[mod]}`);
    } catch (err) {
      if (btn) { btn.disabled = false; btn.textContent = "⚡ Riprova"; }
      document.getElementById("mod-results-area").innerHTML = `<div class="result-section" style="color:var(--accent-red)">Errore: ${err.message}</div>`;
      UI.setStatus(`✗ ${err.message}`);
    }
  }

  // ── Render results with profile plots ──────────────────────────────────────
  function renderResults(mod, resp) {
    const area = document.getElementById("mod-results-area"); if (!area || !resp.results) return;
    const r = resp.results;
    let html = "";

    if (mod === "psg") {
      html = `<div class="result-section">
        <div class="summary-row ${r.passed?'pass':'fail'}"><span class="summary-label">PSG</span><span class="summary-value">${UI.fmt(r.psg_percent,4)}%</span></div>
        <div class="summary-row info"><span class="summary-label">Segnale UFOV (S)</span><span class="summary-value">${UI.fmt(r.signal_mean,1)}</span></div>
        <div class="summary-row info"><span class="summary-label">S_Right / S_Left</span><span class="summary-value">${UI.fmt(r.s_right,1)} / ${UI.fmt(r.s_left,1)}</span></div>
        <div class="summary-row info"><span class="summary-label">S_Up / S_Down</span><span class="summary-value">${UI.fmt(r.s_up,1)} / ${UI.fmt(r.s_down,1)}</span></div>
        <div class="summary-row info"><span class="summary-label">Limite ACR / AAPM</span><span class="summary-value">≤ 2.5% / ≤ 1.0%</span></div>
        <div class="summary-row ${r.passed_aapm?'pass':'fail'}"><span class="summary-label">AAPM</span><span class="summary-value">${r.passed_aapm?'✓ PASS':'✗ FAIL'}</span></div>
      </div>`;
    } else if (mod === "piu") {
      html = `<div class="result-section">
        <div class="summary-row ${r.passed?'pass':'fail'}"><span class="summary-label">PIU</span><span class="summary-value">${UI.fmt(r.piu_percent,2)}%</span></div>
        <div class="summary-row info"><span class="summary-label">S_max / S_min</span><span class="summary-value">${UI.fmt(r.s_max,1)} / ${UI.fmt(r.s_min,1)}</span></div>
        <div class="summary-row info"><span class="summary-label">Limite</span><span class="summary-value">≥ ${r.limit||87.5}%</span></div>
      </div>`;
    } else if (mod === "snr") {
      const method = document.getElementById("snr-method")?.value || "single_lr";
      let mainSnr = r.snr;
      if (method === "single_ud") mainSnr = r.snr_ud || r.snr;
      else if (method === "single_all") mainSnr = r.snr_all || r.snr;
      html = `<div class="result-section">
        <div class="summary-row pass"><span class="summary-label">SNR (metodo selezionato)</span><span class="summary-value" style="font-size:18px;color:var(--accent-yellow);">${UI.fmt(mainSnr,1)}</span></div>
        <div class="summary-row info"><span class="summary-label">SNR (L+R) — Eq.7</span><span class="summary-value">${UI.fmt(r.snr_lr||r.snr,1)}</span></div>
        <div class="summary-row info"><span class="summary-label">SNR (U+D)</span><span class="summary-value">${UI.fmt(r.snr_ud,1)}</span></div>
        <div class="summary-row info"><span class="summary-label">SNR (all 4)</span><span class="summary-value">${UI.fmt(r.snr_all,1)}</span></div>
        <div class="summary-row info"><span class="summary-label">Segnale medio S</span><span class="summary-value">${UI.fmt(r.signal_mean,1)}</span></div>
        <div class="summary-row info"><span class="summary-label">σ_L / σ_R</span><span class="summary-value">${UI.fmt(r.std_left,3)} / ${UI.fmt(r.std_right,3)}</span></div>
        <div class="summary-row info"><span class="summary-label">σ_U / σ_D</span><span class="summary-value">${UI.fmt(r.std_up,3)} / ${UI.fmt(r.std_down,3)}</span></div>
        ${r.method === "two_image_subtraction" ? `<div class="summary-row info"><span class="summary-label">σ_diff (subtraction)</span><span class="summary-value">${UI.fmt(r.sigma_diff,4)}</span></div>` : ""}
        <div class="summary-row info"><span class="summary-label">Metodo</span><span class="summary-value">${r.method||"single image NEMA"}</span></div>
      </div>
      <div class="result-section"><h4>Confronto metodi SNR (articolo)</h4>
        <table class="result-table"><thead><tr><th>Metodo</th><th>SNR</th><th>Ref.</th></tr></thead><tbody>
          <tr><td>A) Single — σ(L+R)</td><td style="font-weight:700">${UI.fmt(r.snr_lr||r.snr,1)}</td><td>Eq.7</td></tr>
          <tr><td>A) Single — σ(U+D)</td><td>${UI.fmt(r.snr_ud,1)}</td><td>—</td></tr>
          <tr><td>A) Single — σ(all 4)</td><td>${UI.fmt(r.snr_all,1)}</td><td>—</td></tr>
          ${r.method === "two_image_subtraction" ? `<tr><td>C) Two-image subtraction</td><td style="font-weight:700;color:var(--accent-cyan)">${UI.fmt(r.snr,1)}</td><td>Eq.6</td></tr>` : ""}
        </tbody></table>
      </div>`;
    } else if (mod === "snru") {
      html = `<div class="result-section">
        <div class="summary-row ${r.passed?'pass':'fail'}"><span class="summary-label">SNRU</span><span class="summary-value">${UI.fmt(r.snru_percent,2)}%</span></div>
        <div class="summary-row info"><span class="summary-label">SNR medio</span><span class="summary-value">${UI.fmt(r.snr_mean,1)}</span></div>
        <div class="summary-row info"><span class="summary-label">σ SNR</span><span class="summary-value">${UI.fmt(r.snr_std,3)}</span></div>
        <div class="summary-row info"><span class="summary-label">Limite achievable / acceptable</span><span class="summary-value">≤ 5% / ≤ 10%</span></div>
      </div>`;
      if (r.rois && r.rois.length > 0) {
        html += `<div class="result-section"><h4>ROI SNR (5 posizioni)</h4><table class="result-table"><thead><tr><th>Posizione</th><th>Media</th><th>σ</th><th>SNR</th></tr></thead><tbody>`;
        for (const roi of r.rois) html += `<tr><td>${roi.name}</td><td>${UI.fmt(roi.mean_val,1)}</td><td>${UI.fmt(roi.std_val,2)}</td><td style="font-weight:700">${UI.fmt(roi.snr,1)}</td></tr>`;
        html += `</tbody></table></div>`;
        // Bar chart of SNR values
        html += `<div class="result-section"><h4>Profilo SNR</h4><canvas id="snru-chart" width="350" height="150" style="width:100%;max-width:400px;"></canvas></div>`;
      }
    } else if (mod === "geometric") {
      const gp = r.geometric_profiles || {};
      const d45 = gp.diagonal_45?.diameter_mm;
      const d135 = gp.diagonal_135?.diameter_mm;
      html = `<div class="result-section">
        <div class="summary-row ${r.passed?'pass':'fail'}"><span class="summary-label">Geometria</span><span class="summary-value">${UI.passIcon(r.passed)}</span></div>
        <div class="summary-row info"><span class="summary-label">Diametro H / V</span><span class="summary-value">${UI.fmt(r.diameter_h_mm,2)} / ${UI.fmt(r.diameter_v_mm,2)} mm</span></div>
        <div class="summary-row info"><span class="summary-label">Nominale</span><span class="summary-value">${r.nominal_diameter_mm||190} mm</span></div>
        <div class="summary-row info"><span class="summary-label">Oblique 45 / 135</span><span class="summary-value">${d45 !== undefined ? UI.fmt(d45,2) : "-"} / ${d135 !== undefined ? UI.fmt(d135,2) : "-"} mm</span></div>
      </div>
      <div class="result-section">
        <h4>Profili lineari ROI</h4>
        <canvas id="geometric-profile-chart" width="350" height="170" style="width:100%;max-width:420px;"></canvas>
      </div>`;
    } else if (mod === "slice_thickness") {
      html = `<div class="result-section">
        <div class="summary-row ${r.passed?'pass':'fail'}"><span class="summary-label">Spessore</span><span class="summary-value">${UI.fmt(r.measured_thickness_mm,2)} mm</span></div>
        <div class="summary-row info"><span class="summary-label">Nominale</span><span class="summary-value">${r.nominal_thickness_mm||5} mm</span></div>
        <div class="summary-row info"><span class="summary-label">Rampa sup/inf</span><span class="summary-value">${UI.fmt(r.top_ramp_length_mm,2)} / ${UI.fmt(r.bottom_ramp_length_mm,2)} mm</span></div>
        <div class="summary-row info"><span class="summary-label">Segnale medio rampe</span><span class="summary-value">${UI.fmt(r.ramp_signal_mean,1)} (soglia ${UI.fmt(r.ramp_threshold,1)})</span></div>
        <div class="summary-row info"><span class="summary-label">Formula ACR</span><span class="summary-value">0.2*T*B/(T+B)</span></div>
      </div>`;
      if (r.slice_thickness_profiles) {
        html += `<div class="result-section">
          <h4>Profili rampe</h4>
          <div style="font-size:11px;color:var(--text-muted);margin-bottom:8px;">Profilo grezzo medio per colonna, senza filtro. Soglia = meta del segnale medio nelle ROI, come da manuale ACR.</div>
          <canvas id="slice-thickness-profile-chart" width="760" height="230" style="width:100%;height:230px;border-radius:6px;background:#0f172a;"></canvas>
      </div>`;
      }
    } else if (mod === "slice_position") {
      html = `<div class="result-section">
        <div class="summary-row ${r.passed?'pass':'fail'}"><span class="summary-label">Errore posizione</span><span class="summary-value">${UI.fmt(r.slice_position_error_mm,2)} mm</span></div>
        <div class="summary-row info"><span class="summary-label">Barra 1 / 2</span><span class="summary-value">${UI.fmt(r.bar_length_1_mm,2)} / ${UI.fmt(r.bar_length_2_mm,2)} mm</span></div>
      </div>`;
    } else if (mod === "resolution") {
      html = `<div class="result-section">
        <div class="summary-row info"><span class="summary-label">Modalita</span><span class="summary-value">assistita MIP + picchi</span></div>
        <div class="summary-row info"><span class="summary-label">Valutazione</span><span class="summary-value">manuale sui picchi H/V</span></div>
      </div>`;
      if (r.grid_rects && r.grid_rects.length > 0) {
        const labels = ["1.1 mm", "1.0 mm", "0.9 mm"];
        const mods = [r.modulation_1_1mm, r.modulation_1_0mm, r.modulation_0_9mm];
        const manualTicks = r.manual_resolution_ticks || {};
        html += `<div class="result-section"><h4>Registrazione visiva</h4><div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:8px;">`;
        for (let i = 0; i < labels.length; i++) {
          const checked = manualTicks[labels[i]] === true;
          html += `<label style="display:inline-flex;align-items:center;gap:5px;font-size:12px;"><input type="checkbox" class="resolution-manual-tick" data-target="${labels[i]}" ${checked ? "checked" : ""}>${labels[i]}</label>`;
        }
        html += `</div><table class="result-table"><thead><tr><th>Target</th><th>ROI y,x,h,w</th><th>Picchi H/V</th><th>Mod.</th></tr></thead><tbody>`;
        for (let i = 0; i < r.grid_rects.length; i++) {
          const mip = r.resolution_mip?.[i];
          const hc = mip?.horizontal?.count ?? 0;
          const vc = mip?.vertical?.count ?? 0;
          html += `<tr><td>${labels[i]}</td><td>${r.grid_rects[i].join(", ")}</td><td>${hc} / ${vc}</td><td>${UI.fmt(mods[i],4)}</td></tr>`;
        }
        html += `</tbody></table></div>`;
      }
      if (r.resolution_mip && r.resolution_mip.length > 0) {
        html += `<div class="result-section"><h4>Profili MIP H / V</h4>`;
        for (let i = 0; i < r.resolution_mip.length; i++) {
          const target = r.resolution_mip[i].target_mm;
          html += `<div style="font-size:12px;font-weight:600;color:var(--text-secondary);margin:12px 0 4px;">${target.toFixed(1)} mm</div>
            <canvas class="resolution-mip-chart" id="resolution-mip-${i}" width="760" height="190" style="width:100%;height:190px;border-radius:6px;background:#0f172a;"></canvas>`;
        }
        html += `</div>`;
      }
    } else if (false && mod === "resolution") {
      html = `<div class="result-section">
        <div class="summary-row ${r.passed?'pass':'fail'}"><span class="summary-label">Risoluzione</span><span class="summary-value">${r.resolved_mm||"—"} mm</span></div>
      </div>`;
      if (r.grid_rects && r.grid_rects.length > 0) {
        const labels = ["1.1 mm", "1.0 mm", "0.9 mm"];
        const mods = [r.modulation_1_1mm, r.modulation_1_0mm, r.modulation_0_9mm];
        const resolved = [r.resolved_1_1mm, r.resolved_1_0mm, r.resolved_0_9mm];
        html += `<div class="result-section"><h4>ROI risoluzione</h4><table class="result-table"><thead><tr><th>Target</th><th>ROI y,x,h,w</th><th>Mod.</th><th>Esito</th></tr></thead><tbody>`;
        for (let i = 0; i < r.grid_rects.length; i++) {
          html += `<tr><td>${labels[i]}</td><td>${r.grid_rects[i].join(", ")}</td><td>${UI.fmt(mods[i],4)}</td><td>${UI.passIcon(resolved[i])}</td></tr>`;
        }
        html += `</tbody></table></div>`;
      }
    } else if (mod === "low_contrast") {
      html = `<div class="result-section">
        <div class="summary-row ${r.passed?'pass':'fail'}"><span class="summary-label">Spoke visibili</span><span class="summary-value">${r.n_visible||0} / ${r.n_total||"?"}</span></div>
      </div>`;
    } else {
      html = `<div class="result-section"><pre style="font-size:10px;overflow:auto;max-height:200px;">${JSON.stringify(r,null,2)}</pre></div>`;
    }
    area.innerHTML = html;
    if (mod === "resolution") {
      for (const input of area.querySelectorAll(".resolution-manual-tick")) {
        input.addEventListener("change", () => {
          const current = AppState.results[mod]?.results;
          if (!current) return;
          current.manual_resolution_ticks = current.manual_resolution_ticks || {};
          current.manual_resolution_ticks[input.dataset.target] = input.checked;
        });
      }
    }

    // Draw SNRU bar chart if applicable
    if (mod === "snru" && r.rois) setTimeout(() => drawSnruChart(r), 50);
    if (mod === "geometric" && r.geometric_profiles) setTimeout(() => drawGeometricProfileChart(r), 50);
    if (mod === "resolution" && r.resolution_mip) setTimeout(() => drawResolutionMipCharts(r), 50);
    if (mod === "slice_thickness" && r.slice_thickness_profiles) setTimeout(() => drawSliceThicknessProfileChart(r), 50);
  }

  function drawSliceThicknessProfileChart(r) {
    const canvas = document.getElementById("slice-thickness-profile-chart"); if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const W = canvas.width, H = canvas.height;
    const pad = { l: 42, r: 16, t: 18, b: 30 };
    const profiles = [
      { label: "Top", color: "#22d3ee", p: r.slice_thickness_profiles?.top },
      { label: "Bottom", color: "#fb923c", p: r.slice_thickness_profiles?.bottom },
    ].filter(s => s.p?.values?.length > 1);
    if (!profiles.length) return;
    const vals = profiles.flatMap(s => s.p.values);
    const yMin = Math.min(...vals);
    const yMax = Math.max(...vals);
    const xMin = Math.min(...profiles.flatMap(s => s.p.x_mm || []));
    const xMax = Math.max(...profiles.flatMap(s => s.p.x_mm || []));
    const toX = x => pad.l + (x - xMin) / Math.max(1e-6, xMax - xMin) * (W - pad.l - pad.r);
    const toY = y => H - pad.b - (y - yMin) / Math.max(1e-6, yMax - yMin) * (H - pad.t - pad.b);

    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = "#0f172a"; ctx.fillRect(0, 0, W, H);
    ctx.strokeStyle = "rgba(148,163,184,.35)"; ctx.lineWidth = 1;
    for (let i = 0; i <= 4; i++) {
      const y = pad.t + i * (H - pad.t - pad.b) / 4;
      ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(W - pad.r, y); ctx.stroke();
    }
    ctx.strokeStyle = "#64748b";
    ctx.beginPath(); ctx.moveTo(pad.l, pad.t); ctx.lineTo(pad.l, H - pad.b); ctx.lineTo(W - pad.r, H - pad.b); ctx.stroke();

    for (const s of profiles) {
      const x = s.p.x_mm;
      const y = s.p.values;
      const ys = s.p.smoothed || [];
      const hasDifferentSmooth = ys.length === y.length && ys.some((v, i) => Math.abs(v - y[i]) > 1e-6);
      if (hasDifferentSmooth) {
        ctx.globalAlpha = 0.4;
        ctx.strokeStyle = s.color; ctx.lineWidth = 1.2; ctx.beginPath();
        for (let i = 0; i < ys.length; i++) {
          const px = toX(x[i]), py = toY(ys[i]);
          if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
        }
        ctx.stroke(); ctx.globalAlpha = 1;
      }
      ctx.strokeStyle = s.color; ctx.lineWidth = 2.2; ctx.beginPath();
      for (let i = 0; i < y.length; i++) {
        const px = toX(x[i]), py = toY(y[i]);
        if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
      }
      ctx.stroke();
      if (s.p.threshold !== undefined) {
        ctx.save(); ctx.setLineDash([5,4]); ctx.globalAlpha = 0.55;
        const ty = toY(s.p.threshold);
        ctx.beginPath(); ctx.moveTo(pad.l, ty); ctx.lineTo(W - pad.r, ty); ctx.stroke();
        ctx.restore();
      }
      ctx.fillStyle = "#ef4444"; ctx.strokeStyle = "#fff"; ctx.lineWidth = 1;
      for (const edge of [s.p.left_px, s.p.right_px]) {
        if (edge === null || edge === undefined) continue;
        const idx = Math.max(0, Math.min(x.length - 1, Math.round(edge)));
        ctx.beginPath(); ctx.arc(toX(x[idx]), toY(y[idx]), 4, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
      }
    }
    ctx.font = "11px sans-serif"; ctx.textAlign = "left";
    ctx.fillStyle = "#22d3ee"; ctx.fillText(`Top ${UI.fmt(r.top_ramp_length_mm,1)} mm`, pad.l + 8, 13);
    ctx.fillStyle = "#fb923c"; ctx.fillText(`Bottom ${UI.fmt(r.bottom_ramp_length_mm,1)} mm`, pad.l + 110, 13);
    ctx.fillStyle = "#cbd5e1"; ctx.textAlign = "right";
    ctx.fillText(`Spessore ${UI.fmt(r.measured_thickness_mm,2)} mm`, W - pad.r, 13);
  }

  function drawResolutionMipCharts(r) {
    if (!Array.isArray(r.resolution_mip)) return;
    for (let i = 0; i < r.resolution_mip.length; i++) {
      const canvas = document.getElementById(`resolution-mip-${i}`);
      if (!canvas) continue;
      const item = r.resolution_mip[i];
      const ctx = canvas.getContext("2d");
      const W = canvas.width, H = canvas.height;
      const pad = { l: 34, r: 12, t: 14, b: 24 };
      const hProf = item.horizontal || {};
      const vProf = item.vertical || {};
      const series = [
        { label: "H", color: "#f97316", data: hProf.values || [], smooth: hProf.smoothed || [], peaks: hProf.peaks || [], threshold: hProf.threshold },
        { label: "V", color: "#3b82f6", data: vProf.values || [], smooth: vProf.smoothed || [], peaks: vProf.peaks || [], threshold: vProf.threshold },
      ].filter(s => s.data.length > 1);
      if (!series.length) continue;

      const yVals = series.flatMap(s => s.data);
      const yMin = Math.min(...yVals);
      const yMax = Math.max(...yVals);
      const xMax = Math.max(...series.map(s => s.data.length - 1));
      const toX = x => pad.l + x / Math.max(1, xMax) * (W - pad.l - pad.r);
      const toY = y => H - pad.b - (y - yMin) / Math.max(1e-6, yMax - yMin) * (H - pad.t - pad.b);

      ctx.clearRect(0, 0, W, H);
      ctx.fillStyle = "#0f172a";
      ctx.fillRect(0, 0, W, H);
      ctx.strokeStyle = "rgba(148,163,184,.35)";
      ctx.lineWidth = 1;
      for (let g = 0; g <= 4; g++) {
        const y = pad.t + g * (H - pad.t - pad.b) / 4;
        ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(W - pad.r, y); ctx.stroke();
      }
      ctx.strokeStyle = "#64748b";
      ctx.beginPath(); ctx.moveTo(pad.l, pad.t); ctx.lineTo(pad.l, H - pad.b); ctx.lineTo(W - pad.r, H - pad.b); ctx.stroke();

      for (const s of series) {
        if (s.smooth.length === s.data.length) {
          ctx.globalAlpha = 0.35;
          ctx.strokeStyle = s.color;
          ctx.lineWidth = 1.2;
          ctx.beginPath();
          for (let j = 0; j < s.smooth.length; j++) {
            const x = toX(j), y = toY(s.smooth[j]);
            if (j === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
          }
          ctx.stroke();
          ctx.globalAlpha = 1;
        }
        ctx.strokeStyle = s.color;
        ctx.lineWidth = 2.2;
        ctx.beginPath();
        for (let j = 0; j < s.data.length; j++) {
          const x = toX(j), y = toY(s.data[j]);
          if (j === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        }
        ctx.stroke();

        if (s.threshold !== undefined) {
          ctx.globalAlpha = 0.55;
          ctx.setLineDash([3, 3]);
          const ty = toY(s.threshold);
          ctx.beginPath(); ctx.moveTo(pad.l, ty); ctx.lineTo(W - pad.r, ty); ctx.stroke();
          ctx.setLineDash([]);
          ctx.globalAlpha = 1;
        }

        ctx.fillStyle = "#ef4444";
        ctx.strokeStyle = "#ffffff";
        ctx.lineWidth = 1;
        for (const peak of s.peaks) {
          const px = toX(peak.index);
          const py = toY(s.data[Math.max(0, Math.min(s.data.length - 1, peak.index))]);
          ctx.beginPath();
          ctx.arc(px, py, 3.2, 0, Math.PI * 2);
          ctx.fill();
          ctx.stroke();
        }
      }

      ctx.font = "10px sans-serif";
      ctx.fillStyle = "#cbd5e1";
      ctx.fillText(`H ${hProf.count || 0}`, pad.l + 6, 11);
      ctx.fillStyle = "#93c5fd";
      ctx.fillText(`V ${vProf.count || 0}`, pad.l + 48, 11);
      ctx.fillStyle = "#cbd5e1";
      ctx.textAlign = "right";
      ctx.fillText(`${item.target_mm.toFixed(1)} mm`, W - pad.r, 11);
      ctx.textAlign = "left";
    }
  }

  function drawGeometricProfileChart(r) {
    const canvas = document.getElementById("geometric-profile-chart"); if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const W = canvas.width, H = canvas.height;
    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = "#0f172a";
    ctx.fillRect(0, 0, W, H);

    const profiles = [
      { label: "H", color: "#f97316", data: r.geometric_profiles?.horizontal?.best },
      { label: "V", color: "#3b82f6", data: r.geometric_profiles?.vertical?.best },
    ].filter(p => p.data?.profile?.x_mm?.length > 1);
    if (!profiles.length) return;

    const xs = profiles.flatMap(p => p.data.profile.x_mm);
    const ys = profiles.flatMap(p => p.data.profile.values);
    const xMin = Math.min(...xs), xMax = Math.max(...xs);
    const yMin = Math.min(...ys), yMax = Math.max(...ys);
    const pad = { l: 34, r: 12, t: 14, b: 26 };
    const toX = x => pad.l + (x - xMin) / Math.max(1e-6, xMax - xMin) * (W - pad.l - pad.r);
    const toY = y => H - pad.b - (y - yMin) / Math.max(1e-6, yMax - yMin) * (H - pad.t - pad.b);

    ctx.strokeStyle = "rgba(148,163,184,.35)";
    ctx.lineWidth = 1;
    for (let i = 0; i <= 4; i++) {
      const y = pad.t + i * (H - pad.t - pad.b) / 4;
      ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(W - pad.r, y); ctx.stroke();
    }
    ctx.strokeStyle = "#64748b";
    ctx.beginPath(); ctx.moveTo(pad.l, pad.t); ctx.lineTo(pad.l, H - pad.b); ctx.lineTo(W - pad.r, H - pad.b); ctx.stroke();

    for (const p of profiles) {
      const x = p.data.profile.x_mm;
      const y = p.data.profile.values;
      ctx.strokeStyle = p.color;
      ctx.lineWidth = 1.8;
      ctx.beginPath();
      for (let i = 0; i < x.length; i++) {
        const px = toX(x[i]), py = toY(y[i]);
        if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
      }
      ctx.stroke();
      if (p.data.threshold !== undefined) {
        ctx.setLineDash([3, 3]);
        ctx.globalAlpha = 0.65;
        const ty = toY(p.data.threshold);
        ctx.beginPath(); ctx.moveTo(pad.l, ty); ctx.lineTo(W - pad.r, ty); ctx.stroke();
        ctx.setLineDash([]);
        ctx.globalAlpha = 1;
      }
    }

    ctx.font = "10px sans-serif";
    ctx.fillStyle = "#cbd5e1";
    ctx.fillText(`${Math.round(xMin)} mm`, pad.l, H - 8);
    ctx.textAlign = "right";
    ctx.fillText(`${Math.round(xMax)} mm`, W - pad.r, H - 8);
    ctx.textAlign = "left";
    profiles.forEach((p, i) => {
      ctx.fillStyle = p.color;
      ctx.fillText(`${p.label} ${p.data.diameter_mm.toFixed(1)} mm`, pad.l + 8 + i * 92, 12);
    });
    ctx.textAlign = "left";
  }

  function drawSnruChart(r) {
    const canvas = document.getElementById("snru-chart"); if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const rois = r.rois, n = rois.length;
    const W = canvas.width, H = canvas.height, pad = 30;
    const barW = (W - 2*pad) / n * 0.7, gap = (W - 2*pad) / n;
    const maxSnr = Math.max(...rois.map(r => r.snr)) * 1.15;
    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = "#1e293b"; ctx.fillRect(0, 0, W, H);
    // Bars
    for (let i = 0; i < n; i++) {
      const x = pad + gap * i + (gap - barW) / 2;
      const h = (rois[i].snr / maxSnr) * (H - 2*pad);
      ctx.fillStyle = i === 0 ? "#22d3ee" : "#60a5fa";
      ctx.fillRect(x, H - pad - h, barW, h);
      ctx.fillStyle = "#e2e8f0"; ctx.font = "9px sans-serif"; ctx.textAlign = "center";
      ctx.fillText(rois[i].name.split(" ")[0], x + barW/2, H - pad + 12);
      ctx.fillText(rois[i].snr.toFixed(0), x + barW/2, H - pad - h - 4);
    }
    // Mean line
    const meanY = H - pad - (r.snr_mean / maxSnr) * (H - 2*pad);
    ctx.strokeStyle = "#fbbf24"; ctx.lineWidth = 1.5; ctx.setLineDash([4,3]);
    ctx.beginPath(); ctx.moveTo(pad, meanY); ctx.lineTo(W-pad, meanY); ctx.stroke();
    ctx.setLineDash([]); ctx.fillStyle = "#fbbf24"; ctx.font = "bold 9px sans-serif"; ctx.textAlign = "left";
    ctx.fillText(`media=${r.snr_mean.toFixed(1)}`, W-pad+2, meanY+3);
  }

  // Analyze All
  document.getElementById("btn-analyze-all").addEventListener("click", async () => {
    UI.setStatus("Analisi tutti i moduli…");
    try {
      const resp = await API.analyzeAll();
      for (const [mod, data] of Object.entries(resp.results || {})) { AppState.results[mod] = data; const ts = document.getElementById(`ts-${mod}`); if (ts) ts.className = `tab-status ${data.results?.passed === false ? "fail" : "pass"}`; }
      UI.setStatus("✓ Completata"); const at = document.querySelector(".tab-btn.active"); if (at) showModule(at.dataset.module);
    } catch (e) { UI.setStatus(`✗ ${e.message}`); }
  });
  document.getElementById("btn-go-report").addEventListener("click", () => { setupStep5(); UI.showStep(5); });

  // ═══════════════════════════════════════════════════════════════════════════
  // STEP 5: Report
  // ═══════════════════════════════════════════════════════════════════════════
  function setupStep5() {
    const c = document.getElementById("report-container"); c.innerHTML = "";
    const allP = Object.values(AppState.results).every(r => r.results?.passed !== false);
    const hdr = document.createElement("div"); hdr.className = "report-card"; hdr.style.gridColumn = "1/-1";
    hdr.innerHTML = `<div class="report-card-header"><h3>Report QC MRI — ACR</h3><span class="status-badge ${allP?'pass':'fail'}">${allP?'✓ CONFORME':'✗ NON CONFORME'}</span></div>
      <div class="report-kv-grid"><div class="kv-item"><span class="kv-lbl">Data</span><span class="kv-val">${AppState.metaInfo.data_controllo||"—"}</span></div>
      <div class="kv-item"><span class="kv-lbl">Presidio</span><span class="kv-val">${AppState.metaInfo.presidio||"—"}</span></div>
      <div class="kv-item"><span class="kv-lbl">Sala</span><span class="kv-val">${AppState.metaInfo.sala||"—"}</span></div>
      <div class="kv-item"><span class="kv-lbl">Scanner</span><span class="kv-val">${AppState.dicomMeta?.manufacturer||""} ${AppState.dicomMeta?.model||""} ${AppState.dicomMeta?.magnetic_field_T||""}T</span></div></div>`;
    c.appendChild(hdr);
    for (const mod of AppState.moduleOrder) {
      if (!AppState.results[mod]) continue;
      const d = AppState.results[mod], r = d.results||{};
      const card = document.createElement("div"); card.className = "report-card";
      let val = r.psg_percent !== undefined ? `${UI.fmt(r.psg_percent,4)}%` : r.piu_percent !== undefined ? `${UI.fmt(r.piu_percent,2)}%` : r.snr !== undefined ? `SNR=${UI.fmt(r.snr,1)}` : r.snru_percent !== undefined ? `${UI.fmt(r.snru_percent,2)}%` : r.passed !== undefined ? (r.passed?"PASS":"FAIL") : "—";
      card.innerHTML = `<div class="report-card-header"><h3>${AppState.moduleLabels[mod]}</h3><span class="status-badge ${r.passed===false?'fail':'pass'}">${r.passed===false?'✗ FAIL':'✓ PASS'}</span></div>
        <div class="report-kv-grid"><div class="kv-item"><span class="kv-lbl">Risultato</span><span class="kv-val">${val}</span></div></div>
        ${d.overlay_image?`<img src="data:image/png;base64,${d.overlay_image}" style="width:100%;border-radius:6px;margin-top:8px;"/>`:""}`;
      c.appendChild(card);
    }
  }
  document.getElementById("btn-new-analysis").addEventListener("click", () => { AppState.reset(); UI.showStep(1); UI.setStatus("Pronto"); });

  // Health check
  async function checkHealth() { try { await API.health(); UI.setApiStatus(true); } catch { UI.setApiStatus(false); } }
  await checkHealth(); setInterval(checkHealth, 15000);
  UI.setStatus("Pronto");
})();
