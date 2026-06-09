/**
 * api.js — HTTP client per MRI QC backend
 */
"use strict";

const API = {
  baseUrl: "http://127.0.0.1:8181",

  async fetch(path, opts = {}) {
    const url = `${this.baseUrl}${path}`;
    const res = await fetch(url, {
      headers: { "Content-Type": "application/json" },
      ...opts,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    return res.json();
  },

  get(path) { return this.fetch(path); },
  post(path, body) {
    return this.fetch(path, { method: "POST", body: JSON.stringify(body) });
  },

  health() { return this.get("/health"); },

  loadDicom(inputDir) {
    return this.post("/load-dicom", { input_dir: inputDir });
  },

  getSlices() { return this.get("/slices"); },

  getSliceImage(idx, wl = null, ww = null, size = 0) {
    let url = `/slice-image/${idx}?size=${size}`;
    if (wl != null) url += `&wl=${wl}`;
    if (ww != null) url += `&ww=${ww}`;
    return this.get(url);
  },

  getThumbnails(wl = null, ww = null, size = 128) {
    let url = `/slice-thumbnails?size=${size}`;
    if (wl != null) url += `&wl=${wl}`;
    if (ww != null) url += `&ww=${ww}`;
    return this.get(url);
  },

  getModuleConfig() { return this.get("/module-config"); },

  suggestSlices() { return this.get("/suggest-slices"); },

  assignSlices(assignments) {
    return this.post("/assign-slices", { assignments });
  },

  analyzeModule(module, kwargs = null) {
    return this.post("/analyze", { module, kwargs });
  },

  analyzeAll() { return this.post("/analyze-all", {}); },

  setMetaInfo(info) { return this.post("/meta-info", info); },

  getDicomMeta() { return this.get("/dicom-meta"); },

  getPixelValue(sliceIdx, row, col) {
    return this.get(`/pixel-value?slice_idx=${sliceIdx}&row=${row}&col=${col}`);
  },

  // Multi-sequence & persistence
  getSequences() { return this.get("/sequences"); },
  setActiveSequence(uid) { return this.post("/set-active-sequence", { uid }); },
  saveSession(filepath = "") { return this.post("/save-session", { filepath }); },
  loadSession(filepath) { return this.post("/load-session", { filepath }); },
  relaxometry(sliceIdx = 0, roiFraction = 0.75) {
    return this.post("/relaxometry", { slice_idx: sliceIdx, roi_fraction: roiFraction });
  },
  browseFs(path = "") { return this.get(`/browse-fs?path=${encodeURIComponent(path)}`); },

  loadDicomRecursive(inputDir) {
    return this.post("/load-dicom", { input_dir: inputDir, recursive: true });
  },

  get _base() { return this.baseUrl; },
};
