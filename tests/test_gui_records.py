"""Palm measurements, child records and the model tab, driven through the window."""
import time
from pathlib import Path

import pytest

tk = pytest.importorskip("tkinter")

import dermatoglyphics as dg  # noqa: E402
import ridge_counter as rc  # noqa: E402

SAMPLE = Path(__file__).resolve().parent.parent / "sample_data" / "sample_loop.png"


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(rc, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(dg, "default_data_folder", lambda: tmp_path / "data")
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"no display: {exc}")
    root.geometry("1200x860")
    window = rc.RidgeCounterApp(root)
    root.update()
    window.open_image(str(SAMPLE))
    end = time.time() + 30
    while (window.busy or window.analysis is None) and time.time() < end:
        root.update()
        time.sleep(0.01)
    root.update()
    yield window
    root.destroy()


def click(app, x, y):
    cx, cy = app._to_canvas(x, y)
    app.canvas.event_generate("<ButtonPress-1>", x=int(cx), y=int(cy))
    app.canvas.event_generate("<ButtonRelease-1>", x=int(cx), y=int(cy))
    app.root.update()


def test_palm_mode_measures_atd_angle_and_ab_count(app):
    app.measure.set("palm")
    app._on_measure_changed()
    assert app.place_mode.get() == "a"
    spots = {"a": (60, 120), "b": (200, 110), "d": (270, 160), "t": (160, 330)}
    for name in ("a", "b", "d", "t"):
        click(app, *spots[name])
    placed = {n: app.points[n] for n in spots}
    expected = dg.atd_angle(placed["a"], placed["t"], placed["d"])
    assert app.atd == pytest.approx(expected)
    assert f"ATD angle: {expected:.0f}°" in app.count_text.get()
    assert app.result.count == rc.count_ridges(app.analysis.ridges, placed["a"], placed["b"], app.analysis.ridge_period).count

    app.measure.set("finger")
    app._on_measure_changed()
    assert app.points["core"] is not None  # finger points survive switching modes


def test_adding_a_finger_suggests_the_pattern_and_fills_the_record(app):
    dialog = rc.AddFingerDialog(app)
    assert dialog.pattern.get() == "ulnar loop"  # delta left of core, thumb on the left (right hand)
    dialog.thumb_side.set("right")
    assert dialog.pattern.get() == "radial loop"
    dialog.thumb_side.set("left")
    dialog.finger.set("ring")
    dialog._ok()
    finger = app.records.record.fingers["right ring"]
    assert finger.pattern == "ulnar loop" and finger.ridge_count == app.result.count
    assert app.records.record.scans == ["sample_loop.png"]
    assert app.records.dirty


def test_adding_a_palm(app):
    app.measure.set("palm")
    app._on_measure_changed()
    for spot in ((60, 120), (200, 110), (270, 160), (160, 330)):
        click(app, *spot)
    dialog = rc.AddPalmDialog(app)
    dialog.hand.set("left")
    dialog.crease.set("Sydney line")
    dialog._ok()
    palm = app.records.record.palms["left"]
    assert palm.atd_angle == pytest.approx(round(app.atd, 1)) and palm.crease == "Sydney line"
    assert palm.ab_ridge_count == app.result.count


def test_save_new_and_open_a_record(app, monkeypatch):
    ui = app.records
    ui.child_id.set("baby-001")
    ui.label.set(dg.LABEL_NOT_DS)
    ui.finger_vars["left thumb"][0].set("whorl")
    ui.finger_vars["left thumb"][1].set("14")
    ui.save()
    saved = ui.store.children / "baby-001.json"
    assert saved.exists() and not ui.dirty
    assert ui.store.counts()["without_ds"] == 1

    ui.new()
    assert ui.child_id.get() == "" and ui.record.fingers["left thumb"].pattern == "unknown"

    monkeypatch.setattr(rc.filedialog, "askopenfilename", lambda **kwargs: str(saved))
    ui.open()
    assert ui.record.child_id == "baby-001" and ui.record.fingers["left thumb"].ridge_count == 14
    assert ui.label.get() == dg.LABEL_NOT_DS


def test_assessment_and_untrained_model(app, monkeypatch):
    ui = app.records
    text = ui.report.get("1.0", "end")
    assert "not a diagnosis" in text and "No trained model yet" in text

    shown = []
    monkeypatch.setattr(rc.messagebox, "showinfo", lambda title, message, **kw: shown.append(message))
    ui.train()
    assert shown and "Not enough confirmed records" in shown[0] and ui.model is None


def test_typing_in_a_form_does_not_trigger_shortcuts(app):
    app.notebook.select(app.notebook.tabs()[1])
    app.root.update()
    entry = app.records.id_entry
    mode = app.place_mode.get()
    entry.event_generate("<Key-d>")
    app.root.update()
    assert app.place_mode.get() == mode
