import tempfile
import unittest
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.dummy import DummyRegressor

from production_pv_pipeline import (
    PRODUCTION_FEATURES,
    SystemConfiguration,
    predict_pv_power,
    solar_and_poa_features,
)


class TestProductionPipeline(unittest.TestCase):
    def setUp(self):
        self.config = SystemConfiguration(
            system_id=999,
            latitude=39.74,
            longitude=-105.17,
            elevation_m=1800.0,
            dc_capacity_kW=1.12,
            azimuth_deg=180.0,
            tilt_deg=30.0,
            tracking_type="fixed",
        )
        self.weather = pd.DataFrame(
            {
                "timestamp": pd.to_datetime(["2020-06-21 12:00", "2020-06-21 00:00"]),
                "timezone": ["America/Denver", "America/Denver"],
                "ghi_W_m2": [900.0, 0.0],
                "dni_W_m2": [800.0, 0.0],
                "dhi_W_m2": [100.0, 0.0],
                "ambient_temp_C": [25.0, 15.0],
            }
        )

    def test_solar_position_and_poa_are_reproducible(self):
        features = solar_and_poa_features(self.weather, self.config)
        self.assertEqual(list(features["poa_synthetic_W_m2"] >= 0), [True, True])
        self.assertGreater(features.loc[0, "solar_elevation_deg"], 0)
        self.assertEqual(features.loc[1, "poa_synthetic_W_m2"], 0.0)
        self.assertEqual(set(PRODUCTION_FEATURES), set(features.columns) & set(PRODUCTION_FEATURES))

    def test_invalid_geometry_is_rejected(self):
        with self.assertRaises(ValueError):
            SystemConfiguration(**{**self.config.__dict__, "tilt_deg": -1}).validate()

    def test_inference_reuses_feature_contract_and_reconstructs_watts(self):
        model = DummyRegressor(strategy="constant", constant=0.5)
        model.fit(np.zeros((2, len(PRODUCTION_FEATURES))), [0.5, 0.5])
        with tempfile.TemporaryDirectory() as directory:
            model_path = Path(directory) / "model.joblib"
            joblib.dump(model, model_path)

            def provider(latitude, longitude, timestamp):
                return self.weather.iloc[[0]].copy()

            result = predict_pv_power(
                capacity_kW=1.12,
                latitude=39.74,
                longitude=-105.17,
                datetime_value="2020-06-21 12:00",
                azimuth=180,
                tilt=30,
                model_path=model_path,
                weather_provider=provider,
            )
            self.assertAlmostEqual(result["normalized_power"], 0.5)
            self.assertAlmostEqual(result["predicted_power_W"], 560.0)


if __name__ == "__main__":
    unittest.main()