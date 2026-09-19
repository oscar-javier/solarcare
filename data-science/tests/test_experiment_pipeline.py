import unittest

import pandas as pd

from experiment_pipeline import build_temporal_split, compute_train_max_normalization


class TestExperimentPipeline(unittest.TestCase):
    def test_train_max_used_for_normalization_without_leakage(self):
        df = pd.DataFrame(
            {
                "system_id": [1, 1, 1, 1, 1, 1],
                "timestamp": pd.to_datetime([
                    "2020-01-01 00:00:00",
                    "2020-01-01 01:00:00",
                    "2020-01-01 02:00:00",
                    "2020-01-01 03:00:00",
                    "2020-01-01 04:00:00",
                    "2020-01-01 05:00:00",
                ]),
                "ac_power": [10, 20, 30, 40, 50, 100],
                "poa_irradiance": [1, 2, 3, 4, 5, 6],
                "ambient_temp": [10, 11, 12, 13, 14, 15],
                "sin_hora": [0.0, 0.1, 0.2, 0.3, 0.4, 0.5],
                "cos_hora": [1.0, 0.9, 0.8, 0.7, 0.6, 0.5],
                "sin_dia_anual": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6],
                "cos_dia_anual": [0.9, 0.8, 0.7, 0.6, 0.5, 0.4],
            }
        )

        train, test = build_temporal_split(df, test_fraction=0.5, seed=42)
        result = compute_train_max_normalization(train, test, target_column="ac_power")

        # Entrenamiento tiene max=40, pruebas no deben afectar la normalización.
        self.assertAlmostEqual(result["train_max_by_system"][1], 40.0)
        self.assertAlmostEqual(result["test"]["ac_power_norm"].iloc[-1], 100 / 40.0, places=6)

    def test_temporal_split_keeps_older_rows_in_train(self):
        df = pd.DataFrame(
            {
                "system_id": [1, 1, 1, 1, 1],
                "timestamp": pd.to_datetime([
                    "2020-01-01 00:00:00",
                    "2020-01-01 01:00:00",
                    "2020-01-01 02:00:00",
                    "2020-01-01 03:00:00",
                    "2020-01-01 04:00:00",
                ]),
                "ac_power": [10, 20, 30, 40, 50],
                "poa_irradiance": [1, 2, 3, 4, 5],
                "ambient_temp": [10, 11, 12, 13, 14],
                "sin_hora": [0.1, 0.2, 0.3, 0.4, 0.5],
                "cos_hora": [0.9, 0.8, 0.7, 0.6, 0.5],
                "sin_dia_anual": [0.1, 0.2, 0.3, 0.4, 0.5],
                "cos_dia_anual": [0.9, 0.8, 0.7, 0.6, 0.5],
            }
        )

        train, test = build_temporal_split(df, test_fraction=0.4, seed=42)
        self.assertEqual(len(train), 3)
        self.assertEqual(len(test), 2)
        self.assertLess(train["timestamp"].max().timestamp(), test["timestamp"].min().timestamp())


if __name__ == "__main__":
    unittest.main()
