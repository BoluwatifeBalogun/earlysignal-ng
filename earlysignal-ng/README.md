# EarlySignal NG

An AI-based student performance prediction system for Nigerian tertiary institutions.
It is the implementation of the HND seminar write-up *Design and Implementation of an
AI-Based Student Performance Prediction System* (Olasimbo Bilaal Olaotan, F/HD/24/3211030,
Department of Computer Science, Yaba College of Technology), with the case study widened
from one department to Nigeria as a whole.

A lecturer or academic adviser enters three figures for a student (continuous assessment
score, attendance rate, previous GPA). The system returns the predicted outcome, a risk
band, and an explanation of which figure pushed the estimate up or down.

## Run it

Python 3.11 or newer.

```bash
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
python manage.py bootstrap        # creates the database, loads the model, adds demo data
python manage.py runserver
```

Open http://127.0.0.1:8000

| Account | Username | Password |
|---|---|---|
| Administrator | `admin` | `Admin@2026` |
| Lecturer / adviser | `lecturer` | `Lecturer@2026` |

Change both passwords before showing the system to anyone outside the project.

If the model fails to load after installing different library versions, rebuild it with
`python manage.py train_model` (about 30 seconds).

## Commands

| Command | What it does |
|---|---|
| `python manage.py bootstrap` | Migrate, train the model if none exists, seed demo data |
| `python manage.py train_model` | Clean the dataset, train Random Forest and Logistic Regression, evaluate, deploy the better one |
| `python manage.py train_model --data path/to/file.csv` | Train on your own labelled records |
| `python manage.py seed_demo` | Add the demo accounts and 280 demo students |
| `python manage.py test` | Run the 52 unit and integration tests |

## What is inside

```
config/                 Django project settings and root URLs
core/                   The web application (presentation and application tiers)
  models.py             User, Student, AcademicRecord, Prediction (the ERD in Figure 3.2)
  views.py, forms.py    Pages, validation, role checks
  services/predictor.py Loads the trained model, predicts, explains, suggests next steps
  services/records.py   Saves predictions, imports CSV files row by row
  nigeria.py            36 states and the FCT, six zones, institution types, GPA scales
  templates/, static/   Green and white interface, self-hosted fonts, no CDN needed
  tests/                Unit and integration tests
ml/                     The machine learning tier
  dataset.py            Synthetic Nigeria-wide dataset generator
  pipeline.py           Cleaning, split, training, cross-validation, hypothesis test
  explain.py            Per-prediction contribution of each indicator
  artifacts/            model.joblib and metrics.json
  data/                 nigeria_student_records.csv
notebooks/              01_eda.ipynb, the sprint 1 cleaning and exploratory analysis (already run)
docs/                   PLAN.md (algorithm, flow, work plan, traceability to the write-up)
                        AUDIT.md (audit of the build against the write-up, with a field scenario)
                        UAT_QUESTIONNAIRE.md (user acceptance testing form)
```

## The model in brief

- Inputs: CA score (%), attendance (%), previous GPA as a percentage of its scale
  (4.00 for polytechnics, 5.00 for universities and colleges of education).
- Target: under-perform (semester average below 50) or pass.
- Random Forest is compared with a Logistic Regression baseline on an 80/20 stratified
  split and 5-fold cross-validation. The one with the higher cross-validated F1 is
  deployed. On a near tie (within 0.005) the simpler Logistic Regression is kept.
- The model's score is calibrated (Platt scaling) so the chance shown matches how often
  students with that score really under-performed in testing.
- Risk bands: low means not flagged (chance under about 33%). Medium means flagged as
  at risk but still more likely to pass than not (33% to 50%). High means more likely
  than not to under-perform (50% or more). In testing, 4%, 33% and 83% of the students
  in those bands went on to under-perform.

Current results on 1,157 held-out records:

| Model | Accuracy | Precision | Recall | F1 | ROC AUC |
|---|---|---|---|---|---|
| Random Forest (deployed) | 88.7% | 74.1% | 89.1% | 80.9% | 96.1% |
| Logistic Regression | 88.2% | 73.0% | 89.1% | 80.2% | 95.8% |

Predicting "pass" for everyone would score 73.0%.

## The data is synthetic

No real student records were available, so `ml/dataset.py` generates 6,000 records
shaped by Nigerian assessment rules (the 75% attendance requirement, NBTE and NUC GPA
scales), plus deliberate duplicates and gaps so the cleaning step has work to do. The
figures above describe how well the method works on that data. They are not evidence
about real students. To use real data, export anonymised records with the columns
`ca_score, attendance_rate, previous_gpa, gpa_scale, outcome` (or `previous_result` as a
percentage) and retrain from the Model performance page or the command line.

## Hosting

Set these environment variables on the host (Render, Railway, PythonAnywhere, a VPS):

```
DJANGO_SECRET_KEY=<a long random string>
DJANGO_DEBUG=0
DJANGO_ALLOWED_HOSTS=yourdomain.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://yourdomain.com
```

With `DJANGO_DEBUG=0` the app refuses to start on the default secret key, marks cookies
as secure and redirects to HTTPS. Set `DJANGO_SSL_REDIRECT=0` only if you need to test
production mode on plain HTTP.

Build command: `pip install -r requirements.txt && python manage.py collectstatic --noinput && python manage.py bootstrap`

Start command: `gunicorn config.wsgi --timeout 120` (retraining from the Model performance page
takes about 20 seconds, close to Gunicorn's default 30 second limit)

SQLite is fine for a defence demo. On hosts with a temporary disk the database resets on
each deploy, so point `DATABASES` at PostgreSQL for anything that has to last. With
`DJANGO_DEBUG=0` the sign-in page no longer shows the demo account buttons.

## Limits worth stating in the defence

- A prediction is an estimate that supports an adviser's judgement. It is not a grade.
- Three indicators cannot capture everything that affects a student (health, finance,
  family). The write-up scopes the system to these three on purpose.
- The explanation shows what moved the model's estimate. It does not prove cause.
- The gap between Random Forest and Logistic Regression is not statistically
  significant on this data (McNemar p = 0.46). See docs/AUDIT.md before the defence.
