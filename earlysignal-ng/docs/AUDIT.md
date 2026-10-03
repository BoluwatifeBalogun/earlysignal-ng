# Audit: EarlySignal NG against the seminar write-up

Audited on 2 October 2026 against *Design and Implementation of an AI-Based Student
Performance Prediction System* (Olasimbo Bilaal Olaotan), Chapters 1 to 3. The audit had
three parts: a line-by-line check of the build against every objective, requirement and
design decision in the write-up; a validity check of the model beyond its headline
metrics; and a field scenario run in a real browser.

## 1. Verdict

The build does what Chapter Three specifies. All six functional requirements work, the
architecture and database match Figures 3.1 to 3.3, and the model is trained, compared
and evaluated the way sections 3.8.4 and 3.10 describe.

The audit also found thirteen defects, the most serious being that the "chance of
under-performing" shown to lecturers was overstated in the middle of the range. All
thirteen are fixed in this version (section 3).

Seven matters remain open. They are decisions for the author, not bugs (section 4). Three
of them will come up in a defence: the data is synthetic, the write-up still describes a
single department, and Random Forest does not beat Logistic Regression by a
statistically significant margin.

## 2. Conformance to the write-up

Status: **Met**, **Met with a deviation** (works, but differs from the text), **Open**
(not yet satisfied).

### Aim, objectives and research questions

| Item | Status | Evidence |
|---|---|---|
| Aim: web-based system, Random Forest evaluated against Logistic Regression, three indicators, early estimates | Met | `ml/pipeline.py`, Model performance page |
| Objective 1: examine and identify suitable indicators | Met | Permutation importance (CA 60%, attendance 26%, previous result 14%), correlations, `notebooks/01_eda.ipynb` |
| Objective 2: design the architecture and database | Met with a deviation | Three tiers and four entities as designed; STUDENT and PREDICTION carry extra fields |
| Objective 3: develop the model and integrate it | Met | `core/services/predictor.py`; a prediction is stored against its record |
| Objective 4: test accuracy, functionality and usability | Open | Accuracy and functionality are tested. Usability has a questionnaire but no respondents yet |
| RQ1: which indicators matter most "at Yaba College of Technology" | Met with a deviation | Answered, but on national synthetic data. The question needs rewording |
| RQ2: how to structure the system | Met | `docs/PLAN.md` section 3 |
| RQ3: what accuracy is achievable | Met with a deviation | 88.7% on held-out records, but the records are synthetic |
| RQ4: how functional, accurate and usable | Open | Same gap as objective 4 |
| H0 and H1 (1.5): accuracy meaningfully better than chance on unseen data | Met | 88.7% against a 73.0% baseline; permutation test p = 0.0099; all three correlations p < 0.001. H0 rejected |

### Functional requirements (3.7.2)

| Requirement | Status | Evidence from the scenario |
|---|---|---|
| 1. User authentication | Met | Wrong password refused with a clear message; weak new password refused; deactivated account signed out on its next click |
| 2. Entry or import, single and bulk | Met | Record form with validation beside each field; a 41-row class list and a 2,000-row file imported |
| 3. Prediction from the trained model | Met | Stored in 35 ms once the model is loaded |
| 4. Result with risk indication a non-technical lecturer can read | Met | Band, plain-language outcome, reasons, next steps, and how students in that band actually turned out |
| 5. Prediction history | Met | History page with filters and export; each student page shows the signal over time |
| 6. Admin: manage accounts, correct records | Met | Account creation, password reset, deactivation, record correction with an audit trail |

### Non-functional requirements (3.7.3)

| Requirement | Status | Measured |
|---|---|---|
| Usability (TAM) | Open | Designed for it (visible labels, errors by the field, works at phone width, no horizontal scroll on any page at 375 px), but not yet measured with users |
| Response time | Met | One prediction: 25 ms median on one core. First prediction after a restart: about 1.1 s while the model loads. 2,000-row import with predictions: 7.6 s. Pages: 70 to 380 ms with 2,300 students |
| Reliability of the model | Met | Section 5 below |
| Security | Met with a deviation | Anonymous users are redirected from every app page; lecturers get 403 on every admin action; CSRF enforced; sign out is POST only; passwords hashed (PBKDF2); script tags in names are escaped. Deviation: no per-institution access control (section 4, item 4) |
| Maintainability | Met with a deviation | Django conventions, separate model, service and view modules, 52 tests, documentation. Deviation: the project is not yet under Git |

### Design (3.8), tools (3.6), method (3.9), testing (3.10)

