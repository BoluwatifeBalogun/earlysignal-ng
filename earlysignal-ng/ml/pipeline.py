"""Training pipeline: clean, split, train both candidates, compare, select.

Follows sections 3.5, 3.8.4 and 3.10.2 of the seminar report:

1. remove duplicates, exclude (never impute) records missing an indicator
2. stratified 80/20 train/test split
3. train Random Forest and the Logistic Regression baseline
4. 5-fold cross-validation on the training portion
5. accuracy, precision, recall, F1 and a confusion matrix on the held-out test
6. deploy the better model; on a near tie keep the more interpretable one
   (and report whether the gap is statistically significant, and what each costs to run)
   then calibrate its score so the chance shown to a lecturer matches observed rates
7. test H0 (the indicators carry no relationship with the outcome)
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from scipy import stats
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import (
    StratifiedKFold,
    cross_val_predict,
    cross_validate,
    permutation_test_score,
    train_test_split,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from .dataset import OUTCOME_PASS, OUTCOME_UNDER, generate

BASE = Path(__file__).resolve().parent
DATA_PATH = BASE / "data" / "nigeria_student_records.csv"
MODEL_PATH = BASE / "artifacts" / "model.joblib"
METRICS_PATH = BASE / "artifacts" / "metrics.json"

FEATURES = ["ca_score", "attendance_rate", "previous_result"]
FEATURE_LABELS = {
    "ca_score": "Continuous assessment",
    "attendance_rate": "Attendance",
    "previous_result": "Previous result",
}
RF_NAME = "Random Forest"
LR_NAME = "Logistic Regression"
SEED = 42
TIE_MARGIN = 0.005  # F1 gap below which the simpler model is preferred
DECISION_THRESHOLD = 0.5  # on the model's raw score
HIGH_FROM = 0.5  # on the calibrated chance: more likely than not
_EPS = 1e-3


def _logit(score):
    s = np.clip(np.asarray(score, dtype=float), _EPS, 1 - _EPS)
    return np.log(s / (1 - s))


def calibrate(score, calibration: dict | None):
    """Turn the model's raw score into an honest chance.

    Both candidates are trained with balanced class weights so they do not
    ignore the under-performing minority. That makes them good at ranking
    students but inflates the raw score: a raw 0.57 turned out to mean about
    a one in three chance. Platt scaling (a two-parameter logistic curve
    fitted on out-of-fold training predictions) maps the score back to the
    rate actually observed.
    """
    if not calibration:
        return np.asarray(score, dtype=float)
    z = calibration["a"] * _logit(score) + calibration["b"]
    return 1.0 / (1.0 + np.exp(-z))


def band_for(score: float, chance: float) -> str:
    """Low: not flagged. Medium: flagged, but still more likely to pass than
    not. High: more likely than not to under-perform."""
    if score < DECISION_THRESHOLD:
        return "Low"
    return "High" if chance >= HIGH_FROM else "Medium"


class DatasetError(ValueError):
    """Raised when a training file cannot be used."""


def ensure_dataset(path: Path = DATA_PATH) -> Path:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        generate().to_csv(path, index=False)
    return path


def clean(raw: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Apply the cleaning rules from section 3.5 and report what was removed."""
    df = raw.copy()
    df.columns = [c.strip().lower() for c in df.columns]
    rows_raw = len(df)

    if "previous_result" not in df.columns:
        if {"previous_gpa", "gpa_scale"} <= set(df.columns):
            df["previous_result"] = (
                pd.to_numeric(df["previous_gpa"], errors="coerce")
                / pd.to_numeric(df["gpa_scale"], errors="coerce")
                * 100
            )
        else:
            raise DatasetError(
                "The file needs a previous_result column (percent), or both "
                "previous_gpa and gpa_scale."
            )
    missing_cols = [c for c in FEATURES + ["outcome"] if c not in df.columns]
    if missing_cols:
        raise DatasetError("Missing column(s): " + ", ".join(missing_cols))

    # Names never reach the model (section 3.5.1).
    df = df.drop(columns=[c for c in ("full_name", "name") if c in df.columns])

    before = len(df)
    df = df.drop_duplicates()
    duplicates = before - len(df)

    for col in FEATURES:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    before = len(df)
    df = df.dropna(subset=FEATURES + ["outcome"])
    missing = before - len(df)

    before = len(df)
    in_range = df[FEATURES].ge(0).all(axis=1) & df[FEATURES].le(100).all(axis=1)
    df = df[in_range]
    out_of_range = before - len(df)

    label = df["outcome"].astype(str).str.strip().str.lower()
    under_words = {OUTCOME_UNDER.lower(), "under-perform", "underperform", "at risk", "fail", "1"}
    pass_words = {OUTCOME_PASS.lower(), "on track", "0"}
    known = label.isin(under_words | pass_words)
    unknown_labels = int((~known).sum())
    df = df[known].copy()
    df["target"] = label[known].isin(under_words).astype(int)

    if len(df) < 200:
        raise DatasetError(
            f"Only {len(df)} usable records remain after cleaning. At least 200 are needed."
        )
    if df["target"].nunique() < 2:
        raise DatasetError("The file needs both Pass and Under-perform records.")

    summary = {
        "rows_raw": int(rows_raw),
        "duplicates_removed": int(duplicates),
        "missing_removed": int(missing),
        "out_of_range_removed": int(out_of_range),
        "unknown_label_removed": unknown_labels,
        "rows_used": int(len(df)),
        "under_perform": int(df["target"].sum()),
        "pass": int((1 - df["target"]).sum()),
        "under_perform_share": round(float(df["target"].mean()), 4),
    }
    return df, summary


