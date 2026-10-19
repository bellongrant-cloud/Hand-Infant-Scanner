#!/usr/bin/env python3
"""Ridge Counter: dermatoglyphic ridge counts from fingerprint and palm scans.

Open the point-and-click window:   python ridge_counter.py [SCAN]
Count from the command line:       python ridge_counter.py count SCAN [--core X,Y --delta X,Y]
On Windows, double-click "Ridge Counter.bat", or drag a scan onto it.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import queue
import subprocess
import sys
import threading
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

try:
    import numpy as np
    import cv2
except ImportError:
    np = None
    cv2 = None

try:
    import dermatoglyphics as dg  # child records and the model; must sit next to this file
except ImportError:
    dg = None

try:
    import tkinter as tk
    import tkinter.font as tkfont
    from tkinter import filedialog, messagebox, ttk
except ImportError:
    tk = None

__version__ = "2.0.0"
REQUIRED_PACKAGES = ("numpy", "opencv-python-headless")
INSTALL_COMMAND = "python -m pip install " + " ".join(REQUIRED_PACKAGES)
ORIENTATION_BINS = 16
MIN_PERIOD, MAX_PERIOD = 3.0, 40.0
CSV_FIELDS = (
    "analyzed_at", "image", "ridge_count", "core_x", "core_y", "delta_x", "delta_y",
    "core_source", "delta_source", "ridge_period_px",
)


# ---------------------------------------------------------------------------
# Image input / output
# ---------------------------------------------------------------------------

def read_image(path) -> np.ndarray:
    """Read a scan as 8-bit grayscale. Works with non-ASCII Windows paths.

    Transparent areas are treated as white paper: exported prints often
    store the gaps between ridges as transparent black pixels.
    """
    data = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_UNCHANGED) if data.size else None
    if image is None:
        raise ValueError(f"Could not read {Path(path).name} as an image.")
    if image.dtype != np.uint8:
        image = cv2.normalize(image, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    if image.ndim == 2:
        return image
    if image.shape[2] == 4:
        alpha = image[:, :, 3:4].astype(np.float32) / 255.0
        image = (image[:, :, :3] * alpha + 255.0 * (1.0 - alpha)).astype(np.uint8)
    elif image.shape[2] == 2:
        alpha = image[:, :, 1].astype(np.float32) / 255.0
        return (image[:, :, 0] * alpha + 255.0 * (1.0 - alpha)).astype(np.uint8)
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


def write_image(path, image: np.ndarray) -> None:
    ok, buffer = cv2.imencode(Path(path).suffix or ".png", image)
    if not ok:
        raise OSError(f"Could not encode {path}")
    buffer.tofile(str(path))


# ---------------------------------------------------------------------------
# Analysis: enhancement, ridge map, orientation, singular points
# ---------------------------------------------------------------------------

@dataclass
class SingularPoint:
    x: int
    y: int
    kind: str  # "core" or "delta"
    score: float


@dataclass
class Analysis:
    gray: np.ndarray          # original scan, uint8
    enhanced: np.ndarray      # Gabor response, positive on ridges
    ridges: np.ndarray        # bool ridge map
    mask: np.ndarray          # bool skin / print area
    orientation: np.ndarray   # ridge direction in radians, [0, pi)
    coherence: np.ndarray     # orientation reliability, [0, 1]
    ridge_period: float       # ridge-to-ridge spacing in pixels
    cores: list = field(default_factory=list)
    deltas: list = field(default_factory=list)
    light_ridges: bool = False


def _blur(image: np.ndarray, sigma: float) -> np.ndarray:
    return cv2.GaussianBlur(image, (0, 0), sigma)


def _odd(value: float) -> int:
    n = max(3, int(round(value)))
    return n if n % 2 else n + 1


def _local_normalize(image: np.ndarray, sigma: float) -> np.ndarray:
    """Remove uneven brightness/contrast (finger pressure, lighting)."""
    centered = image - _blur(image, sigma)
    std = np.sqrt(_blur(centered * centered, sigma))
    floor = 0.1 * float(np.percentile(std, 90)) + 1e-6
    return centered / np.maximum(std, floor)


def _clean_mask(mask: np.ndarray, period: float) -> np.ndarray:
    """Smooth a region mask, drop small islands and fill interior holes."""
    mask = mask.astype(np.uint8)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (_odd(2 * period),) * 2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return mask.astype(bool)
    areas = [cv2.contourArea(c) for c in contours]
    keep = [c for c, a in zip(contours, areas) if a >= 0.1 * max(areas)]
    filled = np.zeros_like(mask)
    cv2.drawContours(filled, keep, -1, 1, thickness=cv2.FILLED)
    return filled.astype(bool)


def texture_mask(image: np.ndarray, period: float) -> np.ndarray:
    """Rough print area: anywhere with noticeable texture."""
    sigma = max(period, 4.0)
    mean = _blur(image, sigma)
    std = np.sqrt(np.maximum(_blur(image * image, sigma) - mean * mean, 0.0))
    textured = std[std > 1.0]  # the print may cover only a few % of a mostly blank scan
    if textured.size == 0:
        return np.zeros(image.shape, bool)
    level = float(np.percentile(textured, 95))
    return _clean_mask(std > 0.3 * level, period)


def ridge_quality_mask(norm: np.ndarray, enhanced: np.ndarray, period: float, region: np.ndarray) -> np.ndarray:
    """Print area proper: where a good share of local energy is ridge-like.

    Unlike a plain texture test this rejects the step at the edge of the
    finger and background noise. The cut-off adapts to the scan, so faint
    or noisy prints are not thrown away.
    """
    quality = _blur(enhanced * enhanced, period) / (_blur(norm * norm, period) + 1e-6)
    typical = float(np.percentile(quality[region], 95)) if region.any() else 0.0
    threshold = min(0.2, max(0.05, 0.3 * typical))
    return _clean_mask(quality > threshold, period)


def estimate_ridge_period(norm: np.ndarray, mask: np.ndarray) -> float:
    """Dominant ridge-to-ridge spacing in pixels, from averaged tile spectra."""
    h, w = norm.shape
    tile = 32
    while tile * 2 <= min(h, w) and tile < 128:  # small tiles fit inside small prints
        tile *= 2
    step = tile // 2
    tiles = [
        (mask[y:y + tile, x:x + tile].mean(), y, x)
        for y in range(0, h - tile + 1, step)
        for x in range(0, w - tile + 1, step)
    ]
    best = max(t[0] for t in tiles)
    if best == 0:
        raise ValueError("No ridge pattern found in this image.")
    window = np.outer(np.hanning(tile), np.hanning(tile)).astype(np.float32)
    power = np.zeros((tile, tile))
    for coverage, y, x in tiles:
        if coverage >= min(0.9, best):
            spectrum = np.fft.fft2(norm[y:y + tile, x:x + tile] * window)
            power += spectrum.real ** 2 + spectrum.imag ** 2

    freqs = np.fft.fftfreq(tile)
    radius = np.rint(np.hypot(freqs[None, :], freqs[:, None]) * tile).astype(int).ravel()
    profile = np.bincount(radius, weights=power.ravel()) / np.maximum(np.bincount(radius), 1)
    # Weighting by frequency flattens the broad low-frequency hump from blotchy ink.
    profile = profile * np.arange(len(profile))
    lo = max(1, int(math.floor(tile / MAX_PERIOD)))
    hi = min(len(profile) - 2, int(math.ceil(tile / MIN_PERIOD)))
    # Take the strongest interior peak: large-scale shading makes the
    # spectrum rise towards low frequencies without forming a peak.
    peaks = [k for k in range(lo, hi + 1) if profile[k] > profile[k - 1] and profile[k] >= profile[k + 1]]
    k = max(peaks, key=lambda i: profile[i]) if peaks else lo + int(np.argmax(profile[lo:hi + 1]))
    # Ridge spectra are broad plateaus; use the weighted centre of the peak.
    floor = float(np.percentile(profile[lo:hi + 1], 20))
    half = floor + 0.5 * (profile[k] - floor)
    a, b = k, k
    while a - 1 >= lo and profile[a - 1] > half:
        a -= 1
    while b + 1 <= hi and profile[b + 1] > half:
        b += 1
    weights = profile[a:b + 1] - floor
    centre = float(np.sum(np.arange(a, b + 1) * weights) / np.sum(weights))
    return float(np.clip(tile / centre, MIN_PERIOD, MAX_PERIOD))


def orientation_field(norm: np.ndarray, period: float):
    """Per-pixel ridge direction (radians, [0, pi)) and coherence."""
    gx = cv2.Sobel(norm, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(norm, cv2.CV_32F, 0, 1, ksize=3)
    sigma = max(period, 3.0)
    gxx, gyy, gxy = _blur(gx * gx, sigma), _blur(gy * gy, sigma), _blur(gx * gy, sigma)
    orientation = np.mod(0.5 * np.arctan2(2 * gxy, gxx - gyy) + np.pi / 2, np.pi)
    coherence = np.sqrt((gxx - gyy) ** 2 + 4 * gxy ** 2) / (gxx + gyy + 1e-6)
    return orientation.astype(np.float32), coherence.astype(np.float32)


def _gabor_kernel(period: float, ridge_angle: float) -> np.ndarray:
    """Even Gabor kernel, zero-mean, unit gain for a matched ridge pattern."""
    sigma_across, sigma_along = 0.45 * period, 0.5 * period
    half = int(math.ceil(3 * sigma_along))
    y, x = np.mgrid[-half:half + 1, -half:half + 1].astype(np.float32)
    normal = ridge_angle + math.pi / 2
    u = x * math.cos(normal) + y * math.sin(normal)
    v = -x * math.sin(normal) + y * math.cos(normal)
    envelope = np.exp(-0.5 * ((u / sigma_across) ** 2 + (v / sigma_along) ** 2))
    carrier = np.cos(2 * math.pi * u / period)
    kernel = envelope * carrier
    kernel -= envelope * (kernel.sum() / envelope.sum())
    kernel /= np.sum(kernel * carrier)
    return kernel.astype(np.float32)


def gabor_enhance(norm: np.ndarray, orientation: np.ndarray, period: float, mask: np.ndarray) -> np.ndarray:
    """Oriented Gabor filtering, interpolating between neighbouring orientation bins."""
    step = math.pi / ORIENTATION_BINS
    position = orientation / step
    lower = np.floor(position).astype(np.int32) % ORIENTATION_BINS
    frac = (position - np.floor(position)).astype(np.float32)
    upper = (lower + 1) % ORIENTATION_BINS
    weight_mask = mask.astype(np.float32)

    kernels = [_gabor_kernel(period, b * step) for b in range(ORIENTATION_BINS)]
    half = kernels[0].shape[0] // 2
    padded = cv2.copyMakeBorder(norm, half, half, half, half, cv2.BORDER_REFLECT_101)
    out = np.zeros_like(norm)
    for b, kernel in enumerate(kernels):
        weight = (np.where(lower == b, 1 - frac, 0) + np.where(upper == b, frac, 0)) * weight_mask
        ys, xs = np.nonzero(weight)
        if ys.size == 0:
            continue
        y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
        region = padded[y0:y1 + 2 * half, x0:x1 + 2 * half]
        response = cv2.filter2D(region, cv2.CV_32F, kernel)[half:half + y1 - y0, half:half + x1 - x0]
        out[y0:y1, x0:x1] += weight[y0:y1, x0:x1] * response
    return out


def _ring_offsets(radius: int) -> list:
    ring = [
        (dy, dx)
        for dy in range(-radius, radius + 1)
        for dx in range(-radius, radius + 1)
        if max(abs(dy), abs(dx)) == radius
    ]
    ring.sort(key=lambda p: math.atan2(p[0], p[1]))
    return ring


def _surrounding_coherence(coherence: np.ndarray, x: int, y: int, period: float) -> float:
    h, w = coherence.shape
    outer = int(math.ceil(3 * period))
    y0, y1, x0, x1 = max(0, y - outer), min(h, y + outer + 1), max(0, x - outer), min(w, x + outer + 1)
    yy, xx = np.mgrid[y0:y1, x0:x1]
    dist = np.hypot(xx - x, yy - y)
    ring = (dist >= 1.5 * period) & (dist <= outer)
    return float(coherence[y0:y1, x0:x1][ring].mean()) if ring.any() else 0.0


def _singular_blobs(candidates, kind, step, coherence, period) -> list:
    n, _, stats, centroids = cv2.connectedComponentsWithStats(candidates.astype(np.uint8), connectivity=8)
    points = []
    for i in range(1, n):
        x, y = int(round(centroids[i][0] * step)), int(round(centroids[i][1] * step))
        area = float(stats[i, cv2.CC_STAT_AREA])
        points.append(SingularPoint(x, y, kind, area * _surrounding_coherence(coherence, x, y, period)))
    return points


def find_singular_points(orientation, coherence, mask, period):
    """Cores and deltas via the Poincare index on a ring around each grid point.

    Returns (cores, deltas), each sorted best-first. A whorl centre
    (index +1) is reported as a core.
    """
    sigma = max(period, 3.0)
    cos2 = _blur(np.cos(2 * orientation) * coherence, sigma)
    sin2 = _blur(np.sin(2 * orientation) * coherence, sigma)
    smooth = 0.5 * np.arctan2(sin2, cos2)

    step = max(2, int(round(period / 2)))
    radius = max(2, int(round(1.5 * period / step)))
    margin = int(math.ceil((radius + 1) * step))
    inner = cv2.erode(
        mask.astype(np.uint8),
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * margin + 1,) * 2),
        borderType=cv2.BORDER_CONSTANT,
        borderValue=0,
    ) > 0

    grid = smooth[::step, ::step]
    valid = inner[::step, ::step]
    gh, gw = grid.shape
    padded = np.pad(grid, radius, mode="edge")
    ring = [padded[radius + dy:radius + dy + gh, radius + dx:radius + dx + gw] for dy, dx in _ring_offsets(radius)]
    total = np.zeros_like(grid)
    for a, b in zip(ring, ring[1:] + ring[:1]):
        total += np.mod(b - a + np.pi / 2, np.pi) - np.pi / 2
    index = total / (2 * np.pi)

    core_map = valid & ((np.abs(index - 0.5) < 0.2) | (np.abs(index - 1.0) < 0.2))
    delta_map = valid & (np.abs(index + 0.5) < 0.2)
    cores = _singular_blobs(core_map, "core", step, coherence, period)
    deltas = _singular_blobs(delta_map, "delta", step, coherence, period)

    # A core and delta sitting right next to each other is a noise artefact.
    near = 1.5 * period
    noisy_cores = {i for i, c in enumerate(cores) for d in deltas if math.hypot(c.x - d.x, c.y - d.y) < near}
    noisy_deltas = {j for j, d in enumerate(deltas) for c in cores if math.hypot(c.x - d.x, c.y - d.y) < near}
    cores = sorted((c for i, c in enumerate(cores) if i not in noisy_cores), key=lambda p: -p.score)
    deltas = sorted((d for j, d in enumerate(deltas) if j not in noisy_deltas), key=lambda p: -p.score)
    return cores, deltas


def snap_to_ridge(ridges: np.ndarray, point, reach: float):
    """Move a point onto the nearest ridge pixel within `reach` px.

    By definition the core and the delta sit on a ridge, and that ridge is
    not counted. Detected singular points land on the pattern's centre,
    which can be a pixel or two into the neighbouring valley; snapping
    keeps the endpoint rule from adding that ridge to the count.
    """
    x, y = point
    h, w = ridges.shape
    if not (0 <= x < w and 0 <= y < h) or ridges[y, x]:
        return point
    r = int(math.ceil(reach))
    y0, y1, x0, x1 = max(0, y - r), min(h, y + r + 1), max(0, x - r), min(w, x + r + 1)
    ys, xs = np.nonzero(ridges[y0:y1, x0:x1])
    if ys.size == 0:
        return point
    distance = np.hypot(xs + x0 - x, ys + y0 - y)
    i = int(np.argmin(distance))
    return point if distance[i] > reach else (int(xs[i] + x0), int(ys[i] + y0))


def analyze(gray: np.ndarray, light_ridges: bool = False, ridge_period: float | None = None) -> Analysis:
    """Run the full image analysis once; counting afterwards is instant."""
    if gray.ndim != 2 or min(gray.shape) < 32:
        raise ValueError("The image is too small to analyze (it needs to be at least 32x32 pixels).")
    image = gray.astype(np.float32)
    if not light_ridges:
        image = 255.0 - image

    rough = texture_mask(image, 8.0)
    if not rough.any():
        raise ValueError("No ridge pattern found in this image.")
    period = float(ridge_period) if ridge_period else estimate_ridge_period(_local_normalize(image, 10.0), rough)

    rough = texture_mask(image, period) | rough
    norm = _local_normalize(image, max(2 * period, 8.0))
    norm[~rough] = 0
    orientation, coherence = orientation_field(norm, period)
    enhanced = gabor_enhance(norm, orientation, period, rough)
    mask = ridge_quality_mask(norm, enhanced, period, rough) & rough
    if not mask.any():
        mask = rough
    ridges = (enhanced > 0) & mask
    cores, deltas = find_singular_points(orientation, coherence, mask, period)
    for point in cores + deltas:
        point.x, point.y = snap_to_ridge(ridges, (point.x, point.y), 0.5 * period)
    return Analysis(gray, enhanced, ridges, mask, orientation, coherence, period, cores, deltas, light_ridges)


# ---------------------------------------------------------------------------
# Ridge counting
# ---------------------------------------------------------------------------

@dataclass
class RidgeCount:
    count: int
    start: tuple
    end: tuple
    crossings: list = field(default_factory=list)  # midpoint of each counted ridge
    excluded: list = field(default_factory=list)   # ridges touching an endpoint (not counted)


def _runs(on: np.ndarray) -> list:
    edges = np.diff(np.concatenate(([0], on.astype(np.int8), [0])))
    return list(zip(np.nonzero(edges == 1)[0].tolist(), (np.nonzero(edges == -1)[0] - 1).tolist()))


def count_ridges(ridges: np.ndarray, start, end, period: float, endpoint_tolerance: float = 0.0) -> RidgeCount:
    """Count ridges crossed by the straight line from start to end.

    Follows the Galton convention: every ridge crossing or touching the
    line counts, except the ridges the two end points themselves sit on
    (a ridge whose run comes within `endpoint_tolerance` px of an end).
    Specks up to 0.15 ridge periods long are ignored, then gaps up to 0.2
    periods are bridged (pores, small breaks); both are at least 1 px.
    """
    h, w = ridges.shape
    (x0, y0), (x1, y1) = start, end
    length = math.hypot(x1 - x0, y1 - y0)
    if length < 1:
        return RidgeCount(0, tuple(start), tuple(end))

    n = int(math.ceil(length / 0.5)) + 1
    t = np.linspace(0.0, 1.0, n)
    xs = np.floor(x0 + t * (x1 - x0) + 0.5).astype(int)
    ys = np.floor(y0 + t * (y1 - y0) + 0.5).astype(int)
    inside = (xs >= 0) & (xs < w) & (ys >= 0) & (ys < h)
    on = np.zeros(n, bool)
    on[inside] = ridges[ys[inside], xs[inside]]
    spacing = length / (n - 1)

    min_length, max_gap = max(1.0, 0.15 * period), max(1.0, 0.2 * period)
    runs = []
    for s, e in _runs(on):
        if (e - s + 1) * spacing <= min_length:
            continue
        if runs and (s - runs[-1][1] - 1) * spacing <= max_gap:
            runs[-1] = (runs[-1][0], e)
        else:
            runs.append((s, e))

    tolerance = endpoint_tolerance / spacing
    crossings, excluded = [], []
    for s, e in runs:
        mid = (s + e) // 2
        point = (int(xs[mid]), int(ys[mid]))
        (excluded if s <= tolerance or e >= n - 1 - tolerance else crossings).append(point)
    return RidgeCount(len(crossings), tuple(start), tuple(end), crossings, excluded)


def suggest_points(analysis: Analysis, core=None, delta=None):
    """Pick a core and delta that belong to the same finger.

    On a whole-hand scan the best core and the best delta can sit on
    different fingers, so a delta is paired with the nearest core (or the
    other way round when one point is already known). Either may be None.
    """
    reach = 30 * analysis.ridge_period

    def nearest(point, candidates):
        close = [c for c in candidates if math.hypot(c.x - point[0], c.y - point[1]) <= reach]
        best = min(close, key=lambda c: math.hypot(c.x - point[0], c.y - point[1]), default=None)
        return (best.x, best.y) if best else None

    if core is not None and delta is not None:
        return core, delta
    if core is not None:
        return core, nearest(core, analysis.deltas)
    if delta is not None:
        return nearest(delta, analysis.cores), delta
    for d in analysis.deltas:
        partner = nearest((d.x, d.y), analysis.cores)
        if partner:
            return partner, (d.x, d.y)
    first = analysis.cores[0] if analysis.cores else None
    return ((first.x, first.y) if first else None), None


def suggest_pattern(analysis: Analysis, core, delta=None, thumb_side: str = "left") -> str:
    """Best guess at a fingertip pattern, for the person to confirm.

    A second core within 20 ridge widths means a whorl. Otherwise a loop
    opens away from its delta, and it is radial if it opens toward the
    thumb side of the image, ulnar if toward the little finger.
    """
    if core is None:
        return "unknown"
    period = analysis.ridge_period
    for other in analysis.cores:
        if 2 * period < math.hypot(other.x - core[0], other.y - core[1]) <= 20 * period:
            return "whorl"
    if delta is None:
        return "unknown"
    opens_right = delta[0] < core[0]
    return "radial loop" if opens_right == (thumb_side == "right") else "ulnar loop"


def count_between(analysis: Analysis, core, delta) -> RidgeCount:
    return count_ridges(analysis.ridges, delta, core, analysis.ridge_period)


# ---------------------------------------------------------------------------
# Results: annotated image, report, CSV log
# ---------------------------------------------------------------------------

RIDGE_TINT = np.array((255, 150, 40), np.float32) if np is not None else None  # BGR


def make_base_image(analysis: Analysis, show_ridges: bool = True) -> np.ndarray:
    base = cv2.cvtColor(analysis.gray, cv2.COLOR_GRAY2BGR)
    if show_ridges:
        sel = analysis.ridges
        base[sel] = (0.5 * base[sel] + 0.5 * RIDGE_TINT).astype(np.uint8)
    return base


def render_overlay(analysis: Analysis, result: RidgeCount, labels=("delta", "core")) -> np.ndarray:
    image = make_base_image(analysis)
    h, w = image.shape[:2]
    font = cv2.FONT_HERSHEY_SIMPLEX
    # Markers scale with the ridge spacing so they never hide the ridges they mark.
    period = analysis.ridge_period
    r = max(2, int(round(0.3 * period)))
    thick = max(1, int(round(period / 10)))
    small = max(0.3, period / 22)
    cv2.line(image, result.start, result.end, (0, 215, 255), thick, cv2.LINE_AA)
    for p in result.excluded:
        cv2.circle(image, p, r, (170, 170, 170), thick, cv2.LINE_AA)
    for i, p in enumerate(result.crossings, start=1):
        cv2.circle(image, p, r, (60, 220, 60), -1, cv2.LINE_AA)
        cv2.putText(image, str(i), (p[0] + r + 1, p[1] - r), font, small, (40, 160, 40), thick, cv2.LINE_AA)
    for point, label, color in ((result.start, labels[0], (200, 60, 200)), (result.end, labels[1], (60, 60, 230))):
        cv2.circle(image, point, 2 * r, color, thick + 1, cv2.LINE_AA)
        cv2.putText(image, label, (point[0] + 2 * r + 3, point[1] + 3 * r), font, 1.4 * small, color, thick, cv2.LINE_AA)
    s = max(1.0, min(h, w) / 400)
    text = f"Ridge count: {result.count}"
    (tw, th), base = cv2.getTextSize(text, font, 0.7 * s, int(s) + 1)
    cv2.rectangle(image, (0, 0), (tw + 16, th + base + 16), (30, 30, 30), -1)
    cv2.putText(image, text, (8, th + 8), font, 0.7 * s, (60, 220, 60), int(s) + 1, cv2.LINE_AA)
    return image


def build_report(image_path, analysis: Analysis, result: RidgeCount, sources=None) -> dict:
    sources = sources or {}
    return {
        "image": str(image_path),
        "ridge_count": result.count,
        "core": list(result.end),
        "delta": list(result.start),
        "core_source": sources.get("core", "manual"),
        "delta_source": sources.get("delta", "manual"),
        "ridge_period_px": round(analysis.ridge_period, 2),
        "light_ridges": analysis.light_ridges,
        "counted_ridges_at": [list(p) for p in result.crossings],
        "endpoint_ridges_not_counted": [list(p) for p in result.excluded],
        "analyzed_at": datetime.now().isoformat(timespec="seconds"),
        "ridge_counter_version": __version__,
    }


@dataclass
class SavedFiles:
    annotated: Path
    report: Path
    log: Path


def save_results(folder, image_path, analysis: Analysis, result: RidgeCount, sources=None) -> SavedFiles:
    """Write <scan>_ridgecount.png and .json, and append a row to ridge_counts.csv."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    stem = Path(image_path).stem
    saved = SavedFiles(folder / f"{stem}_ridgecount.png", folder / f"{stem}_ridgecount.json", folder / "ridge_counts.csv")
    report = build_report(image_path, analysis, result, sources)

    write_image(saved.annotated, render_overlay(analysis, result))
    saved.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    new_log = not saved.log.exists()
    with saved.log.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if new_log:
            writer.writerow(CSV_FIELDS)
        writer.writerow([
            report["analyzed_at"], Path(image_path).name, result.count,
            report["core"][0], report["core"][1], report["delta"][0], report["delta"][1],
            report["core_source"], report["delta_source"], report["ridge_period_px"],
        ])
    return saved


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------

