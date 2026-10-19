"""Child records, dermatoglyphic markers and a trainable Down syndrome model.

Research use only. Nothing here diagnoses anything: Down syndrome is
confirmed with a chromosome test (karyotype). The model can only be
trained from records whose result was confirmed by such a test, and it
refuses to train until both groups have enough children.
"""
from __future__ import annotations

import csv
import json
import math
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np

HANDS = ("right", "left")
FINGERS = ("thumb", "index", "middle", "ring", "little")
FINGER_KEYS = tuple(f"{hand} {finger}" for hand in HANDS for finger in FINGERS)
PATTERNS = ("unknown", "arch", "ulnar loop", "radial loop", "whorl")
CREASES = ("unknown", "normal", "Sydney line", "single transverse (simian) crease")
HALLUCAL = ("unknown", "tibial arch", "other pattern")
SEXES = ("unknown", "female", "male")
LABEL_UNKNOWN = "not tested / unknown"
LABEL_DS = "Down syndrome (confirmed by test)"
LABEL_NOT_DS = "no Down syndrome (confirmed)"
LABELS = (LABEL_UNKNOWN, LABEL_DS, LABEL_NOT_DS)
MIN_PER_GROUP = 20
DISCLAIMER = (
    "Research aid only - not a diagnosis. Many children without Down syndrome show some of "
    "these markers, and some children with Down syndrome show none. Down syndrome is confirmed "
    "with a chromosome test (karyotype)."
)


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------

@dataclass
class Finger:
    pattern: str = "unknown"
    ridge_count: int | None = None  # for whorls, the larger of the two counts


@dataclass
class Palm:
    crease: str = "unknown"
    atd_angle: float | None = None
    ab_ridge_count: int | None = None


@dataclass
class Foot:
    hallucal: str = "unknown"  # pattern in the big-toe (hallucal) area of the sole


@dataclass
class ChildRecord:
    child_id: str
    label: str = LABEL_UNKNOWN
    sex: str = "unknown"
    notes: str = ""
    fingers: dict = field(default_factory=lambda: {k: Finger() for k in FINGER_KEYS})
    palms: dict = field(default_factory=lambda: {h: Palm() for h in HANDS})
    feet: dict = field(default_factory=lambda: {h: Foot() for h in HANDS})
    scans: list = field(default_factory=list)
    updated: str = ""

    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict) -> "ChildRecord":
        def choice(value, options, default):
            return value if value in options else default

        def number(value, kind):
            return None if value in (None, "") else kind(value)

        record = cls(
            child_id=str(data["child_id"]),
            label=choice(data.get("label"), LABELS, LABEL_UNKNOWN),
            sex=choice(data.get("sex"), SEXES, "unknown"),
            notes=str(data.get("notes", "")),
            scans=[str(s) for s in data.get("scans", [])],
            updated=str(data.get("updated", "")),
        )
        for key, value in data.get("fingers", {}).items():
            if key in record.fingers:
                record.fingers[key] = Finger(choice(value.get("pattern"), PATTERNS, "unknown"), number(value.get("ridge_count"), int))
        for key, value in data.get("palms", {}).items():
            if key in record.palms:
                record.palms[key] = Palm(
                    choice(value.get("crease"), CREASES, "unknown"),
                    number(value.get("atd_angle"), float),
                    number(value.get("ab_ridge_count"), int),
                )
        for key, value in data.get("feet", {}).items():
            if key in record.feet:
                record.feet[key] = Foot(choice(value.get("hallucal"), HALLUCAL, "unknown"))
        return record


def atd_angle(a, t, d) -> float:
    """Angle at the axial triradius t between the lines to triradii a and d, in degrees."""
    v1 = (a[0] - t[0], a[1] - t[1])
    v2 = (d[0] - t[0], d[1] - t[1])
    norm = math.hypot(*v1) * math.hypot(*v2)
    if norm == 0:
        raise ValueError("Triradii a, d and t must be at different places.")
    cos = (v1[0] * v2[0] + v1[1] * v2[1]) / norm
    return math.degrees(math.acos(max(-1.0, min(1.0, cos))))


def axial_triradius_position(angle: float) -> str:
    """Classical bands: t below 45 degrees, t' from 45 to 56, t'' above 56."""
    if angle > 56:
        return "t'' (distal)"
    if angle >= 45:
        return "t' (intermediate)"
    return "t (proximal)"


# ---------------------------------------------------------------------------
# Features
# ---------------------------------------------------------------------------

