import unittest

import pandas as pd

from pvdaq_units import UnitConversionError, load_metric_catalog, transform_metric_values
from transform_load import resample_to_hourly, standardize_columns


CATALOG = load_metric_catalog("pvdaq_metrics.csv")


class TestPVDAQUnits(unittest.TestCase):
    def test_watts_scale_one_is_unchanged(self):
        result = transform_metric_values(pd.Series([0.0, 123.5]), CATALOG.loc[422])
        self.assertEqual(result.tolist(), [0.0, 123.5])

    def test_system_34_hectowatts_become_watts(self):
        result = transform_metric_values(pd.Series([1.0, 1.55]), CATALOG.loc[2695])
        self.assertEqual(result.tolist(), [100.0, 155.0])

    def test_system_1239_exported_watts_are_not_scaled_twice(self):
        result = transform_metric_values(pd.Series([18550.0]), CATALOG.loc[3015])
        self.assertEqual(result.iloc[0], 18550.0)
        self.assertEqual(CATALOG.loc[3015, "calc_scale"], 1000)
        self.assertFalse(CATALOG.loc[3015, "calc_applies_to_exported_value"])

    def test_system_1430_applies_metadata_scale_to_watts(self):
        result = transform_metric_values(pd.Series([332.0]), CATALOG.loc[5074])
        self.assertEqual(result.iloc[0], 664000.0)
        self.assertEqual(CATALOG.loc[5074, "calc_scale"], 2000)
        self.assertEqual(CATALOG.loc[5074, "calc_offset"], 0)
        self.assertIn("raw_value * calc_scale", CATALOG.loc[5074, "calc_details"])

    def test_temperature_fahrenheit_is_celsius_before_resampling(self):
        raw = pd.DataFrame(
            {
                "measured_on": pd.to_datetime(["2020-01-01 06:05", "2020-01-01 06:35"]),
                "system_id": [34, 34],
                "ac_power_hw__2695": [1.0, 2.0],
                "poa_irradiance__2679": [100.0, 200.0],
                "ambient_temp_f__2688": [32.0, 50.0],
            }
        )
        canonical = standardize_columns(raw, 34, CATALOG)
        hourly = resample_to_hourly(canonical)
        self.assertEqual(hourly.loc[0, "ac_power_W"], 150.0)
        self.assertEqual(hourly.loc[0, "ambient_temp_C"], 5.0)

    def test_unsupported_units_fail_loudly(self):
        metadata = CATALOG.loc[422].copy()
        metadata["raw_units"] = "horsepower"
        with self.assertRaises(UnitConversionError):
            transform_metric_values(pd.Series([1.0]), metadata)


if __name__ == "__main__":
    unittest.main()