| Item | Status | Note |
|---|---|---|
| Three-tier architecture (Fig. 3.1) | Met | The model can be retrained or swapped without touching the interface |
| ERD (Fig. 3.2) | Met with a deviation | Same four entities and relationships. Added: institution, type, state, zone on STUDENT; chance, explanation, model version, requester on PREDICTION; corrected-by and corrected-at on ACADEMIC RECORD |
| Use cases (Fig. 3.3) | Met | Lecturer and administrator, as drawn |
| Algorithm selection (3.8.4) | Met | Both trained and compared empirically. See section 4, item 3 |
| Python, scikit-learn, pandas, Django, HTML/CSS/JS, relational database | Met | SQLite by default |
| Jupyter Notebook | Met | `notebooks/01_eda.ipynb`, already executed |
| Git | Open | No repository history ships with the code |
| Five sprints (3.9) | Met | Mapped in `docs/PLAN.md` section 4 |
| Data from departmental records (3.3 to 3.5) | Open | Synthetic data. Cleaning rules (remove duplicates, exclude and never impute, no names) are implemented exactly |
| Unit and integration testing (3.10.1) | Met | 52 tests, all passing |
| Train/test split, accuracy, precision, recall, F1, confusion matrix, k-fold (3.10.2) | Met | Model performance page |
| User acceptance testing (3.10.3) | Open | `docs/UAT_QUESTIONNAIRE.md` is ready; nobody has filled it in |

## 3. Defects found and fixed

1. **The chance shown was overstated.** Both models use balanced class weights, which
   inflates the raw score. A record shown as "57%" belonged to a group where 32% actually
   under-performed; "42%" meant 18%. The score is now calibrated (Platt scaling fitted on
   out-of-fold training predictions). On the test set the shown chance is within 8
   points of reality in every range, and the Brier score fell from 0.077 to 0.069.
2. **Outcome wording and bands did not match the numbers.** A student could be labelled
   "Likely to under-perform" at a true chance near one in three. The outcome is now "At
   risk of under-performing" or "On track to pass", and the bands follow the decision:
   Low is not flagged, Medium is flagged but still more likely to pass, High is more
   likely than not to under-perform. On the test set 4%, 33% and 83% of students in those
   bands under-performed, and each result page now says so.
3. **A record could be filed against the wrong student.** If an imported row carried a
   matric number already in the system, the record was attached to the existing student
   even when the name and institution were different. Such rows are now rejected with a
   message naming the existing student.
4. **The importer rejected what lecturers actually type.** "62%", "18/30", "Lagos
   State", "HND2", "2026/27", column headings like "Student ID", blank spreadsheet rows
   and files saved by Excel in Windows encoding were all refused. All are now accepted.
   Of 41 messy rows, rejections fell from 11 to the 5 that are real errors.
5. **Exported times were in UTC**, one hour behind what the screen showed. Now Lagos time.
6. **Spreadsheet formula injection.** A student name beginning with "=" was exported as a
   live formula. Such cells are now neutralised.
7. **Corrections erased the trail.** When an administrator corrected a record, the old
   figures and the old prediction vanished. The record now shows who corrected it, when,
   what it read before and what the prediction was.
8. **No limit on password guessing.** Sign-in now pauses for 15 minutes after five wrong
   passwords for a username.
9. **Unsafe production defaults.** The app would run in production on the built-in
   secret key with insecure cookies. With `DJANGO_DEBUG=0` it now refuses the default
   key, secures cookies and redirects to HTTPS.
10. **Confident answers outside the model's experience.** No training record had
    attendance under 22%, and the forest rated "CA 70%, attendance 0%" as low risk. Any
    figure outside the training range now carries a visible caution, and a low-risk
    result with a figure that is weak on its own tells the lecturer to use judgement.
11. **Section 1.8 names computational efficiency as a selection criterion and it was not
    reported.** Training and prediction cost per model are now measured and shown.
12. **The model page overstated the permutation test**, which runs on a lighter copy of
    the model. The wording is corrected.
13. **PLAN.md said the write-up names no hypothesis test.** It does (section 1.5). The
    plan is corrected and the build is shown to follow it.

## 4. Open matters for the author

1. **The data is synthetic.** Every accuracy figure describes the method on generated
   records whose outcome was produced from the same three indicators. Chapter Four
   cannot present them as findings about real students. Either obtain anonymised records
   and retrain (one upload), or declare a simulated dataset in Chapter Three and list it
   as a limitation.
2. **The write-up still describes one department.** Title page, abstract, 1.7, RQ1, 3.3
   and 3.4 say Department of Computer Science, YabaTech. The build is national.
