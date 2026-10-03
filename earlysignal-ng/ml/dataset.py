"""Synthetic national dataset generator.

No institution has released records for this project, so the bundled training
data is synthetic. It is modelled on how Nigerian tertiary assessment actually
works rather than drawn at random:

* continuous assessment and the previous GPA both track an underlying ability
* attendance tracks engagement, with a minority of disengaged students
* falling below the 75% attendance requirement carries a real penalty
* weak CA combined with weak attendance compounds
* polytechnics report GPA on 4.00, universities and colleges on 5.00

The raw file deliberately contains duplicate rows and rows with missing
indicators so the cleaning step in ml/pipeline.py has real work to do, as
section 3.5 of the report describes. Replace this file with real, anonymised
records whenever an institution grants access; nothing else has to change.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from core import nigeria

OUTCOME_PASS = "Pass"
OUTCOME_UNDER = "Under-perform"
PASS_MARK = 50  # semester average below this counts as under-performing


def generate(n: int = 6000, seed: int = 2026) -> pd.DataFrame:
    rng = np.random.default_rng(seed)

    inst_idx = rng.integers(0, len(nigeria.INSTITUTIONS), n)
    inst = [nigeria.INSTITUTIONS[i] for i in inst_idx]
    inst_type = np.array([i[1] for i in inst])
    state = np.array([i[2] for i in inst])
    zone = np.array([nigeria.zone_for(s) for s in state])
    scale = np.array([nigeria.scale_for(t) for t in inst_type])
    level = np.array([rng.choice(nigeria.LEVELS[t]) for t in inst_type])
    semester = rng.choice(["First", "Second"], n)

    ability = rng.normal(0, 1, n)
    disengaged = rng.random(n) < 0.14

    prev_pct = np.clip(57 + 11 * ability + rng.normal(0, 8, n), 18, 98)
    gpa = np.round(prev_pct / 100 * scale, 2)

    attendance = 82 + 6 * ability + rng.normal(0, 9, n)
    attendance = attendance - disengaged * rng.uniform(12, 38, n)
    attendance = np.clip(np.round(attendance), 15, 100)

    ca = 58 + 10 * ability + 0.28 * (attendance - 80) + rng.normal(0, 9, n)
    ca = np.clip(np.round(ca, 1), 5, 100)

    semester_avg = (
        0.46 * ca
        + 0.30 * (gpa / scale * 100)
        + 0.16 * attendance
        + 4.5
        + rng.normal(0, 5.5, n)
    )
    below_requirement = attendance < nigeria.ATTENDANCE_REQUIREMENT
    semester_avg = semester_avg - below_requirement * 5.0
    semester_avg = semester_avg - ((ca < 45) & (attendance < 70)) * 5.0
    outcome = np.where(semester_avg < PASS_MARK, OUTCOME_UNDER, OUTCOME_PASS)

    df = pd.DataFrame(
        {
            "ref_code": [f"NG-{i:06d}" for i in range(1, n + 1)],
            "institution_type": inst_type,
            "state": state,
            "zone": zone,
            "level": level,
            "semester": semester,
            "ca_score": ca,
            "attendance_rate": attendance,
            "previous_gpa": gpa,
            "gpa_scale": scale,
            "outcome": outcome,
        }
    )

    # Realistic mess: about 3% of rows lose one indicator, about 2% are
    # entered twice.
    for col in ("ca_score", "attendance_rate", "previous_gpa"):
        mask = rng.random(n) < 0.011
        df.loc[mask, col] = np.nan
    dupes = df.sample(frac=0.02, random_state=seed)
    df = pd.concat([df, dupes], ignore_index=True)
    return df.sample(frac=1, random_state=seed).reset_index(drop=True)


if __name__ == "__main__":
    out = generate()
    print(out.head())
    print(out["outcome"].value_counts(normalize=True))
