import unittest
from rule_engine import validate_reading, evaluate_reading


class TestRuleEngine(unittest.TestCase):

    def setUp(self):
        self.nominal = {
            "spo2": 98.0, "heart_rate": 72.0,
            "systolic": 120.0, "diastolic": 78.0,
            "resp_rate": 15.0, "temperature": 36.6,
            "signal_quality": 0.95, "movement_detected": False,
        }

    # --- validation ---

    def test_nominal_at_rest_is_green(self):
        ok, reason = validate_reading(self.nominal)
        self.assertTrue(ok)
        self.assertEqual(reason, "")
        res = evaluate_reading(self.nominal, environment="iss")
        self.assertEqual(res.state, "green")
        self.assertEqual(res.next_measurement_minutes, 180)

    def test_spo2_88_at_rest_is_red(self):
        r = {**self.nominal, "spo2": 88.0}
        res = evaluate_reading(r, environment="iss")
        self.assertEqual(res.state, "red")
        self.assertEqual(res.next_measurement_minutes, 5)
        self.assertIn("hypoxia", [c["id"] for c in res.possible_causes])

    def test_diastolic_gte_systolic_is_invalid(self):
        r = {**self.nominal, "systolic": 110.0, "diastolic": 115.0}
        ok, reason = validate_reading(r)
        self.assertFalse(ok)
        self.assertIn("diastolic", reason.lower())
        res = evaluate_reading(r)
        self.assertEqual(res.state, "invalid")
        self.assertFalse(res.is_valid)

    def test_hr_150_age47_eva_is_yellow(self):
        # HR max = 208 - 0.7*47 = 175.1; 150/175.1 = 85.66% -> yellow
        r = {**self.nominal, "heart_rate": 150.0}
        res = evaluate_reading(r, environment="eva", age=47)
        self.assertEqual(res.state, "yellow")
        self.assertEqual(res.indicator_states["heart_rate"]["state"], "yellow")
        self.assertAlmostEqual(res.indicator_states["heart_rate"]["hr_pct_max"], 85.7, places=1)

    def test_spo2_88_altitude_is_yellow(self):
        r = {**self.nominal, "spo2": 88.0}
        res = evaluate_reading(r, environment="altitude")
        self.assertEqual(res.state, "yellow")
        self.assertEqual(res.indicator_states["spo2"]["state"], "yellow")

    def test_systolic_140_at_rest_is_yellow(self):
        r = {**self.nominal, "systolic": 140.0}
        res = evaluate_reading(r, environment="iss")
        self.assertEqual(res.state, "yellow")
        self.assertEqual(res.indicator_states["systolic"]["state"], "yellow")

    def test_temperature_38_5_is_red(self):
        r = {**self.nominal, "temperature": 38.5}
        res = evaluate_reading(r, environment="iss")
        self.assertEqual(res.state, "red")
        self.assertIn("hyperthermia_fever", [c["id"] for c in res.possible_causes])

    def test_low_signal_quality_is_invalid(self):
        r = {**self.nominal, "signal_quality": 0.45}
        ok, reason = validate_reading(r)
        self.assertFalse(ok)
        self.assertIn("signal quality", reason.lower())

    def test_movement_detected_is_invalid(self):
        r = {**self.nominal, "movement_detected": True}
        ok, reason = validate_reading(r)
        self.assertFalse(ok)
        self.assertIn("movement", reason.lower())

    def test_severe_symptom_escalates_state(self):
        symptoms = {"frontal_headache": "severe"}
        res = evaluate_reading(self.nominal, environment="iss", symptoms=symptoms)
        self.assertEqual(res.state, "yellow")
        self.assertIn("Escalated to Caution", res.alert_explanation)

    def test_spo2_above_biological_limit_is_invalid(self):
        r = {**self.nominal, "spo2": 104.0}
        ok, reason = validate_reading(r)
        self.assertFalse(ok)
        self.assertIn("biological limits", reason.lower())

    def test_eva_red_does_not_recommend_cabin_mask(self):
        # HR 170 / 175.1 = 97% -> red in EVA
        r = {**self.nominal, "heart_rate": 170.0}
        res = evaluate_reading(r, environment="eva", age=47)
        self.assertEqual(res.state, "red")
        actions_text = " ".join(res.actions).lower()
        self.assertIn("airlock", actions_text)
        self.assertNotIn("don emergency mask with 100% o2", actions_text)

    def test_state_labels_and_symbols(self):
        res = evaluate_reading(self.nominal, environment="iss")
        self.assertEqual(res.label, "Normal")
        self.assertEqual(res.symbol, "\u25cf")  # ●

    def test_green_result_has_actions(self):
        res = evaluate_reading(self.nominal, environment="iss")
        self.assertTrue(len(res.actions) > 0)
        self.assertIn("Continue", res.actions[0])


if __name__ == "__main__":
    unittest.main()
