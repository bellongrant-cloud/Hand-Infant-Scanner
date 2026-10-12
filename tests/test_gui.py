"""Drives the window with real mouse events. Skipped without Tkinter or a display."""
import time
from pathlib import Path

import pytest

tk = pytest.importorskip("tkinter")

import ridge_counter as rc  # noqa: E402

SAMPLE = Path(__file__).resolve().parent.parent / "sample_data" / "sample_loop.png"


@pytest.fixture
def app():
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"no display: {exc}")
    root.geometry("1000x760")
    window = rc.RidgeCounterApp(root)
    root.update()
    yield window
    root.destroy()


def settle(app, timeout=30):
    end = time.time() + timeout
    while app.busy and time.time() < end:
        app.root.update()
        time.sleep(0.01)
    app.root.update()


def open_sample(app):
    app.open_image(str(SAMPLE))
    settle(app)
    assert app.analysis is not None


def press(app, sequence, x, y, **kw):
    app.canvas.event_generate(sequence, x=int(x), y=int(y), **kw)


def click_image(app, x, y):
    cx, cy = app._to_canvas(x, y)
    press(app, "<ButtonPress-1>", cx, cy)
    press(app, "<ButtonRelease-1>", cx, cy)
    app.root.update()


def test_opening_a_scan_suggests_points_and_counts(app):
    open_sample(app)
    assert app.sources == {"core": "auto", "delta": "auto"}
    assert app.count_text.get() == f"Ridge count: {app.result.count}"
    assert app.canvas.find_withtag("image") and app.canvas.find_withtag("overlay")


def test_click_to_place_both_points_then_drag(app):
    open_sample(app)
    app.clear_points()
    click_image(app, 165, 150)
    assert app.place_mode.get() == "delta"
    click_image(app, 95, 265)
    assert app.sources == {"core": "manual", "delta": "manual"}
    assert abs(app.points["core"][0] - 165) <= 1 and abs(app.points["delta"][1] - 265) <= 1
    assert app.result.count == rc.count_between(app.analysis, app.points["core"], app.points["delta"]).count

    core, before = app.points["core"], app.points["delta"]
    cx, cy = app._to_canvas(*before)
    press(app, "<ButtonPress-1>", cx, cy)
    press(app, "<B1-Motion>", cx + 40, cy, state=0x100)
    press(app, "<ButtonRelease-1>", cx + 40, cy)
    app.root.update()
    assert app.points["delta"][0] > before[0] + 10
    assert app.points["core"] == core
    assert app.result.count == rc.count_between(app.analysis, core, app.points["delta"]).count


def test_zooming_keeps_the_point_under_the_cursor(app):
    open_sample(app)
    cx, cy = app._to_canvas(*app.points["core"])
    zoom = app.zoom
    for _ in range(3):
        app._zoom_at(cx, cy, 1.25)
    assert app.zoom > zoom * 1.9
    nx, ny = app._to_canvas(*app.points["core"])
    assert abs(nx - cx) < 1 and abs(ny - cy) < 1


def test_save_writes_image_report_and_log(app, tmp_path, monkeypatch):
    open_sample(app)
    monkeypatch.setattr(rc.filedialog, "askdirectory", lambda **kwargs: str(tmp_path))
    app.save_dialog()
    app.save_dialog()
    assert (tmp_path / "sample_loop_ridgecount.png").exists()
    assert (tmp_path / "sample_loop_ridgecount.json").exists()
    assert len((tmp_path / "ridge_counts.csv").read_text(encoding="utf-8").strip().splitlines()) == 3


def test_unreadable_file_shows_an_error(app, tmp_path, monkeypatch):
    errors = []
    monkeypatch.setattr(rc.messagebox, "showerror", lambda *args, **kwargs: errors.append(args))
    broken = tmp_path / "broken.png"
    broken.write_text("not an image")
    app.open_image(str(broken))
    settle(app)
    assert errors and "Could not read" in errors[0][1]
