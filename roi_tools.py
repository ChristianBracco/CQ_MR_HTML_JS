"""
roi_tools.py
------------
Strumenti ROI per MRI QC con phantom ACR.

Implementa i metodi descritti in:
  Epistatou et al., "An Automated Method for Quality Control in MRI Systems",
  J. Imaging 2020, 6, 111.

Parametri QC:
  - PSG  (Percent Signal Ghosting)
  - PIU  (Percent Image Uniformity)
  - SNR  (Signal-to-Noise Ratio)
  - SNRU (SNR Uniformity)
"""

import math
import numpy as np
from scipy.ndimage import uniform_filter


# ==============================================================================
# PHANTOM DETECTION — Trova centro e raggio del phantom ACR
# ==============================================================================

def find_phantom_circle(arr: np.ndarray, pixel_spacing_mm: float = 1.0):
    """
    Trova automaticamente il centro e il raggio del phantom ACR circolare.

    Metodo: threshold a 25% del massimo segnale, poi trova la riga/colonna
    con la massima estensione (diametro) per determinare centro e raggio.

    Ref: Appendix A del paper — Eq. (21)-(25)

    Returns:
        (center_row, center_col, radius_px)
    """
    h, w = arr.shape
    s_max = np.max(arr)
    threshold = 0.25 * s_max

    # Trova la riga con la massima estensione orizzontale
    max_span_x = 0
    i_start, i_end = 0, 0
    best_row = h // 2

    for j in range(h):
        row_data = arr[j, :]
        above = np.where(row_data >= threshold)[0]
        if len(above) < 2:
            continue
        span = above[-1] - above[0]
        if span > max_span_x:
            max_span_x = span
            i_start = above[0]
            i_end = above[-1]
            best_row = j

    # Trova la colonna con la massima estensione verticale
    max_span_y = 0
    j_start, j_end = 0, 0
    best_col = w // 2

    for i in range(w):
        col_data = arr[:, i]
        above = np.where(col_data >= threshold)[0]
        if len(above) < 2:
            continue
        span = above[-1] - above[0]
        if span > max_span_y:
            max_span_y = span
            j_start = above[0]
            j_end = above[-1]
            best_col = i

    # Centro: Eq. (23), (24)
    x0 = (i_start + i_end) / 2.0
    y0 = (j_start + j_end) / 2.0

    # Raggio: Eq. (25) — minimo tra i due semi-diametri
    r0 = min((i_end - i_start + 1) / 2.0, (j_end - j_start + 1) / 2.0)

    return int(round(y0)), int(round(x0)), int(round(r0))


# ==============================================================================
# PSG — Percent Signal Ghosting
# ==============================================================================

