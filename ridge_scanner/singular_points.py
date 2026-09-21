"""Core / delta (singular point) detection via the Poincare index method.

Automatic singular-point detection is a best-effort assist: it is noisy on
partial, low-contrast, or heavily smudged infant palm/finger scans. The CLI
lets an operator override these with manually marked coordinates, which is
standard practice in dermatoglyphic ridge counting.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


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
    """Poincare index (in units of full turns, e.g. +0.5 = core, -0.5 = delta)
    around the 8-neighborhood of block (by, bx).
    """
    neighbors = [
        (-1, -1), (-1, 0), (-1, 1),
        (0, 1), (1, 1), (1, 0),
        (1, -1), (0, -1),
    ]
    angles = [orientation_field[by + dy, bx + dx] for dy, dx in neighbors]
    total = 0.0
    for i in range(len(angles)):
        total += _angle_diff(angles[i], angles[(i + 1) % len(angles)])
    return total / (2 * np.pi)


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


def _cluster_points(points: list[SingularPoint], block_size: int) -> list[SingularPoint]:
    """Merge nearby same-kind candidates (within ~2 blocks) into one point,
    keeping the highest-confidence member's location.
    """
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


def best_core_delta_pair(points: list[SingularPoint]) -> tuple[SingularPoint | None, SingularPoint | None]:
    """Pick the highest-confidence core and the highest-confidence delta."""
    cores = sorted([p for p in points if p.kind == "core"], key=lambda p: -p.confidence)
    deltas = sorted([p for p in points if p.kind == "delta"], key=lambda p: -p.confidence)
    core = cores[0] if cores else None
    delta = deltas[0] if deltas else None
    return core, delta
