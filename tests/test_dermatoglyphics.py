"""Records, markers and the trainable model.

The labelled records here are synthetic, built only to check that the
training and evaluation machinery works. They say nothing about real
children and no model trained on them is shipped.
"""
import json

import numpy as np
import pytest

import dermatoglyphics as dg


def child(child_id="c1", patterns=None, counts=None, label=dg.LABEL_UNKNOWN, atd=None, crease="unknown", sole="unknown"):
    record = dg.ChildRecord(child_id, label=label)
    for i, key in enumerate(dg.FINGER_KEYS):
        if patterns:
            record.fingers[key].pattern = patterns[i]
        if counts:
            record.fingers[key].ridge_count = counts[i]
    for hand in dg.HANDS:
        record.palms[hand].atd_angle = atd
        record.palms[hand].crease = crease
        record.feet[hand].hallucal = sole
    return record


def test_atd_angle_and_axial_bands():
    assert dg.atd_angle((0, 0), (5, 10), (10, 0)) == pytest.approx(53.13, abs=0.01)
    assert dg.axial_triradius_position(40).startswith("t ")
    assert dg.axial_triradius_position(50).startswith("t'")
    assert dg.axial_triradius_position(60).startswith("t''")
    with pytest.raises(ValueError):
        dg.atd_angle((1, 1), (1, 1), (2, 2))


def test_features_from_a_full_record():
    record = child(patterns=["ulnar loop"] * 8 + ["whorl", "arch"], counts=[10] * 9 + [None],
                   atd=60, crease="single transverse (simian) crease", sole="tibial arch")
    f = dg.features(record)
    assert f["ulnar_loop_share"] == 0.8 and f["whorl_share"] == 0.1 and f["arch_share"] == 0.1
    assert f["total_ridge_count"] == 90  # the arch counts as 0
    assert f["max_atd_angle"] == 60 and f["simian_crease"] == 1.0 and f["tibial_arch"] == 1.0


def test_missing_measurements_stay_missing():
    f = dg.features(dg.ChildRecord("empty"))
    assert all(value is None for value in f.values())


def test_marker_report_flags_and_explains():
    record = child(patterns=["ulnar loop"] * 10, atd=62, crease="single transverse (simian) crease", sole="tibial arch")
    found = {m.name: m for m in dg.markers(record)}
    assert found["Ulnar loops"].points_to_ds is None  # informational: no agreed cut-off
    assert found["Axial triradius / ATD angle"].points_to_ds is True
    assert found["Tibial arch on the sole (big-toe area)"].points_to_ds is True
    assert found["Single transverse (simian) crease"].points_to_ds is True
    assert "not a diagnosis" in dg.assess(record, None, {}).lower()

    typical = child(patterns=["whorl"] * 4 + ["ulnar loop"] * 6, atd=40, crease="normal", sole="other pattern")
    flagged = [m for m in dg.markers(typical) if m.points_to_ds]
    assert flagged == []


def test_record_round_trip_and_bad_values(tmp_path):
    record = child("baby 7/a", patterns=["whorl"] * 10, counts=list(range(10)), label=dg.LABEL_NOT_DS, atd=44.5)
    store = dg.RecordStore(tmp_path)
    store.save(record)
    loaded = store.load("baby 7/a")
    assert loaded.to_json() == record.to_json()

    data = record.to_json()
    data["fingers"]["right thumb"]["pattern"] = "spiral"
    data["label"] = "maybe"
    cleaned = dg.ChildRecord.from_json(data)
    assert cleaned.fingers["right thumb"].pattern == "unknown" and cleaned.label == dg.LABEL_UNKNOWN

    with pytest.raises(ValueError):
        store.save(dg.ChildRecord("   "))


def synthetic_group(rng, n, with_ds):
    """Toy records whose two groups differ in the directions the reviews describe."""
    records = []
    for i in range(n):
        ulnar = rng.binomial(10, 0.85 if with_ds else 0.6)
        whorls = rng.binomial(10 - ulnar, 0.3 if with_ds else 0.7)
        patterns = ["ulnar loop"] * ulnar + ["whorl"] * whorls + ["arch"] * (10 - ulnar - whorls)
        rng.shuffle(patterns)
        counts = [int(rng.normal(9 if with_ds else 13, 3)) for _ in range(10)]
        records.append(child(
            f"{'ds' if with_ds else 'td'}{i}", patterns=patterns, counts=counts,
            label=dg.LABEL_DS if with_ds else dg.LABEL_NOT_DS,
            atd=float(rng.normal(62 if with_ds else 47, 6)),
            crease="single transverse (simian) crease" if rng.random() < (0.45 if with_ds else 0.05) else "normal",
        ))
    return records


def test_training_refuses_too_little_data():
    rng = np.random.default_rng(1)
    with pytest.raises(dg.NotEnoughData) as exc:
        dg.train(synthetic_group(rng, 5, False))  # like today: only confirmed non-Down-syndrome records
    assert exc.value.with_ds == 0 and exc.value.without_ds == 5


def test_training_learns_a_real_difference_and_reports_held_out_accuracy(tmp_path):
    rng = np.random.default_rng(2)
    records = synthetic_group(rng, 60, True) + synthetic_group(rng, 60, False)
    model = dg.train(records)
    e = model.evaluation
    assert e["sensitivity"] > 0.8 and e["specificity"] > 0.8 and e["auc"] > 0.9
    assert e["sensitivity_95ci"][0] < e["sensitivity"] < e["sensitivity_95ci"][1]

    store = dg.RecordStore(tmp_path)
    store.save_model(model)
    reloaded = store.load_model()
    sample = records[0]
    assert reloaded.probability(sample) == pytest.approx(model.probability(sample))
    assert "Model estimate" in dg.assess(sample, reloaded, {"with_ds": 60, "without_ds": 60})


def test_training_on_noise_does_not_look_accurate():
    rng = np.random.default_rng(3)
    records = synthetic_group(rng, 40, False) + synthetic_group(rng, 40, False)
    for r in records[:40]:
        r.label = dg.LABEL_DS  # labels unrelated to the prints
    assert dg.train(records).evaluation["auc"] < 0.75


def test_csv_export(tmp_path):
    store = dg.RecordStore(tmp_path / "data")
    store.save(child("a", patterns=["whorl"] * 10, label=dg.LABEL_NOT_DS))
    store.save(child("b"))
    (store.children / "notes.json").write_text(json.dumps({"hello": 1}))  # stray file is ignored
    rows = store.export_csv(tmp_path / "out.csv").read_text(encoding="utf-8").strip().splitlines()
    assert rows[0].startswith("child_id,label,sex,ulnar_loop_share")
    assert len(rows) == 3
    assert store.counts() == {"with_ds": 0, "without_ds": 1, "unknown": 1}
