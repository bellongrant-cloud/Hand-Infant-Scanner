"""Render an annotated overlay image so a human can visually verify the
detected core/delta points, the counting line, and each counted crossing.
"""
from __future__ import annotations

import numpy as np
import cv2

from .pipeline import RidgeCountResult


def render_annotation(image_path: str, result: RidgeCountResult, out_path: str) -> None:
    base = cv2.imread(image_path, cv2.IMREAD_COLOR)
    if base is None:
        raise FileNotFoundError(image_path)

    overlay = base.copy()
    skeleton_color = (255, 128, 0)  # blue-ish (BGR) skeleton overlay
    overlay[result.skeleton] = skeleton_color

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

    cv2.putText(
        overlay,
        f"ridge count: {result.count}",
        (10, 20),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (0, 255, 0),
        2,
        cv2.LINE_AA,
    )

    cv2.imwrite(out_path, overlay)
