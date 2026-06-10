"""
backend/api.py
--------------
FastAPI REST backend per MRI QC Analyzer (Phantom ACR).

Parametri QC implementati:
  - PSG  (Percent Signal Ghosting)
  - PIU  (Percent Image Uniformity)
  - SNR  (Signal-to-Noise Ratio)
  - SNRU (SNR Uniformity)

Avvio:
    uvicorn backend.api:app --host 0.0.0.0 --port 8700 --reload
"""

from __future__ import annotations

import io
import os
import sys
import base64
import traceback
import datetime
from pathlib import Path
from typing import Dict, List, Optional

import json as _json
import numpy as np
import logging
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Numpy JSON encoder
# ---------------------------------------------------------------------------

class _NumpyEncoder(_json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.bool_):
            return bool(obj)
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)


from starlette.responses import Response as _StarletteResponse


class NumpyJSONResponse(_StarletteResponse):
    media_type = "application/json"

    def __init__(self, content: dict, status_code: int = 200, **kwargs):
        body = _json.dumps(content, cls=_NumpyEncoder, ensure_ascii=False)
        super().__init__(content=body, status_code=status_code, **kwargs)


logger = logging.getLogger("mri_qc_api")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

# Add project root to path
PROJECT_ROOT = str(Path(__file__).parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from dicom_loader import DicomSlice, load_dicom_series, get_series_stats
from roi_tools import (
    find_phantom_circle,
    calculate_psg,
    calculate_piu,
    calculate_snr_single_image,
    calculate_snr_two_images,
    calculate_snru,
    calculate_geometric_accuracy,
    calculate_slice_thickness,
    calculate_slice_position,
    calculate_spatial_resolution,
    calculate_low_contrast,
    calculate_relaxometry,
)

# Serve frontend static files
from fastapi.staticfiles import StaticFiles

FRONTEND_DIR = str(Path(__file__).parent.parent / "frontend")
if os.path.isdir(FRONTEND_DIR):
    pass  # mounted after app creation below

# ==============================================================================
# APP
# ==============================================================================

app = FastAPI(
    title="MRI QC Analyzer API",
    version="1.0.0",
    description="Backend REST per analisi QC MRI con phantom ACR",
)

# CORS
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class ForceCORSMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method == "OPTIONS":
            response = Response(status_code=200)
        else:
            try:
                response = await call_next(request)
            except Exception:
                response = Response(status_code=500)
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "*"
        return response


app.add_middleware(ForceCORSMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==============================================================================
# STATE
# ==============================================================================

class AppState:
    def __init__(self):
        self.reset()

    def reset(self):
        self.all_slices: List[DicomSlice] = []  # ALL loaded slices across sequences
        self.slices: List[DicomSlice] = []       # Active sequence slices
        self.active_sequence_uid: str = ""
        self.input_dir: str = ""
        self.assigned_slices: Dict[str, int] = {}  # module -> slice index
        self.results: Dict[str, dict] = {}
        self.meta_info: dict = {}
        self.all_results: Dict[str, Dict[str, dict]] = {}  # uid -> {module -> result}


state = AppState()

# Module definitions for ACR phantom
ACR_MODULES = {
    "geometric": {"label": "Accuratezza Geometrica", "slice": 1, "color": "#f97316"},
    "resolution": {"label": "Risoluzione Spaziale (Alto Contrasto)", "slice": 1, "color": "#a855f7"},
    "slice_thickness": {"label": "Spessore di Strato", "slice": 1, "color": "#06b6d4"},
    "slice_position": {"label": "Posizione Strato", "slice": 1, "color": "#84cc16"},
    "piu": {"label": "PIU — Uniformità Immagine", "slice": 7, "color": "#2a9d8f"},
    "psg": {"label": "PSG — Percent Signal Ghosting", "slice": 7, "color": "#e63946"},
    "low_contrast": {"label": "Basso Contrasto (LCD)", "slice": 8, "color": "#f472b6"},
    "snr": {"label": "SNR — Signal-to-Noise Ratio", "slice": 7, "color": "#e9c46a"},
    "snru": {"label": "SNRU — SNR Uniformity", "slice": 7, "color": "#457b9d"},
}

MODULE_ORDER = ["geometric", "resolution", "slice_thickness", "slice_position",
                "piu", "psg", "low_contrast", "snr", "snru"]


# ==============================================================================
# PYDANTIC MODELS
# ==============================================================================

class LoadRequest(BaseModel):
    input_dir: str
    recursive: bool = True

class ManualAssignRequest(BaseModel):
    assignments: Dict[str, int]

class AnalyzeRequest(BaseModel):
    module: str
    kwargs: Optional[dict] = None

class MetaInfoRequest(BaseModel):
    data_controllo: str = ""
    tipo_controllo: str = "Costanza"
    presidio: str = ""
    sala: str = ""
    operatori: str = ""
    note: str = ""


class SaveSessionRequest(BaseModel):
    filepath: str = ""


class LoadSessionRequest(BaseModel):
    filepath: str


class SetActiveSequenceRequest(BaseModel):
    uid: str


def _valid_slice_indices(base_idx: int, offsets: List[int]) -> List[int]:
    indices = []
    for off in offsets:
        idx = base_idx + off
        if 0 <= idx < len(state.slices):
            indices.append(idx)
    return indices


def _lcd_stack_indices(base_idx: int) -> List[int]:
    """Return a 4-slice LCD window even if the user clicked slice 9, 10, or 11."""
    n = len(state.slices)
    if n <= 0:
        return []
    if base_idx + 3 < n:
        return [base_idx + i for i in range(4)]
    if base_idx - 3 >= 0:
        start = base_idx - 3
        return [start + i for i in range(4)]
    start = max(0, min(base_idx, n - 4))
    return [i for i in range(start, min(start + 4, n))]


LCD_SLICE_ANGLE_OFFSETS_DEG = {8: 0.0, 9: 9.0, 10: 18.0, 11: 27.0}


def _geometric_slice_score(arr: np.ndarray, pixel_spacing_mm: float = 1.0) -> float:
    """Score axial ACR geometry slice by detecting the large dark central insert."""
    try:
        cr, cc, r0 = find_phantom_circle(arr, pixel_spacing_mm)
    except Exception:
        return 0.0
    h, w = arr.shape
    cr = int(np.clip(round(cr), 0, h - 1))
    cc = int(np.clip(round(cc), 0, w - 1))
    r0 = float(max(r0, 1.0))
    rr, col = np.ogrid[:h, :w]
    dist = np.sqrt((rr - cr) ** 2 + (col - cc) ** 2)
    phantom = dist <= 0.92 * r0
    central_square = (
        (np.abs(rr - cr) <= 0.42 * r0) &
        (np.abs(col - cc) <= 0.42 * r0)
    )
    water_ring = (dist >= 0.52 * r0) & (dist <= 0.88 * r0)
    if not np.any(phantom) or not np.any(central_square) or not np.any(water_ring):
        return 0.0

    water = float(np.median(arr[water_ring]))
    background = float(np.percentile(arr[~phantom], 70)) if np.any(~phantom) else float(np.percentile(arr, 5))
    dark_thr = background + 0.35 * (water - background)
    dark_fraction = float(np.mean(arr[central_square] <= dark_thr))
    water_fraction = float(np.mean(arr[water_ring] > dark_thr))

    # Reward a broad, square-ish dark insert near the center; penalize weak water ring.
    if dark_fraction < 0.18 or water_fraction < 0.35:
        return 0.0
    expected_insert_area = (0.84 * r0) ** 2
    area_term = min(1.0, dark_fraction * central_square.sum() / max(expected_insert_area, 1.0))
    return float(100.0 * dark_fraction * water_fraction * (0.55 + 0.45 * area_term))


def _suggest_slice_assignments() -> Dict[str, int]:
    n = len(state.slices)
    assignments: Dict[str, int] = {}
    if n <= 0:
        return assignments

    defaults = {
        "geometric": min(4, n - 1),
        "resolution": 0,
        "slice_thickness": 0,
        "slice_position": 0,
        "piu": min(6, n - 1),
        "psg": min(6, n - 1),
        "low_contrast": n - 1,
        "snr": min(6, n - 1),
        "snru": min(6, n - 1),
    }
    assignments.update({k: v for k, v in defaults.items() if 0 <= v < n})

    scores = [
        _geometric_slice_score(sl.pixel_array, sl.pixel_spacing_mm)
        for sl in state.slices
    ]
    if scores:
        best_idx = int(np.argmax(scores))
        if scores[best_idx] > 5.0:
            assignments["geometric"] = best_idx
    return assignments


def _analyze_slice_position_pair(base_idx: int, kwargs: Optional[dict] = None) -> dict:
    kwargs = dict(kwargs or {})
    active_idx = kwargs.pop("active_slice_idx", base_idx)
    overrides = kwargs.pop("slice_position_overrides", {}) or {}
    indices = _valid_slice_indices(base_idx, [0, 10])
    per_slice = []
    primary = None
    for idx in indices:
        sl = state.slices[idx]
        slice_kwargs = dict(overrides.get(str(idx), overrides.get(idx, {})))
        if idx == active_idx:
            slice_kwargs.update(kwargs)
        result = calculate_slice_position(sl.pixel_array, sl.pixel_spacing_mm, **slice_kwargs)
        result["slice_number_acr"] = idx - base_idx + 1 if idx != base_idx else 1
        result["slice_idx"] = idx
        result["slice_location"] = sl.slice_location
        per_slice.append(result)
        if idx == base_idx:
            primary = result
    if primary is None and per_slice:
        primary = per_slice[0]
    if primary is None:
        raise HTTPException(400, "Slice posizione non disponibili")
    max_abs = max(abs(r.get("slice_position_error_mm", 0.0)) for r in per_slice)
    primary = dict(primary)
    primary["slice_position_slices"] = per_slice
    primary["slice_position_max_abs_error_mm"] = round(float(max_abs), 2)
    primary["passed"] = all(r.get("passed", False) for r in per_slice)
    primary["analysis_scope"] = "slice_1_and_11"
    return primary


def _analyze_low_contrast_stack(base_idx: int, kwargs: Optional[dict] = None) -> dict:
    kwargs = dict(kwargs or {})
    active_idx = kwargs.pop("active_slice_idx", base_idx)
    overrides = kwargs.pop("lcd_overrides", {}) or {}
    indices = _lcd_stack_indices(base_idx)
    per_slice = []
    primary = None
    total_visible = 0
    active_pos = indices.index(active_idx) if active_idx in indices else 0
    active_acr_slice = 8 + active_pos
    active_lcd_angle = kwargs.get("lcd_angle_offset_deg")

    for pos, idx in enumerate(indices):
        sl = state.slices[idx]
        slice_kwargs = dict(overrides.get(str(idx), overrides.get(idx, {})))
        acr_slice = 8 + pos
        if idx == active_idx:
            slice_kwargs.update(kwargs)
        elif not slice_kwargs:
            slice_kwargs.update({
                k: v for k, v in kwargs.items()
                if k in {
                    "lcd_angle_offset_deg",
                    "lcd_ring_radius_mm",
                    "lcd_method",
                    "center_rc",
                    "radius_px",
                    "lcd_anchor_outer_rc",
                }
            })
        if active_lcd_angle is not None and idx != active_idx:
            ref_offset = LCD_SLICE_ANGLE_OFFSETS_DEG.get(active_acr_slice, 0.0)
            dst_offset = LCD_SLICE_ANGLE_OFFSETS_DEG.get(acr_slice, 0.0)
            slice_kwargs["lcd_angle_offset_deg"] = float(active_lcd_angle) + dst_offset - ref_offset
            slice_kwargs.pop("lcd_anchor_outer_rc", None)
        slice_kwargs.setdefault("lcd_acr_slice_number", acr_slice)
        slice_kwargs.setdefault("lcd_method", "manual")
        result = calculate_low_contrast(sl.pixel_array, sl.pixel_spacing_mm, **slice_kwargs)
        result["slice_number_acr"] = acr_slice
        result["slice_idx"] = idx
        result["slice_location"] = sl.slice_location
        per_slice.append(result)
        total_visible += int(result.get("n_visible", 0))
        if idx == active_idx:
            primary = result
    if primary is None and per_slice:
        primary = per_slice[0]
    if primary is None:
        raise HTTPException(400, "Slice basso contrasto non disponibili")
    field_T = state.slices[base_idx].magnetic_field_T or 1.5
    if field_T >= 3.0:
        t1_limit = t2_limit = 37
    elif field_T >= 1.5:
        t1_limit, t2_limit = 30, 25
    else:
        t1_limit = t2_limit = 7
    primary = dict(primary)
    primary["lcd_slices"] = per_slice
    primary["lcd_total_visible"] = total_visible
    primary["lcd_total_possible"] = 40
    primary["lcd_limit_t1"] = t1_limit
    primary["lcd_limit_t2"] = t2_limit
    primary["passed_t1"] = total_visible >= t1_limit
    primary["passed_t2"] = total_visible >= t2_limit
    primary["passed"] = total_visible >= t2_limit
    primary["field_T"] = field_T
    primary["analysis_scope"] = "slices_8_to_11"
    primary["lcd_anchor_slice"] = None
    primary["lcd_anchor_angle_offset_deg"] = primary.get("lcd_angle_offset_deg")
    primary["lcd_anchor_ring_radius_mm"] = primary.get("lcd_ring_radius_mm")
    return primary


# ==============================================================================
# UTILITY
# ==============================================================================

def _slice_to_base64(arr: np.ndarray, wl=None, ww=None, size: int = 0) -> str:
    from PIL import Image

    arr = arr.astype(np.float32)

    if wl is None or ww is None or ww <= 1:
        finite = arr[np.isfinite(arr)]
        if finite.size == 0:
            finite = arr.flatten()
        p2 = np.percentile(finite, 2)
        p98 = np.percentile(finite, 98)
        if abs(p98 - p2) < 1:
            p2, p98 = np.min(finite), np.max(finite)
        wl = (p98 + p2) / 2.0
        ww = (p98 - p2)

    lo = wl - ww / 2.0
    hi = wl + ww / 2.0
    den = max(hi - lo, 1e-6)
    img = np.clip((arr - lo) / den * 255.0, 0, 255).astype(np.uint8)

    pil_img = Image.fromarray(img, mode="L")
    if size > 0 and size != img.shape[0]:
        pil_img = pil_img.resize((size, size), Image.LANCZOS)

    buf = io.BytesIO()
    pil_img.save(buf, format="PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _slice_summary(sl: DicomSlice, idx: int) -> dict:
    return {
        "idx": idx,
        "filename": sl.filename,
        "z": round(sl.slice_location, 2),
        "thickness": round(sl.slice_thickness_mm, 2),
        "instance": sl.instance_number,
        "pv_min": float(np.min(sl.pixel_array)),
        "pv_max": float(np.max(sl.pixel_array)),
    }


# ==============================================================================
# ENDPOINTS
# ==============================================================================

@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0", "modality": "MRI"}


# ==============================================================================
# FILESYSTEM BROWSING
# ==============================================================================

@app.get("/browse-fs")
async def browse_filesystem(path: str = Query("")):
    """Browse filesystem directories for DICOM folder selection."""
    import string

    if not path:
        # Return drives on Windows, root on Unix
        if sys.platform == "win32":
            drives = []
            for letter in string.ascii_uppercase:
                drive = f"{letter}:\\"
                if os.path.isdir(drive):
                    drives.append({"name": f"{letter}:", "path": drive, "is_dir": True})
            return {"current": "", "parent": "", "entries": drives}
        else:
            path = "/"

    path = os.path.abspath(path)
    if not os.path.isdir(path):
        raise HTTPException(400, f"Non è una directory: {path}")

    parent = os.path.dirname(path)
    if parent == path:
        parent = ""  # root

    entries = []
    try:
        for name in sorted(os.listdir(path)):
            full = os.path.join(path, name)
            if name.startswith("."):
                continue
            is_dir = os.path.isdir(full)
            entry = {"name": name, "path": full, "is_dir": is_dir}
            if not is_dir:
                entry["size"] = os.path.getsize(full)
            entries.append(entry)
    except PermissionError:
        pass

    # Count DICOM-like files (no extension or common DICOM extensions)
    dicom_count = sum(1 for e in entries if not e["is_dir"] and
                      (not "." in e["name"] or e["name"].lower().endswith((".dcm", ".ima"))))

    return {
        "current": path,
        "parent": parent,
        "entries": entries[:500],  # limit to 500 entries
        "dicom_file_count": dicom_count,
    }


@app.post("/load-dicom")
async def load_dicom(req: LoadRequest):
    if not os.path.isdir(req.input_dir):
        raise HTTPException(400, f"Directory non valida: {req.input_dir}")

    try:
        state.reset()
        state.input_dir = req.input_dir
        all_loaded = load_dicom_series(req.input_dir, recursive=req.recursive)
        state.all_slices = all_loaded
        logger.info("Loaded %d MRI slices from %s", len(all_loaded), req.input_dir)

        # Group by series_instance_uid
        groups: Dict[str, List[DicomSlice]] = {}
        for sl in all_loaded:
            uid = sl.series_instance_uid or "unknown"
            groups.setdefault(uid, []).append(sl)

        # Auto-select first T1 sequence (TR < 1000) or fall back to largest group
        selected_uid = ""
        for uid, slices in groups.items():
            if slices and slices[0].tr_ms > 0 and slices[0].tr_ms < 1000:
                selected_uid = uid
                break
        if not selected_uid:
            # Fall back to the group with the most slices
            selected_uid = max(groups.keys(), key=lambda u: len(groups[u]))

        state.active_sequence_uid = selected_uid
        state.slices = groups.get(selected_uid, all_loaded)

        stats = get_series_stats(state.slices)

        # Build sequences summary
        sequences_info = []
        for uid, grp in groups.items():
            rep = grp[0]
            sequences_info.append({
                "uid": uid,
                "description": rep.series_description,
                "tr_ms": rep.tr_ms,
                "te_ms": rep.te_ms,
                "n_slices": len(grp),
                "is_active": uid == selected_uid,
            })

        return NumpyJSONResponse({
            "success": True,
            "n_slices": len(state.slices),
            "n_total_slices": len(all_loaded),
            "active_sequence_uid": selected_uid,
            "sequences": sequences_info,
            "stats": stats,
            "slices": [_slice_summary(sl, i) for i, sl in enumerate(state.slices)],
            "suggested_assignments": _suggest_slice_assignments(),
        })
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(500, str(e))


@app.get("/slices")
async def get_slices():
    if not state.slices:
        raise HTTPException(400, "Nessuna serie caricata")
    return {
        "n_slices": len(state.slices),
        "slices": [_slice_summary(sl, i) for i, sl in enumerate(state.slices)],
    }


@app.get("/slice-image/{idx}")
async def get_slice_image(idx: int, wl: float = Query(None), ww: float = Query(None), size: int = Query(0)):
    if not state.slices or idx < 0 or idx >= len(state.slices):
        raise HTTPException(400, f"Indice slice non valido: {idx}")
    sl = state.slices[idx]
    b64 = _slice_to_base64(sl.pixel_array, wl, ww, size)
    return {"idx": idx, "image": b64}


@app.get("/slice-thumbnails")
async def get_thumbnails(wl: float = Query(None), ww: float = Query(None), size: int = Query(128)):
    if not state.slices:
        raise HTTPException(400, "Nessuna serie caricata")
    thumbs = []
    for i, sl in enumerate(state.slices):
        b64 = _slice_to_base64(sl.pixel_array, wl, ww, size)
        thumbs.append({"idx": i, "image": b64, "z": round(sl.slice_location, 2)})
    return {"thumbnails": thumbs}


@app.get("/module-config")
async def get_module_config():
    """Ritorna configurazione moduli ACR."""
    return {
        "modules": ACR_MODULES,
        "module_order": MODULE_ORDER,
    }


@app.get("/suggest-slices")
async def suggest_slices():
    if not state.slices:
        raise HTTPException(400, "Nessuna serie caricata")
    return {"assignments": _suggest_slice_assignments()}


@app.post("/assign-slices")
async def assign_slices_manual(req: ManualAssignRequest):
    if not state.slices:
        raise HTTPException(400, "Nessuna serie caricata")
    state.assigned_slices = req.assignments
    return {"success": True, "assignments": state.assigned_slices}


@app.post("/analyze")
async def analyze_module(req: AnalyzeRequest):
    if not state.slices:
        raise HTTPException(400, "Nessuna serie caricata")

    module = req.module.lower()
    if module not in ACR_MODULES:
        raise HTTPException(400, f"Modulo '{module}' non valido. Validi: {MODULE_ORDER}")

    if module not in state.assigned_slices:
        raise HTTPException(400, f"Modulo '{module}' non assegnato a nessuna slice")

    idx = state.assigned_slices[module]
    if idx < 0 or idx >= len(state.slices):
        raise HTTPException(400, f"Indice slice {idx} non valido")

    sl = state.slices[idx]
    arr = sl.pixel_array
    ps = sl.pixel_spacing_mm
    kwargs = req.kwargs or {}

    logger.info("Analyze %s on slice #%d", module, idx)

    try:
        if module == "geometric":
            result = calculate_geometric_accuracy(arr, ps, **kwargs)
        elif module == "resolution":
            result = calculate_spatial_resolution(arr, ps, **kwargs)
        elif module == "slice_thickness":
            result = calculate_slice_thickness(arr, ps, **kwargs)
        elif module == "slice_position":
            result = _analyze_slice_position_pair(idx, kwargs)
        elif module == "psg":
            result = calculate_psg(arr, ps, **kwargs)
        elif module == "piu":
            result = calculate_piu(arr, ps, **kwargs)
            field_T = sl.magnetic_field_T or 1.5
            result["limit"] = 87.5 if field_T < 3.0 else 82.0
            result["passed"] = result["piu_percent"] >= result["limit"]
            result["field_T"] = field_T
        elif module == "low_contrast":
            result = _analyze_low_contrast_stack(idx, kwargs)
        elif module == "snr":
            snr_idx2 = kwargs.pop("second_slice_idx", None)
            snr_method = kwargs.pop("snr_method", "single_lr")
            if snr_method == "two_image" and snr_idx2 is not None and 0 <= snr_idx2 < len(state.slices):
                if int(snr_idx2) == int(idx):
                    raise HTTPException(400, "Per two_image_subtraction scegli una seconda immagine diversa dalla corrente")
                arr2 = state.slices[snr_idx2].pixel_array
                result = calculate_snr_two_images(arr, arr2, ps, **kwargs)
                result["primary_slice_idx"] = idx
                result["second_slice_idx"] = int(snr_idx2)
                result["primary_slice_location"] = sl.slice_location
                result["second_slice_location"] = state.slices[snr_idx2].slice_location
            else:
                result = calculate_snr_single_image(arr, ps, **kwargs)
                # Add method info
                result["method"] = snr_method
        elif module == "snru":
            result = calculate_snru(arr, ps, **kwargs)
        else:
            raise HTTPException(400, f"Modulo '{module}' non implementato")

        # Generate overlay image
        overlay_b64 = _generate_overlay(module, sl, result)

        state.results[module] = result

        return NumpyJSONResponse({
            "success": True,
            "module": module,
            "results": result,
            "overlay_image": overlay_b64,
            "slice_info": {
                "filename": sl.filename,
                "z": sl.slice_location,
                "idx": idx,
            },
        })
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(500, f"Errore analisi {module}: {e}")


@app.post("/analyze-all")
async def analyze_all():
    if not state.slices:
        raise HTTPException(400, "Nessuna serie caricata")
    if not state.assigned_slices:
        raise HTTPException(400, "Nessuna slice assegnata")

    results = {}
    errors = {}

    for module in MODULE_ORDER:
        if module not in state.assigned_slices:
            continue
        try:
            idx = state.assigned_slices[module]
            sl = state.slices[idx]
            arr = sl.pixel_array
            ps = sl.pixel_spacing_mm

            if module == "geometric":
                result = calculate_geometric_accuracy(arr, ps)
            elif module == "resolution":
                result = calculate_spatial_resolution(arr, ps)
            elif module == "slice_thickness":
                result = calculate_slice_thickness(arr, ps)
            elif module == "slice_position":
                result = _analyze_slice_position_pair(idx)
            elif module == "psg":
                result = calculate_psg(arr, ps)
            elif module == "piu":
                result = calculate_piu(arr, ps)
                field_T = sl.magnetic_field_T or 1.5
                result["limit"] = 87.5 if field_T < 3.0 else 82.0
                result["passed"] = result["piu_percent"] >= result["limit"]
            elif module == "low_contrast":
                result = _analyze_low_contrast_stack(idx)
            elif module == "snr":
                result = calculate_snr_single_image(arr, ps)
            elif module == "snru":
                result = calculate_snru(arr, ps)
            else:
                continue

            overlay_b64 = _generate_overlay(module, sl, result)
            state.results[module] = result
            results[module] = {
                "success": True,
                "results": result,
                "overlay_image": overlay_b64,
                "slice_info": {"filename": sl.filename, "z": sl.slice_location, "idx": idx},
            }
        except Exception as e:
            errors[module] = str(e)

    return NumpyJSONResponse({
        "success": len(errors) == 0,
        "results": results,
        "errors": errors,
    })


@app.post("/meta-info")
async def set_meta_info(req: MetaInfoRequest):
    state.meta_info = req.model_dump()
    return {"success": True}


@app.get("/dicom-meta")
async def get_dicom_meta():
    if not state.slices:
        raise HTTPException(400, "Nessuna serie caricata")
    sl = state.slices[0]
    return {
        "manufacturer": sl.manufacturer,
        "model": sl.model_name,
        "institution": sl.institution_name,
        "station": sl.station_name,
        "protocol": sl.protocol_name,
        "tr_ms": sl.tr_ms,
        "te_ms": sl.te_ms,
        "flip_angle": sl.flip_angle,
        "magnetic_field_T": sl.magnetic_field_T,
        "bandwidth_hz": sl.bandwidth_hz,
        "pixel_spacing_mm": sl.pixel_spacing_mm,
        "slice_thickness_mm": sl.slice_thickness_mm,
        "fov_mm": sl.fov_mm,
        "matrix_size": sl.matrix_size,
        "frequency_encoding_dir": sl.frequency_encoding_dir,
        "phase_encoding_dir": sl.phase_encoding_dir,
        "study_date": sl.study_date,
        "series_description": sl.series_description,
        "patient_position": sl.patient_position,
        "n_slices": len(state.slices),
        "n_averages": sl.n_averages,
        "serial_number": sl.serial_number,
    }


@app.get("/pixel-value")
async def get_pixel_value(slice_idx: int = Query(0), row: int = Query(0), col: int = Query(0)):
    if not state.slices or slice_idx < 0 or slice_idx >= len(state.slices):
        raise HTTPException(400, "Slice non valida")
    sl = state.slices[slice_idx]
    arr = sl.pixel_array
    r = max(0, min(arr.shape[0] - 1, row))
    c = max(0, min(arr.shape[1] - 1, col))
    return {"row": r, "col": c, "value": round(float(arr[r, c]), 1)}


# ==============================================================================
# OVERLAY IMAGE GENERATION
# ==============================================================================

def _generate_overlay(module: str, sl: DicomSlice, result: dict) -> str:
    """Genera immagine PNG con overlay ROI."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Circle, Rectangle

    arr = sl.pixel_array
    h, w = arr.shape
    dpi = 100
    fig, ax = plt.subplots(1, 1, figsize=(w / dpi, h / dpi), dpi=dpi, facecolor="#0f172a")

    # Auto windowing
    p2, p98 = np.percentile(arr, 2), np.percentile(arr, 98)
    ax.imshow(arr, cmap="gray", vmin=p2, vmax=p98, interpolation="nearest",
              extent=[0, w, h, 0], origin="upper")
    ax.set_xlim(0, w)
    ax.set_ylim(h, 0)
    ax.axis("off")
    ax.set_position([0, 0, 1, 1])

    cr = result.get("center_rc", (h // 2, w // 2))
    r0 = result.get("radius_px", min(h, w) // 3)

    # Phantom outline
    ax.add_patch(Circle((cr[1], cr[0]), r0, color="cyan", fill=False, lw=1.5, ls="--", alpha=0.5))
    ax.plot(cr[1], cr[0], "+", color="#22d3ee", markersize=12, markeredgewidth=2)

    if module == "psg":
        # UFOV circle
        r_ufov = result.get("ufov_radius_px", int(0.8 * r0))
        ax.add_patch(Circle((cr[1], cr[0]), r_ufov, color="#22c55e", fill=False, lw=1.5))

        # Background ROIs
        rois = result.get("rois", {})
        colors = {"right": "#fb923c", "left": "#fb923c", "up": "#60a5fa", "down": "#60a5fa"}
        for name, roi_data in rois.items():
            rect = roi_data.get("rect", [0, 0, 10, 10])
            color = colors.get(name, "#ffffff")
            ax.add_patch(Rectangle((rect[1], rect[0]), rect[3], rect[2],
                                   fill=False, edgecolor=color, lw=2))
            ax.text(rect[1] + rect[3] // 2, rect[0] + rect[2] // 2,
                    f"{name[0].upper()}\n{roi_data['mean']:.0f}",
                    color=color, fontsize=7, ha="center", va="center", fontweight="bold")

    elif module == "piu":
        r_ufov = result.get("ufov_radius_px", int(0.8 * r0))
        ax.add_patch(Circle((cr[1], cr[0]), r_ufov, color="#22c55e", fill=False, lw=1.5, ls="--"))

        # Max and min positions
        max_pos = result.get("max_position_rc", (0, 0))
        min_pos = result.get("min_position_rc", (0, 0))
        r_mask = result.get("mask_radius_px", 5)
        ax.add_patch(Circle((max_pos[1], max_pos[0]), r_mask, color="#ef4444", fill=False, lw=2))
        ax.text(max_pos[1], max_pos[0] - r_mask - 3, f"MAX\n{result['s_max']:.0f}",
                color="#ef4444", fontsize=7, ha="center", va="bottom", fontweight="bold")
        ax.add_patch(Circle((min_pos[1], min_pos[0]), r_mask, color="#3b82f6", fill=False, lw=2))
        ax.text(min_pos[1], min_pos[0] - r_mask - 3, f"MIN\n{result['s_min']:.0f}",
                color="#3b82f6", fontsize=7, ha="center", va="bottom", fontweight="bold")

    elif module == "snr":
        r_ufov = result.get("ufov_radius_px", int(0.8 * r0))
        ax.add_patch(Circle((cr[1], cr[0]), r_ufov, color="#eab308", fill=False, lw=1.5))
        ax.text(cr[1], cr[0], f"SNR={result['snr']:.1f}", color="#eab308",
                fontsize=10, ha="center", va="center", fontweight="bold")

    elif module == "snru":
        rois = result.get("rois", [])
        for roi in rois:
            rc = roi["center_rc"]
            rpx = roi["radius_px"]
            ax.add_patch(Circle((rc[1], rc[0]), rpx, color="#60a5fa", fill=False, lw=2))
            ax.text(rc[1], rc[0], f"{roi['snr']:.0f}", color="#60a5fa",
                    fontsize=7, ha="center", va="center", fontweight="bold")

    # Title
    titles = {
        "psg": f"PSG = {result.get('psg_percent', 0):.3f}%",
        "piu": f"PIU = {result.get('piu_percent', 0):.1f}%",
        "snr": f"SNR = {result.get('snr', 0):.1f}",
        "snru": f"SNRU = {result.get('snru_percent', 0):.2f}%",
    }
    title = titles.get(module, module.upper())
    passed = result.get("passed", True)
    color = "#22c55e" if passed else "#ef4444"
    ax.text(w // 2, 15, title, color=color, fontsize=10, ha="center", va="top", fontweight="bold")

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, facecolor="#0f172a", pad_inches=0)
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.getvalue()).decode("ascii")


# ==============================================================================
# MULTI-SEQUENCE & SESSION PERSISTENCE ENDPOINTS
# ==============================================================================

@app.get("/sequences")
async def get_sequences():
    """Returns list of detected sequences grouped by series_instance_uid."""
    if not state.all_slices:
        raise HTTPException(400, "Nessuna serie caricata")

    groups: Dict[str, List[DicomSlice]] = {}
    for sl in state.all_slices:
        uid = sl.series_instance_uid or "unknown"
        groups.setdefault(uid, []).append(sl)

    sequences = []
    for uid, grp in groups.items():
        rep = grp[0]
        sequences.append({
            "uid": uid,
            "description": rep.series_description,
            "tr_ms": rep.tr_ms,
            "te_ms": rep.te_ms,
            "n_slices": len(grp),
            "is_active": uid == state.active_sequence_uid,
        })

    return {"sequences": sequences}


@app.post("/set-active-sequence")
async def set_active_sequence(req: SetActiveSequenceRequest):
    """Switch to a specific sequence by series_instance_uid."""
    if not state.all_slices:
        raise HTTPException(400, "Nessuna serie caricata")

    # Save current results before switching
    if state.active_sequence_uid and state.results:
        state.all_results[state.active_sequence_uid] = dict(state.results)

    # Find slices for the requested UID
    matching = [sl for sl in state.all_slices if sl.series_instance_uid == req.uid]
    if not matching:
        raise HTTPException(404, f"Sequenza con UID '{req.uid}' non trovata")

    state.active_sequence_uid = req.uid
    state.slices = matching
    state.assigned_slices = {}
    state.results = state.all_results.get(req.uid, {})

    return NumpyJSONResponse({
        "success": True,
        "active_sequence_uid": req.uid,
        "n_slices": len(state.slices),
        "slices": [_slice_summary(sl, i) for i, sl in enumerate(state.slices)],
        "suggested_assignments": _suggest_slice_assignments(),
    })


def _build_session_data() -> dict:
    """Build the full session dict for JSON persistence (no pixel data or overlays)."""
    # Save current sequence results
    if state.active_sequence_uid and state.results:
        state.all_results[state.active_sequence_uid] = dict(state.results)

    # Group slices by UID
    groups: Dict[str, List[DicomSlice]] = {}
    for sl in state.all_slices:
        uid = sl.series_instance_uid or "unknown"
        groups.setdefault(uid, []).append(sl)

    # DICOM meta from first slice of active sequence
    dicom_meta = {}
    if state.slices:
        sl0 = state.slices[0]
        dicom_meta = {
            "manufacturer": sl0.manufacturer,
            "model": sl0.model_name,
            "institution": sl0.institution_name,
            "station": sl0.station_name,
            "protocol": sl0.protocol_name,
            "magnetic_field_T": sl0.magnetic_field_T,
            "study_date": sl0.study_date,
            "serial_number": sl0.serial_number,
        }

    # Build per-sequence data
    sequences_data = []
    for uid, grp in groups.items():
        rep = grp[0]
        # Get results for this sequence (strip overlay images)
        seq_results = state.all_results.get(uid, {})
        clean_results = {}
        for module, res in seq_results.items():
            clean = {k: v for k, v in res.items()
                     if k not in ("overlay_image", "pixel_array")}
            # Also strip overlay from nested lcd_slices / slice_position_slices
            for nested_key in ("lcd_slices", "slice_position_slices"):
                if nested_key in clean and isinstance(clean[nested_key], list):
                    clean[nested_key] = [
                        {k2: v2 for k2, v2 in item.items()
                         if k2 not in ("overlay_image", "pixel_array")}
                        for item in clean[nested_key]
                    ]
            clean_results[module] = clean

        sequences_data.append({
            "uid": uid,
            "series_description": rep.series_description,
            "tr_ms": rep.tr_ms,
            "te_ms": rep.te_ms,
            "n_slices": len(grp),
            "slices": [
                {
                    "filename": s.filename,
                    "z": round(s.slice_location, 2),
                    "thickness": round(s.slice_thickness_mm, 2),
                    "instance": s.instance_number,
                }
                for s in grp
            ],
            "results": clean_results,
        })

    return {
        "timestamp": datetime.datetime.now().isoformat(),
        "input_dir": state.input_dir,
        "active_sequence_uid": state.active_sequence_uid,
        "assigned_slices": state.assigned_slices,
        "meta_info": state.meta_info,
        "dicom_meta": dicom_meta,
        "sequences": sequences_data,
    }


@app.post("/save-session")
async def save_session(req: SaveSessionRequest):
    """Save current analysis session to a JSON file."""
    if not state.all_slices:
        raise HTTPException(400, "Nessuna serie caricata — nulla da salvare")

    filepath = req.filepath.strip() if req.filepath else ""
    if not filepath:
        # Auto-generate filename in input_dir
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"mri_qc_session_{ts}.json"
        base_dir = state.input_dir if state.input_dir and os.path.isdir(state.input_dir) else "."
        filepath = os.path.join(base_dir, filename)

    try:
        session_data = _build_session_data()
        # Ensure directory exists
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            _json.dump(session_data, f, cls=_NumpyEncoder, ensure_ascii=False, indent=2)
        logger.info("Session saved to %s", filepath)
        return {"success": True, "filepath": os.path.abspath(filepath)}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(500, f"Errore salvataggio sessione: {e}")


@app.post("/load-session")
async def load_session(req: LoadSessionRequest):
    """Load a previously saved session from a JSON file."""
    filepath = req.filepath.strip()
    if not filepath or not os.path.isfile(filepath):
        raise HTTPException(400, f"File sessione non trovato: {filepath}")

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = _json.load(f)
        logger.info("Session loaded from %s", filepath)
        # Restore meta_info if present
        if "meta_info" in data and data["meta_info"]:
            state.meta_info = data["meta_info"]
        # Restore assigned_slices if present
        if "assigned_slices" in data and data["assigned_slices"]:
            state.assigned_slices = data["assigned_slices"]
        # Restore all_results from sequences
        if "sequences" in data:
            for seq in data["sequences"]:
                uid = seq.get("uid", "")
                if uid and "results" in seq:
                    state.all_results[uid] = seq["results"]
            # If active sequence matches, restore its results
            active_uid = data.get("active_sequence_uid", "")
            if active_uid and active_uid in state.all_results:
                state.results = state.all_results[active_uid]
        return {"success": True, "data": data}
    except _json.JSONDecodeError as e:
        raise HTTPException(400, f"File JSON non valido: {e}")
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(500, f"Errore caricamento sessione: {e}")


# ==============================================================================
# RELAXOMETRY ENDPOINT
# ==============================================================================


class RelaxometryRequest(BaseModel):
    slice_idx: int = 0
    roi_fraction: float = 0.75


@app.post("/relaxometry")
async def analyze_relaxometry(req: RelaxometryRequest):
    """Estimate T1/T2 relaxation from multiple sequences at the same slice location.

    Groups all loaded sequences by slice location, collects signal at different
    TR/TE values, and fits exponential decay/recovery models.
    """
    if not state.all_slices:
        raise HTTPException(400, "Nessuna serie caricata")

    # Group all slices by series UID
    groups: Dict[str, List[DicomSlice]] = {}
    for sl in state.all_slices:
        uid = sl.series_instance_uid or "unknown"
        groups.setdefault(uid, []).append(sl)

    if len(groups) < 2:
        raise HTTPException(400, "Servono almeno 2 sequenze diverse per la relassometria")

    # Get the target z-location from the active sequence
    if req.slice_idx < 0 or req.slice_idx >= len(state.slices):
        raise HTTPException(400, f"Indice slice {req.slice_idx} non valido")

    target_z = state.slices[req.slice_idx].slice_location
    ps = state.slices[req.slice_idx].pixel_spacing_mm

    # Find matching slices at the same z-location from all sequences
    tolerance_mm = 2.0  # Allow 2mm tolerance for matching z positions
    slices_data = []
    for uid, grp in groups.items():
        # Find the closest slice to target_z in this group
        best = None
        best_dist = float("inf")
        for sl in grp:
            d = abs(sl.slice_location - target_z)
            if d < best_dist:
                best_dist = d
                best = sl
        if best is not None and best_dist <= tolerance_mm:
            slices_data.append({
                "pixel_array": best.pixel_array,
                "tr_ms": best.tr_ms,
                "te_ms": best.te_ms,
                "series_description": best.series_description,
                "uid": uid,
            })

    if len(slices_data) < 2:
        raise HTTPException(400,
            f"Solo {len(slices_data)} sequenza trovata alla posizione z={target_z:.1f} mm. "
            "Servono almeno 2 sequenze con slice alla stessa posizione.")

    try:
        result = calculate_relaxometry(slices_data, ps, roi_fraction=req.roi_fraction)
        # Add sequence info
        result["sequences_used"] = [
            {
                "uid": sd["uid"],
                "description": sd["series_description"],
                "tr_ms": sd["tr_ms"],
                "te_ms": sd["te_ms"],
            }
            for sd in slices_data
        ]
        result["target_z_mm"] = round(float(target_z), 2)
        result["slice_idx"] = req.slice_idx

        return NumpyJSONResponse({"success": True, "results": result})
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(500, f"Errore relassometria: {e}")


# ==============================================================================
# STATIC FILES — serve frontend on same port
# ==============================================================================

if os.path.isdir(FRONTEND_DIR):
    from starlette.staticfiles import StaticFiles as _SF
    from starlette.responses import Response as _Resp

    class NoCacheStaticFiles(_SF):
        async def __call__(self, scope, receive, send):
            """Wrapper that adds no-cache headers to all static files."""
            async def send_with_headers(message):
                if message.get("type") == "http.response.start":
                    headers = dict(message.get("headers", []))
                    # Add cache-busting headers
                    new_headers = list(message.get("headers", []))
                    new_headers.append((b"cache-control", b"no-cache, no-store, must-revalidate"))
                    new_headers.append((b"pragma", b"no-cache"))
                    new_headers.append((b"expires", b"0"))
                    message["headers"] = new_headers
                await send(message)
            await super().__call__(scope, receive, send_with_headers)

    app.mount("/frontend", NoCacheStaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")


# ==============================================================================
# MAIN
# ==============================================================================

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("MRI_QC_API_PORT", "8181"))
    uvicorn.run("backend.api:app", host="127.0.0.1", port=port, reload=True)
