import pandas as pd
from django.test import SimpleTestCase

from ml import pipeline
from ml.dataset import generate


class CleaningTests(SimpleTestCase):
    def setUp(self):
        self.raw = generate(n=600, seed=7)

    def test_duplicates_and_incomplete_rows_are_removed_not_filled(self):
        clean, summary = pipeline.clean(self.raw)
        self.assertEqual(clean[pipeline.FEATURES].isna().sum().sum(), 0)
        self.assertEqual(clean.duplicated().sum(), 0)
        self.assertEqual(
            summary["rows_used"],
            summary["rows_raw"] - summary["duplicates_removed"] - summary["missing_removed"]
            - summary["out_of_range_removed"] - summary["unknown_label_removed"])

    def test_names_never_reach_the_model(self):
        raw = self.raw.copy()
        raw["full_name"] = "Someone"
        clean, _ = pipeline.clean(raw)
        self.assertNotIn("full_name", clean.columns)

    def test_out_of_range_values_are_dropped(self):
        raw = self.raw.copy()
        raw.loc[raw.index[0], "ca_score"] = 140
        _, summary = pipeline.clean(raw)
        self.assertGreaterEqual(summary["out_of_range_removed"], 1)

    def test_gpa_is_converted_to_a_percentage_of_its_scale(self):
        clean, _ = pipeline.clean(self.raw)
        row = clean.iloc[0]
        self.assertAlmostEqual(row["previous_result"], row["previous_gpa"] / row["gpa_scale"] * 100, places=6)
        self.assertTrue(clean["previous_result"].between(0, 100).all())

    def test_a_ready_made_percentage_column_is_also_accepted(self):
        raw = self.raw.copy()
        raw["previous_result"] = raw["previous_gpa"] / raw["gpa_scale"] * 100
        raw = raw.drop(columns=["previous_gpa", "gpa_scale"])
        clean, _ = pipeline.clean(raw)
        self.assertGreater(len(clean), 200)

    def test_unusable_files_raise_a_clear_error(self):
        with self.assertRaises(pipeline.DatasetError):
            pipeline.clean(pd.DataFrame({"ca_score": [1], "attendance_rate": [1]}))
        with self.assertRaises(pipeline.DatasetError):
            pipeline.clean(self.raw.head(50))

    def test_training_beats_the_majority_baseline(self):
        metrics = pipeline.train(permutations=10, save=False, data_path=self._small())
        best = metrics["models"][metrics["selected"]]["test"]
        majority = max(metrics["data"]["under_perform_share"], 1 - metrics["data"]["under_perform_share"])
        self.assertGreater(best["accuracy"], majority)
        self.assertEqual(set(metrics["models"]), {"Random Forest", "Logistic Regression"})

    def _small(self):
        import tempfile
        from pathlib import Path
        path = Path(tempfile.mkdtemp()) / "small.csv"
        generate(n=900, seed=11).to_csv(path, index=False)
        return path
