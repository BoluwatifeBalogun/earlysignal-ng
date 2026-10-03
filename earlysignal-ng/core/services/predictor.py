"""Application tier glue between Django and the trained model.

The model is loaded once and reloaded automatically when the artifact file
changes, so retraining never needs a server restart and the interface tier
never has to know which algorithm is deployed (section 3.8.1).
"""
from __future__ import annotations

import json
import threading

import joblib
import numpy as np

from core import nigeria
from ml import explain
from ml.pipeline import (
    DECISION_THRESHOLD, FEATURE_LABELS, FEATURES, HIGH_FROM, METRICS_PATH, MODEL_PATH,
    RF_NAME, band_for, calibrate,
)

OUTCOME_UNDER = "At risk of under-performing"
OUTCOME_PASS = "On track to pass"

_lock = threading.Lock()
_cache: dict = {"mtime": None, "bundle": None}


class ModelNotTrained(RuntimeError):
    pass


def model_ready() -> bool:
    return MODEL_PATH.exists()


def load_bundle() -> dict:
    if not MODEL_PATH.exists():
        raise ModelNotTrained(
            "No trained model was found. Run: python manage.py train_model"
        )
    mtime = MODEL_PATH.stat().st_mtime
    with _lock:
        if _cache["mtime"] != mtime:
            bundle = joblib.load(MODEL_PATH)
            if hasattr(bundle["model"], "n_jobs"):
                bundle["model"].n_jobs = 1  # single predictions: threads only add latency
            _cache.update(mtime=mtime, bundle=bundle)
        return _cache["bundle"]


def load_metrics() -> dict | None:
    if not METRICS_PATH.exists():
        return None
    return json.loads(METRICS_PATH.read_text())


def outcome_for(score: float) -> str:
    """The classifier's decision, the thing precision and recall measure."""
    return OUTCOME_UNDER if score >= DECISION_THRESHOLD else OUTCOME_PASS


def display_percent(chance: float) -> int:
    # A forest can vote unanimously, but no forecast is certain.
    return min(max(round(chance * 100), 1), 99)


def band_thresholds() -> dict:
    """Band edges on the calibrated chance, as whole percentages."""
    bundle = load_bundle()
    return {
        "flag_from": round(float(calibrate(DECISION_THRESHOLD, bundle.get("calibration"))) * 100),
        "high_from": round(HIGH_FROM * 100),
    }


def validate_inputs(ca_score, attendance_rate, previous_result) -> np.ndarray:
    values = []
    for name, raw in zip(FEATURES, (ca_score, attendance_rate, previous_result)):
        try:
            v = float(raw)
        except (TypeError, ValueError):
            raise ValueError(f"{FEATURE_LABELS[name]} must be a number.")
        if not np.isfinite(v) or v < 0 or v > 100:
            raise ValueError(f"{FEATURE_LABELS[name]} must be between 0 and 100.")
        values.append(v)
    return np.array(values, dtype=float)


def predict(ca_score, attendance_rate, previous_result) -> dict:
    """Return the outcome, risk band and per-indicator explanation."""
    x = validate_inputs(ca_score, attendance_rate, previous_result)
    bundle = load_bundle()
    model = bundle["model"]
    cal = bundle.get("calibration")
    score = float(model.predict_proba(x.reshape(1, -1))[0, 1])
    chance = float(calibrate(score, cal))

    if bundle["name"] == RF_NAME:
        base_score, contrib = explain.explain_forest(model, x, positive=1)
    else:
        base_score, contrib = explain.explain_logistic(model, x, 1, bundle["base_rate"])
    # The explanation is worked out on the model's raw score, then rescaled so
    # that starting point + the three shares = the calibrated chance shown.
    baseline = float(calibrate(base_score, cal))
    gap = score - float(base_score)
    scale = (chance - baseline) / gap if abs(gap) > 1e-9 else 0.0
    contrib = np.asarray(contrib, dtype=float) * scale

    factors = [
        {
            "feature": f,
            "label": FEATURE_LABELS[f],
            "value": round(float(x[i]), 2),
            "contribution": round(float(contrib[i]), 4),
            "points": round(float(contrib[i]) * 100, 1),
            "direction": "raises" if contrib[i] > 0.005 else "lowers" if contrib[i] < -0.005 else "neutral",
        }
        for i, f in enumerate(FEATURES)
    ]
    band = band_for(score, chance)
    return {
        "probability": round(chance, 4),
        "score": round(score, 4),
        "percent": display_percent(chance),
        "outcome": outcome_for(score),
        "risk": band,
        "baseline": round(baseline, 4),
        "baseline_percent": round(baseline * 100),
        "factors": factors,
        "advice": advice(x, factors, band),
        "cautions": cautions(x, bundle),
        "model_name": bundle["name"],
        "model_version": bundle["version"],
    }


