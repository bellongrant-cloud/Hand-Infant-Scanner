#!/usr/bin/env python3
"""
Dermatoglyphic ridge-count tool — single-file version.

Computes a Galton-style ridge count (the standard dermatoglyphic
measurement used in palm/finger print research and genetic screening)
from a scanner image: the number of ridges crossed by a straight line
drawn between a delta (triradius) and a core (pattern center).

Pipeline
--------
1. Load + normalize the scan (brightness/contrast).
2. Segment the skin/ridge area from blank background.
3. Estimate local ridge orientation + frequency per block.
4. Gabor-filter the image tuned to local orientation/frequency to
   sharpen ridges and suppress noise.
5. Otsu-binarize and skeletonize to 1px-wide ridge lines.
6. Detect core/delta singular points via the Poincare index (auto,
   best-effort) or use manually supplied coordinates (recommended).
7. Walk the straight line from delta to core over the skeleton and
   count distinct ridge crossings.
8. Write an annotated image + JSON report so the count can be
   verified visually.

Usage
-----
    pip install numpy scipy opencv-python-headless scikit-image

    # Auto-detect core/delta (check the warnings + annotated image!)
    python ridge_count_standalone.py scan.png --output-dir out/

    # Manually specify core/delta (recommended for accuracy)
    python ridge_count_standalone.py scan.png --core 128,85 --delta 128,200 --output-dir out/

Accuracy notes
--------------
Automatic core/delta detection is the weakest link: it is sensitive to
image quality, especially on soft/smudged infant palm prints. Always
check the annotated output image before trusting an auto-detected
count; prefer manually marked points for anything used in a real
assessment. The ridge-counting step itself (given correct core/delta
points) is the accuracy-critical, well-tested part of this tool.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import cv2


# --------------------------------------------------------------------------
# Preprocessing: load, normalize, segment, enhance, binarize, skeletonize
# --------------------------------------------------------------------------

def load_grayscale(path: str) -> np.ndarray:
    """Load an image from a scanner as a float64 grayscale array in [0, 255]."""
    image = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise FileNotFoundError(f"Could not read image at {path!r}")
    return image.astype(np.float64)


def normalize(image: np.ndarray, target_mean: float = 100.0, target_var: float = 100.0) -> np.ndarray:
    """Normalize image mean/variance (Hong, Wan & Jain style normalization).

    Equalizes brightness/contrast differences between scanners without
    changing the ridge/valley structure.
    """
    mean = image.mean()
    var = image.var()
    if var == 0:
        return np.full_like(image, target_mean)
    normalized = target_mean + np.sign(image - mean) * np.sqrt(
        (target_var * (image - mean) ** 2) / var
    )
    return normalized


def segmentation_mask(image: np.ndarray, block_size: int = 16, threshold_ratio: float = 0.1) -> np.ndarray:
    """Estimate a foreground mask (skin/ridge area vs. blank background) using
    block-wise standard deviation: background regions of a scan are flat
    (low local variance) while ridged skin has texture.
    """
    h, w = image.shape
    mask = np.zeros_like(image, dtype=bool)
    stds, blocks = [], []
    for y in range(0, h, block_size):
        for x in range(0, w, block_size):
            block = image[y : y + block_size, x : x + block_size]
            if block.size == 0:
                continue
            stds.append(block.std())
            blocks.append((y, x))
    if not stds:
        return np.ones_like(image, dtype=bool)
    threshold = max(np.mean(stds) * threshold_ratio, 1e-6)
    for std, (y, x) in zip(stds, blocks):
        if std >= threshold:
            mask[y : y + block_size, x : x + block_size] = True
    mask_u8 = mask.astype(np.uint8) * 255
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (block_size, block_size))
    mask_u8 = cv2.morphologyEx(mask_u8, cv2.MORPH_CLOSE, kernel)
    mask_u8 = cv2.morphologyEx(mask_u8, cv2.MORPH_OPEN, kernel)
    return mask_u8 > 0


def compute_orientation_field(image: np.ndarray, block_size: int = 16, smooth_kernel: int = 5) -> np.ndarray:
    """Return a (blocks_y, blocks_x) array of ridge orientation angles in
    radians in [0, pi) — the direction *along* the ridge (gradient method,
    Hong/Wan/Jain, with doubled-angle smoothing to avoid 0/pi wrap-around).
    """
    gx = cv2.Sobel(image, cv2.CV_64F, 1, 0, ksize=3)
    gy = cv2.Sobel(image, cv2.CV_64F, 0, 1, ksize=3)

    h, w = image.shape
    blocks_y, blocks_x = h // block_size, w // block_size
    vx = np.zeros((blocks_y, blocks_x))
    vy = np.zeros((blocks_y, blocks_x))

    for by in range(blocks_y):
        for bx in range(blocks_x):
            y0, y1 = by * block_size, (by + 1) * block_size
            x0, x1 = bx * block_size, (bx + 1) * block_size
            block_gx = gx[y0:y1, x0:x1]
            block_gy = gy[y0:y1, x0:x1]
            vx[by, bx] = np.sum(2 * block_gx * block_gy)
            vy[by, bx] = np.sum(block_gx ** 2 - block_gy ** 2)

    if smooth_kernel > 1:
        vx = cv2.blur(vx, (smooth_kernel, smooth_kernel))
        vy = cv2.blur(vy, (smooth_kernel, smooth_kernel))

    theta = 0.5 * np.arctan2(vx, vy)
    orientation = (theta + np.pi / 2) % np.pi
    return orientation


def _peak_spacing(signal: np.ndarray, min_wavelength: float, max_wavelength: float) -> float | None:
    """Estimate the dominant spacing between local maxima of a 1-D signal."""
    if len(signal) < 5:
        return None
    smoothed = np.convolve(signal, np.ones(3) / 3.0, mode="same")
    peaks = [
        i for i in range(1, len(smoothed) - 1)
        if smoothed[i] > smoothed[i - 1] and smoothed[i] >= smoothed[i + 1]
    ]
    if len(peaks) < 2:
        return None
    spacings = np.diff(peaks)
    spacings = spacings[(spacings >= min_wavelength) & (spacings <= max_wavelength)]
    if len(spacings) == 0:
        return None
    return float(np.median(spacings))


def estimate_frequency_field(
    image: np.ndarray,
    orientation_field: np.ndarray,
    block_size: int = 16,
    window: int = 5,
    min_wavelength: float = 3.0,
    max_wavelength: float = 25.0,
) -> np.ndarray:
    """Estimate local ridge frequency (cycles/pixel) per block via the
    x-signature method: project along the ridge normal and find the
    spacing between successive peaks.
    """
    h, w = image.shape
    blocks_y, blocks_x = orientation_field.shape
    freq = np.zeros((blocks_y, blocks_x))

    for by in range(blocks_y):
        for bx in range(blocks_x):
            cy = by * block_size + block_size // 2
            cx = bx * block_size + block_size // 2
            theta = orientation_field[by, bx]
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


def gabor_enhance(
    image: np.ndarray,
    orientation_field: np.ndarray,
    frequency_field: np.ndarray,
    block_size: int,
    kernel_size: int = 15,
) -> np.ndarray:
    """Enhance ridges by convolving each block with a Gabor kernel tuned to
    that block's local ridge orientation and frequency.
    """
    h, w = image.shape
    out = np.zeros_like(image, dtype=np.float64)
    blocks_y, blocks_x = orientation_field.shape

    pad = kernel_size // 2
    padded = cv2.copyMakeBorder(image, pad, pad, pad, pad, cv2.BORDER_REFLECT)

    for by in range(blocks_y):
        for bx in range(blocks_x):
            freq = frequency_field[by, bx]
            if freq <= 0:
                continue
            theta = orientation_field[by, bx]
            wavelength = 1.0 / freq
            kernel = cv2.getGaborKernel(
                (kernel_size, kernel_size),
                sigma=kernel_size / 3.0,
                theta=theta + np.pi / 2,
                lambd=max(wavelength, 3.0),
                gamma=0.7,
                psi=0,
                ktype=cv2.CV_64F,
            )
            y0, y1 = by * block_size, min((by + 1) * block_size, h)
            x0, x1 = bx * block_size, min((bx + 1) * block_size, w)
            if y0 >= y1 or x0 >= x1:
                continue
            region = padded[y0 : y1 + 2 * pad, x0 : x1 + 2 * pad]
            filtered = cv2.filter2D(region, cv2.CV_64F, kernel)
            out[y0:y1, x0:x1] = filtered[pad : pad + (y1 - y0), pad : pad + (x1 - x0)]
    return out


def binarize(image: np.ndarray, mask: np.ndarray | None = None) -> np.ndarray:
    """Otsu-threshold the enhanced image into a boolean ridge mask (True = ridge)."""
    img_u8 = cv2.normalize(image, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    _, binary = cv2.threshold(img_u8, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    result = binary > 0
    if mask is not None:
        result &= mask
    return result


def skeletonize(binary: np.ndarray) -> np.ndarray:
    """Thin a binary ridge mask to 1-pixel-wide ridge lines."""
    from skimage.morphology import skeletonize as sk_skeletonize

    return sk_skeletonize(binary)


# --------------------------------------------------------------------------
# Singular points: core / delta detection via the Poincare index
# --------------------------------------------------------------------------

@dataclass
class SingularPoint:
    x: int
    y: int
    kind: str  # "core" or "delta"
    confidence: float


def _angle_diff(a1: float, a2: float) -> float:
    """Smallest signed difference a2 - a1, wrapped to (-pi/2, pi/2] for
    orientation angles that live in [0, pi).
    """
    diff = a2 - a1
    while diff > np.pi / 2:
        diff -= np.pi
    while diff <= -np.pi / 2:
        diff += np.pi
    return diff


def poincare_index(orientation_field: np.ndarray, by: int, bx: int) -> float:
    """Poincare index (in full turns: +0.5 = core, -0.5 = delta) around the
    8-neighborhood of block (by, bx).
    """
    neighbors = [
        (-1, -1), (-1, 0), (-1, 1),
        (0, 1), (1, 1), (1, 0),
        (1, -1), (0, -1),
    ]
    angles = [orientation_field[by + dy, bx + dx] for dy, dx in neighbors]
    total = sum(
        _angle_diff(angles[i], angles[(i + 1) % len(angles)]) for i in range(len(angles))
    )
    return total / (2 * np.pi)


def _cluster_points(points: list[SingularPoint], block_size: int) -> list[SingularPoint]:
    """Merge nearby same-kind candidates (within ~2.5 blocks) into one point."""
    clustered: list[SingularPoint] = []
    used = [False] * len(points)
    radius = block_size * 2.5

    for i, p in enumerate(points):
        if used[i]:
            continue
        cluster = [p]
        used[i] = True
        for j in range(i + 1, len(points)):
            if used[j] or points[j].kind != p.kind:
                continue
            q = points[j]
            if np.hypot(p.x - q.x, p.y - q.y) <= radius:
                cluster.append(q)
                used[j] = True
        best = max(cluster, key=lambda sp: sp.confidence)
        mean_x = int(np.mean([sp.x for sp in cluster]))
        mean_y = int(np.mean([sp.y for sp in cluster]))
        clustered.append(SingularPoint(mean_x, mean_y, p.kind, best.confidence))

    return clustered


def find_singular_points(
    orientation_field: np.ndarray,
    block_size: int,
    mask: np.ndarray | None = None,
    core_threshold: float = 0.4,
    delta_threshold: float = 0.4,
) -> list[SingularPoint]:
    """Scan the orientation field for core and delta candidates and cluster
    adjacent detections into single points.
    """
    blocks_y, blocks_x = orientation_field.shape
    raw_points: list[SingularPoint] = []

    for by in range(1, blocks_y - 1):
        for bx in range(1, blocks_x - 1):
            if mask is not None:
                cy = by * block_size + block_size // 2
                cx = bx * block_size + block_size // 2
                if cy >= mask.shape[0] or cx >= mask.shape[1] or not mask[cy, cx]:
                    continue
            index = poincare_index(orientation_field, by, bx)
            cy = by * block_size + block_size // 2
            cx = bx * block_size + block_size // 2
            if index >= core_threshold:
                raw_points.append(SingularPoint(cx, cy, "core", abs(index)))
            elif index <= -delta_threshold:
                raw_points.append(SingularPoint(cx, cy, "delta", abs(index)))

    return _cluster_points(raw_points, block_size)


def best_core_delta_pair(points: list[SingularPoint]) -> tuple[SingularPoint | None, SingularPoint | None]:
    """Pick the highest-confidence core and the highest-confidence delta."""
    cores = sorted((p for p in points if p.kind == "core"), key=lambda p: -p.confidence)
    deltas = sorted((p for p in points if p.kind == "delta"), key=lambda p: -p.confidence)
    return (cores[0] if cores else None), (deltas[0] if deltas else None)


# --------------------------------------------------------------------------
# Ridge counting: Galton-style crossings between two points on the skeleton
# --------------------------------------------------------------------------

@dataclass
class LineCountResult:
    count: int
    crossings: list[tuple[int, int]]
    line_points: list[tuple[int, int]]


def _line_points(p0: tuple[int, int], p1: tuple[int, int], step: float = 1.0) -> list[tuple[float, float]]:
    x0, y0 = p0
    x1, y1 = p1
    dist = float(np.hypot(x1 - x0, y1 - y0))
    n = max(int(round(dist / step)), 1)
    return [(x0 + (x1 - x0) * t / n, y0 + (y1 - y0) * t / n) for t in range(n + 1)]


def count_ridges_along_line(
    skeleton: np.ndarray,
    p0: tuple[int, int],
    p1: tuple[int, int],
    band_half_width: int = 1,
    exclude_px: float = 0.0,
    min_run_gap: int = 1,
) -> LineCountResult:
    """Count ridge crossings of the skeletonized ridge image along the
    straight segment from p0 to p1 (e.g. delta -> core).

    band_half_width: perpendicular tolerance (px) around the line, to
        bridge small alignment gaps between the straight line and the
        (possibly curved) skeleton ridge.
    exclude_px: length (in px) ignored at each end of the line, so the
        ridge the core/delta point itself sits on isn't counted.
    min_run_gap: consecutive "no ridge" samples bridged so a single ridge
        crossed at a shallow angle isn't split into two crossings.
    """
    h, w = skeleton.shape
    x0, y0 = p0
    x1, y1 = p1
    dist = float(np.hypot(x1 - x0, y1 - y0))
    if dist < 1e-6:
        return LineCountResult(0, [], [])

    dx, dy = (x1 - x0) / dist, (y1 - y0) / dist
    perp_x, perp_y = -dy, dx

    points = _line_points(p0, p1, step=1.0)
    n = len(points)

    start_idx = max(int(round((exclude_px / dist) * (n - 1))), 0) if dist > 0 else 0
    end_idx = min(n - 1 - start_idx, n - 1)

    hits = np.zeros(n, dtype=bool)
    for i, (px, py) in enumerate(points):
        for w_off in range(-band_half_width, band_half_width + 1):
            sx = int(round(px + w_off * perp_x))
            sy = int(round(py + w_off * perp_y))
            if 0 <= sx < w and 0 <= sy < h and skeleton[sy, sx]:
                hits[i] = True
                break

    if min_run_gap > 0:
        i = 0
        while i < n:
            if not hits[i]:
                j = i
                while j < n and not hits[j]:
                    j += 1
                gap = j - i
                if gap <= min_run_gap and i > 0 and j < n:
                    hits[i:j] = True
                i = j
            else:
                i += 1

    crossings: list[tuple[int, int]] = []
    in_run = False
    for i in range(start_idx, end_idx + 1):
        if hits[i] and not in_run:
            in_run = True
            px, py = points[i]
            crossings.append((int(round(px)), int(round(py))))
        elif not hits[i]:
            in_run = False

    return LineCountResult(
        count=len(crossings),
        crossings=crossings,
        line_points=[(int(round(px)), int(round(py))) for px, py in points],
    )


# --------------------------------------------------------------------------
# Pipeline: wires the stages above into one call
# --------------------------------------------------------------------------

@dataclass
class RidgeCountResult:
    count: int
    core: tuple[int, int]
    delta: tuple[int, int]
    core_confidence: float | None
    delta_confidence: float | None
    crossings: list[tuple[int, int]]
    line_points: list[tuple[int, int]]
    skeleton: np.ndarray
    orientation_field: np.ndarray
    block_size: int
    warnings: list[str] = field(default_factory=list)


def run_ridge_count(
    image_path: str,
    core: tuple[int, int] | None = None,
    delta: tuple[int, int] | None = None,
    block_size: int = 16,
    band_half_width: int = 1,
    exclude_px: float = 0.0,
) -> RidgeCountResult:
    warnings: list[str] = []

    raw = load_grayscale(image_path)
    normalized = normalize(raw)
    mask = segmentation_mask(normalized, block_size=block_size)

    orientation_field = compute_orientation_field(normalized, block_size=block_size)
    frequency_field = estimate_frequency_field(normalized, orientation_field, block_size=block_size)

    enhanced = gabor_enhance(normalized, orientation_field, frequency_field, block_size=block_size)
    binary = binarize(enhanced, mask=mask)
    skeleton = skeletonize(binary)

    core_conf = delta_conf = None

    if core is None or delta is None:
        candidates = find_singular_points(orientation_field, block_size=block_size, mask=mask)
        auto_core, auto_delta = best_core_delta_pair(candidates)

        if core is None:
            if auto_core is None:
                raise ValueError("Could not auto-detect a core point; pass --core X,Y explicitly.")
            core = (auto_core.x, auto_core.y)
            core_conf = auto_core.confidence
            warnings.append(f"Core auto-detected at {core} (confidence={core_conf:.2f}); verify visually.")
        if delta is None:
            if auto_delta is None:
                raise ValueError("Could not auto-detect a delta point; pass --delta X,Y explicitly.")
            delta = (auto_delta.x, auto_delta.y)
            delta_conf = auto_delta.confidence
            warnings.append(f"Delta auto-detected at {delta} (confidence={delta_conf:.2f}); verify visually.")

    line_result = count_ridges_along_line(
        skeleton, delta, core, band_half_width=band_half_width, exclude_px=exclude_px
    )

    return RidgeCountResult(
        count=line_result.count,
        core=core,
        delta=delta,
        core_confidence=core_conf,
        delta_confidence=delta_conf,
        crossings=line_result.crossings,
        line_points=line_result.line_points,
        skeleton=skeleton,
        orientation_field=orientation_field,
        block_size=block_size,
        warnings=warnings,
    )


# --------------------------------------------------------------------------
# Visualization
# --------------------------------------------------------------------------

def render_annotation(image_path: str, result: RidgeCountResult, out_path: str) -> None:
    base = cv2.imread(image_path, cv2.IMREAD_COLOR)
    if base is None:
        raise FileNotFoundError(image_path)

    overlay = base.copy()
    overlay[result.skeleton] = (255, 128, 0)  # BGR skeleton overlay

    cv2.line(overlay, result.delta, result.core, (0, 255, 255), 1, cv2.LINE_AA)

    cv2.circle(overlay, result.core, 5, (0, 0, 255), 2)
    cv2.putText(overlay, "core", (result.core[0] + 6, result.core[1]),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 255), 1, cv2.LINE_AA)

    cv2.circle(overlay, result.delta, 5, (255, 0, 255), 2)
    cv2.putText(overlay, "delta", (result.delta[0] + 6, result.delta[1]),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 0, 255), 1, cv2.LINE_AA)

    for i, (cx, cy) in enumerate(result.crossings, start=1):
        cv2.circle(overlay, (cx, cy), 3, (0, 255, 0), -1)
        cv2.putText(overlay, str(i), (cx + 3, cy - 3),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 255, 0), 1, cv2.LINE_AA)

    cv2.putText(overlay, f"ridge count: {result.count}", (10, 20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2, cv2.LINE_AA)

    cv2.imwrite(out_path, overlay)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _parse_point(s: str) -> tuple[int, int]:
    try:
        x_str, y_str = s.split(",")
        return int(x_str), int(y_str)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Expected 'X,Y', got {s!r}") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ridge_count_standalone.py",
        description=(
            "Compute a dermatoglyphic ridge count (core-to-delta) from a "
            "fingerprint/palm scanner image."
        ),
    )
    parser.add_argument("image", help="Path to the scanner image (PNG/BMP/TIFF/JPEG).")
    parser.add_argument("--core", type=_parse_point, default=None,
                         help="Core point as X,Y pixel coords. Auto-detected if omitted.")
    parser.add_argument("--delta", type=_parse_point, default=None,
                         help="Delta (triradius) point as X,Y pixel coords. Auto-detected if omitted.")
    parser.add_argument("--block-size", type=int, default=16, help="Orientation-field block size in px.")
    parser.add_argument("--band-half-width", type=int, default=1, help="Sampling band half-width in px.")
    parser.add_argument("--exclude-px", type=float, default=0.0, help="Px to exclude at each line endpoint.")
    parser.add_argument("--output-dir", default=None, help="Directory to write annotated image + JSON report.")
    parser.add_argument("--json", action="store_true", help="Print result as JSON to stdout.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        result = run_ridge_count(
            args.image,
            core=args.core,
            delta=args.delta,
            block_size=args.block_size,
            band_half_width=args.band_half_width,
            exclude_px=args.exclude_px,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    for w in result.warnings:
        print(f"warning: {w}", file=sys.stderr)

    report = {
        "ridge_count": result.count,
        "core": result.core,
        "delta": result.delta,
        "core_confidence": result.core_confidence,
        "delta_confidence": result.delta_confidence,
        "crossings": result.crossings,
    }

    if args.output_dir:
        out_dir = Path(args.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        render_annotation(args.image, result, str(out_dir / "annotated.png"))
        with open(out_dir / "report.json", "w") as f:
            json.dump(report, f, indent=2)
        print(f"wrote {out_dir / 'annotated.png'} and {out_dir / 'report.json'}")

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"Ridge count: {result.count}")
        print(f"Core: {result.core}  Delta: {result.delta}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