def _candidates() -> dict:
    return {
        RF_NAME: RandomForestClassifier(
            n_estimators=300,
            max_depth=8,
            min_samples_leaf=5,
            class_weight="balanced",
            random_state=SEED,
            n_jobs=-1,
        ),
        LR_NAME: Pipeline(
            [
                ("scale", StandardScaler()),
                ("clf", LogisticRegression(class_weight="balanced", max_iter=1000)),
            ]
        ),
    }


def _scores(y_true, y_pred, y_prob) -> dict:
    return {
        "accuracy": round(float(accuracy_score(y_true, y_pred)), 4),
        "precision": round(float(precision_score(y_true, y_pred, zero_division=0)), 4),
        "recall": round(float(recall_score(y_true, y_pred, zero_division=0)), 4),
        "f1": round(float(f1_score(y_true, y_pred, zero_division=0)), 4),
        "roc_auc": round(float(roc_auc_score(y_true, y_prob)), 4),
    }


def train(data_path: Path | None = None, permutations: int = 100, save: bool = True) -> dict:
    path = Path(data_path) if data_path else ensure_dataset()
    try:
        raw = pd.read_csv(path)
    except Exception as exc:  # unreadable upload
        raise DatasetError(f"The file could not be read as CSV ({exc}).") from exc
    df, data_summary = clean(raw)

    X = df[FEATURES].to_numpy(dtype=float)
    y = df["target"].to_numpy()
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, stratify=y, random_state=SEED
    )
    data_summary.update(train_rows=int(len(y_train)), test_rows=int(len(y_test)))

    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=SEED)
    scoring = ["accuracy", "precision", "recall", "f1", "roc_auc"]
    fitted, results, correct = {}, {}, {}
    for name, model in _candidates().items():
        cv_res = cross_validate(model, X_train, y_train, cv=cv, scoring=scoring)
        started = time.perf_counter()
        model.fit(X_train, y_train)
        fit_seconds = time.perf_counter() - started
        prob = model.predict_proba(X_test)[:, 1]
        pred = (prob >= DECISION_THRESHOLD).astype(int)
        correct[name] = pred == y_test
        # Computational efficiency (section 1.8): one record at a time, as the
        # web application calls it.
        if hasattr(model, "n_jobs"):
            model.n_jobs = 1
        started = time.perf_counter()
        for row in X_test[:30]:
            model.predict_proba(row.reshape(1, -1))
        predict_ms = (time.perf_counter() - started) / 30 * 1000
        if hasattr(model, "n_jobs"):
            model.n_jobs = -1
        tn, fp, fn, tp = confusion_matrix(y_test, pred, labels=[0, 1]).ravel()
        results[name] = {
            "test": _scores(y_test, pred, prob),
            "confusion": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
            "timing": {"fit_seconds": round(fit_seconds, 3), "predict_ms": round(predict_ms, 2)},
            "cv": {
                m: {
                    "mean": round(float(cv_res[f"test_{m}"].mean()), 4),
                    "std": round(float(cv_res[f"test_{m}"].std()), 4),
                    "folds": [round(float(v), 4) for v in cv_res[f"test_{m}"]],
                }
                for m in scoring
            },
        }
        fitted[name] = model

    rf_f1 = results[RF_NAME]["cv"]["f1"]["mean"]
    lr_f1 = results[LR_NAME]["cv"]["f1"]["mean"]
    if rf_f1 - lr_f1 > TIE_MARGIN:
        selected = RF_NAME
        reason = (
            f"Random Forest had the higher cross-validated F1 on under-performing "
            f"students ({rf_f1:.3f} against {lr_f1:.3f})."
        )
    elif lr_f1 - rf_f1 > TIE_MARGIN:
        selected = LR_NAME
        reason = (
            f"Logistic Regression had the higher cross-validated F1 on "
            f"under-performing students ({lr_f1:.3f} against {rf_f1:.3f})."
        )
    else:
        selected = LR_NAME
        reason = (
            f"The two models were within {TIE_MARGIN} F1 of each other "
            f"({rf_f1:.3f} and {lr_f1:.3f}), so the more interpretable Logistic "
            f"Regression was kept, as section 2.4.4 of the report directs."
        )
    model = fitted[selected]

    # Is the gap between the two models more than noise? McNemar's exact test
    # on the held-out records where exactly one of them was right.
    rf_only = int((correct[RF_NAME] & ~correct[LR_NAME]).sum())
    lr_only = int((~correct[RF_NAME] & correct[LR_NAME]).sum())
    mcnemar_p = (
        float(stats.binomtest(rf_only, rf_only + lr_only, 0.5).pvalue)
        if rf_only + lr_only else 1.0
    )
    comparison = {
        "rf_only_correct": rf_only,
        "lr_only_correct": lr_only,
        "p_value": round(mcnemar_p, 4),
        "significant": bool(mcnemar_p < 0.05),
    }

    # Calibration: fitted on out-of-fold training predictions, checked on the
    # held-out test records.
    oof = cross_val_predict(model, X_train, y_train, cv=cv, method="predict_proba")[:, 1]
    platt = LogisticRegression(C=1e6, max_iter=1000).fit(_logit(oof).reshape(-1, 1), y_train)
    calibration = {"method": "Platt scaling", "a": float(platt.coef_[0, 0]), "b": float(platt.intercept_[0])}
    raw_test = model.predict_proba(X_test)[:, 1]
    cal_test = calibrate(raw_test, calibration)
    reliability = []
    for lo, hi in [(0, .05), (.05, .2), (.2, .35), (.35, .5), (.5, .7), (.7, .9), (.9, 1.01)]:
        mask = (cal_test >= lo) & (cal_test < hi)
        if mask.any():
            reliability.append({
                "range": f"{round(lo * 100)} to {min(round(hi * 100), 100)}%",
                "n": int(mask.sum()),
                "predicted": round(float(cal_test[mask].mean()), 4),
                "observed": round(float(y_test[mask].mean()), 4),
            })
    test_bands = np.array([band_for(s_, c_) for s_, c_ in zip(raw_test, cal_test)])
    bands = []
    for band in ("Low", "Medium", "High"):
        mask = test_bands == band
        bands.append({
            "band": band,
            "n": int(mask.sum()),
            "share": round(float(mask.mean()), 4),
            "observed": round(float(y_test[mask].mean()), 4) if mask.any() else None,
        })
    calibration_report = {
        **calibration,
        "brier_raw": round(float(brier_score_loss(y_test, raw_test)), 4),
        "brier_calibrated": round(float(brier_score_loss(y_test, cal_test)), 4),
        "flag_from": round(float(calibrate(DECISION_THRESHOLD, calibration)), 4),
        "high_from": HIGH_FROM,
        "reliability": reliability,
        "bands": bands,
    }
    feature_ranges = {
        f: [round(float(X_train[:, i].min()), 2), round(float(X_train[:, i].max()), 2)]
        for i, f in enumerate(FEATURES)
    }

    # Majority-class baseline: what "chance" looks like on this data.
    dummy = DummyClassifier(strategy="most_frequent").fit(X_train, y_train)
    dummy_pred = dummy.predict(X_test)
    baseline = {
        "accuracy": round(float(accuracy_score(y_test, dummy_pred)), 4),
        "f1": round(float(f1_score(y_test, dummy_pred, zero_division=0)), 4),
    }

    # Which indicators the deployed model leans on.
    perm = permutation_importance(
        model, X_test, y_test, scoring="f1", n_repeats=10, random_state=SEED
    )
    total = perm.importances_mean.clip(min=0).sum() or 1.0
    importance = [
        {
            "feature": f,
            "label": FEATURE_LABELS[f],
            "share": round(float(max(perm.importances_mean[i], 0) / total), 4),
            "drop_in_f1": round(float(perm.importances_mean[i]), 4),
        }
        for i, f in enumerate(FEATURES)
    ]

    # Hypothesis test (section 1.5).
    indicator_tests = []
    for i, f in enumerate(FEATURES):
        r, p = stats.pointbiserialr(y, X[:, i])
        indicator_tests.append(
            {
                "feature": f,
                "label": FEATURE_LABELS[f],
                "r": round(float(r), 4),
                "p_value": float(p),
                "significant": bool(p < 0.05),
            }
        )
    light = (
        RandomForestClassifier(
            n_estimators=40, max_depth=8, min_samples_leaf=5,
            class_weight="balanced", random_state=SEED, n_jobs=-1,
        )
        if selected == RF_NAME
        else _candidates()[LR_NAME]
    )
    rng = np.random.default_rng(SEED)
    idx = rng.choice(len(y_train), size=min(len(y_train), 1500), replace=False)
    score, perm_scores, p_value = permutation_test_score(
        light, X_train[idx], y_train[idx], scoring="accuracy",
        cv=StratifiedKFold(3, shuffle=True, random_state=SEED),
        n_permutations=permutations, random_state=SEED,
    )
    hypothesis = {
        "indicators": indicator_tests,
        "permutation": {
            "score": round(float(score), 4),
            "shuffled_mean": round(float(perm_scores.mean()), 4),
            "p_value": round(float(p_value), 4),
            "n_permutations": int(permutations),
        },
        "reject_null": bool(p_value < 0.05 and all(t["significant"] for t in indicator_tests)),
    }

    trained_at = datetime.now(timezone.utc)
    version = trained_at.strftime("%Y%m%d-%H%M")
    metrics = {
        "version": version,
        "trained_at": trained_at.isoformat(),
        "sklearn_version": sklearn.__version__,
        "data_file": path.name,
        "features": FEATURES,
        "data": data_summary,
        "models": results,
        "selected": selected,
        "selection_reason": reason,
        "baseline": baseline,
        "comparison": comparison,
        "calibration": calibration_report,
        "feature_ranges": feature_ranges,
        "importance": importance,
        "hypothesis": hypothesis,
        "feature_means": {
            f: round(float(X_train[:, i].mean()), 2) for i, f in enumerate(FEATURES)
        },
    }
    if save:
        MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {
                "model": model,
                "name": selected,
                "features": FEATURES,
                "version": version,
                "base_rate": float(y_train.mean()),
                "calibration": calibration,
                "feature_ranges": feature_ranges,
            },
            MODEL_PATH,
        )
        METRICS_PATH.write_text(json.dumps(metrics, indent=2))
    return metrics
