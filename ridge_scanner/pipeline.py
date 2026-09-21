"""End-to-end pipeline: scanner image -> preprocessing -> orientation field
-> (optional) singular point detection -> ridge count.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import preprocessing as pp
from . import orientation as ori
from . import singular_points as sp
from .ridge_count import count_ridges_along_line


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

    raw = pp.load_grayscale(image_path)
    normalized = pp.normalize(raw)
    mask = pp.segmentation_mask(normalized, block_size=block_size)

    orientation_field = ori.compute_orientation_field(normalized, block_size=block_size)
    frequency_field = ori.estimate_frequency_field(normalized, orientation_field, block_size=block_size)

    enhanced = pp.gabor_enhance(normalized, orientation_field, frequency_field, block_size=block_size)
    binary = pp.binarize(enhanced, mask=mask)
    skeleton = pp.skeletonize(binary)

    core_conf = delta_conf = None

    if core is None or delta is None:
        candidates = sp.find_singular_points(orientation_field, block_size=block_size, mask=mask)
        auto_core, auto_delta = sp.best_core_delta_pair(candidates)

        if core is None:
            if auto_core is None:
                raise ValueError(
                    "Could not auto-detect a core point; pass --core X,Y explicitly."
                )
            core = (auto_core.x, auto_core.y)
            core_conf = auto_core.confidence
            warnings.append(
                f"Core auto-detected at {core} (confidence={core_conf:.2f}); verify visually."
            )
        if delta is None:
            if auto_delta is None:
                raise ValueError(
                    "Could not auto-detect a delta point; pass --delta X,Y explicitly."
                )
            delta = (auto_delta.x, auto_delta.y)
            delta_conf = auto_delta.confidence
            warnings.append(
                f"Delta auto-detected at {delta} (confidence={delta_conf:.2f}); verify visually."
            )

    result = count_ridges_along_line(
        skeleton, delta, core, band_half_width=band_half_width, exclude_px=exclude_px
    )

    return RidgeCountResult(
        count=result.count,
        core=core,
        delta=delta,
        core_confidence=core_conf,
        delta_confidence=delta_conf,
        crossings=result.crossings,
        line_points=result.line_points,
        skeleton=skeleton,
        orientation_field=orientation_field,
        block_size=block_size,
        warnings=warnings,
    )
