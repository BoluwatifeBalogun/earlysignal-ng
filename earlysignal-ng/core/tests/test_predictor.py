import numpy as np
from django.test import SimpleTestCase

from core.services import predictor


class PredictorTests(SimpleTestCase):
    def test_model_is_available(self):
        self.assertTrue(predictor.model_ready())

    def test_result_shape_and_ranges(self):
        r = predictor.predict(55, 70, 60)
        self.assertGreaterEqual(r["probability"], 0)
        self.assertLessEqual(r["probability"], 1)
        self.assertIn(r["risk"], {"Low", "Medium", "High"})
        self.assertIn(r["outcome"], {predictor.OUTCOME_PASS, predictor.OUTCOME_UNDER})
        self.assertEqual([f["feature"] for f in r["factors"]],
                         ["ca_score", "attendance_rate", "previous_result"])
        self.assertTrue(r["advice"])

    def test_contributions_and_baseline_sum_to_the_probability(self):
        for x in [(20, 40, 30), (55, 70, 60), (85, 95, 90), (40, 90, 35), (75, 30, 80)]:
            r = predictor.predict(*x)
            total = r["baseline"] + sum(f["contribution"] for f in r["factors"])
            self.assertAlmostEqual(total, r["probability"], places=2, msg=str(x))

    def test_weak_and_strong_students_land_in_opposite_bands(self):
        weak = predictor.predict(15, 35, 25)
        strong = predictor.predict(88, 96, 90)
        self.assertEqual(weak["risk"], "High")
        self.assertEqual(weak["outcome"], predictor.OUTCOME_UNDER)
        self.assertEqual(strong["risk"], "Low")
        self.assertEqual(strong["outcome"], predictor.OUTCOME_PASS)

    def test_risk_falls_as_each_indicator_improves(self):
        low = np.array([[20, 60, 55], [55, 25, 55], [55, 60, 15]], dtype=float)
        high = np.array([[90, 60, 55], [55, 98, 55], [55, 60, 95]], dtype=float)
        for a, b in zip(predictor.predict_many(low), predictor.predict_many(high)):
            self.assertGreater(a["probability"], b["probability"])

    def test_bands_line_up_with_the_decision(self):
        from ml.pipeline import band_for
        self.assertEqual(band_for(0.49, 0.30), "Low")       # not flagged
        self.assertEqual(band_for(0.50, 0.33), "Medium")    # flagged, still likelier to pass
        self.assertEqual(band_for(0.80, 0.50), "High")      # more likely than not
        for x in [(20, 40, 30), (52, 74, 55), (48, 71, 55), (85, 95, 90)]:
            r = predictor.predict(*x)
            flagged = r["outcome"] == predictor.OUTCOME_UNDER
            self.assertEqual(flagged, r["risk"] != "Low", msg=str(x))
            self.assertEqual(r["risk"] == "High", r["probability"] >= 0.5, msg=str(x))

    def test_single_and_bulk_predictions_agree(self):
        rows = [(20, 40, 30), (52, 74, 55), (85, 95, 90)]
        for row, bulk in zip(rows, predictor.predict_many(rows)):
            single = predictor.predict(*row)
            self.assertEqual((single["probability"], single["risk"], single["outcome"]),
                             (bulk["probability"], bulk["risk"], bulk["outcome"]))

    def test_calibration_lowers_the_inflated_middle_scores(self):
        r = predictor.predict(52, 74, 55)
        self.assertNotEqual(r["score"], r["probability"])
        metrics = predictor.load_metrics()
        self.assertLess(metrics["calibration"]["brier_calibrated"], metrics["calibration"]["brier_raw"])
        for row in metrics["calibration"]["reliability"]:   # shown chance within 10 points of reality
            self.assertLess(abs(row["predicted"] - row["observed"]), 0.10, msg=row["range"])

    def test_figures_outside_the_training_range_carry_a_caution(self):
        self.assertTrue(predictor.predict(70, 2, 70)["cautions"])
        self.assertFalse(predictor.predict(60, 80, 60)["cautions"])

    def test_bad_inputs_are_rejected(self):
        for bad in [("x", 50, 50), (50, None, 50), (50, 50, 101), (-1, 50, 50), ("nan", 50, 50)]:
            with self.assertRaises(ValueError):
                predictor.predict(*bad)

    def test_single_prediction_is_fast(self):
        import time
        predictor.predict(50, 50, 50)  # warm the cache
        start = time.perf_counter()
        predictor.predict(61, 72, 48)
        self.assertLess(time.perf_counter() - start, 1.0)
