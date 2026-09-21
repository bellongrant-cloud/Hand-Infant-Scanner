"""Ridge orientation and frequency field estimation.

Implements the standard gradient-based orientation estimation method
(Hong, Wan & Jain, 1998) with a "doubled angle" smoothing step, plus an
x-signature based local ridge frequency estimate.
"""
from __future__ import annotations

import numpy as np
import cv2


def compute_orientation_field(image: np.ndarray, block_size: int = 16, smooth_kernel: int = 5) -> np.ndarray:
    """Return a (blocks_y, blocks_x) array of ridge orientation angles in
    radians, in the range [0, pi). Orientation is the direction *along*
    the ridge (not the gradient direction).
    """
    gx = cv2.Sobel(image, cv2.CV_64F, 1, 0, ksize=3)
    gy = cv2.Sobel(image, cv2.CV_64F, 0, 1, ksize=3)

    h, w = image.shape
    blocks_y = h // block_size
    blocks_x = w // block_size

    vx = np.zeros((blocks_y, blocks_x))
    vy = np.zeros((blocks_y, blocks_x))

    for by in range(blocks_y):
        for bx in range(blocks_x):
            y0, y1 = by * block_size, (by + 1) * block_size
            x0, x1 = bx * block_size, (bx + 1) * block_size
            block_gx = gx[y0:y1, x0:x1]
            block_gy = gy[y0:y1, x0:x1]
            # Doubled-angle vector averaging avoids the 0/pi wrap-around problem.
            vx[by, bx] = np.sum(2 * block_gx * block_gy)
            vy[by, bx] = np.sum(block_gx ** 2 - block_gy ** 2)

    # Smooth the doubled-angle vector field (low-pass filter) before halving,
    # which greatly stabilizes orientation near noisy/low-contrast regions.
    if smooth_kernel > 1:
        vx = cv2.blur(vx, (smooth_kernel, smooth_kernel))
        vy = cv2.blur(vy, (smooth_kernel, smooth_kernel))

    theta = 0.5 * np.arctan2(vx, vy)
    # Convert gradient-normal angle to ridge-direction angle (perpendicular),
    # wrapped into [0, pi).
    orientation = (theta + np.pi / 2) % np.pi
    return orientation


def estimate_frequency_field(
    image: np.ndarray,
    orientation_field: np.ndarray,
    block_size: int = 16,
    window: int = 5,
    min_wavelength: float = 3.0,
    max_wavelength: float = 25.0,
) -> np.ndarray:
    """Estimate local ridge frequency (cycles/pixel) per block using the
    x-signature method: project a window oriented along the ridge normal
    and find the spacing between successive peaks.
    """
    h, w = image.shape
    blocks_y, blocks_x = orientation_field.shape
    freq = np.zeros((blocks_y, blocks_x))

    half = window * block_size // 2

    for by in range(blocks_y):
        for bx in range(blocks_x):
            cy = by * block_size + block_size // 2
            cx = bx * block_size + block_size // 2
            theta = orientation_field[by, bx]
            # Sample a 1-D signature perpendicular to the ridge orientation.
            normal = theta + np.pi / 2
            length = block_size * window
            ts = np.arange(-length // 2, length // 2)
            xs = cx + ts * np.cos(normal)
            ys = cy + ts * np.sin(normal)
            valid = (xs >= 0) & (xs < w) & (ys >= 0) & (ys < h)
            if valid.sum() < min_wavelength * 2:
                freq[by, bx] = 0
                continue
            xs_i = xs[valid].astype(int)
            ys_i = ys[valid].astype(int)
            signature = image[ys_i, xs_i]
            wavelength = _peak_spacing(signature, min_wavelength, max_wavelength)
            freq[by, bx] = 0.0 if wavelength is None else 1.0 / wavelength

    return freq


def _peak_spacing(signal: np.ndarray, min_wavelength: float, max_wavelength: float) -> float | None:
    """Estimate the dominant spacing between local maxima of a 1-D signal."""
    if len(signal) < 5:
        return None
    smoothed = np.convolve(signal, np.ones(3) / 3.0, mode="same")
    peaks = []
    for i in range(1, len(smoothed) - 1):
        if smoothed[i] > smoothed[i - 1] and smoothed[i] >= smoothed[i + 1]:
            peaks.append(i)
    if len(peaks) < 2:
        return None
    spacings = np.diff(peaks)
    spacings = spacings[(spacings >= min_wavelength) & (spacings <= max_wavelength)]
    if len(spacings) == 0:
        return None
    return float(np.median(spacings))


def upsample_field(field: np.ndarray, block_size: int, shape: tuple[int, int]) -> np.ndarray:
    """Nearest-neighbor upsample a per-block field to full pixel resolution."""
    blocks_y, blocks_x = field.shape
    out = np.zeros(shape, dtype=field.dtype)
    for by in range(blocks_y):
        for bx in range(blocks_x):
            y0, y1 = by * block_size, min((by + 1) * block_size, shape[0])
            x0, x1 = bx * block_size, min((bx + 1) * block_size, shape[1])
            out[y0:y1, x0:x1] = field[by, bx]
    return out
