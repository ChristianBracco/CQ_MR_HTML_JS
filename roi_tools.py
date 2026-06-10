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
from scipy import ndimage
from scipy.ndimage import uniform_filter


# ==============================================================================
# PHANTOM DETECTION â€” Trova centro e raggio del phantom ACR
# ==============================================================================

def find_phantom_circle(arr: np.ndarray, pixel_spacing_mm: float = 1.0):
    """
    Trova automaticamente il centro e il raggio del phantom ACR circolare.

    Metodo: threshold a 25% del massimo segnale, poi trova la riga/colonna
    con la massima estensione (diametro) per determinare centro e raggio.

    Ref: Appendix A del paper â€” Eq. (21)-(25)

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

    # Raggio: Eq. (25) â€” minimo tra i due semi-diametri
    r0 = min((i_end - i_start + 1) / 2.0, (j_end - j_start + 1) / 2.0)

    return int(round(y0)), int(round(x0)), int(round(r0))


# ==============================================================================
# PSG â€” Percent Signal Ghosting
# ==============================================================================

def calculate_psg(arr: np.ndarray, pixel_spacing_mm: float = 1.0,
                  center_rc=None, radius_px=None):
    """
    Calcola il Percent Signal Ghosting (PSG) secondo ACR.

    Ref: Eq. (1) del paper:
        PSG(%) = 100 Ã— |((S_R + S_L) - (S_U + S_D)) / (2 Ã— S)|

    Usa slice #7 del phantom ACR.
    - 1 ROI circolare centrale (UFOV, R = 0.8 Ã— R0)
    - 4 ROI rettangolari nel background (U, D, L, R)
      con area = 10 cmÂ² ciascuna, posizionate a 0.1Ã—R0 dal phantom e dal bordo.

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

    # ROI circolare centrale: UFOV con R = 0.8 Ã— R0
    r_ufov = int(0.8 * r0)
    Y, X = np.ogrid[:h, :w]
    ufov_mask = ((X - cc)**2 + (Y - cr)**2) <= r_ufov**2
    signal_mean = float(np.mean(arr[ufov_mask]))

    # 4 ROI rettangolari nel background
    # Larghezza w_q: ROI a 0.1Ã—R0 dal phantom E dal bordo immagine
    # Area = 10 cmÂ² = 1000 mmÂ²
    # H_q = 1000 / (w_q Ã— px Ã— py)  â€” Eq. (2)

    target_area_mm2 = 1000.0  # 10 cmÂ²
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

    # PSG â€” Eq. (1)
    if signal_mean > 0:
        psg = 100.0 * abs((s_R + s_L) - (s_U + s_D)) / (2.0 * signal_mean)
    else:
        psg = 0.0

    # Limiti: ACR â‰¤ 2.5%, AAPM â‰¤ 1.0%
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
# PIU â€” Percent Image Uniformity
# ==============================================================================

