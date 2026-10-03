# EarlySignal NG: algorithm, flow and work plan

Implementation plan for *Design and Implementation of an AI-Based Student Performance
Prediction System* (Olasimbo Bilaal Olaotan, YabaTech Computer Science, 2026), with the
case study set to Nigeria as a whole.

## 1. What the write-up requires

| Area | Requirement (section) |
|---|---|
| Inputs | Three indicators only: CA score, attendance, previous result (1.7, 3.5) |
| Model | Random Forest, compared with a Logistic Regression baseline, chosen on accuracy and interpretability (3.8.4, 3.9) |
| Data rules | Remove duplicates, exclude records with a missing indicator (never impute), replace names with reference codes (3.5, 3.5.1) |
| Stack | Python, Django, scikit-learn, pandas, relational database, HTML/CSS/JS (3.6) |
| Architecture | Three tiers: presentation, application, data (3.8.1) |
| Database | STUDENT, ACADEMIC RECORD, PREDICTION, USER (3.8.2) |
| Users | Lecturer or adviser, administrator (3.8.3) |
| Testing | Unit and integration tests, train/test split, accuracy, precision, recall, F1, confusion matrix, k-fold, UAT (3.10) |
| Hypothesis | H0: the indicators have no significant relationship with performance (1.5) |

## 2. The algorithm

### 2.1 Training (run once, or whenever new data arrives)

```
1. LOAD the labelled records (CSV)
2. CLEAN
   a. drop name columns; keep reference codes only
   b. drop exact duplicate rows
   c. drop any row missing CA score, attendance or previous result (no imputation)
   d. drop rows with a value outside 0 to 100
   e. previous_result = previous_gpa / gpa_scale * 100
      (4.00 scale for polytechnics, 5.00 for universities and colleges of education)
3. LABEL   target = 1 if outcome is "Under-perform" (semester average below 50), else 0
4. SPLIT   80% train, 20% test, stratified on the target, fixed seed
5. TRAIN two candidates on the training part
   a. Random Forest: 300 trees, max depth 8, min 5 records per leaf, balanced class weights
   b. Logistic Regression: standardised inputs, balanced class weights
6. VALIDATE each with 5-fold stratified cross-validation on the training part
7. TEST each on the held-out 20%: accuracy, precision, recall, F1, ROC AUC, confusion matrix
8. SELECT the model with the higher cross-validated F1 on the under-perform class.
   If the gap is under 0.005, keep Logistic Regression because it is easier to interpret.
   Also report McNemar's exact test (is the gap more than noise?) and what each model
   costs to train and to run, since section 1.8 names computational efficiency.
9. CALIBRATE the chosen model. Balanced class weights inflate the raw score, so a
   two-parameter logistic curve (Platt scaling) is fitted on out-of-fold training
   predictions and checked on the test set. The chance shown to a lecturer is the
   calibrated one.
10. TEST THE HYPOTHESIS, as section 1.5 frames it: is accuracy on unseen records
   meaningfully better than chance?
   a. held-out accuracy against the majority-class baseline
   b. permutation test: the model's score against its score on shuffled labels
   c. point-biserial correlation of each indicator with the target, with p-values
   Reject H0 if the permutation p is below 0.05 and every indicator is significant
11. SAVE the chosen model, its calibration and training ranges (model.joblib) and the
   full report (metrics.json)
```

### 2.2 Prediction (every request)

```
INPUT  ca_score, attendance_rate, previous_gpa, institution_type
1. validate: each figure is a number in range; GPA does not exceed its scale
2. previous_result = previous_gpa / scale * 100
3. score  = model.predict_proba([ca_score, attendance_rate, previous_result])
4. chance = calibrate(score)                      -> honest chance of under-performing
5. outcome = "At risk of under-performing" if score >= 0.50 else "On track to pass"
   (this is the decision that precision, recall and F1 measure)
6. risk    = Low if not flagged; Medium if flagged and chance < 50%; High if chance >= 50%
7. explain = contribution of each indicator
      Random Forest: follow the record down every tree and credit each split's change in
      score to the indicator it splits on, then average over the trees.
      Logistic Regression: split the change in log-odds between the indicators.
      The shares are rescaled so starting point + the three shares = the chance shown.
8. caution = a warning if any figure lies outside the range the model was trained on
9. advice  = plain-language next steps from the band and the weakest indicators
             (for example attendance under the 75% examination requirement)
10. store PREDICTION against the ACADEMIC RECORD, with the model version and who asked
OUTPUT outcome, risk band, chance, explanation, advice
```

### 2.3 Why these choices

