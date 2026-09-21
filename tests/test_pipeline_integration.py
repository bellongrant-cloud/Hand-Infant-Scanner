"""End-to-end smoke test: a synthetic fingerprint-like image runs through
the full pipeline (preprocessing, orientation, singular points, ridge
counting) without crashing, and manual core/delta points give a sane count.
"""
import numpy as np
import cv2
import pytest

from ridge_scanner.pipeline import run_ridge_count


def make_synthetic_fingerprint(path, size=256, wavelength=10):
    """Loop-type fingerprint pattern: concentric-ish arcs around a core,
    with a delta below. Built from a sinusoidal ridge field so it has a
    real, known-ish ridge structure (not a mathematically perfect
    dermatoglyphic pattern, just enough texture to exercise the pipeline).
    """
    y, x = np.mgrid[0:size, 0:size]
    cx, cy = size / 2, size / 3
    dx, dy = x - cx, y - cy
    r = np.sqrt(dx ** 2 + dy ** 2)
    theta = np.arctan2(dy, dx)
    field = np.sin(2 * np.pi * r / wavelength + 1.5 * theta)
    image = (128 + 100 * field).astype(np.uint8)
    # Add mild noise to emulate scanner sensor noise.
    noise = np.random.default_rng(0).normal(0, 5, image.shape)
    image = np.clip(image.astype(np.float64) + noise, 0, 255).astype(np.uint8)
    cv2.imwrite(str(path), image)


@pytest.fixture
def synthetic_image(tmp_path):
    path = tmp_path / "synthetic_print.png"
    make_synthetic_fingerprint(path)
    return str(path)


def test_pipeline_runs_with_manual_points(synthetic_image):
    result = run_ridge_count(
        synthetic_image,
        core=(128, 85),
        delta=(128, 200),
    )
    assert result.count >= 0
    assert result.skeleton.dtype == bool
    assert result.core == (128, 85)
    assert result.delta == (128, 200)


def test_pipeline_auto_detects_or_raises_clean_error(synthetic_image):
    try:
        result = run_ridge_count(synthetic_image)
        assert result.count >= 0
        assert isinstance(result.core, tuple)
        assert isinstance(result.delta, tuple)
    except ValueError as exc:
        assert "auto-detect" in str(exc)