FEATURES = (
    ("ulnar_loop_share", "Share of fingers with ulnar loops"),
    ("whorl_share", "Share of fingers with whorls"),
    ("arch_share", "Share of fingers with arches"),
    ("radial_loop_share", "Share of fingers with radial loops"),
    ("ring_little_ulnar_share", "Share of ring and little fingers with ulnar loops"),
    ("total_ridge_count", "Total finger ridge count"),
    ("max_atd_angle", "Largest palm ATD angle"),
    ("mean_ab_ridge_count", "Average a-b ridge count"),
    ("simian_crease", "Single transverse (simian) crease"),
    ("sydney_line", "Sydney line"),
    ("tibial_arch", "Tibial arch on the sole"),
)
FEATURE_LABELS = dict(FEATURES)


def features(record: ChildRecord) -> dict:
    """Numbers the model and the marker report use; None where not measured."""
    patterns = [f.pattern for f in record.fingers.values() if f.pattern != "unknown"]
    n = len(patterns)

    def share(pattern):
        return patterns.count(pattern) / n if n else None

    ring_little = [record.fingers[f"{h} {f}"].pattern for h in HANDS for f in ("ring", "little")]
    ring_little = [p for p in ring_little if p != "unknown"]

    counts = []
    for finger in record.fingers.values():
        if finger.ridge_count is not None:
            counts.append(finger.ridge_count)
        elif finger.pattern == "arch":
            counts.append(0)  # arches have no ridge count by convention
    if len(counts) == 10:
        total = float(sum(counts))
    elif len(counts) >= 6:
        total = float(round(sum(counts) / len(counts) * 10))
    else:
        total = None

    atds = [p.atd_angle for p in record.palms.values() if p.atd_angle is not None]
    abs_ = [p.ab_ridge_count for p in record.palms.values() if p.ab_ridge_count is not None]
    creases = [p.crease for p in record.palms.values() if p.crease != "unknown"]
    soles = [f.hallucal for f in record.feet.values() if f.hallucal != "unknown"]

    def flag(values, wanted):
        return (1.0 if wanted in values else 0.0) if values else None

    return {
        "ulnar_loop_share": share("ulnar loop"),
        "whorl_share": share("whorl"),
        "arch_share": share("arch"),
        "radial_loop_share": share("radial loop"),
        "ring_little_ulnar_share": ring_little.count("ulnar loop") / len(ring_little) if ring_little else None,
        "total_ridge_count": total,
        "max_atd_angle": max(atds) if atds else None,
        "mean_ab_ridge_count": sum(abs_) / len(abs_) if abs_ else None,
        "simian_crease": flag(creases, "single transverse (simian) crease"),
        "sydney_line": flag(creases, "Sydney line"),
        "tibial_arch": flag(soles, "tibial arch"),
    }


# ---------------------------------------------------------------------------
# Marker report (literature-based, no score)
# ---------------------------------------------------------------------------

REVIEWS = "Jacob 2026 (IRJMETS review); Smail 2020 (MicroMedicine review)"
JACOB = "Jacob 2026 (IRJMETS review)"


@dataclass
class Marker:
    name: str
    measured: str
    reported: str
    points_to_ds: bool | None  # None: not measured, or no agreed cut-off
    source: str


