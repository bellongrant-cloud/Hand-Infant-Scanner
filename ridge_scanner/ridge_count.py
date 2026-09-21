"""Galton-style ridge counting between two points (typically core & delta)
on a skeletonized ridge image.

The count is the number of ridges that the straight line segment between
the two points crosses -- the standard dermatoglyphic ridge-count
definition. Endpoints themselves (the core/delta singularities) are not
counted as ridges.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class RidgeCountResult:
    count: int
    crossings: list[tuple[int, int]]  # pixel coords of each counted crossing
    line_points: list[tuple[int, int]]


def _line_points(p0: tuple[int, int], p1: tuple[int, int], step: float = 1.0) -> list[tuple[float, float]]:
    x0, y0 = p0
    x1, y1 = p1
    dist = float(np.hypot(x1 - x0, y1 - y0))
    n = max(int(round(dist / step)), 1)
    return [
        (x0 + (x1 - x0) * t / n, y0 + (y1 - y0) * t / n)
        for t in range(n + 1)
    ]


def count_ridges_along_line(
    skeleton: np.ndarray,
    p0: tuple[int, int],
    p1: tuple[int, int],
    band_half_width: int = 1,
    exclude_px: float = 0.0,
    min_run_gap: int = 1,
) -> RidgeCountResult:
    """Count ridge crossings of the skeletonized ridge image along the
    straight segment from p0 to p1.

    Parameters
    ----------
    skeleton: boolean array, True where a 1px-wide ridge line exists.
    p0, p1: endpoint pixel coordinates as (x, y), e.g. delta and core.
    band_half_width: perpendicular half-width (in px) of the sampling band
        around the line; bridges small alignment gaps between the straight
        line and the (possibly curved) skeleton ridge.
    exclude_px: length (in px) to ignore at each end of the line, to avoid
        counting the ridge the core/delta point itself sits on.
    min_run_gap: minimum number of consecutive "no ridge" samples required
        to treat two ridge hits as separate crossings (bridges 1-pixel
        skeleton gaps so a single ridge isn't double-counted).
    """
    h, w = skeleton.shape
    x0, y0 = p0
    x1, y1 = p1
    dist = float(np.hypot(x1 - x0, y1 - y0))
    if dist < 1e-6:
        return RidgeCountResult(0, [], [])

    dx, dy = (x1 - x0) / dist, (y1 - y0) / dist
    perp_x, perp_y = -dy, dx

    points = _line_points(p0, p1, step=1.0)
    n = len(points)

    start_idx = int(round((exclude_px / dist) * (n - 1))) if dist > 0 else 0
    end_idx = n - 1 - start_idx
    start_idx = max(start_idx, 0)
    end_idx = min(end_idx, n - 1)

    hits = np.zeros(n, dtype=bool)
    for i, (px, py) in enumerate(points):
        for w_off in range(-band_half_width, band_half_width + 1):
            sx = int(round(px + w_off * perp_x))
            sy = int(round(py + w_off * perp_y))
            if 0 <= sx < w and 0 <= sy < h and skeleton[sy, sx]:
                hits[i] = True
                break

    # Bridge gaps shorter than min_run_gap so a single ridge crossed at a
    # shallow angle (which can produce a 1px skeleton break) isn't split
    # into two crossings.
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

    return RidgeCountResult(
        count=len(crossings),
        crossings=crossings,
        line_points=[(int(round(px)), int(round(py))) for px, py in points],
    )
