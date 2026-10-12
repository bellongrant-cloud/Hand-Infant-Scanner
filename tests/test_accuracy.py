"""Full pipeline on synthetic scans whose correct ridge counts are known."""
import math

import cv2
import numpy as np
import pytest

import ridge_counter as rc
from tests.synthetic import finger_mask, loop_field, rings_field, stripes_field, to_scan


@pytest.mark.parametrize("period", [5.0, 6.0, 8.0, 10.0, 13.0, 18.0])
@pytest.mark.parametrize("light_ridges", [False, True])
def test_concentric_rings_count_exactly(period, light_ridges):
    """Lines between valley centres at radius j*period and m*period cross m - j ridges."""
    size = int(period * 26)
    centre = (size / 2, size / 2)
    scan = to_scan(rings_field((size, size), period, centre), seed=int(period), noise=12, light_ridges=light_ridges)
    analysis = rc.analyze(scan, light_ridges=light_ridges)
    for angle in (0, 37, 90, 145, 230, 300):
        d = (math.cos(math.radians(angle)), math.sin(math.radians(angle)))
        for inner, outer in ((2, 9), (3, 11)):
            a = (round(centre[0] + inner * period * d[0]), round(centre[1] + inner * period * d[1]))
            b = (round(centre[0] + outer * period * d[0]), round(centre[1] + outer * period * d[1]))
            assert rc.count_between(analysis, b, a).count == outer - inner, f"angle {angle}, {inner}->{outer}"


@pytest.mark.parametrize("period", [6.0, 9.0, 14.0])
@pytest.mark.parametrize("angle", [0, 20, 65, 110])
def test_straight_ridges_count_exactly_at_any_crossing_angle(period, angle):
    size = int(period * 24)
    scan = to_scan(stripes_field((size, size), period, angle), seed=3, noise=14)
    analysis = rc.analyze(scan)
    normal = (math.cos(math.radians(angle)), math.sin(math.radians(angle)))
    crossed = 8
    for tilt in (0, 30, 55):
        d = (math.cos(math.radians(angle + tilt)), math.sin(math.radians(angle + tilt)))
        length = crossed * period / math.cos(math.radians(tilt))
        for on_ridge in (False, True):
            sx, sy = size / 2 - d[0] * length / 2, size / 2 - d[1] * length / 2
            u = sx * normal[0] + sy * normal[1]
            target = (math.floor(u / period) + (0.5 if on_ridge else 0.0)) * period
            sx, sy = sx + (target - u) * normal[0], sy + (target - u) * normal[1]
            start = (round(sx), round(sy))
            end = (round(sx + d[0] * length), round(sy + d[1] * length))
            expected = crossed - 1 if on_ridge else crossed  # ridges under both end points are not counted
            assert rc.count_ridges(analysis.ridges, start, end, analysis.ridge_period).count == expected, (
                f"tilt {tilt}, endpoints on ridges: {on_ridge}"
            )


def make_loop(period, seed, noise=12.0, blur=1.0):
    k = period / 9.0
    shape = (int(380 * k), int(320 * k))
    core, delta = (int(165 * k), int(150 * k)), (int(95 * k), int(265 * k))
    field = loop_field(shape, period, core, delta, seed=seed)
    mask = finger_mask(shape)
    scan = to_scan(field, seed=seed, noise=noise, blur=blur, mask=mask)
    visible = cv2.GaussianBlur(np.clip(field, -1, 1), (0, 0), blur) > 0
    return scan, visible, mask, core, delta


LOOP_CASES = [(9.0, 0), (9.0, 1), (9.0, 2), (6.0, 0), (12.0, 0)]


@pytest.mark.parametrize("period,seed", LOOP_CASES)
def test_finds_core_and_delta_on_loop_prints(period, seed):
    scan, _, _, core, delta = make_loop(period, seed)
    analysis = rc.analyze(scan)
    assert analysis.cores and analysis.deltas
    assert math.hypot(analysis.cores[0].x - core[0], analysis.cores[0].y - core[1]) <= period
    assert math.hypot(analysis.deltas[0].x - delta[0], analysis.deltas[0].y - delta[1]) <= period
    assert abs(analysis.ridge_period - period) <= 0.1 * period


def test_core_to_delta_counts_on_loop_prints():
    errors = []
    for period, seed in LOOP_CASES:
        scan, visible, _, core, delta = make_loop(period, seed)
        got = rc.count_between(rc.analyze(scan), core, delta).count
        errors.append(got - rc.count_ridges(visible, delta, core, period).count)
    assert max(abs(e) for e in errors) <= 1, errors
    assert sum(e == 0 for e in errors) >= len(errors) - 2, errors


def test_random_lines_on_loop_prints_match_visible_ridges():
    """Lines between points a person would pick: clearly on a ridge or clearly in a valley."""
    exact = within_one = total = 0
    for period in (6.0, 9.0, 12.0):
        for seed in range(3):
            scan, visible, mask, _, _ = make_loop(period, seed)
            analysis = rc.analyze(scan)
            inside = cv2.distanceTransform(visible.astype(np.uint8), cv2.DIST_L2, 5)
            outside = cv2.distanceTransform((~visible).astype(np.uint8), cv2.DIST_L2, 5)
            interior = cv2.erode(mask.astype(np.uint8), np.ones((int(4 * period) | 1,) * 2, np.uint8)) > 0
            candidates = np.argwhere(interior & (np.maximum(inside, outside) >= 0.22 * period))
            rng = np.random.default_rng(seed)
            for _ in range(30):
                (y0, x0), (y1, x1) = candidates[rng.integers(len(candidates), size=2)]
                if math.hypot(x1 - x0, y1 - y0) < 4 * period:
                    continue
                got = rc.count_ridges(analysis.ridges, (x0, y0), (x1, y1), analysis.ridge_period).count
                error = got - rc.count_ridges(visible, (x0, y0), (x1, y1), period).count
                total += 1
                exact += error == 0
                within_one += abs(error) <= 1
    assert exact / total >= 0.85, f"{exact}/{total} exact"
    assert within_one / total >= 0.98, f"{within_one}/{total} within one ridge"


def test_print_area_follows_the_finger():
    scan, _, mask, _, _ = make_loop(9.0, 0)
    analysis = rc.analyze(scan)
    assert (analysis.mask & mask).sum() >= 0.95 * mask.sum()
    assert (analysis.mask & ~mask).sum() <= 0.03 * mask.sum()


def test_faint_noisy_fine_ridges_are_not_thrown_away():
    scan, _, mask, _, _ = make_loop(6.0, 1, noise=25.0, blur=1.5)
    analysis = rc.analyze(scan)
    assert abs(analysis.ridge_period - 6.0) <= 0.6
    assert (analysis.mask & mask).sum() >= 0.8 * mask.sum()


def test_blank_or_tiny_images_are_rejected():
    with pytest.raises(ValueError):
        rc.analyze(np.full((200, 200), 200, np.uint8))
    with pytest.raises(ValueError):
        rc.analyze(np.zeros((20, 20), np.uint8))