def markers(record: ChildRecord) -> list:
    f = features(record)
    known = [x.pattern for x in record.fingers.values() if x.pattern != "unknown"]
    n = len(known)
    out = []

    pattern_note = ("The reviews give no cut-off, and this pattern is common in children without Down syndrome, "
                    "so it is not flagged here; the trained model weighs it.")
    if n:
        out.append(Marker(
            "Ulnar loops", f"{known.count('ulnar loop')} of {n} fingers with a known pattern",
            f"Reported more often in Down syndrome. {pattern_note}", None, REVIEWS))
        out.append(Marker(
            "Whorls", f"{known.count('whorl')} of {n} fingers",
            f"Reported less often in Down syndrome. {pattern_note}", None, JACOB))
    else:
        out.append(Marker("Finger patterns", "not recorded", "Record the pattern on each fingertip.", None, REVIEWS))

    if f["ring_little_ulnar_share"] is not None:
        rl = [record.fingers[f"{h} {x}"].pattern for h in HANDS for x in ("ring", "little")]
        rl = [p for p in rl if p != "unknown"]
        out.append(Marker(
            "Ulnar loops on ring and little fingers", f"{rl.count('ulnar loop')} of {len(rl)}",
            f"Reported more often on the 4th and 5th fingers in Down syndrome. {pattern_note}", None, JACOB))

    if f["total_ridge_count"] is not None:
        out.append(Marker(
            "Total finger ridge count", f"{f['total_ridge_count']:.0f}",
            "Reported lower in Down syndrome; the reviews give no cut-off, so it is not flagged.",
            None, JACOB))

    if f["max_atd_angle"] is not None:
        angle = f["max_atd_angle"]
        out.append(Marker(
            "Axial triradius / ATD angle", f"{angle:.0f} degrees: {axial_triradius_position(angle)}",
            "Distal axial triradius and wide ATD angle in Down syndrome. Flagged above 56 degrees "
            "(classical t'' band). ATD angles are larger in infants than adults, so this cut-off "
            "can over-flag newborns.", angle > 56, JACOB + "; t/t'/t'' bands: Penrose"))

    if f["mean_ab_ridge_count"] is not None:
        out.append(Marker(
            "a-b ridge count", f"{f['mean_ab_ridge_count']:.0f}",
            "Altered in several chromosomal disorders; the reviews give no direction for Down "
            "syndrome, so it is not flagged.", None, JACOB))

    creases = [p.crease for p in record.palms.values() if p.crease != "unknown"]
    if creases:
        out.append(Marker(
            "Single transverse (simian) crease",
            "present" if f["simian_crease"] else "absent",
            "Reported more often in Down syndrome (also seen in some typical children).",
            bool(f["simian_crease"]), REVIEWS))
        out.append(Marker(
            "Sydney line", "present" if f["sydney_line"] else "absent",
            "Reported more often in Down syndrome.", bool(f["sydney_line"]), JACOB))
    else:
        out.append(Marker("Palm creases", "not recorded", "Record the crease type of each palm.", None, REVIEWS))

    if f["tibial_arch"] is not None:
        out.append(Marker(
            "Tibial arch on the sole (big-toe area)", "present" if f["tibial_arch"] else "absent",
            "A classic Down syndrome marker in the dermatoglyphics literature.",
            bool(f["tibial_arch"]), "Classical literature (e.g. Penrose); not in the papers provided"))
    else:
        out.append(Marker("Sole (big-toe area)", "not recorded",
                          "Record the hallucal pattern from a sole print.", None, "Classical literature"))
    return out


def summarize(record: ChildRecord) -> str:
    found = markers(record)
    judged = [m for m in found if m.points_to_ds is not None]
    flagged = [m for m in judged if m.points_to_ds]
    lines = [f"Flaggable markers measured: {len(judged)}. Flagged (the way reported in Down syndrome): {len(flagged)}.", ""]
    for m in found:
        if m.points_to_ds is None:
            tag = "MISSING" if m.measured == "not recorded" else "INFO"
        else:
            tag = "FLAG" if m.points_to_ds else "no flag"
        lines.append(f"[{tag}] {m.name}: {m.measured}")
        lines.append(f"    {m.reported}  ({m.source})")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Trainable model: regularised logistic regression with honest evaluation
# ---------------------------------------------------------------------------

class NotEnoughData(Exception):
    def __init__(self, with_ds: int, without_ds: int, needed: int):
        self.with_ds, self.without_ds, self.needed = with_ds, without_ds, needed
        super().__init__(
            f"Not enough confirmed records to train: {with_ds} with Down syndrome and {without_ds} without. "
            f"The model needs at least {needed} of each."
        )


def _matrix(records) -> np.ndarray:
    rows = [[features(r)[name] for name, _ in FEATURES] for r in records]
    return np.array([[np.nan if v is None else v for v in row] for row in rows], dtype=float)


def _sigmoid(z):
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))


def _fit(X: np.ndarray, y: np.ndarray, penalty: float = 1.0):
    """Class-balanced, L2-regularised logistic regression (Newton's method)."""
    present = ~np.isnan(X)
    means = np.where(present, X, 0.0).sum(axis=0) / np.maximum(present.sum(axis=0), 1)
    filled = np.where(present, X, means)
    scales = filled.std(axis=0)
    scales = np.where(scales < 1e-9, 1.0, scales)
    Z = np.hstack([np.ones((len(X), 1)), (filled - means) / scales])
    weights = np.where(y == 1, len(y) / (2 * max(y.sum(), 1)), len(y) / (2 * max((1 - y).sum(), 1)))
    reg = np.full(Z.shape[1], penalty)
    reg[0] = 0.0
    beta = np.zeros(Z.shape[1])
    for _ in range(100):
        p = _sigmoid(Z @ beta)
        gradient = Z.T @ (weights * (y - p)) - reg * beta
        hessian = (Z * (weights * p * (1 - p))[:, None]).T @ Z + np.diag(reg) + 1e-9 * np.eye(Z.shape[1])
        step = np.linalg.solve(hessian, gradient)
        beta += step
        if np.max(np.abs(step)) < 1e-8:
            break
    return beta, means, scales


