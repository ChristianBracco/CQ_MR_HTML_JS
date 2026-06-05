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
        self.slices: List[DicomSlice] = []
        self.input_dir: str = ""
        self.assigned_slices: Dict[str, int] = {}  # module -> slice index
        self.results: Dict[str, dict] = {}
        self.meta_info: dict = {}


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


@app.post("/load-dicom")
async def load_dicom(req: LoadRequest):
    if not os.path.isdir(req.input_dir):
        raise HTTPException(400, f"Directory non valida: {req.input_dir}")

    try:
        state.reset()
        state.input_dir = req.input_dir
        state.slices = load_dicom_series(req.input_dir)
        logger.info("Loaded %d MRI slices from %s", len(state.slices), req.input_dir)

        stats = get_series_stats(state.slices)

        return NumpyJSONResponse({
            "success": True,
            "n_slices": len(state.slices),
            "stats": stats,
            "slices": [_slice_summary(sl, i) for i, sl in enumerate(state.slices)],
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
            result = calculate_slice_position(arr, ps, **kwargs)
        elif module == "psg":
            result = calculate_psg(arr, ps, **kwargs)
        elif module == "piu":
            result = calculate_piu(arr, ps, **kwargs)
            field_T = sl.magnetic_field_T or 1.5
            result["limit"] = 87.5 if field_T < 3.0 else 82.0
            result["passed"] = result["piu_percent"] >= result["limit"]
            result["field_T"] = field_T
        elif module == "low_contrast":
            result = calculate_low_contrast(arr, ps, **kwargs)
        elif module == "snr":
            snr_idx2 = kwargs.pop("second_slice_idx", None)
            snr_method = kwargs.pop("snr_method", "single_lr")
            if snr_method == "two_image" and snr_idx2 is not None and 0 <= snr_idx2 < len(state.slices):
                arr2 = state.slices[snr_idx2].pixel_array
                result = calculate_snr_two_images(arr, arr2, ps, **kwargs)
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
                result = calculate_slice_position(arr, ps)
            elif module == "psg":
                result = calculate_psg(arr, ps)
            elif module == "piu":
                result = calculate_piu(arr, ps)
                field_T = sl.magnetic_field_T or 1.5
                result["limit"] = 87.5 if field_T < 3.0 else 82.0
                result["passed"] = result["piu_percent"] >= result["limit"]
            elif module == "low_contrast":
                result = calculate_low_contrast(arr, ps)
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
# STATIC FILES — serve frontend on same port
# ==============================================================================

if os.path.isdir(FRONTEND_DIR):
    app.mount("/frontend", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")


# ==============================================================================
# MAIN
# ==============================================================================

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("MRI_QC_API_PORT", "8181"))
    uvicorn.run("backend.api:app", host="127.0.0.1", port=port, reload=True)
