"""Dermatoglyphic ridge-count pipeline for infant hand/finger scans."""

from .pipeline import RidgeCountResult, run_ridge_count

__all__ = ["RidgeCountResult", "run_ridge_count"]