def _parse_point(text: str):
    try:
        x, y = (int(round(float(v))) for v in text.replace(" ", "").split(","))
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected X,Y (for example 120,85), got {text!r}") from None
    return x, y


def _parse_period(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected a number of pixels, got {text!r}") from None
    if not MIN_PERIOD <= value <= MAX_PERIOD:
        raise argparse.ArgumentTypeError(f"ridge period must be between {MIN_PERIOD:g} and {MAX_PERIOD:g} pixels")
    return value


def cli_main(argv) -> int:
    parser = argparse.ArgumentParser(
        prog="ridge_counter.py count",
        description="Count the ridges between the core and delta of a fingerprint "
                    "(or between two palm triradii) in a scan image.",
    )
    parser.add_argument("image", help="scan image (PNG, BMP, TIFF, JPEG, ...)")
    parser.add_argument("--core", type=_parse_point, metavar="X,Y", help="core position in pixels (auto-detected if omitted)")
    parser.add_argument("--delta", type=_parse_point, metavar="X,Y", help="delta / triradius position in pixels (auto-detected if omitted)")
    parser.add_argument("--light-ridges", action="store_true", help="the ridges are lighter than the valleys in this scan")
    parser.add_argument("--ridge-period", type=_parse_period, metavar="PX", help="ridge spacing in pixels (estimated automatically if omitted)")
    parser.add_argument("--output-dir", metavar="DIR", help="save an annotated image, a JSON report and a CSV row here")
    parser.add_argument("--json", action="store_true", help="print the full report as JSON")
    args = parser.parse_args(argv)

    try:
        analysis = analyze(read_image(args.image), args.light_ridges, args.ridge_period)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    core, delta = suggest_points(analysis, args.core, args.delta)
    points = {"core": core, "delta": delta}
    sources = {"core": "manual" if args.core else "auto", "delta": "manual" if args.delta else "auto"}
    for name in ("core", "delta"):
        if points[name] is None:
            print(f"error: couldn't find the {name} automatically; give it with --{name} X,Y", file=sys.stderr)
            return 1

    result = count_between(analysis, points["core"], points["delta"])
    info = sys.stderr if args.json else sys.stdout
    if args.output_dir:
        try:
            saved = save_results(args.output_dir, args.image, analysis, result, sources)
        except OSError as exc:
            print(f"error: couldn't save results: {exc}", file=sys.stderr)
            return 1
        print(f"Saved {saved.annotated}, {saved.report} and a row in {saved.log}", file=info)

    if args.json:
        print(json.dumps(build_report(args.image, analysis, result, sources), indent=2))
    else:
        print(f"Ridge count: {result.count}")
        print(f"Core:  {points['core'][0]},{points['core'][1]} ({sources['core']})")
        print(f"Delta: {points['delta'][0]},{points['delta'][1]} ({sources['delta']})")
        print(f"Ridge spacing: {analysis.ridge_period:.1f} px")
        if "auto" in sources.values():
            print("Note: auto-detected points can be wrong. Check the annotated image, or give --core/--delta.")
    return 0


USAGE = f"""Ridge Counter {__version__}

  python ridge_counter.py [SCAN]              open the point-and-click window
  python ridge_counter.py count SCAN [...]    count from the command line
                                              (python ridge_counter.py count --help)
"""


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] in (["-h"], ["--help"]):
        print(USAGE)
        return 0
    if argv[:1] == ["--version"]:
        print(__version__)
        return 0
    if argv[:1] == ["count"]:
        if np is None:
            print(f"Ridge Counter needs numpy and OpenCV. Install them with:\n  {INSTALL_COMMAND}", file=sys.stderr)
            return 1
        return cli_main(argv[1:])
    if len(argv) > 1 or (argv and argv[0].startswith("-")):
        print(USAGE, file=sys.stderr)
        return 2
    return gui_main(argv[0] if argv else None)