- **F1 on the under-perform class** drives selection because a missed struggling student
  costs more than a false alarm, and plain accuracy rewards guessing "pass" for everyone.
- **Balanced class weights** stop the model ignoring the smaller under-perform group.
- **Depth and leaf limits** on the forest keep it from memorising a three-column dataset.
- **Per-prediction explanation** answers section 2.4.4: a lecturer sees why, not just what.

## 3. System flow

```
                         PRESENTATION TIER (browser)
   Landing page   Sign in   Dashboard   Students   Record form   CSV import
   Prediction result   History   Model performance   User accounts
                                   |
                                   v
                         APPLICATION TIER (Django)
   urls -> views -> forms (validation, role checks)
                 -> services/records.py   (save, bulk import)
                 -> services/predictor.py (load model, predict, explain, advise)
                 -> ml/pipeline.py        (retrain, administrators only)
                                   |
                 +-----------------+------------------+
                 v                                    v
            DATA TIER                           MODEL ARTEFACTS
   USER, STUDENT, ACADEMIC RECORD,        model.joblib, metrics.json,
   PREDICTION (SQLite, any Django DB)     training dataset (CSV)
```

Lecturer flow: sign in, add or find a student, enter a record (or import a class list),
request a prediction, read the risk band and explanation, act, review the history later.

Administrator flow: everything above, plus create and deactivate accounts, reset
passwords, correct or delete records (the prediction is refreshed), retrain the model.

## 4. Work plan (the five sprints of section 3.9)

| Sprint | Write-up | Delivered here |
|---|---|---|
| 1 | Clean and explore the data | `ml/dataset.py`, the cleaning step in `ml/pipeline.py`, cleaning report on the Model performance page |
| 2 | Train and compare the algorithms | Random Forest against Logistic Regression, 80/20 split, 5-fold CV, selection rule, hypothesis test, `metrics.json` |
| 3 | Database, authentication, data entry | `core/models.py`, sign in and roles, student and record forms, CSV import with row-level errors |
| 4 | Integrate the model and show results | `services/predictor.py`, record page with gauge, explanation, advice and a what-if panel |
| 5 | History, admin functions, refinement, testing | History with filters and CSV export, user accounts, record correction with audit trail, retraining, dashboard by zone, 52 automated tests, UAT form |

## 5. Tools

| Purpose | Tool |
|---|---|
| Language | Python 3.12 |
| Web framework | Django 5.2 |
| Machine learning | scikit-learn 1.8 (RandomForestClassifier, LogisticRegression) |
| Data handling | pandas, NumPy, SciPy (point-biserial test) |
| Model storage | joblib |
| Database | SQLite through the Django ORM (PostgreSQL or MySQL by changing one setting) |
| Front end | Django templates, hand-written CSS and JavaScript, self-hosted fonts |
| Serving | WhiteNoise for static files, Gunicorn |
| Testing | Django test runner (unit and integration) |
| Version control | Git |

## 6. Traceability to the write-up

| Write-up item | Where it lives |
|---|---|
| Objective: build a model from CA, attendance, previous result | `ml/pipeline.py` |
| Objective: web application for data entry and prediction | `core/` |
| Objective: evaluate with accuracy, precision, recall, F1 | Model performance page, `metrics.json` |
| FR: user authentication | `/login/`, hashed passwords, roles |
| FR: single and bulk data entry | Record form, `/app/import/` |
| FR: prediction with risk indication | Record page |
| FR: prediction history | `/app/history/` |
| FR: administrative functions | `/app/users/`, record correction and deletion |
| NFR: usability (TAM) | Plain-language results, visible labels, errors beside fields, mobile layout |
| NFR: response time | One prediction takes about 25 ms on a single core |
| NFR: security | Role checks on every admin view, CSRF, hashed passwords, POST-only sign out, sign-in pause after 5 wrong passwords, formula-safe CSV export |
| NFR: reliability | Bad CSV rows are reported and skipped, good rows still save |
| NFR: maintainability | Model, services and views are separate modules; retraining needs no code change |
| Figure 3.2 ERD | `core/models.py` |
| Figure 3.3 use cases | Lecturer and Administrator roles |
| 3.5.1 ethics | Training file has reference codes only; names never reach the model |
| 3.10 testing | `core/tests/`, Model performance page, `docs/UAT_QUESTIONNAIRE.md` |
| 1.5 hypothesis | Hypothesis test card on the Model performance page |

## 7. Results on the bundled dataset

6,120 rows in the file; 120 duplicates and 217 incomplete rows removed; 5,783 used
(4,626 train, 1,157 test); 26.9% under-performed.

