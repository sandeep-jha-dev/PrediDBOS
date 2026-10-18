import sys
import unittest
from pathlib import Path

import numpy as np

# Import the existing calibration implementation.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "ml"))

from calibration import (
    MulticlassPlattCalibrator,
    compute_ece,
    compute_ece_binary,
)


class TestCalibrationMetrics(unittest.TestCase):

    def test_ece_is_zero_for_perfect_certain_predictions(self):
        probabilities = np.array([
            [1.0, 0.0],
            [0.0, 1.0],
        ])
        true_labels = np.array([0, 1])

        result = compute_ece(probabilities, true_labels)

        self.assertAlmostEqual(result, 0.0)

    def test_ece_is_one_for_certain_wrong_predictions(self):
        probabilities = np.array([
            [1.0, 0.0],
            [0.0, 1.0],
        ])
        true_labels = np.array([1, 0])

        result = compute_ece(probabilities, true_labels)

        self.assertAlmostEqual(result, 1.0)

    def test_binary_ece_is_zero_for_perfect_predictions(self):
        probabilities = np.array([1.0, 0.0])
        true_labels = np.array([1.0, 0.0])

        result = compute_ece_binary(probabilities, true_labels)

        self.assertAlmostEqual(result, 0.0)


class TestMulticlassPlattCalibrator(unittest.TestCase):

    def test_prediction_requires_fitted_calibrator(self):
        calibrator = MulticlassPlattCalibrator(n_classes=2)
        probabilities = np.array([[0.7, 0.3]])

        with self.assertRaises(ValueError):
            calibrator.predict_proba(probabilities)

    def test_fit_rejects_wrong_number_of_classes(self):
        calibrator = MulticlassPlattCalibrator(n_classes=2)
        probabilities = np.array([[0.7, 0.2, 0.1]])
        true_labels = np.array([0])

        with self.assertRaises(ValueError):
            calibrator.fit(probabilities, true_labels)

    def test_calibrated_probabilities_sum_to_one(self):
        probabilities = np.array([
            [0.9, 0.1],
            [0.8, 0.2],
            [0.7, 0.3],
            [0.3, 0.7],
            [0.2, 0.8],
            [0.1, 0.9],
        ])
        true_labels = np.array([0, 0, 0, 1, 1, 1])

        calibrator = MulticlassPlattCalibrator(n_classes=2)
        calibrator.fit(probabilities, true_labels)
        calibrated = calibrator.predict_proba(probabilities)

        self.assertEqual(calibrated.shape, probabilities.shape)
        self.assertTrue(np.all(calibrated >= 0.0))
        self.assertTrue(np.all(calibrated <= 1.0))
        np.testing.assert_allclose(
            calibrated.sum(axis=1),
            np.ones(len(calibrated)),
            atol=1e-8,
        )


if __name__ == "__main__":
    unittest.main()
