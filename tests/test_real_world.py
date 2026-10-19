"""Regression tests for problems found on real hand and finger scans."""
from types import SimpleNamespace

import cv2
import numpy as np

import ridge_counter as rc
from tests.synthetic import LOOP_PERIOD, sample_loop


def test_transparent_gaps_between_ridges_read_as_white_paper(tmp_path):
    scan, _ = sample_loop()
    rgba = np.zeros(scan.shape + (4,), np.uint8)  # transparent pixels are black underneath
    ink = scan < 140
    rgba[ink, :3] = scan[ink, None]
    rgba[ink, 3] = 255
    path = tmp_path / "transparent.png"
    cv2.imwrite(str(path), rgba)

    gray = rc.read_image(path)
    assert gray[~ink].min() == 255
    assert abs(rc.analyze(gray).ridge_period - LOOP_PERIOD) <= 1.0


def test_small_print_on_a_large_blank_page():
    scan, _ = sample_loop()
    page = np.full((1400, 1400), 255, np.uint8)  # the print covers about 6% of the page
    page[500:500 + scan.shape[0], 600:600 + scan.shape[1]] = scan
    analysis = rc.analyze(page)
    assert abs(analysis.ridge_period - LOOP_PERIOD) <= 1.0
    assert analysis.cores and analysis.deltas


def test_blotchy_ink_does_not_fool_the_ridge_spacing():
    scan, _ = sample_loop()
    h, w = scan.shape
    y, x = np.mgrid[0:h, 0:w]
    blotches = 60 * np.sin(2 * np.pi * x / 70) * np.sin(2 * np.pi * y / 55)  # dark/light patches ~30 px across
    blotchy = np.clip(scan.astype(np.float32) - np.maximum(blotches, 0), 0, 255).astype(np.uint8)
    assert abs(rc.analyze(blotchy).ridge_period - LOOP_PERIOD) <= 1.0


def test_detected_points_sit_on_a_ridge():
    analysis = rc.analyze(sample_loop()[0])
    for point in analysis.cores + analysis.deltas:
        assert analysis.ridges[point.y, point.x]


def test_snap_moves_only_short_distances():
    ridges = np.zeros((40, 40), bool)
    ridges[:, 20:23] = True
    assert rc.snap_to_ridge(ridges, (18, 10), 3) == (20, 10)
    assert rc.snap_to_ridge(ridges, (10, 10), 3) == (10, 10)
    assert rc.snap_to_ridge(ridges, (21, 10), 3) == (21, 10)


def test_points_are_paired_on_the_same_finger():
    point = lambda x, y: rc.SingularPoint(x, y, "", 1.0)  # noqa: E731
    hand = SimpleNamespace(
        ridge_period=7.0,
        cores=[point(1500, 520), point(300, 960)],   # best core is on another finger
        deltas=[point(230, 1070)],
    )
    assert rc.suggest_points(hand) == ((300, 960), (230, 1070))
    assert rc.suggest_points(hand, core=(1490, 530)) == ((1490, 530), None)
    assert rc.suggest_points(hand, delta=(1560, 640)) == ((1500, 520), (1560, 640))