def calculate_piu(arr: np.ndarray, pixel_spacing_mm: float = 1.0,
                  center_rc=None, radius_px=None,
                  ufov_fraction: float = 0.8,
                  ufov_radius_px=None):
    """
    Calcola la Percent Image Uniformity (PIU) secondo ACR.

    Ref: Eq. (3), (4) del paper:
        I1 = (1/N_M) Ã— (I * M)   â€” convoluzione con maschera circolare 1 cmÂ²
        PIU% = 100 Ã— [1 - (S_max - S_min) / (S_max + S_min)]

    Usa slice #7 del phantom ACR.
    La maschera M Ã¨ un disco con area = 1 cmÂ² (raggio r = ceil(10/px / sqrt(Ï€)))

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

    # Raggio maschera per area 1 cmÂ² = 100 mmÂ²
    # Area cerchio = Ï€ Ã— rÂ² â†’ r = sqrt(100/Ï€) / px
    r_mask_mm = math.sqrt(100.0 / math.pi)
    r_mask_px = int(math.ceil(r_mask_mm / px))

    # Crea maschera circolare
    mask_size = 2 * r_mask_px + 1
    Y_m, X_m = np.ogrid[:mask_size, :mask_size]
    mask = ((X_m - r_mask_px)**2 + (Y_m - r_mask_px)**2 <= r_mask_px**2).astype(np.float32)
    n_mask = mask.sum()

    # Convoluzione â€” Eq. (3)
    from scipy.ndimage import convolve
    i1 = convolve(arr.astype(np.float64), mask, mode='constant', cval=0.0) / n_mask

    # UFOV: cerchio con R = 0.8 Ã— R0
    if ufov_radius_px is not None:
        r_ufov = int(round(float(ufov_radius_px)))
    else:
        ufov_fraction = max(0.45, min(0.9, float(ufov_fraction)))
        r_ufov = int(round(ufov_fraction * r0))
    Y, X = np.ogrid[:h, :w]
    ufov_mask = ((X - cc)**2 + (Y - cr)**2) <= r_ufov**2
    search_radius = max(1, r_ufov - r_mask_px)
    search_mask = ((X - cc)**2 + (Y - cr)**2) <= search_radius**2

    # Trova max e min dentro UFOV
    i1_ufov = i1.copy()
    i1_ufov[~search_mask] = np.nan

    s_max = float(np.nanmax(i1_ufov))
    s_min = float(np.nanmin(i1_ufov))

    # Posizioni max e min
    max_pos = np.unravel_index(np.nanargmax(i1_ufov), i1_ufov.shape)
    min_pos = np.unravel_index(np.nanargmin(i1_ufov), i1_ufov.shape)

    # PIU â€” Eq. (4)
    if (s_max + s_min) > 0:
        piu = 100.0 * (1.0 - (s_max - s_min) / (s_max + s_min))
    else:
        piu = 0.0

    # Limiti: ACR â‰¥ 87.5% (<3T), â‰¥ 82% (3T); AAPM â‰¥ 90%
    field_T = 1.5  # default, verrÃ  sovrascritto dal chiamante
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
        "ufov_fraction": round(float(r_ufov / max(float(r0), 1e-6)), 3),
        "piu_search_radius_px": search_radius,
        "mask_radius_px": r_mask_px,
    }


# ==============================================================================
# SNR â€” Signal-to-Noise Ratio
# ==============================================================================

def calculate_snr_single_image(arr: np.ndarray, pixel_spacing_mm: float = 1.0,
                               center_rc=None, radius_px=None,
                               bg_rois_std=None):
    """
    Calcola SNR con metodo singola immagine (NEMA MS 1-2008).

    Ref: Eq. (5), (7) del paper:
        SNR = 0.665 Ã— S / Ïƒ_bkg

    Il fattore 0.665 compensa la distribuzione Rayleigh del rumore
    nelle immagini di magnitudine.

    Variante usata: media di Ïƒ_L e Ïƒ_R â€” Eq. (7):
        SNR = 2 Ã— 0.665 Ã— S / (Ïƒ_L + Ïƒ_R)

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

    # Background ROIs â€” stesse del PSG
    gap_px = int(0.1 * r0)
    target_area_mm2 = 1000.0

    def _bg_roi_stats(arr, y0, x0, roi_h, roi_w):
        roi = arr[y0:y0 + roi_h, x0:x0 + roi_w]
        if roi.size > 0:
            return float(np.std(roi)), float(np.mean(roi))
        return 1.0, 0.0

    # Right
    x_start_R = cc + r0 + gap_px
    w_R = max(3, w - gap_px - x_start_R)
    h_R = max(3, int(target_area_mm2 / (w_R * px * py)))
    h_R = min(h_R, h - 2)
    y_start_R = max(0, cr - h_R // 2)
    std_R, mean_R = _bg_roi_stats(arr, y_start_R, x_start_R, h_R, w_R)

    # Left
    x_start_L = gap_px
    w_L = max(3, cc - r0 - gap_px - x_start_L)
    h_L = max(3, int(target_area_mm2 / (w_L * px * py)))
    h_L = min(h_L, h - 2)
    y_start_L = max(0, cr - h_L // 2)
    std_L, mean_L = _bg_roi_stats(arr, y_start_L, x_start_L, h_L, w_L)

    # Up
    y_start_U = gap_px
    w_U_h = max(3, cr - r0 - gap_px - y_start_U)
    h_U_w = max(3, int(target_area_mm2 / (w_U_h * px * py)))
    h_U_w = min(h_U_w, w - 2)
    x_start_U = max(0, cc - h_U_w // 2)
    std_U, mean_U = _bg_roi_stats(arr, y_start_U, x_start_U, w_U_h, h_U_w)

    # Down
    y_start_D = cr + r0 + gap_px
    w_D_h = max(3, h - gap_px - y_start_D)
    h_D_w = max(3, int(target_area_mm2 / (w_D_h * px * py)))
    h_D_w = min(h_D_w, w - 2)
    x_start_D = max(0, cc - h_D_w // 2)
    std_D, mean_D = _bg_roi_stats(arr, y_start_D, x_start_D, w_D_h, h_D_w)

    # SNR con diverse combinazioni di background â€” Eq. (7)
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
        "ufov_radius_px": r_ufov,
        "rois": {
            "right": {"rect": [int(y_start_R), int(x_start_R), int(h_R), int(w_R)], "std": round(std_R, 4), "mean": round(mean_R, 2)},
            "left": {"rect": [int(y_start_L), int(x_start_L), int(h_L), int(w_L)], "std": round(std_L, 4), "mean": round(mean_L, 2)},
            "up": {"rect": [int(y_start_U), int(x_start_U), int(w_U_h), int(h_U_w)], "std": round(std_U, 4), "mean": round(mean_U, 2)},
            "down": {"rect": [int(y_start_D), int(x_start_D), int(w_D_h), int(h_D_w)], "std": round(std_D, 4), "mean": round(mean_D, 2)},
        },
        "passed": True,  # SNR non ha un limite fisso ACR, dipende dal campo
    }


def calculate_snr_two_images(arr1: np.ndarray, arr2: np.ndarray,
                             pixel_spacing_mm: float = 1.0,
                             center_rc=None, radius_px=None):
    """
    Calcola SNR con metodo due immagini (NEMA MS 1-2008, subtraction method).

    Ref: Eq. (6) del paper:
        SNR = 1.41 Ã— S / Ïƒ_D

    dove S Ã¨ il segnale medio nella UFOV e Ïƒ_D Ã¨ la std dell'immagine
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

    # SNR â€” Eq. (6)
    snr = 1.41 * signal_mean / max(sigma_d, 1e-6)

    return {
        "snr": round(snr, 2),
        "signal_1": round(s1, 2),
        "signal_2": round(s2, 2),
        "signal_mean": round(signal_mean, 2),
        "sigma_diff": round(sigma_d, 4),
        "diff_mean_abs": round(float(np.mean(np.abs(diff[ufov_mask]))), 4),
        "method": "two_image_subtraction",
        "center_rc": (cr, cc),
        "radius_px": r0,
        "passed": True,
    }


# ==============================================================================
# SNRU â€” Signal-to-Noise Ratio Uniformity
# ==============================================================================

def calculate_snru(arr: np.ndarray, pixel_spacing_mm: float = 1.0,
                   center_rc=None, radius_px=None):
    """
    Calcola la SNR Uniformity (SNRU) secondo il metodo di Lerski/Ihalainen.

    Ref: Eq. (14), (15) del paper:
        SNR_i = 2 Ã— 0.665 Ã— S_i / (Ïƒ_L + Ïƒ_R),  i = 1,...,5
        SNRU = 100 Ã— Ïƒ_SNR / mean(SNR)

    Usa 5 ROI circolari (~1 cm raggio):
      - 1 al centro
      - 4 a distanza R0/2 (posizioni 3, 6, 9, 12 o'clock)

    Limiti: â‰¤ 5% (achievable), â‰¤ 10% (max acceptable)

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

    # SNR per ogni ROI â€” Eq. (14)
    snr_values = []
    noise_denom = max(std_L + std_R, 1e-6)
    for roi in roi_results:
        snr_i = 2.0 * 0.665 * roi["mean_val"] / noise_denom
        roi["snr"] = round(snr_i, 2)
        snr_values.append(snr_i)

    # SNRU â€” Eq. (15)
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
# GRID DOT DETECTION for geometric distortion
# ==============================================================================


def _detect_grid_dots(arr, cr, cc, r0, pixel_spacing_mm, nominal_diameter_mm):
    """Detect the square insert and its 9 reference points.

    Finds the square insert by detecting its edges in the annular region
    between the insert and the phantom wall. Then computes 9 reference
    points (4 corners, 4 midpoints, 1 center) and measures segment ratios.

    Returns:
        (dots_list, distortion_dict)
    """
    from scipy.ndimage import uniform_filter, sobel

    h, w = arr.shape
    px = float(pixel_spacing_mm)

    # Expected insert size
    insert_side_mm = 148.0 if nominal_diameter_mm >= 180 else 120.0
    insert_half_mm = insert_side_mm / 2.0
    insert_half_px = insert_half_mm / px

    # Strategy: find the 4 edges of the square by scanning profiles
    # from center outward in 4 cardinal directions (up, down, left, right)
    # The edge is where signal drops sharply (water -> acrylic border of insert)

    def _find_edge_from_center(arr, cr, cc, direction, max_dist_px):
        """Scan from center outward to find the insert edge."""
        # direction: 0=up(-row), 1=right(+col), 2=down(+row), 3=left(-col)
        dr = [-1, 0, 1, 0][direction]
        dc = [0, 1, 0, -1][direction]

        # Sample profile from center outward
        positions = []
        values = []
        for d in range(5, int(max_dist_px)):
            r = int(round(cr + d * dr))
            c = int(round(cc + d * dc))
            if r < 0 or r >= h or c < 0 or c >= w:
                break
            positions.append(d)
            values.append(float(arr[r, c]))

        if len(values) < 20:
            return insert_half_px  # fallback to nominal

        vals = np.array(values)
        # Smooth
        k = max(3, len(vals) // 20)
        if k % 2 == 0:
            k += 1
        smoothed = np.convolve(vals, np.ones(k)/k, mode='same')

        # Find the steepest drop (derivative most negative) in the outer region
        # The insert edge should be around 50-75% of the phantom radius
        deriv = np.diff(smoothed)
        search_start = int(0.4 * insert_half_px)
        search_end = min(len(deriv), int(1.0 * insert_half_px))

        if search_end <= search_start:
            return insert_half_px

        region = deriv[search_start:search_end]
        if len(region) < 3:
            return insert_half_px

        # Find steepest negative gradient (signal dropping = entering dark edge)
        min_idx = int(np.argmin(region))
        edge_pos = float(positions[search_start + min_idx])
        return edge_pos

    # Find 4 edge distances from center
    max_search = r0 * 0.95
    edge_up = _find_edge_from_center(arr, cr, cc, 0, max_search)
    edge_right = _find_edge_from_center(arr, cr, cc, 1, max_search)
    edge_down = _find_edge_from_center(arr, cr, cc, 2, max_search)
    edge_left = _find_edge_from_center(arr, cr, cc, 3, max_search)

    # The 4 corners and 4 midpoints from the detected edges
    top = cr - edge_up
    bottom = cr + edge_down
    left = cc - edge_left
    right = cc + edge_right

    mid_r = (top + bottom) / 2.0
    mid_c = (left + right) / 2.0

    # 9 points: corners, midpoints, center
    detected_points = [
        [round(top, 1), round(left, 1)],       # 0: top-left
        [round(top, 1), round(mid_c, 1)],      # 1: top-center
        [round(top, 1), round(right, 1)],      # 2: top-right
        [round(mid_r, 1), round(left, 1)],     # 3: mid-left
        [round(mid_r, 1), round(mid_c, 1)],    # 4: center
        [round(mid_r, 1), round(right, 1)],    # 5: mid-right
        [round(bottom, 1), round(left, 1)],    # 6: bot-left
        [round(bottom, 1), round(mid_c, 1)],   # 7: bot-center
        [round(bottom, 1), round(right, 1)],   # 8: bot-right
    ]

    # Measured dimensions
    width_px = right - left
    height_px = bottom - top
    width_mm = width_px * px
    height_mm = height_px * px
    nominal_half_w = width_mm / 2.0
    nominal_half_h = height_mm / 2.0
    nominal_half_side_mm = insert_side_mm / 2.0

    # Compute segment ratios (measured / nominal)
    segments = [
        (0, 1, "H", "top-L"),    (1, 2, "H", "top-R"),
        (3, 4, "H", "mid-L"),    (4, 5, "H", "mid-R"),
        (6, 7, "H", "bot-L"),    (7, 8, "H", "bot-R"),
        (0, 3, "V", "left-T"),   (1, 4, "V", "ctr-T"),
        (2, 5, "V", "right-T"),  (3, 6, "V", "left-B"),
        (4, 7, "V", "ctr-B"),    (5, 8, "V", "right-B"),
    ]

    segment_results = []
    for ia, ib, direction, label in segments:
        pa = detected_points[ia]
        pb = detected_points[ib]
        dist_px = np.sqrt((pa[0] - pb[0])**2 + (pa[1] - pb[1])**2)
        dist_mm = dist_px * px
        ratio = dist_mm / nominal_half_side_mm
        error_mm = dist_mm - nominal_half_side_mm
        segment_results.append({
            "label": label, "direction": direction,
            "measured_mm": round(dist_mm, 2),
            "nominal_mm": round(nominal_half_side_mm, 2),
            "ratio": round(ratio, 4),
            "error_mm": round(error_mm, 2),
        })

    ratios = [s["ratio"] for s in segment_results]
    errors = [s["error_mm"] for s in segment_results]
    mean_ratio = float(np.mean(ratios))
    max_error = float(np.max(np.abs(errors)))

    distortion_dict = {
        "n_dots_detected": 9,
        "insert_side_mm": insert_side_mm,
        "measured_width_mm": round(width_mm, 2),
        "measured_height_mm": round(height_mm, 2),
        "nominal_segment_mm": round(nominal_half_side_mm, 1),
        "segments": segment_results,
        "mean_ratio": round(mean_ratio, 4),
        "max_abs_error_mm": round(max_error, 2),
        "median_spacing_mm": round(nominal_half_side_mm * mean_ratio, 2),
        "spacing_std_mm": round(float(np.std([s["measured_mm"] for s in segment_results])), 2),
        "max_spacing_deviation_mm": round(max_error, 2),
        "insert_roi_rc": [
            int(top), int(left), int(bottom - top), int(right - left)
        ],
    }

    return detected_points, distortion_dict


# ==============================================================================
# GEOMETRIC ACCURACY â€” Accuratezza geometrica
# ==============================================================================

def calculate_geometric_accuracy(arr: np.ndarray, pixel_spacing_mm: float = 1.0,
                                 center_rc=None, radius_px=None,
                                 nominal_diameter_mm: float = None,
                                 h_line_row=None, v_line_col=None,
                                 force_outer_edges: bool = False):
    """
    Misura l'accuratezza geometrica del phantom ACR.

    Il diametro interno del phantom ACR e' 190 mm (Large) o 165 mm (Medium).
    Se nominal_diameter_mm non e' specificato, viene rilevato automaticamente
    dalla dimensione misurata del phantom.

    Limite ACR: <= +/-2 mm dalla dimensione nominale.
    """
    h, w = arr.shape
    px = float(pixel_spacing_mm)

    if center_rc is None or radius_px is None:
        cr, cc, r0 = find_phantom_circle(arr, pixel_spacing_mm)
    else:
        cr, cc = center_rc
        r0 = radius_px

    # Threshold al 50% del massimo per edge detection
    cr = int(np.clip(round(cr), 0, h - 1))
    cc = int(np.clip(round(cc), 0, w - 1))
    r0 = float(r0)

    # Auto-detect nominal diameter if not specified
    # ACR Large phantom: 190 mm internal diameter
    # ACR Medium phantom: 165 mm internal diameter
    if nominal_diameter_mm is None:
        approx_diameter_mm = 2.0 * r0 * px
        if approx_diameter_mm < 177.5:  # midpoint between 165 and 190
            nominal_diameter_mm = 165.0
        else:
            nominal_diameter_mm = 190.0
    nominal_diameter_mm = float(nominal_diameter_mm)

    rr_grid, cc_grid = np.ogrid[:h, :w]
    dist = np.sqrt((rr_grid - cr) ** 2 + (cc_grid - cc) ** 2)
    phantom_mask = dist <= max(4.0, 0.92 * r0)
    central_mask = (
        (np.abs(rr_grid - cr) <= max(3.0, 0.32 * r0)) &
        (np.abs(cc_grid - cc) <= max(3.0, 0.32 * r0))
    )
    ring_mask = (dist >= max(4.0, 0.48 * r0)) & (dist <= max(6.0, 0.86 * r0))
    phantom_vals = arr[phantom_mask]
    ring_vals = arr[ring_mask]
    central_vals = arr[central_mask]
    water_level = float(np.median(ring_vals)) if ring_vals.size else float(np.percentile(arr, 85))
    background_level = float(np.percentile(arr[~phantom_mask], 70)) if np.any(~phantom_mask) else float(np.percentile(arr, 5))
    outer_threshold = background_level + 0.5 * (water_level - background_level)
    central_level = float(np.median(central_vals)) if central_vals.size else water_level
    central_dark_ratio = central_level / max(water_level, 1e-6)
    dark_threshold = background_level + 0.35 * (water_level - background_level)
    central_dark_fraction = float(np.mean(central_vals <= dark_threshold)) if central_vals.size else 0.0
    use_outer_edges = bool(force_outer_edges or central_dark_ratio < 0.80 or central_dark_fraction > 0.20)

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

    def _outer_edge_crossings(x, vals, threshold):
        inside = vals >= threshold
        if np.count_nonzero(inside) < 2:
            return None
        mid = len(x) // 2

        left_candidates = np.where(inside[:mid])[0]
        right_candidates = np.where(inside[mid:])[0] + mid
        if len(left_candidates) == 0 or len(right_candidates) == 0:
            return _edge_crossings(x, vals, inside, threshold)

        left_i = int(left_candidates[0])
        right_i = int(right_candidates[-1])

        def interp(i_out, i_in):
            x0, x1 = float(x[i_out]), float(x[i_in])
            y0, y1 = float(vals[i_out]), float(vals[i_in])
            if abs(y1 - y0) < 1e-9:
                return x1
            return x0 + (threshold - y0) * (x1 - x0) / (y1 - y0)

        left = interp(max(left_i - 1, 0), left_i)
        right = interp(min(right_i + 1, len(x) - 1), right_i)
        if right <= left:
            return None
        return left, right

    def _find_steepest_edges(x, vals, water_signal):
        """Find phantom inner wall edges using the steepest signal gradient.

        The ACR phantom profile has these transitions (outside to inside):
        - Air→Acrylic: moderate gradient (if acrylic has signal)
        - Acrylic→Water: STEEP gradient (this is the inner wall we want)

        We find the maximum positive derivative on the left half (steepest rise
        = water starts) and maximum negative derivative on the right half
        (steepest fall = water ends). Then interpolate to 50% of water level
        at that location.
        """
        n = len(x)
        if n < 20:
            return None
        mid = n // 2

        # Smooth for robust derivative
        k = max(3, n // 60)
        if k % 2 == 0:
            k += 1
        from numpy import convolve
        vals_s = convolve(vals, np.ones(k) / k, mode='same')

        # Compute derivative
        deriv = np.gradient(vals_s)

        # Left half: find the steepest POSITIVE slope (signal rising into water)
        # Look only in the region where we expect the wall (roughly 15-50% from edge)
        left_start = max(0, int(0.10 * mid))
        left_end = int(0.65 * mid)  # Don't look past ~65% toward center (avoids insert edges)
        left_region = deriv[left_start:left_end]
        if len(left_region) < 3:
            return None
        left_peak_rel = int(np.argmax(left_region))
        left_peak_i = left_start + left_peak_rel
        if deriv[left_peak_i] <= 0:
            return None

        # Right half: find the steepest NEGATIVE slope (signal falling from water)
        right_start = mid + int(0.35 * mid)  # Don't look before 35% from center
        right_end = min(n, n - int(0.10 * mid))
        right_region = deriv[right_start:right_end]
        if len(right_region) < 3:
            return None
        right_peak_rel = int(np.argmin(right_region))
        right_peak_i = right_start + right_peak_rel
        if deriv[right_peak_i] >= 0:
            return None

        # The edge is at the point of steepest gradient.
        # Interpolate to find where signal crosses 50% of water level near this point.
        threshold = 0.50 * water_signal
        search = max(3, n // 30)

        # Left edge: find threshold crossing near the gradient peak
        left_edge = None
        for i in range(max(0, left_peak_i - search), min(left_end, left_peak_i + search)):
            if i + 1 >= n:
                break
            if vals_s[i] < threshold <= vals_s[i + 1]:
                x0, x1 = float(x[i]), float(x[i + 1])
                y0, y1 = float(vals_s[i]), float(vals_s[i + 1])
                if abs(y1 - y0) > 1e-9:
                    left_edge = x0 + (threshold - y0) * (x1 - x0) / (y1 - y0)
                else:
                    left_edge = (x0 + x1) / 2.0
                break
        if left_edge is None:
            left_edge = float(x[left_peak_i])

        # Right edge: find threshold crossing near the gradient peak
        right_edge = None
        for i in range(min(n - 2, right_peak_i + search), max(right_start, right_peak_i - search), -1):
            if vals_s[i] >= threshold > vals_s[i + 1]:
                x0, x1 = float(x[i]), float(x[i + 1])
                y0, y1 = float(vals_s[i]), float(vals_s[i + 1])
                if abs(y1 - y0) > 1e-9:
                    right_edge = x0 + (threshold - y0) * (x1 - x0) / (y1 - y0)
                else:
                    right_edge = (x0 + x1) / 2.0
                break
        if right_edge is None:
            right_edge = float(x[right_peak_i])

        if right_edge <= left_edge:
            return None

        # Validate: result should be reasonable (within 15% of expected)
        measured_mm = (right_edge - left_edge) * px
        if nominal_diameter_mm and (measured_mm < 0.85 * nominal_diameter_mm or measured_mm > 1.15 * nominal_diameter_mm):
            return None

        return left_edge, right_edge

    def _inner_water_edge_crossings(x, vals, threshold, water_signal):
        """Find the inner water boundary edges for measuring internal diameter.

        The ACR phantom profile goes (outside-in):
        air (low) -> acrylic wall (low-to-intermediate) -> water (high) -> [possible dark insert] -> water (high) -> acrylic -> air

        We measure the internal diameter (190 mm for large phantom) by finding
        where the water signal starts/ends. From the outside inward:
        - Left edge: first point where signal rises above threshold (water starts)
        - Right edge: last point where signal falls below threshold (water ends)

        Using threshold = 50% of water_signal ensures acrylic (low signal) is
        excluded while water is captured. This gives the internal water diameter.
        """
        n = len(x)
        above = vals >= threshold

        if np.count_nonzero(above) < 2:
            return None

        # Find first and last positions above threshold
        # These represent the outer edges of the water column
        indices_above = np.where(above)[0]
        left_i = int(indices_above[0])
        right_i = int(indices_above[-1])

        # Interpolate exact crossing positions
        def interp_left(i):
            if i <= 0:
                return float(x[i])
            x0, x1 = float(x[i - 1]), float(x[i])
            y0, y1 = float(vals[i - 1]), float(vals[i])
            if abs(y1 - y0) < 1e-9:
                return x1
            return x0 + (threshold - y0) * (x1 - x0) / (y1 - y0)

        def interp_right(i):
            if i >= n - 1:
                return float(x[i])
            x0, x1 = float(x[i]), float(x[i + 1])
            y0, y1 = float(vals[i]), float(vals[i + 1])
            if abs(y1 - y0) < 1e-9:
                return x0
            return x0 + (threshold - y0) * (x1 - x0) / (y1 - y0)

        left = interp_left(left_i)
        right = interp_right(right_i)

        if right <= left:
            return None

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

        # The ACR phantom internal diameter is 190 mm (water-filled).
        # We measure the INNER water boundary by using a threshold at 50%
        # between water signal and background, but we detect the INNERMOST
        # edges (last rise on the left, first fall on the right) to avoid
        # including the acrylic shell.
        signal = water_level
        background = background_level

        if use_outer_edges:
            # For slices with dark insert: find the TRUE inner water boundary.
            # Use steepest gradient to find the water/acrylic transition.
            threshold = 0.75 * signal
            edges = _find_steepest_edges(x, vals, signal)
            if edges is None:
                # Fallback: use threshold-based detection
                edges = _inner_water_edge_crossings(x, vals, threshold, signal)
                # Validate fallback: if result is unreasonable, return None
                if edges is not None:
                    fallback_mm = (edges[1] - edges[0]) * px
                    if nominal_diameter_mm and (fallback_mm < 0.85 * nominal_diameter_mm or fallback_mm > 1.15 * nominal_diameter_mm):
                        edges = None
        else:
            threshold = 0.75 * signal
            edges = _find_steepest_edges(x, vals, signal)
            if edges is None:
                edges = _inner_water_edge_crossings(x, vals, threshold, signal)
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
    diameter_45_mm = d45_result["diameter_mm"] if d45_result else 0.0
    diameter_135_mm = d135_result["diameter_mm"] if d135_result else 0.0

    # Errori
    error_h_mm = diameter_h_mm - nominal_diameter_mm
    error_v_mm = diameter_v_mm - nominal_diameter_mm
    error_45_mm = diameter_45_mm - nominal_diameter_mm
    error_135_mm = diameter_135_mm - nominal_diameter_mm

    # Limite ACR: Large phantom ±3.0 mm, Medium phantom ±2.0 mm (Table 3)
    limit_mm = 3.0 if nominal_diameter_mm >= 180 else 2.0
    passed_h = abs(error_h_mm) <= limit_mm
    passed_v = abs(error_v_mm) <= limit_mm
    passed_45 = abs(error_45_mm) <= limit_mm if d45_result else True
    passed_135 = abs(error_135_mm) <= limit_mm if d135_result else True
    passed = passed_h and passed_v and passed_45 and passed_135

    # =========================================================================
    # Grid distortion detection (high-contrast dots in the square insert)
    # The ACR phantom slice 5 has a grid of holes that appear as bright dots
    # on a dark background. Detect these dots and measure their spacing to
    # quantify geometric distortion.
    # =========================================================================
    grid_dots = []
    grid_distortion = None
    try:
        grid_dots, grid_distortion = _detect_grid_dots(
            arr, cr, cc, r0, px, nominal_diameter_mm
        )
    except Exception as _grid_err:
        import traceback as _tb
        _tb.print_exc()

    return {
        "diameter_h_mm": round(diameter_h_mm, 2),
        "diameter_v_mm": round(diameter_v_mm, 2),
        "diameter_45_mm": round(diameter_45_mm, 2),
        "diameter_135_mm": round(diameter_135_mm, 2),
        "error_h_mm": round(error_h_mm, 2),
        "error_v_mm": round(error_v_mm, 2),
        "error_45_mm": round(error_45_mm, 2),
        "error_135_mm": round(error_135_mm, 2),
        "nominal_diameter_mm": nominal_diameter_mm,
        "passed_h": passed_h,
        "passed_v": passed_v,
        "passed_45": passed_45,
        "passed_135": passed_135,
        "passed": passed,
        "limit_mm": limit_mm,
        "center_rc": (cr, cc),
        "radius_px": r0,
        "geometric_slice_mode": "outer_phantom_edges" if use_outer_edges else "center_profile_edges",
        "central_dark_ratio": round(float(central_dark_ratio), 3),
        "central_dark_fraction": round(float(central_dark_fraction), 3),
        "outer_threshold": round(float(outer_threshold), 3),
        "geometry_reference": "ACR axial slice 5 phantom diameter: Large 190 mm, Medium 165 mm",
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
        "grid_dots": grid_dots,
        "grid_distortion": grid_distortion,
    }


# ==============================================================================
# SLICE THICKNESS ACCURACY â€” Accuratezza spessore di strato
# ==============================================================================

def calculate_slice_thickness(arr: np.ndarray, pixel_spacing_mm: float = 1.0,
                              center_rc=None, radius_px=None,
                              nominal_thickness_mm: float = 5.0,
                              top_ramp_rect=None, bot_ramp_rect=None):
    """
    Misura l'accuratezza dello spessore di strato usando le rampe incrociate
    nella slice #1 del phantom ACR.

    Il phantom ACR contiene due rampe incrociate a 45Â° nella slice #1.
    Lo spessore si calcola dalla lunghezza del segnale delle rampe:

        thickness = 0.2 Ã— (top_length Ã— bottom_length) / (top_length + bottom_length)

    dove 0.2 Ã¨ il fattore geometrico per rampe a 45Â° con angolo noto,
    e le lunghezze sono misurate al FWHM del profilo di segnale lungo le rampe.

    Limite ACR: 5 mm Â± 0.7 mm

    Args:
        arr: immagine 2D (slice #1)
        pixel_spacing_mm: dimensione pixel
        nominal_thickness_mm: spessore nominale (5 mm)

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

    # Le rampe incrociate sono nella regione centrale della slice #1
    # Estraiamo un profilo orizzontale nella zona delle rampe
    # Le rampe sono tipicamente Â±10-15 pixel sopra e sotto il centro

    # Profilo della rampa superiore (sopra il centro, ~10 px)
    cr = int(np.clip(round(cr), 0, h - 1))
    cc = int(np.clip(round(cc), 0, w - 1))
    r0 = float(r0)

    def _clamp_rect(rect):
        y, x, rh, rw = [int(round(v)) for v in rect]
        y = max(0, min(h - 1, y))
        x = max(0, min(w - 1, x))
        rh = max(1, min(h - y, rh))
        rw = max(1, min(w - x, rw))
        return [y, x, rh, rw]

    def _default_rects():
        ramp_h = max(2, int(round(3.0 / max(px, 1e-6))))
        ramp_w = max(24, int(round(78.0 / max(px, 1e-6))))
        ramp_w = min(ramp_w, max(24, int(round(0.85 * r0))))
        x0 = cc - ramp_w / 2

        # The crossed ramps sit inside the dark horizontal slice-thickness
        # insert. Find that insert first; fixed offsets easily land in the
        # phantom fluid and inflate the measured lengths.
        search_y0 = int(max(0, round(cr - 0.35 * r0)))
        search_y1 = int(min(h, round(cr + 0.15 * r0)))
        search_x0 = int(max(0, round(cc - 0.65 * r0)))
        search_x1 = int(min(w, round(cc + 0.65 * r0)))
        slot_y0 = slot_y1 = None
        if search_y1 > search_y0 + 3 and search_x1 > search_x0 + 8:
            band = arr[search_y0:search_y1, search_x0:search_x1].astype(np.float64)
            row_means = np.mean(band, axis=1)
            dark_cut = min(
                float(np.percentile(row_means, 25)),
                float(np.median(row_means) * 0.45),
            )
            dark = row_means <= dark_cut
            runs = []
            start = None
            for i, is_dark in enumerate(dark):
                if is_dark and start is None:
                    start = i
                elif not is_dark and start is not None:
                    runs.append((start, i - 1))
                    start = None
            if start is not None:
                runs.append((start, len(dark) - 1))
            if runs:
                target = len(dark) / 2.0
                runs.sort(key=lambda run: (-(run[1] - run[0] + 1), abs(((run[0] + run[1]) / 2.0) - target)))
                slot_y0 = search_y0 + runs[0][0]
                slot_y1 = search_y0 + runs[0][1] + 1

        if slot_y0 is not None and slot_y1 is not None and slot_y1 - slot_y0 >= 2 * ramp_h:
            slot_h = slot_y1 - slot_y0
            inset = max(1, int(round(0.18 * slot_h)))
            top_y = slot_y0 + inset
            bot_y = slot_y1 - ramp_h - inset
            if bot_y <= top_y:
                top_y = slot_y0
                bot_y = slot_y1 - ramp_h
            return (
                _clamp_rect([top_y, x0, ramp_h, ramp_w]),
                _clamp_rect([bot_y, x0, ramp_h, ramp_w]),
            )

        offset = max(3, int(round(4.0 / max(px, 1e-6))))
        return (
            _clamp_rect([cr - offset - ramp_h, x0, ramp_h, ramp_w]),
            _clamp_rect([cr + offset, x0, ramp_h, ramp_w]),
        )

    default_top, default_bot = _default_rects()
    top_ramp_rect = _clamp_rect(top_ramp_rect) if top_ramp_rect else default_top
    bot_ramp_rect = _clamp_rect(bot_ramp_rect) if bot_ramp_rect else default_bot

    def _profile_from_rect(rect):
        y, x, rh, rw = rect
        roi = arr[y:y + rh, x:x + rw]
        profile = np.mean(roi, axis=0) if roi.size else np.array([], dtype=float)
        return roi, profile

    top_roi, top_profile = _profile_from_rect(top_ramp_rect)
    bot_roi, bot_profile = _profile_from_rect(bot_ramp_rect)

    top_mean = float(np.mean(top_roi)) if top_roi.size else 0.0
    bot_mean = float(np.mean(bot_roi)) if bot_roi.size else 0.0
    avg_ramp_signal = (top_mean + bot_mean) / 2.0 if (top_mean > 0 or bot_mean > 0) else 0.0
    ramp_threshold = 0.5 * avg_ramp_signal

    def _smooth_profile(profile):
        profile = np.asarray(profile, dtype=np.float64)
        if profile.size < 5:
            return profile
        kernel = np.array([1, 2, 3, 2, 1], dtype=np.float64)
        kernel /= kernel.sum()
        return np.convolve(profile, kernel, mode="same")

    def _measure_length(profile, threshold):
        profile = np.asarray(profile, dtype=np.float64)
        if profile.size == 0:
            return 0.0, None, None, np.array([], dtype=float), threshold
        # ACR asks for a visual threshold measurement. Use the raw profile for
        # the threshold crossing; smoothing can shift ragged ramp ends.
        smoothed = profile.copy()
        use_threshold = threshold
        if use_threshold <= 0 or float(np.max(smoothed)) < use_threshold:
            bg = float(np.percentile(smoothed, 10))
            peak = float(np.percentile(smoothed, 95))
            use_threshold = bg + 0.5 * (peak - bg)
        above = np.where(smoothed >= use_threshold)[0]
        if len(above) < 2:
            return 0.0, None, None, smoothed, use_threshold

        def _cross(edge_idx, neighbor_idx):
            x0, x1 = float(neighbor_idx), float(edge_idx)
            y0, y1 = float(smoothed[neighbor_idx]), float(smoothed[edge_idx])
            if abs(y1 - y0) < 1e-9:
                return x1
            return x0 + (use_threshold - y0) * (x1 - x0) / (y1 - y0)

        left_i = int(above[0])
        right_i = int(above[-1])
        left = _cross(left_i, left_i - 1) if left_i > 0 else float(left_i)
        right = _cross(right_i, right_i + 1) if right_i < len(smoothed) - 1 else float(right_i)
        if right <= left:
            left, right = float(left_i), float(right_i)
        return float((right - left) * px), float(left), float(right), smoothed, use_threshold

    top_length_mm, top_left, top_right, top_smooth, top_threshold = _measure_length(top_profile, ramp_threshold)
    bot_length_mm, bot_left, bot_right, bot_smooth, bot_threshold = _measure_length(bot_profile, ramp_threshold)

    def _pack_profile(rect, profile, smooth, left, right, threshold):
        y, x, rh, rw = rect
        return {
            "rect": rect,
            "x_mm": [round(float((i - (rw - 1) / 2) * px), 3) for i in range(rw)],
            "values": [round(float(v), 3) for v in np.asarray(profile, dtype=float)],
            "smoothed": [round(float(v), 3) for v in np.asarray(smooth, dtype=float)],
            "threshold": round(float(threshold), 3),
            "left_px": None if left is None else round(float(left), 3),
            "right_px": None if right is None else round(float(right), 3),
            "left_rc": None if left is None else [round(float(y + rh / 2), 2), round(float(x + left), 2)],
            "right_rc": None if right is None else [round(float(y + rh / 2), 2), round(float(x + right), 2)],
            "mean_signal": round(float(np.mean(arr[y:y + rh, x:x + rw])), 3),
        }

    # Spessore: formula ACR per rampe incrociate a 45Â°
    # thickness = 0.2 Ã— (L_top Ã— L_bot) / (L_top + L_bot)
    if (top_length_mm + bot_length_mm) > 0:
        measured_thickness_mm = 0.2 * (top_length_mm * bot_length_mm) / (top_length_mm + bot_length_mm)
    else:
        measured_thickness_mm = 0.0

    # Errore
    error_mm = measured_thickness_mm - nominal_thickness_mm

    # Limite: Â±0.7 mm
    limit_mm = 0.7
    passed = abs(error_mm) <= limit_mm

    return {
        "measured_thickness_mm": round(measured_thickness_mm, 2),
        "nominal_thickness_mm": nominal_thickness_mm,
        "error_mm": round(error_mm, 2),
        "top_ramp_length_mm": round(top_length_mm, 2),
        "bottom_ramp_length_mm": round(bot_length_mm, 2),
        "slice_thickness_formula": "0.2 * top * bottom / (top + bottom)",
        "slice_thickness_formula_factor": 0.2,
        "passed": passed,
        "limit_mm": limit_mm,
        "center_rc": (cr, cc),
        "radius_px": r0,
        "top_ramp_rect": top_ramp_rect,
        "bot_ramp_rect": bot_ramp_rect,
        "ramp_signal_mean": round(float(avg_ramp_signal), 3),
        "ramp_threshold": round(float(ramp_threshold), 3),
        "slice_thickness_profiles": {
            "top": _pack_profile(top_ramp_rect, top_profile, top_smooth, top_left, top_right, top_threshold),
            "bottom": _pack_profile(bot_ramp_rect, bot_profile, bot_smooth, bot_left, bot_right, bot_threshold),
        },
    }


# ==============================================================================
# SLICE POSITION ACCURACY â€” Accuratezza posizione strato
# ==============================================================================

def calculate_slice_position(arr: np.ndarray, pixel_spacing_mm: float = 1.0,
                             center_rc=None, radius_px=None):
    """
    Misura l'accuratezza della posizione dello strato usando i wedge
    (cunei incrociati) nella slice #1 e #11 del phantom ACR.

    I due cunei producono due barre di segnale. La differenza di lunghezza
    tra le due barre indica l'offset della posizione dello strato.

    Slice position error = (bar_length_1 - bar_length_2) / 2 Ã— tan(angolo)

    Per il phantom ACR con cunei a 45Â°:
        offset_mm = (L1 - L2) Ã— pixel_spacing / 2

    Limite ACR: â‰¤ Â±5 mm (â‰¤ Â±4 mm raccomandato)

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
    # I cunei sono tipicamente a Â±20-30 mm dal centro, nella parte alta

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
    # Per cunei a 45Â°: offset = (L1 - L2) / 2
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
# HIGH-CONTRAST SPATIAL RESOLUTION â€” Risoluzione spaziale
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

    Limite ACR: â‰¤ 1 mm (i fori da 1 mm devono essere risolti)

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

    def _clamp_rect(rect):
        y, x, rh, rw = [int(round(v)) for v in rect]
        y = max(0, min(h - 1, y))
        x = max(0, min(w - 1, x))
        rh = max(1, min(h - y, rh))
        rw = max(1, min(w - x, rw))
        return [y, x, rh, rw]

    def _runs(mask, min_len=1):
        runs = []
        start = None
        for i, val in enumerate(mask):
            if val and start is None:
                start = i
            elif not val and start is not None:
                if i - start >= min_len:
                    runs.append((start, i))
                start = None
        if start is not None and len(mask) - start >= min_len:
            runs.append((start, len(mask)))
        return runs

    def _default_grid_rects():
        side = max(12, int(round(24.0 / max(px, 1e-6))))
        side = min(side, max(12, int(round(0.24 * r0))))
        base_y = cr + 0.30 * r0
        xs = [cc - 0.27 * r0, cc, cc + 0.27 * r0]
        return [_clamp_rect([base_y - side / 2, x - side / 2, side, side]) for x in xs]

    def _auto_grid_rects_from_insert():
        y0 = int(max(0, round(cr + 0.08 * r0)))
        y1 = int(min(h, round(cr + 0.62 * r0)))
        x0 = int(max(0, round(cc - 0.65 * r0)))
        x1 = int(min(w, round(cc + 0.65 * r0)))
        search = arr[y0:y1, x0:x1]
        if search.size < 100:
            return None

        dark_level = float(np.percentile(search, 28))
        bright_level = float(np.percentile(search, 82))
        dark_threshold = dark_level + 0.35 * (bright_level - dark_level)
        dark = search <= dark_threshold

        row_fraction = dark.mean(axis=1)
        row_runs = _runs(row_fraction > 0.38, min_len=max(6, int(8.0 / max(px, 1e-6))))
        if not row_runs:
            return None
        row_start, row_end = max(row_runs, key=lambda run: (run[1] - run[0], run[0]))

        insert_dark = dark[row_start:row_end, :]
        col_fraction = insert_dark.mean(axis=0)
        col_runs = _runs(col_fraction > 0.28, min_len=max(18, int(50.0 / max(px, 1e-6))))
        if not col_runs:
            return None
        col_start, col_end = max(col_runs, key=lambda run: run[1] - run[0])

        iy0, iy1 = y0 + row_start, y0 + row_end
        ix0, ix1 = x0 + col_start, x0 + col_end
        ih, iw = iy1 - iy0, ix1 - ix0
        if ih < 12 or iw < 60:
            return None

        side = max(12, int(round(24.0 / max(px, 1e-6))))
        side = min(side, max(12, int(round(0.50 * ih))), max(12, int(round(0.20 * iw))))
        target_y = iy0 + 0.38 * ih
        target_fracs = [0.27, 0.50, 0.73]
        return [_clamp_rect([target_y - side / 2, ix0 + frac * iw - side / 2, side, side])
                for frac in target_fracs]

    if grid_rects and len(grid_rects) >= 3:
        grid_rects = [_clamp_rect(rect) for rect in grid_rects[:3]]
    else:
        grid_rects = _auto_grid_rects_from_insert() or _default_grid_rects()

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

    def _smooth_profile(profile):
        profile = np.asarray(profile, dtype=np.float64)
        if profile.size < 5:
            return profile
        kernel = np.array([1, 2, 3, 2, 1], dtype=np.float64)
        kernel /= kernel.sum()
        return np.convolve(profile, kernel, mode="same")

    def _detect_mip_peaks(profile, target_mm):
        profile = np.asarray(profile, dtype=np.float64)
        if profile.size < 3:
            return [], 0.0, profile
        smoothed = _smooth_profile(profile)
        low = float(np.percentile(profile, 15))
        high = float(np.percentile(profile, 95))
        dynamic = max(1e-6, high - low)
        threshold = low + 0.30 * dynamic
        min_prom = 0.06 * dynamic
        min_distance = max(1, int(round(1.25 * target_mm / max(px, 1e-6))))

        candidates = []
        if len(profile) >= 2 and profile[0] >= threshold and profile[0] >= profile[1]:
            candidates.append({
                "index": 0,
                "value": float(profile[0]),
                "smoothed": float(smoothed[0]),
                "prominence": float(profile[0] - profile[1]),
            })
        for i in range(1, len(profile) - 1):
            if profile[i] < threshold:
                continue
            if profile[i] < profile[i - 1] or profile[i] < profile[i + 1]:
                continue
            left_min = float(np.min(profile[max(0, i - min_distance):i + 1]))
            right_min = float(np.min(profile[i:min(len(profile), i + min_distance + 1)]))
            prominence = float(profile[i] - max(left_min, right_min))
            if prominence >= min_prom:
                candidates.append({
                    "index": int(i),
                    "value": float(profile[i]),
                    "smoothed": float(smoothed[i]),
                    "prominence": prominence,
                })
        last = len(profile) - 1
        if last > 0 and profile[last] >= threshold and profile[last] >= profile[last - 1]:
            candidates.append({
                "index": int(last),
                "value": float(profile[last]),
                "smoothed": float(smoothed[last]),
                "prominence": float(profile[last] - profile[last - 1]),
            })

        selected = []
        for peak in sorted(candidates, key=lambda p: p["value"], reverse=True):
            if all(abs(peak["index"] - old["index"]) >= min_distance for old in selected):
                selected.append(peak)
        selected.sort(key=lambda p: p["index"])
        return selected, float(threshold), smoothed

    def _profile_peak_analysis(profile, target_mm):
        peaks, threshold, smoothed = _detect_mip_peaks(profile, target_mm)
        return {
            "values": [round(float(v), 3) for v in np.asarray(profile, dtype=np.float64)],
            "smoothed": [round(float(v), 3) for v in smoothed],
            "threshold": round(float(threshold), 3),
            "peaks": peaks,
            "count": len(peaks),
            "resolved": len(peaks) >= 4,
        }

    def _line_profile_analysis(region, rect, target_mm):
        y, x, rh, rw = rect
        ul_h = max(4, int(np.ceil(0.64 * rh)))
        ul_w = max(4, int(np.ceil(0.64 * rw)))
        lr_y = max(0, int(np.floor(0.36 * rh)))
        lr_x = max(0, int(np.floor(0.36 * rw)))
        h_region = region[:ul_h, :ul_w]
        v_region = region[lr_y:, lr_x:]

        h_profiles = []
        h_rows = np.linspace(0.18 * max(1, h_region.shape[0] - 1),
                             0.82 * max(1, h_region.shape[0] - 1), 4)
        for row_pos in h_rows:
            row = int(round(row_pos))
            band0 = max(0, row - 1)
            band1 = min(h_region.shape[0], row + 2)
            band = h_region[band0:band1, :]
            if band.size == 0:
                profile = np.array([], dtype=np.float64)
                best_row = row
            else:
                band_maxima = np.max(band, axis=1)
                best = int(np.argmax(band_maxima))
                best_row = band0 + best
                profile = band[best, :]
            analysis = _profile_peak_analysis(profile, target_mm)
            analysis["row"] = int(y + best_row)
            analysis["col_start"] = int(x)
            analysis["col_end"] = int(x + max(0, h_region.shape[1] - 1))
            h_profiles.append(analysis)

        v_profiles = []
        v_cols = np.linspace(0.18 * max(1, v_region.shape[1] - 1),
                             0.82 * max(1, v_region.shape[1] - 1), 4)
        for col_pos in v_cols:
            col = int(round(col_pos))
            band0 = max(0, col - 1)
            band1 = min(v_region.shape[1], col + 2)
            band = v_region[:, band0:band1]
            if band.size == 0:
                profile = np.array([], dtype=np.float64)
                best_col = col
            else:
                band_maxima = np.max(band, axis=0)
                best = int(np.argmax(band_maxima))
                best_col = band0 + best
                profile = band[:, best]
            analysis = _profile_peak_analysis(profile, target_mm)
            analysis["col"] = int(x + lr_x + best_col)
            analysis["row_start"] = int(y + lr_y)
            analysis["row_end"] = int(y + lr_y + max(0, v_region.shape[0] - 1))
            v_profiles.append(analysis)

        best_h = max((p["count"] for p in h_profiles), default=0)
        best_v = max((p["count"] for p in v_profiles), default=0)
        return {
            "target_mm": float(target_mm),
            "horizontal_profiles": h_profiles,
            "vertical_profiles": v_profiles,
            "best_horizontal_count": int(best_h),
            "best_vertical_count": int(best_v),
            "resolved_horizontal": any(p["resolved"] for p in h_profiles),
            "resolved_vertical": any(p["resolved"] for p in v_profiles),
            "resolved": any(p["resolved"] for p in h_profiles) or any(p["resolved"] for p in v_profiles),
            "criterion": "at least one row or one column with >=4 peaks",
        }

    def _mip_analysis(region, rect, target_mm):
        y, x, rh, rw = rect
        ul_h = max(3, int(np.ceil(0.64 * rh)))
        ul_w = max(3, int(np.ceil(0.64 * rw)))
        lr_y = max(0, int(np.floor(0.36 * rh)))
        lr_x = max(0, int(np.floor(0.36 * rw)))
        h_region = region[:ul_h, :ul_w]
        v_region = region[lr_y:, lr_x:]

        h_profile = np.max(h_region, axis=0)
        v_profile = np.max(v_region, axis=1)
        h_peaks, h_threshold, h_smooth = _detect_mip_peaks(h_profile, target_mm)
        v_peaks, v_threshold, v_smooth = _detect_mip_peaks(v_profile, target_mm)

        for peak in h_peaks:
            peak["col"] = int(x + peak["index"])
            peak["row"] = int(y + ul_h / 2)
        for peak in v_peaks:
            peak["col"] = int(x + lr_x + v_region.shape[1] / 2)
            peak["row"] = int(y + lr_y + peak["index"])

        return {
            "target_mm": float(target_mm),
            "rect": rect,
            "horizontal_rect": [y, x, int(ul_h), int(ul_w)],
            "vertical_rect": [y + int(lr_y), x + int(lr_x), int(v_region.shape[0]), int(v_region.shape[1])],
            "horizontal": {
                "x_mm": [round(float((i - (ul_w - 1) / 2) * px), 3) for i in range(ul_w)],
                "values": [round(float(v), 3) for v in h_profile],
                "smoothed": [round(float(v), 3) for v in h_smooth],
                "threshold": round(h_threshold, 3),
                "peaks": h_peaks,
                "count": len(h_peaks),
            },
            "vertical": {
                "x_mm": [round(float((i - (v_region.shape[0] - 1) / 2) * px), 3) for i in range(v_region.shape[0])],
                "values": [round(float(v), 3) for v in v_profile],
                "smoothed": [round(float(v), 3) for v in v_smooth],
                "threshold": round(v_threshold, 3),
                "peaks": v_peaks,
                "count": len(v_peaks),
            },
        }

    # Misura modulazione per ogni griglia
    mod_1_1 = _measure_modulation(grid_regions[0])
    mod_1_0 = _measure_modulation(grid_regions[1])
    mod_0_9 = _measure_modulation(grid_regions[2])
    targets_mm = [1.1, 1.0, 0.9]
    mip_results = [
        _mip_analysis(region, rect, target_mm)
        for region, rect, target_mm in zip(grid_regions, grid_rects, targets_mm)
    ]
    line_results = [
        _line_profile_analysis(region, rect, target_mm)
        for region, rect, target_mm in zip(grid_regions, grid_rects, targets_mm)
    ]

    # Il criterio ACR/assistito accetta un target se almeno una riga o colonna
    # del gruppo mostra i 4 fori; i MIP restano visualizzazione di supporto.
    threshold = 0.05
    resolved_1_1 = bool(line_results[0]["resolved"])
    resolved_1_0 = bool(line_results[1]["resolved"])
    resolved_0_9 = bool(line_results[2]["resolved"])

    # Determina la risoluzione raggiunta
    if resolved_0_9:
        resolved_mm = 0.9
    elif resolved_1_0:
        resolved_mm = 1.0
    elif resolved_1_1:
        resolved_mm = 1.1
    else:
        resolved_mm = None

    # Limite: deve risolvere almeno 1.0 mm
    passed = resolved_mm is not None and resolved_mm <= 1.0

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
        "resolution_mip": mip_results,
        "resolution_line_profiles": line_results,
        "analysis_mode": "assisted_line_profiles",
        "resolution_criterion": "at least one row or one column with >=4 peaks",
        "modulation_threshold": threshold,
    }


# ==============================================================================
# LOW-CONTRAST OBJECT DETECTABILITY â€” RilevabilitÃ  oggetti a basso contrasto
# ==============================================================================

def calculate_low_contrast(arr: np.ndarray, pixel_spacing_mm: float = 1.0,
                           center_rc=None, radius_px=None,
                           lcd_angle_offset_deg: float = 0.0,
                           lcd_ring_radius_mm: float = 40.0):
    """
    Valuta la rilevabilitÃ  degli oggetti a basso contrasto nelle slice #8-#11
    del phantom ACR.

    Il phantom ACR contiene dischi a basso contrasto (spoke targets) con
    diametri decrescenti disposti in cerchio. Ogni slice (#8-#11) ha un set
    di 10 dischi con contrasto diverso.

    Metodo: per ogni disco, si misura il CNR (Contrast-to-Noise Ratio)
    rispetto al background circostante. Un disco Ã¨ "visibile" se CNR > soglia.

    Limite ACR: â‰¥ 9 spoke totali visibili (<3T), â‰¥ 37 (3T)

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
    # Ci sono 10 dischi per slice, disposti a intervalli angolari di 36Â°

    n_spokes = 10
    spoke_radius_mm = 45.0  # distanza dal centro all'anello dei dischi
    spoke_radius_px = int(spoke_radius_mm / px)

    # Raggio dei dischi: varia per slice (7mm, 5mm, 4mm, 3mm per slice 8-11)
    # Usiamo un raggio generico e misuriamo il contrasto
    disk_radius_mm = 5.0  # raggio medio del disco
    disk_radius_px = max(2, int(disk_radius_mm / px))

    # Background: anello leggermente piÃ¹ esterno
    bg_inner_px = spoke_radius_px + disk_radius_px + 2
    bg_outer_px = bg_inner_px + max(3, int(5.0 / px))

    # Misura background medio nell'anello
    Y, X = np.ogrid[:h, :w]
    dist_from_center = np.sqrt((X - cc)**2 + (Y - cr)**2)
    bg_mask = (dist_from_center >= bg_inner_px) & (dist_from_center <= bg_outer_px)

    # Fallback: usa un anello interno se quello esterno Ã¨ fuori dal phantom
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

        # VisibilitÃ : CNR > 1.0 (Rose criterion)
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

    # Limiti ACR: â‰¥ 9 spoke per slice (<3T), â‰¥ 37 totali su 4 slice (3T)
    # Per singola slice: â‰¥ 2-3 Ã¨ ragionevole
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


# Override legacy slice-position implementation above with the ACR bar-length
# method. Keeping this at EOF avoids touching older text with broken encoding.
def calculate_slice_position(arr: np.ndarray, pixel_spacing_mm: float = 1.0,
                             center_rc=None, radius_px=None,
                             left_bar_rect=None, right_bar_rect=None):
    """
    ACR slice position accuracy from the two dark vertical crossed-wedge bars.
    The reported value is right length minus left length, so it is negative
    when the left bar is longer, matching the ACR sign convention.
    """
    h, w = arr.shape
    px = float(pixel_spacing_mm)

    if center_rc is None or radius_px is None:
        cr, cc, r0 = find_phantom_circle(arr, pixel_spacing_mm)
    else:
        cr, cc = center_rc
        r0 = radius_px

    cr = int(np.clip(round(cr), 0, h - 1))
    cc = int(np.clip(round(cc), 0, w - 1))
    r0 = float(r0)

    def _clamp_rect(rect):
        y, x, rh, rw = [int(round(v)) for v in rect]
        y = max(0, min(h - 1, y))
        x = max(0, min(w - 1, x))
        rh = max(1, min(h - y, rh))
        rw = max(1, min(w - x, rw))
        return [y, x, rh, rw]

    def _components(mask):
        mh, mw = mask.shape
        seen = np.zeros_like(mask, dtype=bool)
        comps = []
        for rr in range(mh):
            for cc0 in range(mw):
                if not mask[rr, cc0] or seen[rr, cc0]:
                    continue
                stack = [(rr, cc0)]
                seen[rr, cc0] = True
                pts = []
                while stack:
                    pr, pc = stack.pop()
                    pts.append((pr, pc))
                    for nr, nc in ((pr - 1, pc), (pr + 1, pc), (pr, pc - 1), (pr, pc + 1)):
                        if 0 <= nr < mh and 0 <= nc < mw and mask[nr, nc] and not seen[nr, nc]:
                            seen[nr, nc] = True
                            stack.append((nr, nc))
                rows = [p[0] for p in pts]
                cols = [p[1] for p in pts]
                comps.append({
                    "r0": min(rows), "r1": max(rows) + 1,
                    "c0": min(cols), "c1": max(cols) + 1,
                    "area": len(pts),
                })
        return comps

    def _fallback_rects():
        bar_w = max(4, int(round(8.0 / max(px, 1e-6))))
        bar_h = max(12, int(round(28.0 / max(px, 1e-6))))
        y = int(round(cr - 0.86 * r0))
        return (
            _clamp_rect([y, cc - bar_w - 1, bar_h, bar_w]),
            _clamp_rect([y, cc + 1, bar_h, bar_w]),
        )

    def _default_rects():
        search_y0 = int(max(0, round(cr - 0.98 * r0)))
        search_y1 = int(min(h, round(cr - 0.20 * r0)))
        search_x0 = int(max(0, round(cc - 0.26 * r0)))
        search_x1 = int(min(w, round(cc + 0.30 * r0)))
        pad_y = max(2, int(round(2.0 / max(px, 1e-6))))
        pad_x = max(2, int(round(2.0 / max(px, 1e-6))))

        if search_y1 <= search_y0 + 8 or search_x1 <= search_x0 + 8:
            return _fallback_rects()

        patch = arr[search_y0:search_y1, search_x0:search_x1].astype(np.float64)
        yy, xx = np.ogrid[search_y0:search_y1, search_x0:search_x1]
        circle_mask = (yy - cr) ** 2 + (xx - cc) ** 2 <= (0.98 * r0) ** 2
        valid = patch[circle_mask]
        if valid.size < 20:
            valid = patch.reshape(-1)
        dark_cut = float(np.percentile(valid, 8))
        dark = (patch <= dark_cut) & circle_mask

        comps = []
        for comp in _components(dark):
            ch = comp["r1"] - comp["r0"]
            cw = comp["c1"] - comp["c0"]
            min_h = max(8, int(round(8.0 / max(px, 1e-6))))
            if comp["area"] < 8 or ch < min_h or cw < 2 or ch < 1.5 * cw:
                continue
            comp["cy"] = (comp["r0"] + comp["r1"]) / 2.0 + search_y0
            comp["cx"] = (comp["c0"] + comp["c1"]) / 2.0 + search_x0
            comp["score"] = comp["area"] + 2.0 * ch - abs(comp["cx"] - cc) * 0.15
            comps.append(comp)

        if len(comps) < 2:
            return _fallback_rects()

        comps.sort(key=lambda c: c["score"], reverse=True)
        best_pair = None
        best_score = -1e9
        for i in range(min(len(comps), 8)):
            for j in range(i + 1, min(len(comps), 8)):
                a, b = comps[i], comps[j]
                sep = abs(a["cx"] - b["cx"])
                if sep < max(3, int(round(2.0 / max(px, 1e-6)))) or sep > max(30, int(round(30.0 / max(px, 1e-6)))):
                    continue
                y_overlap = min(a["r1"], b["r1"]) - max(a["r0"], b["r0"])
                y_align = abs(a["cy"] - b["cy"])
                score = a["score"] + b["score"] + y_overlap - y_align
                if score > best_score:
                    best_score = score
                    best_pair = (a, b)

        if best_pair is None:
            comps.sort(key=lambda c: abs(c["cx"] - cc))
            best_pair = (comps[0], comps[1])

        left, right = sorted(best_pair, key=lambda c: c["cx"])

        def _rect_from_comp(comp):
            return _clamp_rect([
                search_y0 + comp["r0"] - pad_y,
                search_x0 + comp["c0"] - pad_x,
                (comp["r1"] - comp["r0"]) + 2 * pad_y,
                (comp["c1"] - comp["c0"]) + 2 * pad_x,
            ])

        return _rect_from_comp(left), _rect_from_comp(right)

    default_left, default_right = _default_rects()
    left_bar_rect = _clamp_rect(left_bar_rect) if left_bar_rect else default_left
    right_bar_rect = _clamp_rect(right_bar_rect) if right_bar_rect else default_right

    def _measure_dark_bar(rect):
        y, x, rh, rw = rect
        roi = arr[y:y + rh, x:x + rw].astype(np.float64)
        if roi.size == 0:
            return 0.0, None, None, np.array([], dtype=float), 0.0, 0.0
        profile = np.mean(roi, axis=1)
        water = float(np.percentile(profile, 90))
        bar = float(np.percentile(profile, 10))
        threshold = bar + 0.5 * (water - bar)
        dark_rows = np.where(profile <= threshold)[0]
        if len(dark_rows) < 2:
            return 0.0, None, None, profile, threshold, float(np.mean(roi))

        def _cross(edge_idx, neighbor_idx):
            y0, y1 = float(neighbor_idx), float(edge_idx)
            v0, v1 = float(profile[neighbor_idx]), float(profile[edge_idx])
            if abs(v1 - v0) < 1e-9:
                return y1
            return y0 + (threshold - v0) * (y1 - y0) / (v1 - v0)

        top_i = int(dark_rows[0])
        bot_i = int(dark_rows[-1])
        top = _cross(top_i, top_i - 1) if top_i > 0 else float(top_i)
        bot = _cross(bot_i, bot_i + 1) if bot_i < len(profile) - 1 else float(bot_i)
        if bot <= top:
            top, bot = float(top_i), float(bot_i)
        return float((bot - top) * px), float(top), float(bot), profile, threshold, float(np.mean(roi))

    left_len_mm, left_top, left_bottom, left_profile, left_threshold, left_mean = _measure_dark_bar(left_bar_rect)
    right_len_mm, right_top, right_bottom, right_profile, right_threshold, right_mean = _measure_dark_bar(right_bar_rect)
    slice_position_error_mm = right_len_mm - left_len_mm

    limit_mm = 5.0
    limit_recommended_mm = 4.0
    passed = abs(slice_position_error_mm) <= limit_mm
    passed_recommended = abs(slice_position_error_mm) <= limit_recommended_mm

    def _pack_profile(rect, profile, top, bottom, threshold, length_mm):
        y, x, rh, rw = rect
        return {
            "rect": rect,
            "profile": [round(float(v), 3) for v in profile.tolist()],
            "threshold": round(float(threshold), 3),
            "top_rc": [y + top, x + rw / 2.0] if top is not None else None,
            "bottom_rc": [y + bottom, x + rw / 2.0] if bottom is not None else None,
            "length_mm": round(float(length_mm), 2),
        }

    return {
        "slice_position_error_mm": round(slice_position_error_mm, 2),
        "bar_length_1_mm": round(left_len_mm, 2),
        "bar_length_2_mm": round(right_len_mm, 2),
        "left_bar_length_mm": round(left_len_mm, 2),
        "right_bar_length_mm": round(right_len_mm, 2),
        "left_bar_rect": left_bar_rect,
        "right_bar_rect": right_bar_rect,
        "slice_position_sign_rule": "right - left; negative if left bar is longer",
        "bar_signal_mean": round(float((left_mean + right_mean) / 2.0), 3),
        "bar_threshold": round(float((left_threshold + right_threshold) / 2.0), 3),
        "slice_position_profiles": {
            "left": _pack_profile(left_bar_rect, left_profile, left_top, left_bottom, left_threshold, left_len_mm),
            "right": _pack_profile(right_bar_rect, right_profile, right_top, right_bottom, right_threshold, right_len_mm),
        },
        "passed": passed,
        "passed_recommended": passed_recommended,
        "limit_mm": limit_mm,
        "limit_recommended_mm": limit_recommended_mm,
        "center_rc": (cr, cc),
        "radius_px": r0,
    }


# Override legacy LCD implementation with ACR-style complete-spoke scoring.
def _detect_lcd_black_annulus(arr: np.ndarray, center_rc=None, radius_px=None,
                              pixel_spacing_mm: float = 1.0):
    h, w = arr.shape
    if center_rc is None or radius_px is None:
        cr0, cc0, r0 = find_phantom_circle(arr, pixel_spacing_mm)
    else:
        cr0, cc0 = center_rc
        r0 = radius_px

    cr0 = int(round(cr0))
    cc0 = int(round(cc0))
    Y, X = np.ogrid[:h, :w]
    dist0 = np.sqrt((X - cc0) ** 2 + (Y - cr0) ** 2)
    search = (dist0 >= 20.0 / pixel_spacing_mm) & (dist0 <= min(0.75 * float(r0), 85.0 / pixel_spacing_mm))
    vals = arr[search & (arr > 0)]
    if vals.size < 100:
        return cr0, cc0, r0, None

    dark_cut = float(np.percentile(vals, 8))
    dark = search & (arr <= dark_cut)
    dark = ndimage.binary_opening(dark, structure=np.ones((2, 2)))
    rr_all, cc_all = np.where(dark)
    if rr_all.size < 80:
        return cr0, cc0, r0, None

    radii = np.sqrt((cc_all - cc0) ** 2 + (rr_all - cr0) ** 2)
    bins = np.arange(max(1, int(np.floor(radii.min()))), int(np.ceil(radii.max())) + 2)
    hist, edges = np.histogram(radii, bins=bins)
    if hist.size == 0:
        return cr0, cc0, r0, None
    peak = int(np.argmax(hist))
    peak_radius = float((edges[peak] + edges[peak + 1]) / 2.0)
    band = np.abs(radii - peak_radius) <= max(2.0, 3.0 / pixel_spacing_mm)
    if np.sum(band) < 40:
        return cr0, cc0, r0, peak_radius

    rr = rr_all[band]
    cc_idx = cc_all[band]
    if center_rc is not None:
        annulus_radius_px = float(np.median(np.sqrt((cc_idx - cc0) ** 2 + (rr - cr0) ** 2)))
        return cr0, cc0, r0, annulus_radius_px

    cr = int(round(float(np.mean(rr))))
    cc = int(round(float(np.mean(cc_idx))))
    annulus_radius_px = float(np.median(np.sqrt((cc_idx - cc) ** 2 + (rr - cr) ** 2)))
    return cr, cc, r0, annulus_radius_px


def calculate_low_contrast(arr: np.ndarray, pixel_spacing_mm: float = 1.0,
                           center_rc=None, radius_px=None,
                           lcd_angle_offset_deg: float = 0.0,
                           lcd_ring_radius_mm: float = 40.0,
                           lcd_acr_slice_number=None,
                           lcd_anchor_outer_rc=None,
                           lcd_method: str = "manual"):
    if lcd_anchor_outer_rc is not None and center_rc is not None:
        cr_anchor, cc_anchor = float(center_rc[0]), float(center_rc[1])
        ar, ac = float(lcd_anchor_outer_rc[0]), float(lcd_anchor_outer_rc[1])
        dr = ar - cr_anchor
        dc = ac - cc_anchor
        anchor_radius_px = math.hypot(dr, dc)
        if anchor_radius_px > 1:
            lcd_ring_radius_mm = anchor_radius_px * float(pixel_spacing_mm)
            lcd_angle_offset_deg = math.degrees(math.atan2(dc, -dr))
            lcd_method = "cnr"

    h, w = arr.shape
    px = float(pixel_spacing_mm)
    Y, X = np.ogrid[:h, :w]
    cr, cc, r0, lcd_annulus_radius_px = _detect_lcd_black_annulus(
        arr,
        center_rc=center_rc,
        radius_px=radius_px,
        pixel_spacing_mm=px,
    )
    dist_from_center = np.sqrt((X - cc) ** 2 + (Y - cr) ** 2)

    bg_mask = (dist_from_center >= int(round(62.0 / px))) & (dist_from_center <= int(round(72.0 / px)))
    bg_mask &= ((X - cc) ** 2 + (Y - cr) ** 2) <= (0.9 * float(r0)) ** 2
    bg_values = arr[bg_mask & (arr > 0)]
    if bg_values.size < 50:
        inner = int(round(24.0 / px))
        outer = int(round(70.0 / px))
        bg_mask = (dist_from_center >= inner) & (dist_from_center <= outer)
        bg_values = arr[bg_mask & (arr > 0)]
    bg_mean = float(np.mean(bg_values)) if bg_values.size else float(np.mean(arr[arr > 0]))
    bg_std = float(np.std(bg_values)) if bg_values.size else float(np.std(arr[arr > 0]))

    n_spokes = 10
    spoke_disk_diameters_mm = [7.0, 6.0, 5.0, 4.0, 3.5, 3.0, 2.5, 2.0, 1.75, 1.5]
    lcd_angle_offset_deg = float(lcd_angle_offset_deg)
    lcd_ring_radius_mm = max(15.0, min(70.0, float(lcd_ring_radius_mm)))
    # Literature/pylinac geometry: three object centers on common radii of
    # about 12.75, 25.50, 38.25 mm from the low-contrast disk center.
    scale = lcd_ring_radius_mm / 38.25
    disk_radii_mm = [12.75 * scale, 25.50 * scale, 38.25 * scale]
    spokes = []
    n_visible = 0
    stop_counting = False

    for i in range(n_spokes):
        angle_deg = i * (360.0 / n_spokes) + lcd_angle_offset_deg
        angle_rad = math.radians(angle_deg)
        disk_radius_px_i = max(1, int(round((spoke_disk_diameters_mm[i] / 2.0) / px)))
        disks = []
        complete = True
        for rr_mm in disk_radii_mm:
            rr_px = int(round(rr_mm / px))
            expected_r = int(cr - rr_px * math.cos(angle_rad))
            expected_c = int(cc + rr_px * math.sin(angle_rad))
            disk_r = max(disk_radius_px_i, min(h - disk_radius_px_i - 1, expected_r))
            disk_c = max(disk_radius_px_i, min(w - disk_radius_px_i - 1, expected_c))
            disk_mask = ((X - disk_c) ** 2 + (Y - disk_r) ** 2) <= disk_radius_px_i ** 2
            disk_values = arr[disk_mask]
            disk_mean = float(np.mean(disk_values)) if disk_values.size else 0.0
            disk_std = float(np.std(disk_values)) if disk_values.size else 0.0
            local_outer = max(disk_radius_px_i + 3, int(round(disk_radius_px_i * 2.8)))
            local_inner = disk_radius_px_i + 1
            local_dist = np.sqrt((X - disk_c) ** 2 + (Y - disk_r) ** 2)
            local_mask = (local_dist >= local_inner) & (local_dist <= local_outer)
            local_values = arr[local_mask & (arr > 0)]
            local_mean = float(np.mean(local_values)) if local_values.size else bg_mean
            local_std = float(np.std(local_values)) if local_values.size else bg_std
            cnr_global = abs(disk_mean - bg_mean) / bg_std if bg_std > 0 else 0.0
            cnr_local = abs(disk_mean - local_mean) / local_std if local_std > 0 else 0.0
            cnr = max(cnr_global, cnr_local)
            visible_disk = cnr > 0.35
            complete = complete and visible_disk
            disks.append({
                "center_rc": (disk_r, disk_c),
                "radius_px": disk_radius_px_i,
                "mean_signal": round(disk_mean, 2),
                "std_signal": round(disk_std, 3),
                "local_mean": round(local_mean, 2),
                "local_std": round(local_std, 3),
                "cnr_global": round(cnr_global, 2),
                "cnr_local": round(cnr_local, 2),
                "cnr": round(cnr, 2),
                "visible": visible_disk,
            })

        visible = complete and not stop_counting
        if visible:
            n_visible += 1
        else:
            stop_counting = True

        spokes.append({
            "index": i,
            "angle_deg": round(angle_deg, 1),
            "center_rc": disks[1]["center_rc"],
            "disk_diameter_mm": spoke_disk_diameters_mm[i],
            "disks": disks,
            "complete": complete,
            "visible": visible,
        })

    passed = n_visible >= 2
    return {
        "n_visible": n_visible,
        "n_total": n_spokes,
        "spokes": spokes,
        "bg_mean": round(bg_mean, 2),
        "bg_std": round(bg_std, 4),
        "passed": passed,
        "spoke_radius_mm": 45.0,
        "disk_radius_mm": 5.0,
        "lcd_counting_rule": "ACR contiguous complete spokes; stop at first incomplete",
        "lcd_detection_method": "manual geometry from black annulus",
        "lcd_visibility_cnr_threshold": 0.35,
        "lcd_angle_offset_deg": round(lcd_angle_offset_deg, 2),
        "lcd_ring_radius_mm": round(lcd_ring_radius_mm, 2),
        "lcd_ring_radius_px": round(float(lcd_ring_radius_mm / px), 2),
        "lcd_anchor_outer_rc": (
            int(round(cr - (lcd_ring_radius_mm / px) * math.cos(math.radians(lcd_angle_offset_deg)))),
            int(round(cc + (lcd_ring_radius_mm / px) * math.sin(math.radians(lcd_angle_offset_deg)))),
        ),
        "pixel_spacing_mm": round(px, 6),
        "lcd_annulus_radius_px": round(float(lcd_annulus_radius_px), 2) if lcd_annulus_radius_px is not None else None,
        "lcd_annulus_radius_mm": round(float(lcd_annulus_radius_px * px), 2) if lcd_annulus_radius_px is not None else None,
        "lcd_disk_radii_mm": [round(float(v), 2) for v in disk_radii_mm],
        "center_rc": (cr, cc),
        "radius_px": r0,
    }


# ==============================================================================
# RELAXOMETRY — T1 and T2 estimation from multi-echo/multi-TR data
# ==============================================================================


def calculate_relaxometry(slices_data: list, pixel_spacing_mm: float = 1.0,
                          center_rc=None, radius_px=None,
                          roi_fraction: float = 0.75):
    """
    Estimate T1 and/or T2 relaxation times from multiple acquisitions of the
    same slice at different TR or TE values.

    Args:
        slices_data: list of dicts with keys:
            - "pixel_array": 2D ndarray
            - "tr_ms": repetition time in ms
            - "te_ms": echo time in ms
        pixel_spacing_mm: pixel spacing
        center_rc: optional (row, col) center
        radius_px: optional radius in pixels
        roi_fraction: fraction of phantom radius for ROI (default 0.75)

    Returns:
        dict with T1, T2 estimates and fit quality metrics
    """
    if len(slices_data) < 2:
        return {"error": "Servono almeno 2 acquisizioni per la relassometria"}

    # Determine phantom geometry from first slice
    arr0 = slices_data[0]["pixel_array"]
    h, w = arr0.shape
    px = float(pixel_spacing_mm)

    if center_rc is None or radius_px is None:
        cr, cc, r0 = find_phantom_circle(arr0, px)
    else:
        cr, cc = center_rc
        r0 = radius_px

    cr = int(np.clip(round(cr), 0, h - 1))
    cc = int(np.clip(round(cc), 0, w - 1))
    r0 = float(r0)

    # Create circular ROI mask
    rr, rcc = np.ogrid[:h, :w]
    dist = np.sqrt((rr - cr) ** 2 + (rcc - cc) ** 2)
    roi_mask = dist <= roi_fraction * r0

    # Extract mean signal in ROI for each acquisition
    tr_values = []
    te_values = []
    signals = []

    for sd in slices_data:
        arr = sd["pixel_array"]
        if arr.shape != (h, w):
            continue
        mean_sig = float(np.mean(arr[roi_mask]))
        tr_values.append(float(sd.get("tr_ms", 0)))
        te_values.append(float(sd.get("te_ms", 0)))
        signals.append(mean_sig)

    tr_arr = np.array(tr_values)
    te_arr = np.array(te_values)
    sig_arr = np.array(signals)

    result = {
        "center_rc": (cr, cc),
        "radius_px": r0,
        "roi_fraction": roi_fraction,
        "n_points": len(signals),
        "tr_values_ms": [round(v, 1) for v in tr_values],
        "te_values_ms": [round(v, 1) for v in te_values],
        "signals": [round(v, 2) for v in signals],
    }

    # T2 estimation: if TE varies and TR is ~constant
    # S(TE) = S0 * exp(-TE/T2)
    te_unique = len(set(te_values))
    tr_unique = len(set(tr_values))

    if te_unique > 1 and (tr_unique == 1 or np.std(tr_arr) / np.mean(tr_arr) < 0.1):
        # Fit T2: ln(S) = ln(S0) - TE/T2
        valid = sig_arr > 0
        if np.sum(valid) >= 2:
            te_fit = te_arr[valid]
            ln_sig = np.log(sig_arr[valid])
            # Linear regression: ln(S) = a + b*TE, where b = -1/T2
            try:
                coeffs = np.polyfit(te_fit, ln_sig, 1)
                slope = coeffs[0]  # -1/T2
                intercept = coeffs[1]  # ln(S0)
                if slope < 0:
                    t2_ms = -1.0 / slope
                    s0 = np.exp(intercept)
                    # R-squared
                    predicted = intercept + slope * te_fit
                    ss_res = np.sum((ln_sig - predicted) ** 2)
                    ss_tot = np.sum((ln_sig - np.mean(ln_sig)) ** 2)
                    r_squared = 1.0 - ss_res / max(ss_tot, 1e-12)

                    result["t2_ms"] = round(float(t2_ms), 2)
                    result["t2_s0"] = round(float(s0), 2)
                    result["t2_r_squared"] = round(float(r_squared), 4)
                    result["t2_fit"] = "mono-exponential"
                else:
                    result["t2_ms"] = None
                    result["t2_error"] = "Pendenza positiva — dati non coerenti"
            except Exception as e:
                result["t2_ms"] = None
                result["t2_error"] = str(e)

    # T1 estimation: if TR varies and TE is ~constant
    # S(TR) = S0 * (1 - exp(-TR/T1))  [for SE with 90° flip angle]
    if tr_unique > 1 and (te_unique == 1 or np.std(te_arr) / max(np.mean(te_arr), 1) < 0.1):
        # Non-linear fit: S = S0 * (1 - exp(-TR/T1))
        try:
            from scipy.optimize import curve_fit

            def _t1_model(tr, s0, t1):
                return s0 * (1.0 - np.exp(-tr / t1))

            # Initial guesses
            s0_guess = float(np.max(sig_arr)) * 1.1
            t1_guess = float(np.mean(tr_arr))

            popt, pcov = curve_fit(
                _t1_model, tr_arr, sig_arr,
                p0=[s0_guess, t1_guess],
                bounds=([0, 1], [s0_guess * 5, 10000]),
                maxfev=5000,
            )
            t1_ms = popt[1]
            s0_fit = popt[0]

            # R-squared
            predicted = _t1_model(tr_arr, *popt)
            ss_res = np.sum((sig_arr - predicted) ** 2)
            ss_tot = np.sum((sig_arr - np.mean(sig_arr)) ** 2)
            r_squared = 1.0 - ss_res / max(ss_tot, 1e-12)

            result["t1_ms"] = round(float(t1_ms), 2)
            result["t1_s0"] = round(float(s0_fit), 2)
            result["t1_r_squared"] = round(float(r_squared), 4)
            result["t1_fit"] = "saturation-recovery"
        except Exception as e:
            result["t1_ms"] = None
            result["t1_error"] = str(e)

    return result