def cautions(x: np.ndarray, bundle: dict) -> list[str]:
    """Say so when a figure lies outside anything the model was trained on."""
    notes = []
    for i, f in enumerate(FEATURES):
        lo, hi = bundle.get("feature_ranges", {}).get(f, (0, 100))
        if x[i] < lo:
            notes.append(
                f"{FEATURE_LABELS[f]} of {x[i]:g}% is lower than any record the model learned "
                f"from (lowest {lo:g}%). Treat this estimate with extra caution."
            )
        elif x[i] > hi:
            notes.append(
                f"{FEATURE_LABELS[f]} of {x[i]:g}% is higher than any record the model learned "
                f"from (highest {hi:g}%). Treat this estimate with extra caution."
            )
    return notes


def advice(x: np.ndarray, factors: list[dict], band: str) -> list[str]:
    """Plain-language follow-ups. These are prompts for the adviser's own
    judgement, never automatic decisions."""
    ca, attendance, previous = x
    notes = []
    if attendance < nigeria.ATTENDANCE_REQUIREMENT:
        notes.append(
            f"Attendance is {attendance:.0f}%, below the {nigeria.ATTENDANCE_REQUIREMENT}% most "
            "institutions require to sit an examination. Find out what is keeping the student "
            "away and agree an attendance plan."
        )
    elif attendance < 85 and band != "Low":
        notes.append(
            f"Attendance is {attendance:.0f}%, above the exam requirement but slipping. "
            "A short check-in now is cheaper than a carry-over later."
        )
    if ca < 40:
        notes.append(
            f"Continuous assessment stands at {ca:.0f}%. Review the tests and assignments "
            "already marked with the student and arrange tutorial support before the next one."
        )
    elif ca < 50:
        notes.append(
            f"Continuous assessment is {ca:.0f}%, just under a pass. The remaining tests and "
            "assignments are the quickest way to move this signal."
        )
    if previous < 45:
        notes.append(
            "The previous result was weak, so this is a continuing pattern rather than a "
            "one-semester dip. Consider a referral for academic counselling."
        )
    if band == "Low" and notes:
        # The model looks at the three figures together and can under-rate an
        # unusual mix. A figure that is weak on its own still deserves a look.
        notes.insert(0, "The model rates this record as low risk overall, but at least one "
                        "figure is weak on its own. Use your own judgement here.")
    if band == "Low" and not notes:
        notes.append("No action needed. Keep monitoring as new CA and attendance figures come in.")
    elif not notes:
        strongest = max(factors, key=lambda f: f["contribution"])
        notes.append(
            f"No single indicator is below its usual threshold. {strongest['label']} is "
            "contributing most to the signal, so start the conversation there."
        )
    if band == "High":
        notes.append("Record what was agreed and enter a fresh record after the next CA to see whether the signal moves.")
    return notes


def predict_many(rows) -> list[dict]:
    """Chance, outcome and band for many records at once (bulk import).
    Explanations are filled in the first time each record is opened."""
    bundle = load_bundle()
    scores = bundle["model"].predict_proba(np.asarray(rows, dtype=float))[:, 1]
    chances = calibrate(scores, bundle.get("calibration"))
    return [
        {"probability": round(float(c), 4), "score": round(float(s), 4),
         "outcome": outcome_for(float(s)), "risk": band_for(float(s), float(c))}
        for s, c in zip(scores, chances)
    ]