def calculate_psg(arr: np.ndarray, pixel_spacing_mm: float = 1.0,
                  center_rc=None, radius_px=None):
    """
    Calcola il Percent Signal Ghosting (PSG) secondo ACR.

    Ref: Eq. (1) del paper:
        PSG(%) = 100 × |((S_R + S_L) - (S_U + S_D)) / (2 × S)|

    Usa slice #7 del phantom ACR.
    - 1 ROI circolare centrale (UFOV, R = 0.8 × R0)
    - 4 ROI rettangolari nel background (U, D, L, R)
      con area = 10 cm² ciascuna, posizionate a 0.1×R0 dal phantom e dal bordo.

    Args:
        arr: immagine 2D (slice #7)
        pixel_spacing_mm: dimensione pixel in mm
        center_rc: (row, col) centro phantom (auto se None)
        radius_px: raggio phantom in pixel (auto se None)

    Returns:
        dict con risultati PSG
    """
    h, w = arr.shape
    px = py = pixel_spacing_mm

    # Trova phantom
    if center_rc is None or radius_px is None:
        cr, cc, r0 = find_phantom_circle(arr, pixel_spacing_mm)
    else:
        cr, cc = center_rc
        r0 = radius_px

    # ROI circolare centrale: UFOV con R = 0.8 × R0
    r_ufov = int(0.8 * r0)
    Y, X = np.ogrid[:h, :w]
    ufov_mask = ((X - cc)**2 + (Y - cr)**2) <= r_ufov**2
    signal_mean = float(np.mean(arr[ufov_mask]))

    # 4 ROI rettangolari nel background
    # Larghezza w_q: ROI a 0.1×R0 dal phantom E dal bordo immagine
    # Area = 10 cm² = 1000 mm²
    # H_q = 1000 / (w_q × px × py)  — Eq. (2)

    target_area_mm2 = 1000.0  # 10 cm²
    gap_px = int(0.1 * r0)  # distanza dal phantom

    results_rois = {}

    # ROI Right
    x_start_R = cc + r0 + gap_px
    x_end_R = w - gap_px
    w_R = max(3, x_end_R - x_start_R)
    h_R = max(3, int(target_area_mm2 / (w_R * px * py)))
    h_R = min(h_R, h - 2)
    y_start_R = max(0, cr - h_R // 2)
    roi_R = arr[y_start_R:y_start_R + h_R, x_start_R:x_start_R + w_R]
    s_R = float(np.mean(roi_R)) if roi_R.size > 0 else 0.0
    results_rois["right"] = {"mean": s_R, "rect": [y_start_R, x_start_R, h_R, w_R]}

    # ROI Left
    x_end_L = cc - r0 - gap_px
    x_start_L = gap_px
    w_L = max(3, x_end_L - x_start_L)
    h_L = max(3, int(target_area_mm2 / (w_L * px * py)))
    h_L = min(h_L, h - 2)
    y_start_L = max(0, cr - h_L // 2)
    roi_L = arr[y_start_L:y_start_L + h_L, x_start_L:x_start_L + w_L]
    s_L = float(np.mean(roi_L)) if roi_L.size > 0 else 0.0
    results_rois["left"] = {"mean": s_L, "rect": [y_start_L, x_start_L, h_L, w_L]}

    # ROI Up
    y_end_U = cr - r0 - gap_px
    y_start_U = gap_px
    w_U = max(3, y_end_U - y_start_U)
    h_U = max(3, int(target_area_mm2 / (w_U * px * py)))
    h_U = min(h_U, w - 2)
    x_start_U = max(0, cc - h_U // 2)
    roi_U = arr[y_start_U:y_start_U + w_U, x_start_U:x_start_U + h_U]
    s_U = float(np.mean(roi_U)) if roi_U.size > 0 else 0.0
    results_rois["up"] = {"mean": s_U, "rect": [y_start_U, x_start_U, w_U, h_U]}

    # ROI Down
    y_start_D = cr + r0 + gap_px
    y_end_D = h - gap_px
    w_D = max(3, y_end_D - y_start_D)
    h_D = max(3, int(target_area_mm2 / (w_D * px * py)))
    h_D = min(h_D, w - 2)
    x_start_D = max(0, cc - h_D // 2)
    roi_D = arr[y_start_D:y_start_D + w_D, x_start_D:x_start_D + h_D]
    s_D = float(np.mean(roi_D)) if roi_D.size > 0 else 0.0
    results_rois["down"] = {"mean": s_D, "rect": [y_start_D, x_start_D, w_D, h_D]}

    # PSG — Eq. (1)
    if signal_mean > 0:
        psg = 100.0 * abs((s_R + s_L) - (s_U + s_D)) / (2.0 * signal_mean)
    else:
        psg = 0.0

    # Limiti: ACR ≤ 2.5%, AAPM ≤ 1.0%
    passed_acr = psg <= 2.5
    passed_aapm = psg <= 1.0

    return {
        "psg_percent": round(psg, 4),
        "signal_mean": round(signal_mean, 2),
        "s_right": round(s_R, 2),
        "s_left": round(s_L, 2),
        "s_up": round(s_U, 2),
        "s_down": round(s_D, 2),
        "passed_acr": passed_acr,
        "passed_aapm": passed_aapm,
        "passed": passed_acr,
        "limit_acr": 2.5,
        "limit_aapm": 1.0,
        "center_rc": (cr, cc),
        "radius_px": r0,
        "ufov_radius_px": r_ufov,
        "rois": results_rois,
    }


# ==============================================================================
# PIU — Percent Image Uniformity
# ==============================================================================

def calculate_piu(arr: np.ndarray, pixel_spacing_mm: float = 1.0,
                  center_rc=None, radius_px=None):
    """
    Calcola la Percent Image Uniformity (PIU) secondo ACR.

    Ref: Eq. (3), (4) del paper:
        I1 = (1/N_M) × (I * M)   — convoluzione con maschera circolare 1 cm²
        PIU% = 100 × [1 - (S_max - S_min) / (S_max + S_min)]

    Usa slice #7 del phantom ACR.
    La maschera M è un disco con area = 1 cm² (raggio r = ceil(10/px / sqrt(π)))

    Args:
        arr: immagine 2D (slice #7)
        pixel_spacing_mm: dimensione pixel in mm
        center_rc: (row, col) centro phantom
        radius_px: raggio phantom in pixel

    Returns:
        dict con risultati PIU
    """
    h, w = arr.shape
    px = float(pixel_spacing_mm)

    if center_rc is None or radius_px is None:
        cr, cc, r0 = find_phantom_circle(arr, pixel_spacing_mm)
    else:
        cr, cc = center_rc
        r0 = radius_px

    # Raggio maschera per area 1 cm² = 100 mm²
    # Area cerchio = π × r² → r = sqrt(100/π) / px
    r_mask_mm = math.sqrt(100.0 / math.pi)
    r_mask_px = int(math.ceil(r_mask_mm / px))

    # Crea maschera circolare
    mask_size = 2 * r_mask_px + 1
    Y_m, X_m = np.ogrid[:mask_size, :mask_size]
    mask = ((X_m - r_mask_px)**2 + (Y_m - r_mask_px)**2 <= r_mask_px**2).astype(np.float32)
    n_mask = mask.sum()

    # Convoluzione — Eq. (3)
    from scipy.ndimage import convolve
    i1 = convolve(arr.astype(np.float64), mask, mode='constant', cval=0.0) / n_mask

    # UFOV: cerchio con R = 0.8 × R0
    r_ufov = int(0.8 * r0)
    Y, X = np.ogrid[:h, :w]
    ufov_mask = ((X - cc)**2 + (Y - cr)**2) <= r_ufov**2

    # Trova max e min dentro UFOV
    i1_ufov = i1.copy()
    i1_ufov[~ufov_mask] = np.nan

    s_max = float(np.nanmax(i1_ufov))
    s_min = float(np.nanmin(i1_ufov))

    # Posizioni max e min
    max_pos = np.unravel_index(np.nanargmax(i1_ufov), i1_ufov.shape)
    min_pos = np.unravel_index(np.nanargmin(i1_ufov), i1_ufov.shape)

    # PIU — Eq. (4)
    if (s_max + s_min) > 0:
        piu = 100.0 * (1.0 - (s_max - s_min) / (s_max + s_min))
    else:
        piu = 0.0

    # Limiti: ACR ≥ 87.5% (<3T), ≥ 82% (3T); AAPM ≥ 90%
    field_T = 1.5  # default, verrà sovrascritto dal chiamante
    limit = 87.5 if field_T < 3.0 else 82.0
    passed = piu >= limit

    return {
        "piu_percent": round(piu, 2),
        "s_max": round(s_max, 2),
        "s_min": round(s_min, 2),
        "max_position_rc": (int(max_pos[0]), int(max_pos[1])),
        "min_position_rc": (int(min_pos[0]), int(min_pos[1])),
        "passed": passed,
        "limit": limit,
        "center_rc": (cr, cc),
        "radius_px": r0,
        "ufov_radius_px": r_ufov,
        "mask_radius_px": r_mask_px,
    }


# ==============================================================================
# SNR — Signal-to-Noise Ratio
# ==============================================================================

def calculate_snr_single_image(arr: np.ndarray, pixel_spacing_mm: float = 1.0,
                               center_rc=None, radius_px=None,
                               bg_rois_std=None):
    """
    Calcola SNR con metodo singola immagine (NEMA MS 1-2008).

    Ref: Eq. (5), (7) del paper:
        SNR = 0.665 × S / σ_bkg

    Il fattore 0.665 compensa la distribuzione Rayleigh del rumore
    nelle immagini di magnitudine.

    Variante usata: media di σ_L e σ_R — Eq. (7):
        SNR = 2 × 0.665 × S / (σ_L + σ_R)

    Args:
        arr: immagine 2D (slice #7)
        pixel_spacing_mm: dimensione pixel
        center_rc, radius_px: geometria phantom
        bg_rois_std: dict con std delle ROI background (opzionale)

    Returns:
        dict con risultati SNR
    """
    h, w = arr.shape
    px = py = pixel_spacing_mm

    if center_rc is None or radius_px is None:
        cr, cc, r0 = find_phantom_circle(arr, pixel_spacing_mm)
    else:
        cr, cc = center_rc
        r0 = radius_px

    # UFOV signal
    r_ufov = int(0.8 * r0)
    Y, X = np.ogrid[:h, :w]
    ufov_mask = ((X - cc)**2 + (Y - cr)**2) <= r_ufov**2
    signal_mean = float(np.mean(arr[ufov_mask]))

    # Background ROIs — stesse del PSG
    gap_px = int(0.1 * r0)
    target_area_mm2 = 1000.0

    def _bg_roi_std(arr, y0, x0, roi_h, roi_w):
        roi = arr[y0:y0 + roi_h, x0:x0 + roi_w]
        return float(np.std(roi)) if roi.size > 0 else 1.0

    # Right
    x_start_R = cc + r0 + gap_px
    w_R = max(3, w - gap_px - x_start_R)
    h_R = max(3, int(target_area_mm2 / (w_R * px * py)))
    h_R = min(h_R, h - 2)
    y_start_R = max(0, cr - h_R // 2)
    std_R = _bg_roi_std(arr, y_start_R, x_start_R, h_R, w_R)

    # Left
    x_start_L = gap_px
    w_L = max(3, cc - r0 - gap_px - x_start_L)
    h_L = max(3, int(target_area_mm2 / (w_L * px * py)))
    h_L = min(h_L, h - 2)
    y_start_L = max(0, cr - h_L // 2)
    std_L = _bg_roi_std(arr, y_start_L, x_start_L, h_L, w_L)

    # Up
    y_start_U = gap_px
    w_U_h = max(3, cr - r0 - gap_px - y_start_U)
    h_U_w = max(3, int(target_area_mm2 / (w_U_h * px * py)))
    h_U_w = min(h_U_w, w - 2)
    x_start_U = max(0, cc - h_U_w // 2)
    std_U = _bg_roi_std(arr, y_start_U, x_start_U, w_U_h, h_U_w)

    # Down
    y_start_D = cr + r0 + gap_px
    w_D_h = max(3, h - gap_px - y_start_D)
    h_D_w = max(3, int(target_area_mm2 / (w_D_h * px * py)))
    h_D_w = min(h_D_w, w - 2)
    x_start_D = max(0, cc - h_D_w // 2)
    std_D = _bg_roi_std(arr, y_start_D, x_start_D, w_D_h, h_D_w)

    # SNR con diverse combinazioni di background — Eq. (7)
    snr_lr = 2.0 * 0.665 * signal_mean / max(std_L + std_R, 1e-6)
    snr_ud = 2.0 * 0.665 * signal_mean / max(std_U + std_D, 1e-6)
    snr_all = 4.0 * 0.665 * signal_mean / max(std_L + std_R + std_U + std_D, 1e-6)

    # SNR principale (L+R come da protocollo greco)
    snr = snr_lr

    return {
        "snr": round(snr, 2),
        "snr_lr": round(snr_lr, 2),
        "snr_ud": round(snr_ud, 2),
        "snr_all": round(snr_all, 2),
        "signal_mean": round(signal_mean, 2),
        "std_left": round(std_L, 4),
        "std_right": round(std_R, 4),
        "std_up": round(std_U, 4),
        "std_down": round(std_D, 4),
        "center_rc": (cr, cc),
        "radius_px": r0,
        "passed": True,  # SNR non ha un limite fisso ACR, dipende dal campo
    }


def calculate_snr_two_images(arr1: np.ndarray, arr2: np.ndarray,
                             pixel_spacing_mm: float = 1.0,
                             center_rc=None, radius_px=None):
    """
    Calcola SNR con metodo due immagini (NEMA MS 1-2008, subtraction method).

    Ref: Eq. (6) del paper:
        SNR = 1.41 × S / σ_D

    dove S è il segnale medio nella UFOV e σ_D è la std dell'immagine
    differenza nella stessa ROI.

    Args:
        arr1, arr2: due immagini identiche (stessa slice, stessa sequenza o sequenze consecutive)
        pixel_spacing_mm: dimensione pixel
        center_rc, radius_px: geometria phantom

    Returns:
        dict con risultati SNR
    """
    h, w = arr1.shape

    if center_rc is None or radius_px is None:
        cr, cc, r0 = find_phantom_circle(arr1, pixel_spacing_mm)
    else:
        cr, cc = center_rc
        r0 = radius_px

    # UFOV
    r_ufov = int(0.8 * r0)
    Y, X = np.ogrid[:h, :w]
    ufov_mask = ((X - cc)**2 + (Y - cr)**2) <= r_ufov**2

    # Segnale medio (media delle due immagini)
    s1 = float(np.mean(arr1[ufov_mask]))
    s2 = float(np.mean(arr2[ufov_mask]))
    signal_mean = (s1 + s2) / 2.0

    # Immagine differenza
    diff = arr1.astype(np.float64) - arr2.astype(np.float64)
    sigma_d = float(np.std(diff[ufov_mask]))

    # SNR — Eq. (6)
    snr = 1.41 * signal_mean / max(sigma_d, 1e-6)

    return {
        "snr": round(snr, 2),
        "signal_1": round(s1, 2),
        "signal_2": round(s2, 2),
        "signal_mean": round(signal_mean, 2),
        "sigma_diff": round(sigma_d, 4),
        "method": "two_image_subtraction",
        "center_rc": (cr, cc),
        "radius_px": r0,
        "passed": True,
    }


# ==============================================================================
# SNRU — Signal-to-Noise Ratio Uniformity
# ==============================================================================

def calculate_snru(arr: np.ndarray, pixel_spacing_mm: float = 1.0,
                   center_rc=None, radius_px=None):
    """
    Calcola la SNR Uniformity (SNRU) secondo il metodo di Lerski/Ihalainen.

    Ref: Eq. (14), (15) del paper:
        SNR_i = 2 × 0.665 × S_i / (σ_L + σ_R),  i = 1,...,5
        SNRU = 100 × σ_SNR / mean(SNR)

    Usa 5 ROI circolari (~1 cm raggio):
      - 1 al centro
      - 4 a distanza R0/2 (posizioni 3, 6, 9, 12 o'clock)

    Limiti: ≤ 5% (achievable), ≤ 10% (max acceptable)

    Args:
        arr: immagine 2D (slice #7)
        pixel_spacing_mm: dimensione pixel
        center_rc, radius_px: geometria phantom

    Returns:
        dict con risultati SNRU
    """
    h, w = arr.shape
    px = py = pixel_spacing_mm

    if center_rc is None or radius_px is None:
        cr, cc, r0 = find_phantom_circle(arr, pixel_spacing_mm)
    else:
        cr, cc = center_rc
        r0 = radius_px

    # Raggio ROI piccola: ~1 cm = 10 mm
    roi_r_px = max(3, int(10.0 / px))

    # Distanza dal centro: R0/2
    dist_px = r0 // 2

    # 5 posizioni ROI
    positions = [
        ("Centro", cr, cc),
        ("Top (12h)", cr - dist_px, cc),
        ("Right (3h)", cr, cc + dist_px),
        ("Bottom (6h)", cr + dist_px, cc),
        ("Left (9h)", cr, cc - dist_px),
    ]

    # Misura segnale medio in ogni ROI
    roi_results = []
    Y, X = np.ogrid[:h, :w]

    for name, r, c in positions:
        mask = ((X - c)**2 + (Y - r)**2) <= roi_r_px**2
        mean_val = float(np.mean(arr[mask]))
        std_val = float(np.std(arr[mask]))
        roi_results.append({
            "name": name,
            "center_rc": (int(r), int(c)),
            "mean_val": round(mean_val, 2),
            "std_val": round(std_val, 2),
            "radius_px": roi_r_px,
        })

    # Background noise (L + R) per SNR di ogni ROI
    gap_px = int(0.1 * r0)
    target_area_mm2 = 1000.0

    # Right background
    x_start_R = cc + r0 + gap_px
    w_R = max(3, w - gap_px - x_start_R)
    h_R = max(3, int(target_area_mm2 / (w_R * px * py)))
    h_R = min(h_R, h - 2)
    y_start_R = max(0, cr - h_R // 2)
    roi_R = arr[y_start_R:y_start_R + h_R, x_start_R:x_start_R + w_R]
    std_R = float(np.std(roi_R)) if roi_R.size > 0 else 1.0

    # Left background
    x_start_L = gap_px
    w_L = max(3, cc - r0 - gap_px - x_start_L)
    h_L = max(3, int(target_area_mm2 / (w_L * px * py)))
    h_L = min(h_L, h - 2)
    y_start_L = max(0, cr - h_L // 2)
    roi_L = arr[y_start_L:y_start_L + h_L, x_start_L:x_start_L + w_L]
    std_L = float(np.std(roi_L)) if roi_L.size > 0 else 1.0

    # SNR per ogni ROI — Eq. (14)
    snr_values = []
    noise_denom = max(std_L + std_R, 1e-6)
    for roi in roi_results:
        snr_i = 2.0 * 0.665 * roi["mean_val"] / noise_denom
        roi["snr"] = round(snr_i, 2)
        snr_values.append(snr_i)

    # SNRU — Eq. (15)
    snr_array = np.array(snr_values)
    snr_mean = float(np.mean(snr_array))
    snr_std = float(np.std(snr_array))

    if snr_mean > 0:
        snru = 100.0 * snr_std / snr_mean
    else:
        snru = 0.0

    # Limiti
    passed_achievable = snru <= 5.0
    passed_acceptable = snru <= 10.0

    return {
        "snru_percent": round(snru, 2),
        "snr_mean": round(snr_mean, 2),
        "snr_std": round(snr_std, 4),
        "snr_values": [round(v, 2) for v in snr_values],
        "rois": roi_results,
        "std_left": round(std_L, 4),
        "std_right": round(std_R, 4),
        "passed_achievable": passed_achievable,
        "passed_acceptable": passed_acceptable,
        "passed": passed_acceptable,
        "limit_achievable": 5.0,
        "limit_acceptable": 10.0,
        "center_rc": (cr, cc),
        "radius_px": r0,
        "roi_radius_px": roi_r_px,
        "dist_px": dist_px,
    }


# ==============================================================================
# GEOMETRIC ACCURACY — Accuratezza geometrica
# ==============================================================================

def calculate_geometric_accuracy(arr: np.ndarray, pixel_spacing_mm: float = 1.0,
                                 center_rc=None, radius_px=None,
                                 nominal_diameter_mm: float = 190.0,
                                 h_line_row=None, v_line_col=None):
    """
    Misura l'accuratezza geometrica del phantom ACR.

    Il diametro interno del phantom ACR è 190 mm.
    Si misura il diametro in direzione orizzontale e verticale sulla slice #1
    (e opzionalmente #5 e localizer).

    Limite ACR: ≤ ±2 mm dalla dimensione nominale.

    Metodo:
      - Threshold al 50% del segnale massimo per trovare i bordi
      - Misura distanza tra bordi opposti in H e V

    Args:
        arr: immagine 2D (slice #1 o #5)
        pixel_spacing_mm: dimensione pixel
        nominal_diameter_mm: diametro nominale (190 mm per ACR)

    Returns:
        dict con risultati
    """
    h, w = arr.shape
    px = float(pixel_spacing_mm)

    if center_rc is None or radius_px is None:
        cr, cc, r0 = find_phantom_circle(arr, pixel_spacing_mm)
    else:
        cr, cc = center_rc
        r0 = radius_px

    # Threshold al 50% del massimo per edge detection più precisa
    cr = int(np.clip(round(cr), 0, h - 1))
    cc = int(np.clip(round(cc), 0, w - 1))
    r0 = float(r0)

    def _bilinear(rr, cc_):
        rr = np.asarray(rr, dtype=float)
        cc_ = np.asarray(cc_, dtype=float)
        r1 = np.clip(np.floor(rr).astype(int), 0, h - 1)
        c1 = np.clip(np.floor(cc_).astype(int), 0, w - 1)
        r2 = np.clip(r1 + 1, 0, h - 1)
        c2 = np.clip(c1 + 1, 0, w - 1)
        wr = rr - r1
        wc = cc_ - c1
        return (
            arr[r1, c1] * (1 - wr) * (1 - wc) +
            arr[r2, c1] * wr * (1 - wc) +
            arr[r1, c2] * (1 - wr) * wc +
            arr[r2, c2] * wr * wc
        )

    def _edge_crossings(x, vals, mask, threshold):
        idxs = np.where(mask)[0]
        if len(idxs) < 2:
            return None

        def interp(i, j):
            x0, x1 = float(x[i]), float(x[j])
            y0, y1 = float(vals[i]), float(vals[j])
            if abs(y1 - y0) < 1e-9:
                return x1
            return x0 + (threshold - y0) * (x1 - x0) / (y1 - y0)

        left_i = int(idxs[0])
        right_i = int(idxs[-1])
        left = interp(left_i - 1, left_i) if left_i > 0 else float(x[left_i])
        right = interp(right_i + 1, right_i) if right_i < len(vals) - 1 else float(x[right_i])
        if right <= left:
            left, right = float(x[left_i]), float(x[right_i])
        return left, right

    def _measure_profile(angle_deg, base_r, base_c, offset_px=0.0):
        theta = np.deg2rad(angle_deg)
        dr, dc = np.sin(theta), np.cos(theta)
        pr, pc = np.cos(theta), -np.sin(theta)
        half_len = max(12.0, 1.18 * r0)
        n = int(max(96, min(512, round(2 * half_len) + 1)))
        x = np.linspace(-half_len, half_len, n)
        rr = base_r + offset_px * pr + x * dr
        cc_line = base_c + offset_px * pc + x * dc
        vals = _bilinear(rr, cc_line)

        inner = np.abs(x) <= max(4.0, 0.55 * r0)
        outer = np.abs(x) >= max(6.0, 1.04 * r0)
        signal = float(np.median(vals[inner])) if np.any(inner) else float(np.percentile(vals, 90))
        background = float(np.median(vals[outer])) if np.any(outer) else float(np.percentile(vals, 10))
        threshold = background + 0.5 * (signal - background)
        mask = vals >= threshold if signal >= background else vals <= threshold
        edges = _edge_crossings(x, vals, mask, threshold)
        if edges is None:
            return None
        left, right = edges
        diameter_px = right - left
        step = max(1, len(x) // 180)
        return {
            "angle_deg": float(angle_deg),
            "offset_px": float(offset_px),
            "diameter_px": float(diameter_px),
            "diameter_mm": float(diameter_px * px),
            "threshold": float(threshold),
            "signal": signal,
            "background": background,
            "endpoints_rc": [
                [float(base_r + offset_px * pr + left * dr), float(base_c + offset_px * pc + left * dc)],
                [float(base_r + offset_px * pr + right * dr), float(base_c + offset_px * pc + right * dc)],
            ],
            "profile": {
                "x_mm": [round(float(v * px), 3) for v in x[::step]],
                "values": [round(float(v), 3) for v in vals[::step]],
            },
        }

    def _measure_orientation(angle_deg, base_r, base_c, offsets_px):
        profiles = []
        for offset in offsets_px:
            measured = _measure_profile(angle_deg, base_r, base_c, offset)
            if measured is not None:
                profiles.append(measured)
        if not profiles:
            return None
        diameters = np.array([p["diameter_mm"] for p in profiles], dtype=float)
        best_idx = int(np.argmin(np.abs(diameters - np.median(diameters))))
        return {
            "angle_deg": float(angle_deg),
            "diameter_mm": float(np.median(diameters)),
            "std_mm": float(np.std(diameters)),
            "n_profiles": len(profiles),
            "best": profiles[best_idx],
            "profiles": profiles,
        }

    offsets_px = np.array([-8.0, -4.0, 0.0, 4.0, 8.0]) / max(px, 1e-6)
    h_base_r = int(np.clip(round(h_line_row), 0, h - 1)) if h_line_row is not None else cr
    v_base_c = int(np.clip(round(v_line_col), 0, w - 1)) if v_line_col is not None else cc

    h_result = _measure_orientation(0.0, h_base_r, cc, offsets_px)
    v_result = _measure_orientation(90.0, cr, v_base_c, offsets_px)
    d45_result = _measure_orientation(45.0, cr, cc, offsets_px)
    d135_result = _measure_orientation(135.0, cr, cc, offsets_px)

    diameter_h_mm = h_result["diameter_mm"] if h_result else 0.0
    diameter_v_mm = v_result["diameter_mm"] if v_result else 0.0

    # Errori
    error_h_mm = diameter_h_mm - nominal_diameter_mm
    error_v_mm = diameter_v_mm - nominal_diameter_mm

    # Limite: ≤ ±2 mm
    limit_mm = 2.0
    passed_h = abs(error_h_mm) <= limit_mm
    passed_v = abs(error_v_mm) <= limit_mm
    passed = passed_h and passed_v

    return {
        "diameter_h_mm": round(diameter_h_mm, 2),
        "diameter_v_mm": round(diameter_v_mm, 2),
        "error_h_mm": round(error_h_mm, 2),
        "error_v_mm": round(error_v_mm, 2),
        "nominal_diameter_mm": nominal_diameter_mm,
        "passed_h": passed_h,
        "passed_v": passed_v,
        "passed": passed,
        "limit_mm": limit_mm,
        "center_rc": (cr, cc),
        "radius_px": r0,
        "h_line_row": h_base_r,
        "h_line_endpoints": [
            round(h_result["best"]["endpoints_rc"][0][1], 2),
            round(h_result["best"]["endpoints_rc"][1][1], 2),
        ] if h_result else [round(cc - r0, 2), round(cc + r0, 2)],
        "v_line_col": v_base_c,
        "v_line_endpoints": [
            round(v_result["best"]["endpoints_rc"][0][0], 2),
            round(v_result["best"]["endpoints_rc"][1][0], 2),
        ] if v_result else [round(cr - r0, 2), round(cr + r0, 2)],
        "geometric_profiles": {
            "horizontal": h_result,
            "vertical": v_result,
            "diagonal_45": d45_result,
            "diagonal_135": d135_result,
        },
        "oblique_lines": [
            {
                "name": "45",
                "diameter_mm": round(d45_result["diameter_mm"], 2),
                "endpoints_rc": d45_result["best"]["endpoints_rc"],
            } if d45_result else None,
            {
                "name": "135",
                "diameter_mm": round(d135_result["diameter_mm"], 2),
                "endpoints_rc": d135_result["best"]["endpoints_rc"],
            } if d135_result else None,
        ],
    }


# ==============================================================================
# SLICE THICKNESS ACCURACY — Accuratezza spessore di strato
# ==============================================================================

def calculate_slice_thickness(arr: np.ndarray, pixel_spacing_mm: float = 1.0,
                              center_rc=None, radius_px=None,
                              nominal_thickness_mm: float = 5.0):
    """
    Misura l'accuratezza dello spessore di strato usando le rampe incrociate
    nella slice #1 del phantom ACR.

    Il phantom ACR contiene due rampe incrociate a 45° nella slice #1.
    Lo spessore si calcola dalla lunghezza del segnale delle rampe:

        thickness = 0.2 × (top_length × bottom_length) / (top_length + bottom_length)

    dove 0.2 è il fattore geometrico per rampe a 45° con angolo noto,
    e le lunghezze sono misurate al FWHM del profilo di segnale lungo le rampe.

    Limite ACR: 5 mm ± 0.7 mm

    Args:
        arr: immagine 2D (slice #1)
        pixel_spacing_mm: dimensione pixel
        nominal_thickness_mm: spessore nominale (5 mm)

    Returns:
        dict con risultati
    """
    h, w = arr.shape
    px = pixel_spacing_mm

    if center_rc is None or radius_px is None:
        cr, cc, r0 = find_phantom_circle(arr, pixel_spacing_mm)
    else:
        cr, cc = center_rc
        r0 = radius_px

    # Le rampe incrociate sono nella regione centrale della slice #1
    # Estraiamo un profilo orizzontale nella zona delle rampe
    # Le rampe sono tipicamente ±10-15 pixel sopra e sotto il centro

    # Profilo della rampa superiore (sopra il centro, ~10 px)
    ramp_offset = max(5, int(10.0 / px))
    ramp_width = max(3, int(5.0 / px))  # larghezza della banda di averaging

    # Rampa superiore: media di alcune righe sopra il centro
    top_band = arr[cr - ramp_offset - ramp_width:cr - ramp_offset, :]
    if top_band.size > 0:
        top_profile = np.mean(top_band, axis=0)
    else:
        top_profile = arr[cr - ramp_offset, :]

    # Rampa inferiore: media di alcune righe sotto il centro
    bot_band = arr[cr + ramp_offset:cr + ramp_offset + ramp_width, :]
    if bot_band.size > 0:
        bot_profile = np.mean(bot_band, axis=0)
    else:
        bot_profile = arr[cr + ramp_offset, :]

    def _fwhm_length(profile, px_mm):
        """Calcola la lunghezza FWHM di un profilo."""
        if profile.size == 0:
            return 0.0
        peak = np.max(profile)
        bg = np.min(profile)
        half_max = (peak + bg) / 2.0
        above = np.where(profile >= half_max)[0]
        if len(above) < 2:
            return 0.0
        length_px = above[-1] - above[0]
        return length_px * px_mm

    top_length_mm = _fwhm_length(top_profile, px)
    bot_length_mm = _fwhm_length(bot_profile, px)

    # Spessore: formula ACR per rampe incrociate a 45°
    # thickness = 0.2 × (L_top × L_bot) / (L_top + L_bot)
    if (top_length_mm + bot_length_mm) > 0:
        measured_thickness_mm = 0.2 * (top_length_mm * bot_length_mm) / (top_length_mm + bot_length_mm)
    else:
        measured_thickness_mm = 0.0

    # Errore
    error_mm = measured_thickness_mm - nominal_thickness_mm

    # Limite: ±0.7 mm
    limit_mm = 0.7
    passed = abs(error_mm) <= limit_mm

    return {
        "measured_thickness_mm": round(measured_thickness_mm, 2),
        "nominal_thickness_mm": nominal_thickness_mm,
        "error_mm": round(error_mm, 2),
        "top_ramp_length_mm": round(top_length_mm, 2),
        "bottom_ramp_length_mm": round(bot_length_mm, 2),
        "passed": passed,
        "limit_mm": limit_mm,
        "center_rc": (cr, cc),
        "radius_px": r0,
    }


# ==============================================================================
# SLICE POSITION ACCURACY — Accuratezza posizione strato
# ==============================================================================

def calculate_slice_position(arr: np.ndarray, pixel_spacing_mm: float = 1.0,
                             center_rc=None, radius_px=None):
    """
    Misura l'accuratezza della posizione dello strato usando i wedge
    (cunei incrociati) nella slice #1 e #11 del phantom ACR.

    I due cunei producono due barre di segnale. La differenza di lunghezza
    tra le due barre indica l'offset della posizione dello strato.

    Slice position error = (bar_length_1 - bar_length_2) / 2 × tan(angolo)

    Per il phantom ACR con cunei a 45°:
        offset_mm = (L1 - L2) × pixel_spacing / 2

    Limite ACR: ≤ ±5 mm (≤ ±4 mm raccomandato)

    Args:
        arr: immagine 2D (slice #1 o #11)
        pixel_spacing_mm: dimensione pixel

    Returns:
        dict con risultati
    """
    h, w = arr.shape
    px = pixel_spacing_mm

    if center_rc is None or radius_px is None:
        cr, cc, r0 = find_phantom_circle(arr, pixel_spacing_mm)
    else:
        cr, cc = center_rc
        r0 = radius_px

    # I cunei sono nella parte superiore della slice #1/#11
    # Estraiamo profili verticali nelle due posizioni dei cunei
    # I cunei sono tipicamente a ±20-30 mm dal centro, nella parte alta

    wedge_offset_px = max(10, int(25.0 / px))  # offset laterale dal centro
    search_band = max(5, int(20.0 / px))  # banda verticale di ricerca

    # Profilo verticale sinistro (cuneo sinistro)
    left_col = max(0, cc - wedge_offset_px)
    left_profile = arr[:, left_col]

    # Profilo verticale destro (cuneo destro)
    right_col = min(w - 1, cc + wedge_offset_px)
    right_profile = arr[:, right_col]

    def _bar_length(profile, px_mm):
        """Misura la lunghezza della barra di segnale al FWHM."""
        if profile.size == 0:
            return 0.0
        peak = np.max(profile)
        bg = np.percentile(profile, 10)
        half_max = (peak + bg) / 2.0
        above = np.where(profile >= half_max)[0]
        if len(above) < 2:
            return 0.0
        return (above[-1] - above[0]) * px_mm

    L1_mm = _bar_length(left_profile, px)
    L2_mm = _bar_length(right_profile, px)

    # Offset posizione strato
    # Per cunei a 45°: offset = (L1 - L2) / 2
    slice_position_error_mm = (L1_mm - L2_mm) / 2.0

    # Limiti
    limit_mm = 5.0
    limit_recommended_mm = 4.0
    passed = abs(slice_position_error_mm) <= limit_mm
    passed_recommended = abs(slice_position_error_mm) <= limit_recommended_mm

    return {
        "slice_position_error_mm": round(slice_position_error_mm, 2),
        "bar_length_1_mm": round(L1_mm, 2),
        "bar_length_2_mm": round(L2_mm, 2),
        "passed": passed,
        "passed_recommended": passed_recommended,
        "limit_mm": limit_mm,
        "limit_recommended_mm": limit_recommended_mm,
        "center_rc": (cr, cc),
        "radius_px": r0,
    }


# ==============================================================================
# HIGH-CONTRAST SPATIAL RESOLUTION — Risoluzione spaziale
# ==============================================================================

def calculate_spatial_resolution(arr: np.ndarray, pixel_spacing_mm: float = 1.0,
                                 center_rc=None, radius_px=None,
                                 grid_rects=None):
    """
    Valuta la risoluzione spaziale ad alto contrasto dalla slice #1 del phantom ACR.

    Il phantom ACR contiene griglie di risoluzione (hole arrays) con fori
    di diametro decrescente: 1.1, 1.0, 0.9 mm.
    Il test verifica se le griglie sono risolvibili.

    Metodo automatico: analisi del contrasto locale nelle regioni delle griglie.
    Si misura la modulazione (contrasto) del pattern periodico.

    Limite ACR: ≤ 1 mm (i fori da 1 mm devono essere risolti)

    Args:
        arr: immagine 2D (slice #1)
        pixel_spacing_mm: dimensione pixel

    Returns:
        dict con risultati
    """
    h, w = arr.shape
    px = pixel_spacing_mm

    if center_rc is None or radius_px is None:
        cr, cc, r0 = find_phantom_circle(arr, pixel_spacing_mm)
    else:
        cr, cc = center_rc
        r0 = radius_px

    # Le griglie di risoluzione sono nella parte superiore della slice #1
    # Tipicamente a ~50-60 mm sopra il centro del phantom
    # Ci sono 3 set: UL (1.1mm), UR (1.0mm), LR (0.9mm)

    def _clamp_rect(rect):
        y, x, rh, rw = [int(round(v)) for v in rect]
        y = max(0, min(h - 1, y))
        x = max(0, min(w - 1, x))
        rh = max(1, min(h - y, rh))
        rw = max(1, min(w - x, rw))
        return [y, x, rh, rw]

    if grid_rects and len(grid_rects) >= 3:
        grid_rects = [_clamp_rect(rect) for rect in grid_rects[:3]]
    else:
        grid_region_top = max(0, cr - int(0.7 * r0))
        grid_region_bot = max(0, cr - int(0.3 * r0))
        grid_h = max(1, grid_region_bot - grid_region_top)
        third = w // 3
        grid_rects = [
            _clamp_rect([grid_region_top, 0, grid_h, third]),
            _clamp_rect([grid_region_top, third, grid_h, third]),
            _clamp_rect([grid_region_top, 2 * third, grid_h, w - 2 * third]),
        ]

    grid_regions = [arr[y:y + rh, x:x + rw] for y, x, rh, rw in grid_rects]

    if any(region.size == 0 for region in grid_regions):
        return {
            "resolved_mm": 0.0,
            "passed": False,
            "limit_mm": 1.0,
            "center_rc": (cr, cc),
            "radius_px": r0,
            "grid_rects": grid_rects,
            "modulation_1_1mm": 0.0,
            "modulation_1_0mm": 0.0,
            "modulation_0_9mm": 0.0,
        }

    def _measure_modulation(region):
        """Misura la modulazione del pattern nella regione."""
        if region.size < 10:
            return 0.0
        # Usa la deviazione standard normalizzata come proxy della modulazione
        # Un pattern risolto ha alta varianza locale
        from scipy.ndimage import uniform_filter
        local_mean = uniform_filter(region.astype(np.float64), size=3)
        local_var = uniform_filter((region.astype(np.float64) - local_mean)**2, size=3)
        local_std = np.sqrt(np.mean(local_var))
        global_mean = np.mean(region)
        if global_mean > 0:
            return float(local_std / global_mean)
        return 0.0

    # Misura modulazione per ogni griglia
    mod_1_1 = _measure_modulation(grid_regions[0])
    mod_1_0 = _measure_modulation(grid_regions[1])
    mod_0_9 = _measure_modulation(grid_regions[2])

    # Soglia di risoluzione: modulazione > 0.05 indica pattern risolto
    threshold = 0.05
    resolved_1_1 = mod_1_1 > threshold
    resolved_1_0 = mod_1_0 > threshold
    resolved_0_9 = mod_0_9 > threshold

    # Determina la risoluzione raggiunta
    if resolved_0_9:
        resolved_mm = 0.9
    elif resolved_1_0:
        resolved_mm = 1.0
    elif resolved_1_1:
        resolved_mm = 1.1
    else:
        resolved_mm = 999.0  # non risolto

    # Limite: deve risolvere almeno 1.0 mm
    passed = resolved_mm <= 1.0

    return {
        "resolved_mm": resolved_mm,
        "passed": passed,
        "limit_mm": 1.0,
        "resolved_1_1mm": resolved_1_1,
        "resolved_1_0mm": resolved_1_0,
        "resolved_0_9mm": resolved_0_9,
        "modulation_1_1mm": round(mod_1_1, 4),
        "modulation_1_0mm": round(mod_1_0, 4),
        "modulation_0_9mm": round(mod_0_9, 4),
        "center_rc": (cr, cc),
        "radius_px": r0,
        "grid_rects": grid_rects,
    }


# ==============================================================================
# LOW-CONTRAST OBJECT DETECTABILITY — Rilevabilità oggetti a basso contrasto
# ==============================================================================

def calculate_low_contrast(arr: np.ndarray, pixel_spacing_mm: float = 1.0,
                           center_rc=None, radius_px=None):
    """
    Valuta la rilevabilità degli oggetti a basso contrasto nelle slice #8-#11
    del phantom ACR.

    Il phantom ACR contiene dischi a basso contrasto (spoke targets) con
    diametri decrescenti disposti in cerchio. Ogni slice (#8-#11) ha un set
    di 10 dischi con contrasto diverso.

    Metodo: per ogni disco, si misura il CNR (Contrast-to-Noise Ratio)
    rispetto al background circostante. Un disco è "visibile" se CNR > soglia.

    Limite ACR: ≥ 9 spoke totali visibili (<3T), ≥ 37 (3T)

    Metodo automatico:
      - Identifica la regione dei dischi (anello a ~60mm dal centro)
      - Per ogni posizione angolare, misura il contrasto locale
      - Conta i dischi con CNR sufficiente

    Args:
        arr: immagine 2D (slice #8, #9, #10, o #11)
        pixel_spacing_mm: dimensione pixel

    Returns:
        dict con risultati per la singola slice
    """
    h, w = arr.shape
    px = pixel_spacing_mm

    if center_rc is None or radius_px is None:
        cr, cc, r0 = find_phantom_circle(arr, pixel_spacing_mm)
    else:
        cr, cc = center_rc
        r0 = radius_px

    # I dischi a basso contrasto sono disposti in un anello
    # a circa 45-60 mm dal centro del phantom
    # Ci sono 10 dischi per slice, disposti a intervalli angolari di 36°

    n_spokes = 10
    spoke_radius_mm = 45.0  # distanza dal centro all'anello dei dischi
    spoke_radius_px = int(spoke_radius_mm / px)

    # Raggio dei dischi: varia per slice (7mm, 5mm, 4mm, 3mm per slice 8-11)
    # Usiamo un raggio generico e misuriamo il contrasto
    disk_radius_mm = 5.0  # raggio medio del disco
    disk_radius_px = max(2, int(disk_radius_mm / px))

    # Background: anello leggermente più esterno
    bg_inner_px = spoke_radius_px + disk_radius_px + 2
    bg_outer_px = bg_inner_px + max(3, int(5.0 / px))

    # Misura background medio nell'anello
    Y, X = np.ogrid[:h, :w]
    dist_from_center = np.sqrt((X - cc)**2 + (Y - cr)**2)
    bg_mask = (dist_from_center >= bg_inner_px) & (dist_from_center <= bg_outer_px)

    # Fallback: usa un anello interno se quello esterno è fuori dal phantom
    if np.sum(bg_mask & (arr > 0)) < 50:
        bg_inner_px = spoke_radius_px - disk_radius_px - max(3, int(5.0 / px))
        bg_outer_px = spoke_radius_px - disk_radius_px - 2
        bg_mask = (dist_from_center >= bg_inner_px) & (dist_from_center <= bg_outer_px)

    bg_values = arr[bg_mask & (arr > 0)]
    if bg_values.size > 0:
        bg_mean = float(np.mean(bg_values))
        bg_std = float(np.std(bg_values))
    else:
        bg_mean = float(np.mean(arr[arr > 0]))
        bg_std = float(np.std(arr[arr > 0]))

    # Misura ogni spoke (disco)
    spokes = []
    n_visible = 0

    for i in range(n_spokes):
        angle_deg = i * (360.0 / n_spokes)
        angle_rad = math.radians(angle_deg)

        # Posizione del disco
        disk_r = int(cr - spoke_radius_px * math.cos(angle_rad))
        disk_c = int(cc + spoke_radius_px * math.sin(angle_rad))

        # Clamp to image bounds
        disk_r = max(disk_radius_px, min(h - disk_radius_px - 1, disk_r))
        disk_c = max(disk_radius_px, min(w - disk_radius_px - 1, disk_c))

        # Misura segnale nel disco
        disk_mask = ((X - disk_c)**2 + (Y - disk_r)**2) <= disk_radius_px**2
        disk_values = arr[disk_mask]

        if disk_values.size > 0:
            disk_mean = float(np.mean(disk_values))
            disk_std = float(np.std(disk_values))
        else:
            disk_mean = 0.0
            disk_std = 0.0

        # CNR
        if bg_std > 0:
            cnr = abs(disk_mean - bg_mean) / bg_std
        else:
            cnr = 0.0

        # Visibilità: CNR > 1.0 (Rose criterion)
        visible = cnr > 1.0
        if visible:
            n_visible += 1

        spokes.append({
            "index": i,
            "angle_deg": round(angle_deg, 1),
            "center_rc": (disk_r, disk_c),
            "mean_signal": round(disk_mean, 2),
            "cnr": round(cnr, 2),
            "visible": visible,
        })

    # Limiti ACR: ≥ 9 spoke per slice (<3T), ≥ 37 totali su 4 slice (3T)
    # Per singola slice: ≥ 2-3 è ragionevole
    passed = n_visible >= 2  # per singola slice

    return {
        "n_visible": n_visible,
        "n_total": n_spokes,
        "spokes": spokes,
        "bg_mean": round(bg_mean, 2),
        "bg_std": round(bg_std, 4),
        "passed": passed,
        "spoke_radius_mm": spoke_radius_mm,
        "disk_radius_mm": disk_radius_mm,
        "center_rc": (cr, cc),
        "radius_px": r0,
    }