# ---------------------------------------------------------------------------
# Point-and-click window
# ---------------------------------------------------------------------------

POINT_COLORS = {"core": "#ff5252", "delta": "#e040fb", "a": "#ffab40", "b": "#ffab40", "d": "#ffab40", "t": "#40c4ff"}
MODE_POINTS = {"finger": ("core", "delta"), "palm": ("a", "b", "d", "t")}
POINT_LABELS = {"core": "Core", "delta": "Delta", "a": "a", "b": "b", "d": "d", "t": "t (axial)"}
IMAGE_FILETYPES = [
    ("Scan images", "*.png *.bmp *.tif *.tiff *.jpg *.jpeg *.jp2 *.pgm *.webp"),
    ("All files", "*.*"),
]
HELP_TEXT = "Left-click: place point   Drag a point: move it   Wheel: zoom   Right-drag: pan   F: fit"
SETTINGS_FILE = Path.home() / ".ridge_counter_settings.json"


def _typing(widget) -> bool:
    return isinstance(widget, (tk.Entry, tk.Text, ttk.Entry, ttk.Combobox, tk.Listbox))


def _number(text: str, kind):
    text = text.strip()
    if not text:
        return None
    try:
        return kind(float(text)) if kind is int else kind(text)
    except ValueError:
        return None


