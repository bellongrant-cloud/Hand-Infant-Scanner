import numpy as np
import pytest

from ridge_scanner.ridge_count import count_ridges_along_line


def make_stripe_skeleton(width=220, height=100, wavelength=20, phase=0.0):
    """Vertical ridge stripes: 1px-wide skeleton lines every `wavelength` px."""
    skeleton = np.zeros((height, width), dtype=bool)
    x = phase
    while x < width:
        xi = int(round(x))
        if 0 <= xi < width:
            skeleton[:, xi] = True
        x += wavelength
    return skeleton


@pytest.mark.parametrize("wavelength", [10, 15, 20, 25])
def test_horizontal_line_counts_vertical_stripes(wavelength):
    width, height = 220, 100
    skeleton = make_stripe_skeleton(width, height, wavelength=wavelength, phase=5)
    y = height // 2
    p0 = (0, y)
    p1 = (width - 1, y)

    result = count_ridges_along_line(skeleton, p0, p1)

    expected = len(range(5, width, wavelength))
    assert result.count == expected


def test_diagonal_line_counts_stripes_correctly():
    width, height = 200, 200
    skeleton = make_stripe_skeleton(width, height, wavelength=20, phase=5)
    p0 = (0, 0)
    p1 = (width - 1, height - 1)

    result = count_ridges_along_line(skeleton, p0, p1, band_half_width=1)

    # Diagonal line of length ~283px crossing vertical stripes spaced 20px
    # horizontally: it crosses roughly width/wavelength stripes.
    expected_min = width // 20 - 1
    expected_max = width // 20 + 1
    assert expected_min <= result.count <= expected_max


def test_no_ridges_gives_zero_count():
    skeleton = np.zeros((100, 100), dtype=bool)
    result = count_ridges_along_line(skeleton, (0, 50), (99, 50))
    assert result.count == 0


def test_single_ridge_crossing():
    skeleton = np.zeros((50, 50), dtype=bool)
    skeleton[:, 25] = True
    result = count_ridges_along_line(skeleton, (0, 25), (49, 25))
    assert result.count == 1


def test_exclude_px_ignores_endpoint_ridge():
    skeleton = np.zeros((50, 50), dtype=bool)
    # Ridge right at the start point and one in the middle.
    skeleton[:, 0] = True
    skeleton[:, 25] = True
    result_no_exclude = count_ridges_along_line(skeleton, (0, 25), (49, 25))
    assert result_no_exclude.count == 2

    result_excluded = count_ridges_along_line(skeleton, (0, 25), (49, 25), exclude_px=2)
    assert result_excluded.count == 1


def test_single_pixel_gap_does_not_double_count():
    """A skeleton ridge crossed at a shallow angle can leave a 1px break in
    the sampled hits; min_run_gap should bridge that so it isn't counted
    twice.
    """
    skeleton = np.zeros((50, 50), dtype=bool)
    skeleton[24:26, 25] = True
    skeleton[24:26, 27] = False
    # Simulate a near-miss: ridge pixels at x=25 and x=26 but not x=... this
    # test mainly exercises that a genuinely single, slightly-angled ridge
    # (contiguous except for a 1px dropout) is not split into two crossings.
    line = np.zeros((50, 50), dtype=bool)
    line[25, 20] = True
    line[25, 21] = False  # 1px gap
    line[25, 22] = True
    result = count_ridges_along_line(line, (18, 25), (24, 25), min_run_gap=1)
    assert result.count == 1
