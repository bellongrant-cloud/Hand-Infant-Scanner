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
    """Read a scan as 8-bit grayscale. Works with non-ASCII Windows paths."""
    data = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE) if data.size else None
    if image is None:
        raise ValueError(f"Could not read {Path(path).name} as an image.")
    return image


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
    level = float(np.percentile(std, 95))
    if level < 1e-3:
        return np.zeros(image.shape, bool)
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
    while tile * 2 <= min(h, w) and tile < 256:
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
        if coverage >= min(0.8, best):
            spectrum = np.fft.fft2(norm[y:y + tile, x:x + tile] * window)
            power += spectrum.real ** 2 + spectrum.imag ** 2

    freqs = np.fft.fftfreq(tile)
    radius = np.rint(np.hypot(freqs[None, :], freqs[:, None]) * tile).astype(int).ravel()
    profile = np.bincount(radius, weights=power.ravel()) / np.maximum(np.bincount(radius), 1)
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
    s = max(1.0, min(h, w) / 400)
    thick = max(1, int(round(s)))
    r = max(3, int(round(4 * s)))
    font = cv2.FONT_HERSHEY_SIMPLEX
    cv2.line(image, result.start, result.end, (0, 215, 255), thick, cv2.LINE_AA)
    for p in result.excluded:
        cv2.circle(image, p, r, (170, 170, 170), thick, cv2.LINE_AA)
    for i, p in enumerate(result.crossings, start=1):
        cv2.circle(image, p, r, (60, 220, 60), -1, cv2.LINE_AA)
        cv2.putText(image, str(i), (p[0] + r + 2, p[1] - r), font, 0.4 * s, (60, 220, 60), thick, cv2.LINE_AA)
    for point, label, color in ((result.start, labels[0], (200, 60, 200)), (result.end, labels[1], (60, 60, 230))):
        cv2.circle(image, point, 2 * r, color, thick + 1, cv2.LINE_AA)
        cv2.putText(image, label, (point[0] + 2 * r + 3, point[1] + r), font, 0.5 * s, color, thick, cv2.LINE_AA)
    text = f"Ridge count: {result.count}"
    (tw, th), base = cv2.getTextSize(text, font, 0.7 * s, thick + 1)
    cv2.rectangle(image, (0, 0), (tw + 16, th + base + 16), (30, 30, 30), -1)
    cv2.putText(image, text, (8, th + 8), font, 0.7 * s, (60, 220, 60), thick + 1, cv2.LINE_AA)
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

    points, sources = {}, {}
    for name, given, found in (("core", args.core, analysis.cores), ("delta", args.delta, analysis.deltas)):
        if given is not None:
            points[name], sources[name] = given, "manual"
        elif found:
            points[name], sources[name] = (found[0].x, found[0].y), "auto"
        else:
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

POINT_COLORS = {"core": "#ff5252", "delta": "#e040fb"}
IMAGE_FILETYPES = [
    ("Scan images", "*.png *.bmp *.tif *.tiff *.jpg *.jpeg *.jp2 *.pgm *.webp"),
    ("All files", "*.*"),
]
HELP_TEXT = "Left-click: place point   Drag a point: move it   Wheel: zoom   Right-drag: pan   F: fit"


