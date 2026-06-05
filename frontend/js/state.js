/**
 * state.js — Application state for MRI QC Analyzer
 */
"use strict";

const AppState = {
  currentStep: 1,
  inputDir: "",

  // Slice data
  slices: [],
  thumbnails: [],

  // Module config
  moduleOrder: ["geometric", "resolution", "slice_thickness", "slice_position",
                "piu", "psg", "low_contrast", "snr", "snru"],
  moduleLabels: {
    geometric: "Accuratezza Geometrica",
    resolution: "Risoluzione Spaziale (Alto Contrasto)",
    slice_thickness: "Spessore di Strato",
    slice_position: "Posizione Strato",
    piu: "PIU — Uniformità Immagine",
    psg: "PSG — Percent Signal Ghosting",
    low_contrast: "Basso Contrasto (LCD)",
    snr: "SNR — Signal-to-Noise Ratio",
    snru: "SNRU — SNR Uniformity",
  },
  moduleColors: {
    geometric: "#f97316",
    resolution: "#a855f7",
    slice_thickness: "#06b6d4",
    slice_position: "#84cc16",
    piu: "#2a9d8f",
    psg: "#e63946",
    low_contrast: "#f472b6",
    snr: "#e9c46a",
    snru: "#457b9d",
  },

  // Default slice assignments for ACR phantom (0-indexed)
  // Multiple modules CAN share the same slice
  defaultSlices: {
    geometric: 0,        // Slice 1
    resolution: 0,       // Slice 1
    slice_thickness: 0,  // Slice 1
    slice_position: 0,   // Slice 1
    piu: 6,              // Slice 7
    psg: 6,              // Slice 7
    low_contrast: 7,     // Slice 8
    snr: 6,              // Slice 7
    snru: 6,             // Slice 7
  },

  // Assignments: module -> slice index
  assignments: {},
  activeModule: null,

  // WL/WW
  wl: 500,
  ww: 1000,

  // Grid size
  gridSize: "M",
  gridSizes: { S: 80, M: 120, L: 180, XL: 260 },

  // Analysis results
  results: {},

  // Meta info
  metaInfo: {},

  // DICOM metadata
  dicomMeta: null,

  reset() {
    this.slices = [];
    this.thumbnails = [];
    this.assignments = {};
    this.activeModule = null;
    this.results = {};
    this.dicomMeta = null;
  },
};
