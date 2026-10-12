"""Smoke test for the point-and-click GUI's core logic (not the window
chrome): loading an image, placing core/delta by simulated clicks, running
the pipeline, and producing a savable report. Skipped automatically on
environments without Tkinter (e.g. minimal CI containers) rather than
failing the suite.
"""
import json
import os
import sys
import tempfile
from types import SimpleNamespace

import pytest

tk = pytest.importorskip("tkinter")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ridge_count_gui import RidgeCountApp  # noqa: E402


def _make_app():
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"no display available for Tk: {exc}")
    return root, RidgeCountApp(root)


def test_click_mark_count_and_save(tmp_path):
    root, app = _make_app()
    try:
        demo_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "sample_data",
            "synthetic_demo.png",
        )
        import cv2

        image = cv2.imread(demo_path, cv2.IMREAD_COLOR)
        assert image is not None
        app.image_path = demo_path
        app.original_bgr = image
        app._render(image)

        app.set_mark_mode("core")
        app.on_canvas_click(SimpleNamespace(x=int(128 * app.display_scale), y=int(85 * app.display_scale)))
        app.set_mark_mode("delta")
        app.on_canvas_click(SimpleNamespace(x=int(128 * app.display_scale), y=int(200 * app.display_scale)))

        assert app.core_point == (128, 85)
        assert app.delta_point == (128, 200)

        app.count_ridges()
        assert app.last_result is not None
        assert app.last_result.count > 0
        assert "Ridge count:" in app.result_var.get()

        import tkinter.filedialog as fd

        out_dir = str(tmp_path)
        fd.askdirectory = lambda **kwargs: out_dir
        import tkinter.messagebox as mb

        mb.showinfo = lambda *a, **k: None
        app.save_results()

        assert os.path.exists(os.path.join(out_dir, "annotated.png"))
        with open(os.path.join(out_dir, "report.json")) as f:
            report = json.load(f)
        assert report["ridge_count"] == app.last_result.count
    finally:
        root.destroy()
