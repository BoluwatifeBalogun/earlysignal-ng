"""Per-prediction explanations.

Section 2.4.4 of the report makes interpretability a requirement, not an
extra: a lecturer has to see why a record was flagged. Both candidate models
are explained with the same additive idea, so the interface never changes
when the deployed model does.

    probability of under-performing = baseline + sum(contribution per indicator)

Random Forest: each tree's decision path is walked from root to leaf, and the
change in class probability at every split is credited to the indicator that
split used (the decision-path method of Saabas). Averaged over all trees the
credits add up exactly to the forest's predicted probability.

Logistic Regression: the model is additive in log-odds, so each indicator's
share of the log-odds shift is used to split the probability shift.
"""
from __future__ import annotations

import numpy as np


def _tree_contributions(tree, x: np.ndarray, positive: int, n_features: int):
    t = tree.tree_
    values = t.value[:, 0, :]
    values = values / values.sum(axis=1, keepdims=True)
    node = 0
    bias = values[0, positive]
    contrib = np.zeros(n_features)
    while t.children_left[node] != -1:
        feature = t.feature[node]
        child = (
            t.children_left[node]
            if x[feature] <= t.threshold[node]
            else t.children_right[node]
        )
        contrib[feature] += values[child, positive] - values[node, positive]
        node = child
    return bias, contrib


def explain_forest(forest, x: np.ndarray, positive: int):
    n_features = x.shape[0]
    bias = 0.0
    contrib = np.zeros(n_features)
    for est in forest.estimators_:
        b, c = _tree_contributions(est, x, positive, n_features)
        bias += b
        contrib += c
    n = len(forest.estimators_)
    return bias / n, contrib / n


def explain_logistic(pipeline, x: np.ndarray, positive: int, base_rate: float):
    scaler = pipeline.named_steps["scale"]
    clf = pipeline.named_steps["clf"]
    z = (x - scaler.mean_) / scaler.scale_
    sign = 1.0 if clf.classes_[1] == positive or positive == 1 else -1.0
    logit_parts = sign * clf.coef_[0] * z
    proba = float(pipeline.predict_proba(x.reshape(1, -1))[0, positive])
    bias = float(
        1.0 / (1.0 + np.exp(-sign * clf.intercept_[0]))
    )  # probability for an average record
    shift = proba - bias
    total = logit_parts.sum()
    if abs(total) < 1e-9:
        contrib = np.zeros_like(logit_parts)
    else:
        contrib = logit_parts / total * shift
        # When indicators pull in opposite directions the shares can blow up;
        # fall back to a bounded split in that case.
        if np.abs(contrib).max() > 1.0:
            weights = logit_parts / np.abs(logit_parts).sum()
            contrib = weights * abs(shift) if shift else weights * 0
            contrib = contrib + (shift - contrib.sum()) / len(contrib)
    return bias, contrib