class RidgeCounterApp:
    HIT_RADIUS = 12

    def __init__(self, root, initial_image=None):
        self.root = root
        self.image_path = None
        self.analysis = None
        self.result = None
        self.atd = None
        self.points = {name: None for names in MODE_POINTS.values() for name in names}
        self.sources = dict(self.points)
        self.zoom = 1.0
        self.origin = (0.0, 0.0)  # image coordinates shown at the canvas's top-left
        self.user_moved_view = False
        self.dragging = None
        self.pan_start = None
        self.busy = False
        self._base_cache = None
        self._photo = None
        self._jobs = queue.Queue()

        self.measure = tk.StringVar(value="finger")
        self.place_mode = tk.StringVar(value="core")
        self.show_ridges = tk.BooleanVar(value=True)
        self.light_ridges = tk.BooleanVar(value=False)
        self.count_text = tk.StringVar(value="Ridge count: –")
        self.detail_text = tk.StringVar(value="")
        self.status_text = tk.StringVar(value="Open a scan to begin (Ctrl+O).")

        root.title(f"Ridge Counter {__version__}")
        root.geometry("1200x860")
        root.minsize(760, 560)
        root.report_callback_exception = self._report_error
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill="both", expand=True)
        self.count_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.count_tab, text="Ridge count")
        self._build_ui()
        self.records = None
        if dg is not None:
            self.records = RecordsUI(self)
        else:
            missing = ttk.Frame(self.notebook, padding=20)
            ttk.Label(missing, text="Child records need dermatoglyphics.py in the same folder as ridge_counter.py.").pack()
            self.notebook.add(missing, text="Child record")
        self._bind_events()
        self._poll_id = root.after(50, self._poll_jobs)
        root.bind("<Destroy>", lambda e: root.after_cancel(self._poll_id) if e.widget is root else None, add="+")
        if initial_image:
            root.after(200, lambda: self.open_image(initial_image))

    # -- layout ------------------------------------------------------------

    def _build_ui(self):
        tab = self.count_tab
        bar = ttk.Frame(tab, padding=(8, 6))
        bar.pack(side="top", fill="x")
        self.controls = []

        def button(parent, text, command):
            b = ttk.Button(parent, text=text, command=command)
            b.pack(side="left", padx=3)
            self.controls.append(b)
            return b

        def separator(parent):
            ttk.Separator(parent, orient="vertical").pack(side="left", fill="y", padx=8)

        button(bar, "Open scan…", self.open_dialog)
        separator(bar)
        ttk.Label(bar, text="Measure:").pack(side="left", padx=(0, 4))
        for value, label in (("finger", "Finger (core–delta)"), ("palm", "Palm (a, b, d, t)")):
            rb = ttk.Radiobutton(bar, text=label, value=value, variable=self.measure, command=self._on_measure_changed)
            rb.pack(side="left", padx=2)
            self.controls.append(rb)
        separator(bar)
        ttk.Label(bar, text="Click places:").pack(side="left", padx=(0, 4))
        self.place_frame = ttk.Frame(bar)
        self.place_frame.pack(side="left")
        self._build_place_buttons()
        separator(bar)
        button(bar, "Auto-detect", self.auto_detect)
        button(bar, "Clear points", self.clear_points)

        bar2 = ttk.Frame(tab, padding=(8, 0, 8, 4))
        bar2.pack(side="top", fill="x")
        for text, var, command in (
            ("Show ridges", self.show_ridges, self._on_show_ridges),
            ("Light ridges", self.light_ridges, self._on_light_ridges),
        ):
            cb = ttk.Checkbutton(bar2, text=text, variable=var, command=command)
            cb.pack(side="left", padx=3)
            self.controls.append(cb)
        separator(bar2)
        button(bar2, "Fit", self.fit_view)
        button(bar2, "Save results…", self.save_dialog)
        if dg is not None:
            separator(bar2)
            button(bar2, "Add to child record…", self.add_to_record)

        header = ttk.Frame(tab, padding=(12, 2))
        header.pack(side="top", fill="x")
        big = tkfont.nametofont("TkDefaultFont").copy()
        big.configure(size=20, weight="bold")
        ttk.Label(header, textvariable=self.count_text, font=big).pack(side="left")
        ttk.Label(header, textvariable=self.detail_text, foreground="#555555").pack(side="left", padx=14)

        ttk.Label(tab, text=HELP_TEXT, foreground="#777777", padding=(10, 0, 8, 6)).pack(side="bottom", anchor="w")
        footer = ttk.Frame(tab, padding=(8, 2, 8, 0))
        footer.pack(side="bottom", fill="x")
        self.progress = ttk.Progressbar(footer, mode="indeterminate", length=120)
        self.status_label = ttk.Label(footer, textvariable=self.status_text, anchor="w")
        self.status_label.pack(side="left", fill="x", expand=True)

        self.canvas = tk.Canvas(tab, background="#1e1e1e", highlightthickness=0, cursor="crosshair")
        self.canvas.pack(side="top", fill="both", expand=True, padx=8, pady=4)

    def _build_place_buttons(self):
        for child in self.place_frame.winfo_children():
            if child in self.controls:
                self.controls.remove(child)
            child.destroy()
        for name in MODE_POINTS[self.measure.get()]:
            rb = ttk.Radiobutton(self.place_frame, text=POINT_LABELS[name], value=name, variable=self.place_mode)
            rb.pack(side="left", padx=2)
            self.controls.append(rb)

    def _bind_events(self):
        c = self.canvas
        c.bind("<Configure>", lambda e: self._on_resize())
        c.bind("<ButtonPress-1>", self._on_press)
        c.bind("<B1-Motion>", self._on_drag)
        c.bind("<ButtonRelease-1>", self._on_release)
        for button in (2, 3):
            c.bind(f"<ButtonPress-{button}>", self._on_pan_start)
            c.bind(f"<B{button}-Motion>", self._on_pan_drag)
        c.bind("<MouseWheel>", lambda e: self._zoom_at(e.x, e.y, 1.25 if e.delta > 0 else 0.8))
        c.bind("<Button-4>", lambda e: self._zoom_at(e.x, e.y, 1.25))
        c.bind("<Button-5>", lambda e: self._zoom_at(e.x, e.y, 0.8))

        def on_count_tab(action):
            def handler(event):
                if self.notebook.select() == str(self.count_tab) and not _typing(event.widget):
                    action()
            return handler

        def choose(name):
            return lambda: self.place_mode.set(name) if name in MODE_POINTS[self.measure.get()] else None

        r = self.root
        r.bind("<Control-o>", lambda e: self.open_dialog())
        r.bind("<Control-s>", lambda e: self.records.save() if self.records and self.notebook.select() != str(self.count_tab) else self.save_dialog())
        r.bind("<Key-f>", on_count_tab(self.fit_view))
        r.bind("<Key-c>", on_count_tab(choose("core")))
        r.bind("<Key-d>", on_count_tab(lambda: self.place_mode.set("delta" if self.measure.get() == "finger" else "d")))
        r.bind("<Key-plus>", on_count_tab(lambda: self._zoom_center(1.25)))
        r.bind("<Key-equal>", on_count_tab(lambda: self._zoom_center(1.25)))
        r.bind("<Key-minus>", on_count_tab(lambda: self._zoom_center(0.8)))

    # -- background work ---------------------------------------------------

    def _start_job(self, work, on_done, message):
        self.busy = True
        self.status_text.set(message)
        self.progress.pack(side="left", padx=(0, 8), before=self.status_label)
        self.progress.start(12)
        for widget in self.controls:
            widget.state(["disabled"])

        def run():
            try:
                self._jobs.put((on_done, work(), None))
            except Exception as exc:  # reported in the window
                self._jobs.put((on_done, None, exc))

        threading.Thread(target=run, daemon=True).start()

    def _poll_jobs(self):
        try:
            while True:
                on_done, value, error = self._jobs.get_nowait()
                self.busy = False
                self.progress.stop()
                self.progress.pack_forget()
                for widget in self.controls:
                    widget.state(["!disabled"])
                if error is None:
                    on_done(value)
                else:
                    self.status_text.set("Couldn't analyze that scan.")
                    messagebox.showerror("Couldn't analyze the scan", str(error), parent=self.root)
        except queue.Empty:
            pass
        finally:
            self._poll_id = self.root.after(50, self._poll_jobs)

    # -- opening and analysis ---------------------------------------------

    def open_dialog(self):
        if self.busy:
            return
        path = filedialog.askopenfilename(parent=self.root, title="Open a fingerprint or palm scan", filetypes=IMAGE_FILETYPES)
        if path:
            self.notebook.select(self.count_tab)
            self.open_image(path)

    def open_image(self, path, keep_points=False):
        light = self.light_ridges.get()
        self._start_job(
            lambda: analyze(read_image(path), light_ridges=light),
            lambda analysis: self._on_analyzed(path, analysis, keep_points),
            f"Analyzing {Path(path).name}…",
        )

    def _on_analyzed(self, path, analysis, keep_points):
        new_image = path != self.image_path
        self.image_path = path
        self.analysis = analysis
        self._base_cache = None
        self.root.title(f"Ridge Counter – {Path(path).name}")
        if new_image or not keep_points:
            for name in MODE_POINTS["palm"]:
                self.points[name] = self.sources[name] = None
            self._apply_auto_points()
        if new_image:
            self.user_moved_view = False
            self.fit_view()
        self._recount()
        self._redraw()
        found = [n for n in ("core", "delta") if self.sources[n] == "auto"]
        message = f"Ridge spacing ≈ {analysis.ridge_period:.1f} px. "
        if len(found) == 2:
            message += "Core and delta were found automatically — check them and drag them if they're off."
        elif found:
            message += f"Found the {found[0]} automatically; click to place the other point."
        else:
            message += "Couldn't find the core and delta automatically — click on the image to place them."
        self.status_text.set(message)

    def _apply_auto_points(self, keep_manual=False):
        kept = {n: self.points[n] for n in ("core", "delta") if keep_manual and self.sources[n] == "manual"}
        core, delta = suggest_points(self.analysis, kept.get("core"), kept.get("delta"))
        for name, point in (("core", core), ("delta", delta)):
            if name not in kept:
                self.points[name], self.sources[name] = point, ("auto" if point else None)
        if self.measure.get() == "finger":
            self.place_mode.set("core" if self.points["core"] is None or self.points["delta"] is not None else "delta")

    def auto_detect(self):
        if self.analysis is None or self.busy:
            return
        if self.measure.get() == "palm":
            self.status_text.set("Palm triradii are placed by hand: click a, b, d and the axial triradius t.")
            return
        manual = [n for n in ("core", "delta") if self.sources[n] == "manual"]
        self._apply_auto_points(keep_manual=len(manual) == 1)
        self._recount()
        self._redraw(image_layer=False)
        if None in (self.points["core"], self.points["delta"]):
            self.status_text.set("Auto-detect couldn't find both points here — click on the image to place them.")
        elif len(manual) == 1:
            other = "delta" if manual[0] == "core" else "core"
            self.status_text.set(f"Kept your {manual[0]} and found the nearest {other} on the same finger.")
        else:
            self.status_text.set("Points reset to the automatic suggestions.")

    def clear_points(self):
        names = MODE_POINTS[self.measure.get()]
        for name in names:
            self.points[name] = self.sources[name] = None
        self.place_mode.set(names[0])
        self._recount()
        self._redraw(image_layer=False)

    def _on_measure_changed(self):
        names = MODE_POINTS[self.measure.get()]
        self._build_place_buttons()
        self.place_mode.set(next((n for n in names if self.points[n] is None), names[0]))
        if self.measure.get() == "palm":
            self.status_text.set("Palm: click triradii a and b (below the index and middle fingers), d (below the "
                                 "little finger) and the axial triradius t (near the wrist).")
        self._recount()
        self._redraw(image_layer=False)

    def _on_show_ridges(self):
        self._base_cache = None
        self._redraw()

    def _on_light_ridges(self):
        if self.image_path and not self.busy:
            self.open_image(self.image_path, keep_points=True)

    # -- counting ----------------------------------------------------------

    def _recount(self):
        self.result, self.atd = None, None
        if self.analysis is None:
            self.count_text.set("Ridge count: –")
            self.detail_text.set("")
            return
        p = self.points
        if self.measure.get() == "finger":
            if p["core"] and p["delta"]:
                self.result = count_between(self.analysis, p["core"], p["delta"])
                self.count_text.set(f"Ridge count: {self.result.count}")
                detail = "ridges between delta and core (ridges the points sit on are not counted)"
                if "auto" in (self.sources["core"], self.sources["delta"]):
                    detail += " · auto-detected points: please check"
                self.detail_text.set(detail)
            else:
                self.count_text.set("Ridge count: –")
                missing = [n for n in ("core", "delta") if p[n] is None]
                self.detail_text.set(f"Click on the image to place the {' and '.join(missing)}.")
            return
        parts = []
        if p["a"] and p["b"]:
            self.result = count_ridges(self.analysis.ridges, p["a"], p["b"], self.analysis.ridge_period)
            parts.append(f"a–b ridge count: {self.result.count}")
        if p["a"] and p["d"] and p["t"] and len({p["a"], p["d"], p["t"]}) == 3:
            self.atd = dg.atd_angle(p["a"], p["t"], p["d"]) if dg else None
            if self.atd is not None:
                parts.append(f"ATD angle: {self.atd:.0f}°")
        self.count_text.set("   ".join(parts) if parts else "Palm: –")
        missing = [POINT_LABELS[n] for n in MODE_POINTS["palm"] if p[n] is None]
        self.detail_text.set(f"Still to place: {', '.join(missing)}" if missing else
                             (dg.axial_triradius_position(self.atd) if dg and self.atd is not None else ""))

    # -- view geometry -------------------------------------------------------

    def _canvas_size(self):
        return max(self.canvas.winfo_width(), 1), max(self.canvas.winfo_height(), 1)

    def _to_canvas(self, x, y):
        ox, oy = self.origin
        return (x + 0.5 - ox) * self.zoom, (y + 0.5 - oy) * self.zoom

    def _to_image(self, cx, cy):
        ox, oy = self.origin
        h, w = self.analysis.gray.shape
        x = int(math.floor(ox + cx / self.zoom))
        y = int(math.floor(oy + cy / self.zoom))
        return min(max(x, 0), w - 1), min(max(y, 0), h - 1)

    def _fit_zoom(self):
        h, w = self.analysis.gray.shape
        cw, ch = self._canvas_size()
        return min(cw / w, ch / h)

    def fit_view(self):
        if self.analysis is None:
            return
        h, w = self.analysis.gray.shape
        cw, ch = self._canvas_size()
        self.zoom = self._fit_zoom()
        self.origin = ((w - cw / self.zoom) / 2, (h - ch / self.zoom) / 2)
        self.user_moved_view = False
        self._redraw()

    def _zoom_at(self, cx, cy, factor):
        if self.analysis is None:
            return
        new_zoom = min(max(self.zoom * factor, self._fit_zoom() * 0.5), 32.0)
        ix, iy = self.origin[0] + cx / self.zoom, self.origin[1] + cy / self.zoom
        self.zoom = new_zoom
        self.origin = (ix - cx / new_zoom, iy - cy / new_zoom)
        self.user_moved_view = True
        self._redraw()

    def _zoom_center(self, factor):
        cw, ch = self._canvas_size()
        self._zoom_at(cw / 2, ch / 2, factor)

    def _on_resize(self):
        if self.analysis is not None and not self.user_moved_view:
            self.fit_view()
        else:
            self._redraw()

    # -- mouse -------------------------------------------------------------

    def _point_under(self, cx, cy):
        best = None
        for name in MODE_POINTS[self.measure.get()]:
            point = self.points[name]
            if point is None:
                continue
            px, py = self._to_canvas(*point)
            distance = math.hypot(px - cx, py - cy)
            if distance <= self.HIT_RADIUS and (best is None or distance < best[0]):
                best = (distance, name)
        return best[1] if best else None

    def _on_press(self, event):
        if self.analysis is None or self.busy:
            return
        name = self._point_under(event.x, event.y)
        if name is None:
            name = self.place_mode.get()
            self._move_point(name, event.x, event.y)
            names = MODE_POINTS[self.measure.get()]
            missing = [n for n in names[names.index(name) + 1:] + names[:names.index(name)] if self.points[n] is None]
            if missing:
                self.place_mode.set(missing[0])
        self.dragging = name

    def _on_drag(self, event):
        if self.dragging and not self.busy:
            self._move_point(self.dragging, event.x, event.y)

    def _on_release(self, event):
        if self.dragging and self.result is not None and self.measure.get() == "finger":
            self.status_text.set(f"Core at {self.points['core']}, delta at {self.points['delta']}.")
        self.dragging = None

    def _move_point(self, name, cx, cy):
        self.points[name] = self._to_image(cx, cy)
        self.sources[name] = "manual"
        self._recount()
        self._redraw(image_layer=False)

    def _on_pan_start(self, event):
        self.pan_start = (event.x, event.y, self.origin)

    def _on_pan_drag(self, event):
        if self.analysis is None or self.pan_start is None:
            return
        sx, sy, (ox, oy) = self.pan_start
        self.origin = (ox - (event.x - sx) / self.zoom, oy - (event.y - sy) / self.zoom)
        self.user_moved_view = True
        self._redraw()

    # -- drawing -----------------------------------------------------------

    def _redraw(self, image_layer=True):
        c = self.canvas
        if image_layer:
            c.delete("image", "hint")
            if self.analysis is None:
                cw, ch = self._canvas_size()
                c.create_text(
                    cw / 2, ch / 2, fill="#bbbbbb", justify="center", tags="hint",
                    text="Open a fingerprint or palm scan to begin\n\n"
                         "Ctrl+O, or drag a scan onto “Ridge Counter.bat”",
                )
            else:
                self._draw_image()
        c.delete("overlay")
        if self.analysis is not None:
            self._draw_overlay()

    def _draw_image(self):
        if self._base_cache is None:
            self._base_cache = make_base_image(self.analysis, self.show_ridges.get())
        base = self._base_cache
        h, w = base.shape[:2]
        cw, ch = self._canvas_size()
        ox, oy = self.origin
        x0, y0 = max(0, int(math.floor(ox))), max(0, int(math.floor(oy)))
        x1, y1 = min(w, int(math.ceil(ox + cw / self.zoom))), min(h, int(math.ceil(oy + ch / self.zoom)))
        if x1 <= x0 or y1 <= y0:
            return
        size = (max(1, int(round((x1 - x0) * self.zoom))), max(1, int(round((y1 - y0) * self.zoom))))
        interpolation = cv2.INTER_AREA if self.zoom < 1 else cv2.INTER_NEAREST
        view = cv2.resize(base[y0:y1, x0:x1], size, interpolation=interpolation)
        ok, png = cv2.imencode(".png", view, [cv2.IMWRITE_PNG_COMPRESSION, 0])
        self._photo = tk.PhotoImage(data=png.tobytes())
        self.canvas.create_image((x0 - ox) * self.zoom, (y0 - oy) * self.zoom, anchor="nw", image=self._photo, tags="image")
        self.canvas.tag_lower("image")

    def _label(self, x, y, text, color, anchor):
        self.canvas.create_text(x + 1, y + 1, text=text, fill="#000000", anchor=anchor, tags="overlay")
        self.canvas.create_text(x, y, text=text, fill=color, anchor=anchor, tags="overlay")

    def _draw_overlay(self):
        c = self.canvas
        p = self.points
        if self.measure.get() == "finger":
            line = (p["delta"], p["core"])
        else:
            line = (p["a"], p["b"])
            for end in ("a", "d"):
                if p["t"] and p[end]:
                    c.create_line(*self._to_canvas(*p["t"]), *self._to_canvas(*p[end]),
                                  fill="#40c4ff", width=2, dash=(6, 4), tags="overlay")
        if line[0] and line[1]:
            c.create_line(*self._to_canvas(*line[0]), *self._to_canvas(*line[1]), fill="#ffd400", width=2, tags="overlay")
        if self.result is not None:
            for x, y in self.result.excluded:
                cx, cy = self._to_canvas(x, y)
                c.create_oval(cx - 5, cy - 5, cx + 5, cy + 5, outline="#bdbdbd", width=2, tags="overlay")
            for i, (x, y) in enumerate(self.result.crossings, start=1):
                cx, cy = self._to_canvas(x, y)
                c.create_oval(cx - 5, cy - 5, cx + 5, cy + 5, fill="#00e676", outline="#00391a", tags="overlay")
                self._label(cx + 9, cy - 9, str(i), "#00e676", "w")
        for name in MODE_POINTS[self.measure.get()]:
            point = p[name]
            if point is None:
                continue
            cx, cy = self._to_canvas(*point)
            color = POINT_COLORS[name]
            c.create_oval(cx - 9, cy - 9, cx + 9, cy + 9, outline=color, width=3, tags="overlay")
            c.create_line(cx - 14, cy, cx - 4, cy, fill=color, width=2, tags="overlay")
            c.create_line(cx + 4, cy, cx + 14, cy, fill=color, width=2, tags="overlay")
            c.create_line(cx, cy - 14, cx, cy - 4, fill=color, width=2, tags="overlay")
            c.create_line(cx, cy + 4, cx, cy + 14, fill=color, width=2, tags="overlay")
            label = POINT_LABELS[name] + (" (auto)" if self.sources[name] == "auto" else "")
            self._label(cx + 14, cy + 14, label, color, "nw")

    # -- saving ------------------------------------------------------------

    def save_dialog(self):
        if self.busy or self.analysis is None:
            return
        if self.measure.get() == "palm":
            self.status_text.set("Palm measurements are kept with the child record: use “Add to child record…”.")
            return
        if self.result is None:
            self.status_text.set("Place both the core and the delta before saving.")
            self.root.bell()
            return
        folder = filedialog.askdirectory(
            parent=self.root, title="Choose where to save the results",
            initialdir=str(Path(self.image_path).parent), mustexist=True,
        )
        if not folder:
            return
        try:
            saved = save_results(folder, self.image_path, self.analysis, self.result, self.sources)
        except OSError as exc:
            hint = "\n\nIf ridge_counts.csv is open in Excel, close it and try again." if isinstance(exc, PermissionError) else ""
            messagebox.showerror("Couldn't save the results", f"{exc}{hint}", parent=self.root)
            return
        self.status_text.set(
            f"Saved {saved.annotated.name} and {saved.report.name}, and added a row to {saved.log.name} in {saved.log.parent}"
        )

    def add_to_record(self):
        if self.analysis is None or self.busy or self.records is None:
            self.status_text.set("Open a scan and measure something first.")
            return
        if self.measure.get() == "finger":
            AddFingerDialog(self)
        else:
            AddPalmDialog(self)

    def _report_error(self, exc_type, exc, tb):
        details = "".join(traceback.format_exception(exc_type, exc, tb))
        messagebox.showerror("Something went wrong", f"{exc}\n\nDetails:\n{details[-1500:]}", parent=self.root)