class RidgeCounterApp:
    HIT_RADIUS = 12

    def __init__(self, root, initial_image=None):
        self.root = root
        self.image_path = None
        self.analysis = None
        self.result = None
        self.points = {"core": None, "delta": None}
        self.sources = {"core": None, "delta": None}
        self.zoom = 1.0
        self.origin = (0.0, 0.0)  # image coordinates shown at the canvas's top-left
        self.user_moved_view = False
        self.dragging = None
        self.pan_start = None
        self.busy = False
        self._base_cache = None
        self._photo = None
        self._jobs = queue.Queue()

        self.place_mode = tk.StringVar(value="core")
        self.show_ridges = tk.BooleanVar(value=True)
        self.light_ridges = tk.BooleanVar(value=False)
        self.count_text = tk.StringVar(value="Ridge count: –")
        self.detail_text = tk.StringVar(value="")
        self.status_text = tk.StringVar(value="Open a scan to begin (Ctrl+O).")

        root.title(f"Ridge Counter {__version__}")
        root.geometry("1100x820")
        root.minsize(720, 520)
        root.report_callback_exception = self._report_error
        self._build_ui()
        self._bind_events()
        root.after(50, self._poll_jobs)
        if initial_image:
            root.after(200, lambda: self.open_image(initial_image))

    # -- layout ------------------------------------------------------------

    def _build_ui(self):
        bar = ttk.Frame(self.root, padding=(8, 6))
        bar.pack(side="top", fill="x")
        self.controls = []

        def button(text, command):
            b = ttk.Button(bar, text=text, command=command)
            b.pack(side="left", padx=3)
            self.controls.append(b)
            return b

        def separator():
            ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=8)

        button("Open scan…", self.open_dialog)
        separator()
        ttk.Label(bar, text="Click places:").pack(side="left", padx=(0, 4))
        for value, label in (("core", "Core"), ("delta", "Delta")):
            rb = ttk.Radiobutton(bar, text=label, value=value, variable=self.place_mode)
            rb.pack(side="left", padx=2)
            self.controls.append(rb)
        button("Auto-detect", self.auto_detect)
        button("Clear points", self.clear_points)
        separator()
        for text, var, command in (
            ("Show ridges", self.show_ridges, self._on_show_ridges),
            ("Light ridges", self.light_ridges, self._on_light_ridges),
        ):
            cb = ttk.Checkbutton(bar, text=text, variable=var, command=command)
            cb.pack(side="left", padx=3)
            self.controls.append(cb)
        separator()
        button("Fit", self.fit_view)
        button("Save results…", self.save_dialog)

        header = ttk.Frame(self.root, padding=(12, 2))
        header.pack(side="top", fill="x")
        big = tkfont.nametofont("TkDefaultFont").copy()
        big.configure(size=20, weight="bold")
        ttk.Label(header, textvariable=self.count_text, font=big).pack(side="left")
        ttk.Label(header, textvariable=self.detail_text, foreground="#555555").pack(side="left", padx=14)

        ttk.Label(self.root, text=HELP_TEXT, foreground="#777777", padding=(10, 0, 8, 6)).pack(side="bottom", anchor="w")
        footer = ttk.Frame(self.root, padding=(8, 2, 8, 0))
        footer.pack(side="bottom", fill="x")
        self.progress = ttk.Progressbar(footer, mode="indeterminate", length=120)
        self.status_label = ttk.Label(footer, textvariable=self.status_text, anchor="w")
        self.status_label.pack(side="left", fill="x", expand=True)

        self.canvas = tk.Canvas(self.root, background="#1e1e1e", highlightthickness=0, cursor="crosshair")
        self.canvas.pack(side="top", fill="both", expand=True, padx=8, pady=4)

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
        r = self.root
        r.bind("<Control-o>", lambda e: self.open_dialog())
        r.bind("<Control-s>", lambda e: self.save_dialog())
        r.bind("<Key-f>", lambda e: self.fit_view())
        r.bind("<Key-c>", lambda e: self.place_mode.set("core"))
        r.bind("<Key-d>", lambda e: self.place_mode.set("delta"))
        r.bind("<Key-plus>", lambda e: self._zoom_center(1.25))
        r.bind("<Key-equal>", lambda e: self._zoom_center(1.25))
        r.bind("<Key-minus>", lambda e: self._zoom_center(0.8))

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
            self.root.after(50, self._poll_jobs)

    # -- opening and analysis ---------------------------------------------

    def open_dialog(self):
        if self.busy:
            return
        path = filedialog.askopenfilename(parent=self.root, title="Open a fingerprint or palm scan", filetypes=IMAGE_FILETYPES)
        if path:
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

    def _apply_auto_points(self):
        for name, found in (("core", self.analysis.cores), ("delta", self.analysis.deltas)):
            if found:
                self.points[name], self.sources[name] = (found[0].x, found[0].y), "auto"
            else:
                self.points[name], self.sources[name] = None, None
        self.place_mode.set("core" if self.points["core"] is None or self.points["delta"] is not None else "delta")

    def auto_detect(self):
        if self.analysis is None or self.busy:
            return
        self._apply_auto_points()
        self._recount()
        self._redraw(image_layer=False)
        if None in self.points.values():
            self.status_text.set("Auto-detect couldn't find both points here — click on the image to place them.")
        else:
            self.status_text.set("Points reset to the automatic suggestions.")

    def clear_points(self):
        self.points = {"core": None, "delta": None}
        self.sources = {"core": None, "delta": None}
        self.place_mode.set("core")
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
        core, delta = self.points["core"], self.points["delta"]
        if self.analysis is not None and core and delta:
            self.result = count_between(self.analysis, core, delta)
            self.count_text.set(f"Ridge count: {self.result.count}")
            detail = "ridges between delta and core (ridges the points sit on are not counted)"
            if "auto" in self.sources.values():
                detail += " · auto-detected points: please check"
            self.detail_text.set(detail)
        else:
            self.result = None
            self.count_text.set("Ridge count: –")
            missing = [n for n in ("core", "delta") if self.points[n] is None]
            self.detail_text.set(f"Click on the image to place the {' and '.join(missing)}." if self.analysis else "")

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
        for name, point in self.points.items():
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
            other = "delta" if name == "core" else "core"
            if self.points[other] is None:
                self.place_mode.set(other)
        self.dragging = name

    def _on_drag(self, event):
        if self.dragging and not self.busy:
            self._move_point(self.dragging, event.x, event.y)

    def _on_release(self, event):
        if self.dragging and self.result is not None:
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
        core, delta = self.points["core"], self.points["delta"]
        if core and delta:
            c.create_line(*self._to_canvas(*delta), *self._to_canvas(*core), fill="#ffd400", width=2, tags="overlay")
        if self.result is not None:
            for x, y in self.result.excluded:
                cx, cy = self._to_canvas(x, y)
                c.create_oval(cx - 5, cy - 5, cx + 5, cy + 5, outline="#bdbdbd", width=2, tags="overlay")
            for i, (x, y) in enumerate(self.result.crossings, start=1):
                cx, cy = self._to_canvas(x, y)
                c.create_oval(cx - 5, cy - 5, cx + 5, cy + 5, fill="#00e676", outline="#00391a", tags="overlay")
                self._label(cx + 9, cy - 9, str(i), "#00e676", "w")
        for name, point in self.points.items():
            if point is None:
                continue
            cx, cy = self._to_canvas(*point)
            color = POINT_COLORS[name]
            c.create_oval(cx - 9, cy - 9, cx + 9, cy + 9, outline=color, width=3, tags="overlay")
            c.create_line(cx - 14, cy, cx - 4, cy, fill=color, width=2, tags="overlay")
            c.create_line(cx + 4, cy, cx + 14, cy, fill=color, width=2, tags="overlay")
            c.create_line(cx, cy - 14, cx, cy - 4, fill=color, width=2, tags="overlay")
            c.create_line(cx, cy + 4, cx, cy + 14, fill=color, width=2, tags="overlay")
            label = name.capitalize() + (" (auto)" if self.sources[name] == "auto" else "")
            self._label(cx + 14, cy + 14, label, color, "nw")

    # -- saving ------------------------------------------------------------

    def save_dialog(self):
        if self.busy or self.analysis is None:
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

    def _report_error(self, exc_type, exc, tb):
        details = "".join(traceback.format_exception(exc_type, exc, tb))
        messagebox.showerror("Something went wrong", f"{exc}\n\nDetails:\n{details[-1500:]}", parent=self.root)


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