3. **Random Forest does not clearly beat the baseline.** Test accuracy 88.7% against
   88.2%. McNemar's exact test gives p = 0.46: not significant. The forest is about 50
   times slower per prediction (17 ms against 0.3 ms) and is harder to explain. It also
   has pockets where the estimate rises as attendance improves (about 2% of steps on a
   5-point grid, by up to 10 points of raw score), and it under-rates rare mixes such as
   CA 24% with attendance 80%. On a stress test of 20,000 unusual combinations the two
   scored the same F1 (0.863 and 0.862). By the write-up's own criteria (accuracy,
   interpretability, efficiency) Logistic Regression is a defensible choice. Either keep
   the forest and state these limits, or raise `TIE_MARGIN` in `ml/pipeline.py` and
   retrain so the rule keeps the simpler model.
4. **No per-institution access control.** Any lecturer account can view and export
   students from every institution. In the scenario, a search on part of a matric number
   returned a student at another university first. A national deployment needs each
   account tied to an institution. Related: matric numbers are assumed unique across
   Nigeria, which they are not.
5. **Students with no previous result cannot be predicted.** A first-semester student
   has no previous GPA, and the write-up rules out estimating missing values. State this
   as a limitation, or define what "previous result" means for an entrant.
6. **User acceptance testing has not happened** (3.10.3, objective 4, RQ4).
7. **Smaller points.** No Git history. Section 1.7 lists students as users but Figure 3.3
   does not. The record form asks for CA as a percentage, while lecturers usually hold
   it out of 30 or 40 (the importer accepts "18/30", the form does not). Running a
   prediction again replaces the earlier one, as the 1:1 relationship in Figure 3.2
   implies. The train/test split is by record; with real multi-semester data it should
   be by student. Retraining runs inside the web request (about 18 s). The public
   "try the model" endpoint is not rate limited.

## 5. Model validity beyond the headline metrics

| Check | Result |
|---|---|
| Held-out accuracy, precision, recall, F1 | 0.887, 0.741, 0.891, 0.809 |
| 5-fold F1 on training data | 0.817 ± 0.014 |
| Majority-class baseline accuracy | 0.730 |
| Permutation test | 0.897 on real labels, 0.603 on shuffled labels, p = 0.0099 |
| Random Forest against Logistic Regression | 26 against 20 discordant records, McNemar p = 0.46 |
| Calibration (Brier) | 0.077 raw, 0.069 calibrated |
| Band outcomes on the test set | Low 4% of 782, Medium 33% of 66, High 83% of 309 |
| Explanation arithmetic | Starting point plus the three shares equals the chance shown, checked in tests |
| Single and bulk predictions agree | Yes, checked in tests |

## 6. The field scenario

A course adviser for HND 2 Computer Science, working from her phone (390 px wide), with
an administrator on a laptop. Run in a real browser against a running server.

| Step | What happened |
|---|---|
| Admin creates her account | Created |
| She mistypes her password | Clear message, stays on the sign-in page |
| She tries "12345678" as a new password | Refused: too common, entirely numeric |
| She uploads a class list saved by Excel, with Windows encoding and its own column headings | First build: refused. Now: accepted |
| She uploads 41 rows of typical mess | 34 records imported and predicted in 0.3 s, 1 duplicate skipped, 5 rejected with the row number and reason (blank GPA, "ABS" for CA, GPA 4.20 on a 4.00 scale, attendance 105, a matric number that belongs to someone else) |
| A name containing a script tag | Shown as text, not executed |
| She filters to her high-risk students and opens one | CA 33.5%, attendance 60%, previous result 29.5%: High risk, with reasons, next steps and "83% of students in this band went on to under-perform" |
| She tries the what-if panel: attendance up to 90% | Still High. CA and the previous result are the bigger drivers |
| She adds a student by hand, typing the session as "2026" and GPA 4.5 | Both refused beside the field, with the reason |
| She types attendance 8 instead of 80 | Saved: High risk, with a caution that 8% is below anything the model learned from |
| She looks for a way to fix it | No edit button for lecturers, as the use case specifies |
| The administrator corrects it | Prediction refreshed to 26%, Low. The page keeps the old figures and the old prediction, and adds a note that CA of 24% is weak on its own |
| She tries to save a record with no previous GPA | "This field is required" (open matter 5) |
| Three weeks later she enters a second record | The student page shows both and the signal over time |
| She exports her class | Local times; the formula-style name is neutralised |
| Administrator imports 2,000 rows | 7.6 s, all predicted |
| Administrator deactivates her while she is signed in | Her next click lands on the sign-in page |
| JavaScript errors during the whole run | None |