class _Dialog:
    """Small modal form; subclasses fill `body` and implement `apply`."""

    def __init__(self, app, title):
        self.app = app
        self.top = tk.Toplevel(app.root)
        self.top.title(title)
        self.top.transient(app.root)
        self.top.resizable(False, False)
        self.body = ttk.Frame(self.top, padding=14)
        self.body.pack(fill="both", expand=True)
        self.row = 0

    def field(self, label, widget):
        ttk.Label(self.body, text=label).grid(row=self.row, column=0, sticky="w", pady=3, padx=(0, 10))
        widget.grid(row=self.row, column=1, sticky="we", pady=3)
        self.row += 1
        return widget

    def combo(self, label, values, value):
        var = tk.StringVar(value=value)
        self.field(label, ttk.Combobox(self.body, textvariable=var, values=values, state="readonly", width=34))
        return var

    def entry(self, label, value):
        var = tk.StringVar(value=value)
        self.field(label, ttk.Entry(self.body, textvariable=var, width=36))
        return var

    def finish(self, note=""):
        if note:
            ttk.Label(self.body, text=note, foreground="#666666", wraplength=380, justify="left").grid(
                row=self.row, column=0, columnspan=2, sticky="w", pady=(8, 0))
            self.row += 1
        buttons = ttk.Frame(self.body)
        buttons.grid(row=self.row, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(buttons, text="Cancel", command=self.top.destroy).pack(side="right")
        ttk.Button(buttons, text="Add", command=self._ok).pack(side="right", padx=(0, 8))
        self.top.bind("<Return>", lambda e: self._ok())
        self.top.bind("<Escape>", lambda e: self.top.destroy())
        self.top.grab_set()

    def _ok(self):
        message = self.apply()
        self.top.destroy()
        self.app.status_text.set(message)


class AddFingerDialog(_Dialog):
    def __init__(self, app):
        super().__init__(app, "Add finger to child record")
        self.hand = self.combo("Hand", dg.HANDS, "right")
        self.finger = self.combo("Finger", dg.FINGERS, "index")
        self.thumb_side = self.combo("In this image the thumb side is", ("left", "right"), "left")
        self.pattern = self.combo("Pattern", dg.PATTERNS, "unknown")
        count = app.result.count if app.result is not None else ""
        self.count = self.entry("Ridge count (larger one for a whorl)", str(count))
        self.hand.trace_add("write", lambda *a: self.thumb_side.set("left" if self.hand.get() == "right" else "right"))
        self.thumb_side.trace_add("write", lambda *a: self._suggest())
        self._suggest()
        self.finish("The pattern is a suggestion from the cores and deltas found near your core point - please check it. "
                    "Thumb side: on an ink or scanner print of a right hand the thumb is usually on the left.")

    def _suggest(self):
        p = self.app.points
        guess = suggest_pattern(self.app.analysis, p["core"], p["delta"], self.thumb_side.get())
        self.pattern.set(guess)

    def apply(self):
        key = f"{self.hand.get()} {self.finger.get()}"
        pattern = self.pattern.get()
        count = 0 if pattern == "arch" else _number(self.count.get(), int)
        self.app.records.set_finger(key, pattern, count, self.app.image_path)
        return f"Added {key}: {pattern}, ridge count {'–' if count is None else count}. Save the record in the Child record tab."


class AddPalmDialog(_Dialog):
    def __init__(self, app):
        super().__init__(app, "Add palm to child record")
        self.hand = self.combo("Hand", dg.HANDS, "right")
        atd = f"{app.atd:.1f}" if app.atd is not None else ""
        ab = str(app.result.count) if app.result is not None else ""
        self.atd = self.entry("ATD angle (degrees)", atd)
        self.ab = self.entry("a–b ridge count", ab)
        self.crease = self.combo("Palm crease", dg.CREASES, "unknown")
        self.finish("Palm creases are judged by eye: a single transverse (simian) crease runs right across the palm; "
                    "a Sydney line is the proximal crease reaching the edge of the palm.")

    def apply(self):
        hand = self.hand.get()
        self.app.records.set_palm(hand, _number(self.atd.get(), float), _number(self.ab.get(), int),
                                  self.crease.get(), self.app.image_path)
        return f"Added {hand} palm. Save the record in the Child record tab."


class RecordsUI:
    """The Child record and Model tabs."""

    def __init__(self, app):
        self.app = app
        self.store = dg.RecordStore(self._load_folder())
        self.model = self._load_model()
        self.record = dg.ChildRecord("")
        self.dirty = False
        self._loading = False
        self._build_record_tab()
        self._build_model_tab()
        self._show(self.record)
        self.refresh_model_tab()

    # -- settings & storage --------------------------------------------------

    @staticmethod
    def _load_folder():
        try:
            return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))["data_folder"]
        except (OSError, ValueError, KeyError):
            return dg.default_data_folder()

    def _load_model(self):
        try:
            return self.store.load_model()
        except (OSError, ValueError, TypeError, KeyError):
            return None

    # -- record tab ----------------------------------------------------------

    def _build_record_tab(self):
        tab = ttk.Frame(self.app.notebook, padding=10)
        self.app.notebook.add(tab, text="Child record")
        self.vars = []

        def var(value=""):
            v = tk.StringVar(value=value)
            v.trace_add("write", lambda *a: self._changed())
            self.vars.append(v)
            return v

        top = ttk.Frame(tab)
        top.pack(fill="x")
        self.child_id = var()
        self.label = var(dg.LABEL_UNKNOWN)
        self.sex = var("unknown")
        ttk.Label(top, text="Child ID").pack(side="left")
        self.id_entry = ttk.Entry(top, textvariable=self.child_id, width=18)
        self.id_entry.pack(side="left", padx=(4, 12))
        ttk.Label(top, text="Chromosome test result").pack(side="left")
        ttk.Combobox(top, textvariable=self.label, values=dg.LABELS, state="readonly", width=32).pack(side="left", padx=(4, 12))
        ttk.Label(top, text="Sex").pack(side="left")
        ttk.Combobox(top, textvariable=self.sex, values=dg.SEXES, state="readonly", width=9).pack(side="left", padx=(4, 12))
        for text, command in (("Save", self.save), ("Open…", self.open), ("New", self.new)):
            ttk.Button(top, text=text, command=command).pack(side="right", padx=3)
        self.title = tk.StringVar()
        ttk.Label(tab, textvariable=self.title, foreground="#555555").pack(anchor="w", pady=(4, 6))

        body = ttk.Frame(tab)
        body.pack(fill="both", expand=True)
        form = ttk.Frame(body)
        form.pack(side="left", fill="y", padx=(0, 12))

        fingers = ttk.LabelFrame(form, text="Fingertips", padding=8)
        fingers.pack(fill="x")
        for col, text in enumerate(("", "Right hand", "ridges", "Left hand", "ridges")):
            ttk.Label(fingers, text=text, foreground="#555555").grid(row=0, column=col, sticky="w", padx=3)
        self.finger_vars = {}
        for row, finger in enumerate(dg.FINGERS, start=1):
            ttk.Label(fingers, text=finger.capitalize()).grid(row=row, column=0, sticky="w", padx=3, pady=2)
            for i, hand in enumerate(dg.HANDS):
                pattern, count = var("unknown"), var()
                ttk.Combobox(fingers, textvariable=pattern, values=dg.PATTERNS, state="readonly", width=12).grid(
                    row=row, column=1 + 2 * i, padx=3, pady=2)
                ttk.Entry(fingers, textvariable=count, width=5).grid(row=row, column=2 + 2 * i, padx=3, pady=2)
                self.finger_vars[f"{hand} {finger}"] = (pattern, count)

        palms = ttk.LabelFrame(form, text="Palms", padding=8)
        palms.pack(fill="x", pady=8)
        for col, text in enumerate(("", "Crease", "ATD°", "a–b")):
            ttk.Label(palms, text=text, foreground="#555555").grid(row=0, column=col, sticky="w", padx=3)
        self.palm_vars = {}
        for row, hand in enumerate(dg.HANDS, start=1):
            crease, atd, ab = var("unknown"), var(), var()
            ttk.Label(palms, text=hand.capitalize()).grid(row=row, column=0, sticky="w", padx=3, pady=2)
            ttk.Combobox(palms, textvariable=crease, values=dg.CREASES, state="readonly", width=26).grid(row=row, column=1, padx=3)
            ttk.Entry(palms, textvariable=atd, width=6).grid(row=row, column=2, padx=3)
            ttk.Entry(palms, textvariable=ab, width=5).grid(row=row, column=3, padx=3)
            self.palm_vars[hand] = (crease, atd, ab)

        soles = ttk.LabelFrame(form, text="Soles (big-toe area)", padding=8)
        soles.pack(fill="x")
        self.foot_vars = {}
        for row, foot in enumerate(dg.HANDS):
            v = var("unknown")
            ttk.Label(soles, text=f"{foot.capitalize()} foot").grid(row=row, column=0, sticky="w", padx=3, pady=2)
            ttk.Combobox(soles, textvariable=v, values=dg.HALLUCAL, state="readonly", width=14).grid(row=row, column=1, padx=3)
            self.foot_vars[foot] = v

        notes = ttk.LabelFrame(form, text="Notes", padding=8)
        notes.pack(fill="x", pady=8)
        self.notes = var()
        ttk.Entry(notes, textvariable=self.notes, width=48).pack(fill="x")

        report = ttk.LabelFrame(body, text="Assessment (research aid - not a diagnosis)", padding=8)
        report.pack(side="left", fill="both", expand=True)
        self.report = tk.Text(report, wrap="word", height=20, relief="flat", background="#fafafa")
        self.report.pack(fill="both", expand=True)
        self.report.configure(state="disabled")

    def _show(self, record):
        self._loading = True
        self.child_id.set(record.child_id)
        self.label.set(record.label)
        self.sex.set(record.sex)
        self.notes.set(record.notes)
        for key, (pattern, count) in self.finger_vars.items():
            finger = record.fingers[key]
            pattern.set(finger.pattern)
            count.set("" if finger.ridge_count is None else str(finger.ridge_count))
        for hand, (crease, atd, ab) in self.palm_vars.items():
            palm = record.palms[hand]
            crease.set(palm.crease)
            atd.set("" if palm.atd_angle is None else f"{palm.atd_angle:g}")
            ab.set("" if palm.ab_ridge_count is None else str(palm.ab_ridge_count))
        for foot, v in self.foot_vars.items():
            v.set(record.feet[foot].hallucal)
        self._loading = False
        self._changed(dirty=False)

    def _read_form(self):
        r = self.record
        r.child_id = self.child_id.get().strip()
        r.label, r.sex, r.notes = self.label.get(), self.sex.get(), self.notes.get()
        for key, (pattern, count) in self.finger_vars.items():
            r.fingers[key] = dg.Finger(pattern.get(), _number(count.get(), int))
        for hand, (crease, atd, ab) in self.palm_vars.items():
            r.palms[hand] = dg.Palm(crease.get(), _number(atd.get(), float), _number(ab.get(), int))
        for foot, v in self.foot_vars.items():
            r.feet[foot] = dg.Foot(v.get())

    def _changed(self, dirty=True):
        if self._loading:
            return
        self._read_form()
        self.dirty = self.dirty or dirty
        name = self.record.child_id or "new child (no ID yet)"
        self.title.set(f"{name}{'  •  unsaved changes' if self.dirty else ''}"
                       f"{'  •  scans: ' + ', '.join(self.record.scans) if self.record.scans else ''}")
        text = dg.assess(self.record, self.model, self.store.counts())
        self.report.configure(state="normal")
        self.report.delete("1.0", "end")
        self.report.insert("end", text)
        self.report.configure(state="disabled")

    def _note_scan(self, path):
        if path and Path(path).name not in self.record.scans:
            self.record.scans.append(Path(path).name)

    def set_finger(self, key, pattern, count, scan):
        self._note_scan(scan)
        pattern_var, count_var = self.finger_vars[key]
        pattern_var.set(pattern)
        count_var.set("" if count is None else str(count))

    def set_palm(self, hand, atd, ab, crease, scan):
        self._note_scan(scan)
        crease_var, atd_var, ab_var = self.palm_vars[hand]
        if atd is not None:
            atd_var.set(f"{atd:.1f}")
        if ab is not None:
            ab_var.set(str(ab))
        if crease != "unknown":
            crease_var.set(crease)

    def _discard_ok(self):
        return not self.dirty or messagebox.askyesno(
            "Unsaved changes", "This child's record has unsaved changes. Discard them?", parent=self.app.root)

    def new(self):
        if self._discard_ok():
            self.record = dg.ChildRecord("")
            self.dirty = False
            self._show(self.record)

    def open(self):
        if not self._discard_ok():
            return
        path = filedialog.askopenfilename(parent=self.app.root, title="Open a child record",
                                          initialdir=str(self.store.children), filetypes=[("Child records", "*.json")])
        if not path:
            return
        try:
            self.record = dg.ChildRecord.from_json(json.loads(Path(path).read_text(encoding="utf-8")))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            messagebox.showerror("Couldn't open the record", str(exc), parent=self.app.root)
            return
        self.dirty = False
        self._show(self.record)
        self.app.notebook.select(self.app.notebook.tabs()[1])

    def save(self):
        self._read_form()
        try:
            path = self.store.save(self.record)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Couldn't save the record", str(exc), parent=self.app.root)
            return
        self.dirty = False
        self._changed(dirty=False)
        self.refresh_model_tab()
        self.app.status_text.set(f"Saved {path}")

    # -- model tab -----------------------------------------------------------

    def _build_model_tab(self):
        tab = ttk.Frame(self.app.notebook, padding=10)
        self.app.notebook.add(tab, text="Model")
        buttons = ttk.Frame(tab)
        buttons.pack(fill="x")
        for text, command in (("Train model", self.train), ("Export spreadsheet…", self.export),
                              ("Open data folder", self.open_folder), ("Change data folder…", self.change_folder)):
            ttk.Button(buttons, text=text, command=command).pack(side="left", padx=3)
        self.model_text = tk.Text(tab, wrap="word", relief="flat", background="#fafafa")
        self.model_text.pack(fill="both", expand=True, pady=(8, 0))

    def refresh_model_tab(self):
        counts = self.store.counts()
        text = (
            f"Data folder (stays on this computer): {self.store.folder}\n"
            f"Saved child records: {counts['with_ds']} with Down syndrome (confirmed), "
            f"{counts['without_ds']} without (confirmed), {counts['unknown']} not tested.\n\n"
            f"{dg.describe_model(self.model, counts)}\n\n"
            "How the model works: it learns from saved records whose chromosome test result is known, using "
            "the finger patterns, total ridge count, ATD angle, a–b ridge count, palm creases and sole pattern. "
            f"It needs at least {dg.MIN_PER_GROUP} children in each group before it will train, and it reports "
            "how it did on children it was not trained on. Records with no test result are never used for training.\n\n"
            + dg.DISCLAIMER
        )
        self.model_text.configure(state="normal")
        self.model_text.delete("1.0", "end")
        self.model_text.insert("end", text)
        self.model_text.configure(state="disabled")

    def train(self):
        try:
            self.model = dg.train(self.store.all())
        except dg.NotEnoughData as exc:
            messagebox.showinfo("Not enough data yet", str(exc), parent=self.app.root)
            return
        self.store.save_model(self.model)
        self.refresh_model_tab()
        self._changed(dirty=False)

    def export(self):
        path = filedialog.asksaveasfilename(parent=self.app.root, title="Export all records as a spreadsheet",
                                            defaultextension=".csv", initialfile="child_records.csv",
                                            filetypes=[("CSV spreadsheet", "*.csv")])
        if path:
            try:
                self.store.export_csv(path)
            except OSError as exc:
                messagebox.showerror("Couldn't export", str(exc), parent=self.app.root)
                return
            self.app.status_text.set(f"Exported {path}")

    def open_folder(self):
        folder = str(self.store.folder)
        if sys.platform == "win32":
            os.startfile(folder)
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", folder])

    def change_folder(self):
        folder = filedialog.askdirectory(parent=self.app.root, title="Choose the folder for child records")
        if not folder:
            return
        self.store = dg.RecordStore(folder)
        self.model = self._load_model()
        try:
            SETTINGS_FILE.write_text(json.dumps({"data_folder": folder}), encoding="utf-8")
        except OSError:
            pass  # the change still applies for this session
        self.refresh_model_tab()
        self._changed(dirty=False)


