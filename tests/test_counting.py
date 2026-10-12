"""The counting rule on hand-made ridge maps with obvious answers."""
import numpy as np
import pytest

from ridge_counter import count_ridges


def vertical_ridges(period, width=None, height=60):
    """Ridges centred at x = (k + 0.5) * period, half a period wide; valleys centred at x = k * period."""
    width = width or 30 * period
    x = np.arange(width)
    row = np.cos(2 * np.pi * x / period) < 0
    return np.tile(row, (height, 1))


@pytest.mark.parametrize("period", [6, 9, 12, 20])
def test_counts_every_ridge_between_valley_endpoints(period):
    ridges = vertical_ridges(period)
    result = count_ridges(ridges, (2 * period, 30), (12 * period, 30), period)
    assert result.count == 10
    assert result.excluded == []


@pytest.mark.parametrize("period", [6, 9, 12, 20])
def test_ridges_under_the_endpoints_are_not_counted(period):
    ridges = vertical_ridges(period)
    on_ridge = lambda k: int(k * period + period / 2)  # noqa: E731
    result = count_ridges(ridges, (on_ridge(2), 30), (on_ridge(12), 30), period)
    assert result.count == 9
    assert len(result.excluded) == 2


def test_direction_does_not_matter():
    ridges = vertical_ridges(10)
    forward = count_ridges(ridges, (20, 10), (150, 50), 10)
    backward = count_ridges(ridges, (150, 50), (20, 10), 10)
    assert forward.count == backward.count == 13


def test_diagonal_line_counts_ridges_it_crosses():
    ridges = vertical_ridges(10, width=300, height=300)
    result = count_ridges(ridges, (20, 10), (220, 290), 10)
    assert result.count == 20


def test_pore_inside_a_ridge_is_not_double_counted():
    ridges = vertical_ridges(10)
    ridges[30, 45] = False  # one-pixel hole in the ridge spanning x = 43..47
    assert count_ridges(ridges, (40, 30), (60, 30), 10).count == 2


def test_tiny_speck_in_a_valley_is_ignored():
    ridges = vertical_ridges(10)
    ridges[30, 50] = True  # valley centre
    assert count_ridges(ridges, (40, 30), (60, 30), 10).count == 2


def test_short_island_on_the_line_is_counted():
    ridges = np.zeros((40, 100), bool)
    ridges[18:23, 48:53] = True  # a dot about half a ridge period across
    assert count_ridges(ridges, (10, 20), (90, 20), 10).count == 1


def test_no_ridges_and_zero_length():
    empty = np.zeros((50, 50), bool)
    assert count_ridges(empty, (0, 25), (49, 25), 10).count == 0
    assert count_ridges(vertical_ridges(10), (25, 25), (25, 25), 10).count == 0


def test_line_partly_outside_the_image():
    ridges = vertical_ridges(10, width=100)
    result = count_ridges(ridges, (-40, 30), (40, 30), 10)
    assert result.count == 4
