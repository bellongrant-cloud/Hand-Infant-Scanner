"""Synthetic ridge images with known ground truth, for accuracy tests.

Ridge "fields" are float arrays where values > 0 are ridges. `to_scan`
turns a field into a realistic-looking degraded grayscale scan.

Run `python -m tests.synthetic` to regenerate sample_data/.
"""
from __future__ import annotations

import math
from pathlib import Path

import cv2
import numpy as np


def rings_field(shape, period, center):
    """Concentric ridges at radii (k + 0.5) * period; the centre is a valley."""
    h, w = shape
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    r = np.hypot(x - center[0], y - center[1])
    return -np.cos(2 * np.pi * r / period)


def stripes_field(shape, period, angle_deg):
    """Straight parallel ridges whose normal points at angle_deg.

    Ridge centres sit at u = (k + 0.5) * period, valley centres at u = k * period,
    where u = x*cos(angle) + y*sin(angle).
    """
    h, w = shape
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    a = math.radians(angle_deg)
    u = x * math.cos(a) + y * math.sin(a)
    return -np.cos(2 * np.pi * u / period)


def _gabor(period, ridge_angle):
    sigma = 0.5 * period
    half = int(math.ceil(3 * sigma))
    y, x = np.mgrid[-half:half + 1, -half:half + 1].astype(np.float32)
    normal = ridge_angle + math.pi / 2
    u = x * math.cos(normal) + y * math.sin(normal)
    kernel = np.exp(-(x * x + y * y) / (2 * sigma * sigma)) * np.cos(2 * math.pi * u / period)
    return (kernel - kernel.mean()).astype(np.float32)


def loop_field(shape, period, core, delta, seed=0, iterations=12):
    """Loop-type print grown by orientation-guided filtering of noise.

    The orientation follows the zero-pole model, so the singular points sit
    exactly at `core` (index +1/2) and `delta` (index -1/2).
    """
    h, w = shape
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    theta = 0.5 * (np.arctan2(y - core[1], x - core[0]) - np.arctan2(y - delta[1], x - delta[0]))
    theta = np.mod(theta, np.pi)
    bins = np.rint(theta / (np.pi / 16)).astype(int) % 16
    kernels = [_gabor(period, b * np.pi / 16) for b in range(16)]
    field = np.random.default_rng(seed).standard_normal((h, w)).astype(np.float32)
    for _ in range(iterations):
        out = np.zeros_like(field)
        for b, kernel in enumerate(kernels):
            sel = bins == b
            out[sel] = cv2.filter2D(field, cv2.CV_32F, kernel, borderType=cv2.BORDER_REFLECT)[sel]
        field = np.tanh(2.5 * out / (out.std() + 1e-6))
    return field


def finger_mask(shape, margin=0.04):
    h, w = shape
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    cx, cy = w / 2, h * 0.55
    rx, ry = w * (0.5 - margin), h * (0.55 - margin)
    return ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1.0


def to_scan(field, seed=0, noise=12.0, blur=1.0, light_ridges=False, uneven=True, mask=None):
    """Render a ridge field as an 8-bit scan with dark (or light) ridges."""
    h, w = field.shape
    rng = np.random.default_rng(seed)
    f = np.clip(field, -1, 1)
    amplitude = np.full((h, w), 80.0, np.float32)
    brightness = np.full((h, w), 140.0, np.float32)
    if uneven:
        y, x = np.mgrid[0:h, 0:w].astype(np.float32)
        amplitude *= 0.55 + 0.45 * (x / w)
        brightness += 40 * (y / h) - 20
    sign = 1.0 if light_ridges else -1.0
    image = brightness + sign * amplitude * f
    if mask is not None:
        image = np.where(mask, image, 245.0)
    if blur:
        image = cv2.GaussianBlur(image, (0, 0), blur)
    image = image + rng.normal(0, noise, image.shape)
    return np.clip(image, 0, 255).astype(np.uint8)


LOOP_SHAPE = (380, 320)
LOOP_PERIOD = 9.0
LOOP_CORE = (165, 150)
LOOP_DELTA = (95, 265)


def sample_loop(seed=0):
    """(scan, clean_field) for the sample loop print."""
    field = loop_field(LOOP_SHAPE, LOOP_PERIOD, LOOP_CORE, LOOP_DELTA, seed=seed)
    mask = finger_mask(LOOP_SHAPE)
    return to_scan(field, seed=seed, mask=mask), field


if __name__ == "__main__":
    out = Path(__file__).resolve().parent.parent / "sample_data"
    out.mkdir(exist_ok=True)
    scan, _ = sample_loop()
    cv2.imwrite(str(out / "sample_loop.png"), scan)
    print(f"wrote {out / 'sample_loop.png'}")