# ---------------------------------------------------------------------------
# First-run setup: install numpy + OpenCV without a terminal
# ---------------------------------------------------------------------------

def _no_console_flags() -> dict:
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def install_dependencies():
    """pip-install the required packages into this Python. Returns (ok, output)."""
    command = [sys.executable, "-m", "pip", "install", *REQUIRED_PACKAGES]
    try:
        proc = subprocess.run(command, capture_output=True, text=True, **_no_console_flags())
        output = proc.stdout + proc.stderr
        if proc.returncode != 0 and "No module named pip" in output:
            subprocess.run([sys.executable, "-m", "ensurepip", "--upgrade"], capture_output=True, text=True, **_no_console_flags())
            proc = subprocess.run(command, capture_output=True, text=True, **_no_console_flags())
            output = proc.stdout + proc.stderr
    except OSError as exc:
        return False, str(exc)
    return proc.returncode == 0, output


def run_setup_window(initial_image=None) -> int:
    root = tk.Tk()
    root.title("Ridge Counter – one-time setup")
    root.resizable(False, False)
    frame = ttk.Frame(root, padding=18)
    frame.pack(fill="both", expand=True)
    ttk.Label(
        frame, justify="left", wraplength=460,
        text="Ridge Counter needs two free Python add-ons, numpy and OpenCV.\n\n"
             "Install them now? This needs an internet connection and usually takes a minute or two.",
    ).pack(anchor="w")
    status = tk.StringVar(value="")
    ttk.Label(frame, textvariable=status, wraplength=460, justify="left").pack(anchor="w", pady=(12, 0))
    progress = ttk.Progressbar(frame, mode="indeterminate", length=460)
    details = tk.Text(frame, width=70, height=10, wrap="word")
    buttons = ttk.Frame(frame)
    buttons.pack(anchor="e", pady=(12, 0))
    results = queue.Queue()
    state = {"installed": False}

    def work():
        try:
            results.put(install_dependencies())
        except Exception as exc:  # shown in the window instead of hanging
            results.put((False, f"{type(exc).__name__}: {exc}"))

    def start():
        install_button.state(["disabled"])
        status.set("Installing… please wait.")
        details.pack_forget()
        progress.pack(pady=(8, 0), before=buttons)
        progress.start(12)
        threading.Thread(target=work, daemon=True).start()
        root.after(200, check)

    def check():
        try:
            ok, output = results.get_nowait()
        except queue.Empty:
            root.after(200, check)
            return
        progress.stop()
        progress.pack_forget()
        if ok:
            state["installed"] = True
            status.set("Done! Starting Ridge Counter…")
            root.after(800, root.destroy)
        else:
            status.set(f"The install didn't work. You can try again, or open a terminal and run:\n  {INSTALL_COMMAND}")
            details.delete("1.0", "end")
            details.insert("end", output[-4000:])
            details.pack(pady=(8, 0), before=buttons)
            install_button.state(["!disabled"])
            install_button.configure(text="Try again")

    install_button = ttk.Button(buttons, text="Install", command=start)
    install_button.pack(side="right")
    ttk.Button(buttons, text="Cancel", command=root.destroy).pack(side="right", padx=(0, 8))
    root.mainloop()

    if not state["installed"]:
        return 1
    relaunch(initial_image)
    return 0


def relaunch(initial_image=None):
    """Start a fresh copy of the app (so the newly installed packages load)."""
    subprocess.Popen([sys.executable, os.path.abspath(__file__), *([initial_image] if initial_image else [])])


def _enable_windows_dpi_awareness():
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass


def gui_main(initial_image=None) -> int:
    if tk is None:
        print(
            "This Python has no Tkinter, so the window can't open. Use the command line instead:\n"
            "  python ridge_counter.py count SCAN --core X,Y --delta X,Y",
            file=sys.stderr,
        )
        return 1
    _enable_windows_dpi_awareness()
    if np is None:
        return run_setup_window(initial_image)
    root = tk.Tk()
    RidgeCounterApp(root, initial_image)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