def _wilson(successes: int, total: int, z: float = 1.96):
    if total == 0:
        return (0.0, 0.0, 1.0)
    p = successes / total
    centre = (p + z * z / (2 * total)) / (1 + z * z / total)
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / (1 + z * z / total)
    return (p, max(0.0, centre - half), min(1.0, centre + half))


def _auc(y: np.ndarray, scores: np.ndarray) -> float:
    order = np.argsort(scores)
    ranks = np.empty(len(scores))
    ranks[order] = np.arange(1, len(scores) + 1)
    for value in np.unique(scores):  # average ranks for ties
        tied = scores == value
        ranks[tied] = ranks[tied].mean()
    pos = y == 1
    n_pos, n_neg = pos.sum(), (~pos).sum()
    return float((ranks[pos].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


@dataclass
class Model:
    coefficients: list
    intercept: float
    means: list
    scales: list
    trained_with: dict          # {"with_ds": n, "without_ds": n}
    evaluation: dict            # cross-validated results
    trained_at: str

    def probability(self, record: ChildRecord) -> float:
        x = _matrix([record])[0]
        x = np.where(np.isnan(x), self.means, x)
        z = self.intercept + float(np.dot(self.coefficients, (x - np.array(self.means)) / np.array(self.scales)))
        return float(_sigmoid(z))

    def explain(self, record: ChildRecord, top: int = 4) -> list:
        """Features that pushed this child's result up or down the most."""
        raw = _matrix([record])[0]
        x = np.where(np.isnan(raw), self.means, raw)
        contributions = np.array(self.coefficients) * (x - np.array(self.means)) / np.array(self.scales)
        order = np.argsort(-np.abs(contributions))[:top]
        return [(FEATURES[i][1], float(contributions[i]), not np.isnan(raw[i])) for i in order]

    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict) -> "Model":
        return cls(**data)


def train(records, min_per_group: int = MIN_PER_GROUP, folds: int = 5, seed: int = 0) -> Model:
    """Train on confirmed records only and report cross-validated accuracy."""
    labelled = [r for r in records if r.label in (LABEL_DS, LABEL_NOT_DS)]
    y = np.array([1 if r.label == LABEL_DS else 0 for r in labelled])
    with_ds, without_ds = int(y.sum()), int(len(y) - y.sum())
    if with_ds < min_per_group or without_ds < min_per_group:
        raise NotEnoughData(with_ds, without_ds, min_per_group)
    X = _matrix(labelled)

    rng = np.random.default_rng(seed)
    fold_of = np.empty(len(y), int)
    for cls in (0, 1):
        idx = rng.permutation(np.nonzero(y == cls)[0])
        fold_of[idx] = np.arange(len(idx)) % folds
    scores = np.empty(len(y))
    for k in range(folds):
        test = fold_of == k
        beta, means, scales = _fit(X[~test], y[~test])
        filled = np.where(np.isnan(X[test]), means, X[test])
        scores[test] = _sigmoid(beta[0] + ((filled - means) / scales) @ beta[1:])

    predicted = scores >= 0.5
    tp = int((predicted & (y == 1)).sum())
    tn = int((~predicted & (y == 0)).sum())
    sens, s_lo, s_hi = _wilson(tp, with_ds)
    spec, p_lo, p_hi = _wilson(tn, without_ds)
    evaluation = {
        "method": f"{folds}-fold cross-validation (each child predicted by a model that never saw them)",
        "sensitivity": sens, "sensitivity_95ci": [s_lo, s_hi],
        "specificity": spec, "specificity_95ci": [p_lo, p_hi],
        "auc": _auc(y, scores),
        "caught": f"{tp} of {with_ds} children with Down syndrome",
        "cleared": f"{tn} of {without_ds} children without Down syndrome",
    }
    beta, means, scales = _fit(X, y)
    return Model(
        coefficients=beta[1:].tolist(), intercept=float(beta[0]), means=means.tolist(), scales=scales.tolist(),
        trained_with={"with_ds": with_ds, "without_ds": without_ds}, evaluation=evaluation,
        trained_at=datetime.now().isoformat(timespec="seconds"),
    )


def describe_model(model: Model | None, record_counts: dict) -> str:
    if model is None:
        return (
            "No trained model yet.\n"
            f"Confirmed records: {record_counts.get('with_ds', 0)} with Down syndrome, "
            f"{record_counts.get('without_ds', 0)} without. Training needs at least {MIN_PER_GROUP} of each, "
            "confirmed by a chromosome test. Until then, use the marker report."
        )
    e = model.evaluation
    return (
        f"Trained {model.trained_at} on {model.trained_with['with_ds']} children with Down syndrome and "
        f"{model.trained_with['without_ds']} without.\n"
        f"Tested by {e['method']}:\n"
        f"  Caught {e['caught']} - sensitivity {e['sensitivity']:.0%} "
        f"(95% range {e['sensitivity_95ci'][0]:.0%}-{e['sensitivity_95ci'][1]:.0%})\n"
        f"  Correctly cleared {e['cleared']} - specificity {e['specificity']:.0%} "
        f"(95% range {e['specificity_95ci'][0]:.0%}-{e['specificity_95ci'][1]:.0%})\n"
        f"  AUC {e['auc']:.2f} (0.5 = guessing, 1.0 = perfect)"
    )


def assess(record: ChildRecord, model: Model | None, record_counts: dict) -> str:
    """The full text shown for one child: marker report, then the model's view."""
    parts = [summarize(record), ""]
    if model is None:
        parts.append(describe_model(None, record_counts))
    else:
        p = model.probability(record)
        parts.append(f"Model estimate: {p:.0%} chance this record belongs to the Down syndrome group.")
        for name, contribution, measured in model.explain(record):
            direction = "towards" if contribution > 0 else "away from"
            note = "" if measured else " (not measured - filled with the average)"
            parts.append(f"  {name}: pushed {direction} Down syndrome{note}")
        parts.append(describe_model(model, record_counts))
    parts += ["", DISCLAIMER]
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Local storage (never uploaded anywhere)
# ---------------------------------------------------------------------------

def default_data_folder() -> Path:
    documents = Path.home() / "Documents"
    return (documents if documents.is_dir() else Path.home()) / "Ridge Counter Data"


class RecordStore:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.children = self.folder / "children"
        self.children.mkdir(parents=True, exist_ok=True)

    def _path(self, child_id: str) -> Path:
        slug = re.sub(r"[^A-Za-z0-9._-]+", "_", child_id.strip()) or "child"
        return self.children / f"{slug}.json"

    def save(self, record: ChildRecord) -> Path:
        if not record.child_id.strip():
            raise ValueError("Give the child an ID before saving.")
        record.updated = datetime.now().isoformat(timespec="seconds")
        path = self._path(record.child_id)
        path.write_text(json.dumps(record.to_json(), indent=2), encoding="utf-8")
        return path

    def load(self, child_id: str) -> ChildRecord:
        return ChildRecord.from_json(json.loads(self._path(child_id).read_text(encoding="utf-8")))

    def all(self) -> list:
        records = []
        for path in sorted(self.children.glob("*.json")):
            try:
                records.append(ChildRecord.from_json(json.loads(path.read_text(encoding="utf-8"))))
            except (ValueError, KeyError, TypeError):
                continue  # skip files that aren't records
        return records

    def counts(self) -> dict:
        labels = [r.label for r in self.all()]
        return {"with_ds": labels.count(LABEL_DS), "without_ds": labels.count(LABEL_NOT_DS),
                "unknown": labels.count(LABEL_UNKNOWN)}

    def save_model(self, model: Model) -> Path:
        path = self.folder / "model.json"
        path.write_text(json.dumps(model.to_json(), indent=2), encoding="utf-8")
        return path

    def load_model(self) -> Model | None:
        path = self.folder / "model.json"
        if not path.exists():
            return None
        return Model.from_json(json.loads(path.read_text(encoding="utf-8")))

    def export_csv(self, path) -> Path:
        path = Path(path)
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["child_id", "label", "sex", *[name for name, _ in FEATURES]])
            for r in self.all():
                values = features(r)
                writer.writerow([r.child_id, r.label, r.sex,
                                 *["" if values[name] is None else round(values[name], 4) for name, _ in FEATURES]])
        return path