| Model | Accuracy | Precision | Recall | F1 | ROC AUC | CV F1 (5-fold) |
|---|---|---|---|---|---|---|
| Random Forest (deployed) | 0.887 | 0.741 | 0.891 | 0.809 | 0.961 | 0.817 ± 0.014 |
| Logistic Regression | 0.882 | 0.730 | 0.891 | 0.802 | 0.958 | 0.809 ± 0.017 |

Confusion matrix for the Random Forest: 748 passes predicted as pass, 97 passes flagged,
34 under-performers missed, 278 under-performers caught. Majority-class baseline: 0.730.

Hypothesis: point-biserial r = -0.647 (CA), -0.547 (attendance), -0.503 (previous
result), each with p below 0.001. Permutation test: 0.897 on real labels against 0.603
on shuffled labels, p = 0.0099. H0 is rejected.

Indicator importance (share of F1 lost when scrambled): CA 60%, attendance 26%,
previous result 14%.

Model comparison: on the 1,157 test records Random Forest alone was right 26 times and
Logistic Regression alone 20 times. McNemar exact p = 0.46, so the gap is not
statistically significant. Cost: Random Forest about 0.9 s to train and 17 ms per
prediction; Logistic Regression about 0.01 s and 0.3 ms.

Calibration: Brier score 0.077 before, 0.069 after. Risk bands on the test set: Low 782
students of whom 4% under-performed, Medium 66 (33%), High 309 (83%).

The gap between the two models is small (0.008 in cross-validated F1). That is worth
saying plainly in Chapter Four: on three well-behaved indicators a linear model does
nearly as well as a forest.

## 8. Where the build differs from the write-up (to reconcile before the defence)

1. **Scope.** Sections 1.7, 3.3 and 3.4 limit the study to the Department of Computer
   Science, YabaTech. The build is Nigeria-wide as requested. Those sections, the title
   page and the abstract need to say so, or the panel will see a mismatch.
2. **Data source.** Section 3.5 describes secondary data from departmental records.
   The bundled dataset is synthetic. Either collect real anonymised records and retrain,
   or state in Chapter Three that a simulated dataset modelled on Nigerian assessment
   rules was used and list it as a limitation.
3. **Extra Student fields.** Institution, institution type, state and zone were added to
   STUDENT. Figure 3.2 needs those attributes.
4. **Previous result.** Stored as GPA on the institution's own scale and converted to a
   percentage for the model, so 4.00 and 5.00 scales can share one model.
5. **Extra Prediction fields.** Probability, explanation, model name and version, and the
   requesting user were added for interpretability and audit.
6. **Record to student.** A student can hold several records (one per semester or
   reassessment), which matches section 3.3. Each record has at most one prediction.
7. **Students as users.** Section 1.7 names students among the intended users, but
   Figure 3.3 gives only lecturers and administrators a role. The build follows the
   figure. Either drop "students" from 1.7 or describe them as indirect beneficiaries.
8. **Additions.** A public "try the model" panel (stores nothing), a what-if panel on
   each record, CSV export, a national dashboard and in-app retraining go beyond the
   stated requirements.
9. **Hypothesis method.** Section 1.5 says H0 is tested indirectly: accuracy on unseen
   data meaningfully better than chance. The build does exactly that (88.7% against a
   73.0% baseline, permutation p = 0.0099) and adds point-biserial correlations. Name
   the permutation test and the correlations in section 3.10.
10. **Research question 1** asks about "students at Yaba College of Technology". With a
   national case study it needs rewording.
11. **Calibration and risk bands.** Not in the write-up. Section 3.10.2 should mention
   that the score is calibrated and how the three bands are defined.
12. **Still to do by the author:** run the user acceptance test with real lecturers
   (3.10.3), put the code under Git (3.6), and decide how first-semester students with
   no previous result are handled. See docs/AUDIT.md.

## 9. Front-end design notes

- Design rules came from the ui-ux-pro-max skill: data-dense dashboard layout, bento grid
  landing page, 4.5:1 text contrast, 44 px touch targets, visible labels, errors next to
  the field, colour never the only signal (every risk band has an icon and text),
  reduced-motion support, tabular numerals. Its suggested blue palette was replaced with
  green and white.
- Effects modelled on 21st.dev components (border beam, spotlight card, shimmer button,
  number ticker, marquee, blur-fade reveal, dot grid) were rewritten in plain CSS and
  JavaScript. The originals are React and Tailwind components, so they could not be
  dropped into Django templates as they are.
- Layout ideas in the style of Framer sites: floating pill navigation, large tight
  display type, bento tiles, a full-width call-to-action band.
- Fonts: Bricolage Grotesque and Instrument Sans, self-hosted under the SIL Open Font
  License.
