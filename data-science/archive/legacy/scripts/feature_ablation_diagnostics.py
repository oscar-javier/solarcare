"""Diagnostic LOSO ablation experiments; never writes final model artifacts."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from final_pv_pipeline import build_model_pipeline, build_time_features, attach_system_metadata, clean_dataset_frame, load_system_capacities

SYSTEMS = [10, 34, 1239, 1430]
OUTPUT_DIR = Path("results/diagnostics/feature_ablation")
TIME_FEATURES = ["sin_hour", "cos_hour", "sin_day_of_year", "cos_day_of_year"]
MODEL_FEATURES = {
    "A_with_geography": [
        "poa_irradiance_W_m2", "ambient_temp_C", *TIME_FEATURES,
        "latitude", "longitude", "elevation",
    ],
    "B_without_geography": [
        "poa_irradiance_W_m2", "ambient_temp_C", *TIME_FEATURES,
    ],
    "C_GHI_DNI_DHI": [
        "GHI", "DNI", "DHI", "ambient_temp_C", *TIME_FEATURES,
    ],
}


def score(y_true: pd.Series, prediction: np.ndarray, capacity_kW: np.ndarray) -> dict[str, float]:
    prediction = np.asarray(prediction, dtype=float)
    y_true = np.asarray(y_true, dtype=float)
    prediction_w = prediction * capacity_kW * 1000.0
    y_true_w = y_true * capacity_kW * 1000.0
    return {
        "mae_normalized": float(mean_absolute_error(y_true, prediction)),
        "rmse_normalized": float(np.sqrt(mean_squared_error(y_true, prediction))),
        "r2_normalized": float(r2_score(y_true, prediction)),
        "pct_prediction_lt_0": float(np.mean(prediction < 0) * 100.0),
        "pct_prediction_gt_1": float(np.mean(prediction > 1) * 100.0),
        "mae_W": float(mean_absolute_error(y_true_w, prediction_w)),
        "rmse_W": float(np.sqrt(mean_squared_error(y_true_w, prediction_w))),
        "r2_W": float(r2_score(y_true_w, prediction_w)),
    }


def main() -> None:
    data = pd.read_csv("output/lectura_horaria.csv", low_memory=False)
    data, cleaning_summary = clean_dataset_frame(data, SYSTEMS)
    data = attach_system_metadata(build_time_features(data))
    capacities = load_system_capacities("capacidades_sistemas.csv")
    data["dc_capacity_kW"] = data["system_id"].map(capacities)
    data["normalized_power"] = data["ac_power_W"] / (data["dc_capacity_kW"] * 1000.0)

    availability = {
        name: {"available": all(feature in data.columns for feature in features), "features": features}
        for name, features in MODEL_FEATURES.items()
    }
    rows = []
    for test_system in SYSTEMS:
        train = data[data["system_id"] != test_system].copy()
        test = data[data["system_id"] == test_system].copy()
        y_train = train["normalized_power"]
        y_test = test["normalized_power"]
        capacity_test = test["dc_capacity_kW"].to_numpy(dtype=float)
        for model_name, features in MODEL_FEATURES.items():
            if not availability[model_name]["available"]:
                continue
            X_train, X_test = train[features], test[features]
            estimators = {
                "mean_global": None,
                "linear_scaled": make_pipeline(StandardScaler(), LinearRegression()),
                "polynomial_degree_2": build_model_pipeline(degree=2, ridge=False),
            }
            for estimator_name, estimator in estimators.items():
                if estimator is None:
                    prediction = np.full(len(test), y_train.mean(), dtype=float)
                else:
                    estimator.fit(X_train, y_train)
                    prediction = estimator.predict(X_test)
                row = {
                    "feature_set": model_name,
                    "model": estimator_name,
                    "test_system": test_system,
                    "train_systems": json.dumps([s for s in SYSTEMS if s != test_system]),
                    "n_train": len(train),
                    "n_test": len(test),
                }
                row.update(score(y_test, prediction, capacity_test))
                rows.append(row)

    result = pd.DataFrame(rows)
    average = (
        result.groupby(["feature_set", "model"], as_index=False)[
            ["mae_normalized", "rmse_normalized", "r2_normalized", "pct_prediction_lt_0", "pct_prediction_gt_1", "mae_W", "rmse_W", "r2_W"]
        ].mean()
    )
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    result.to_csv(OUTPUT_DIR / "loso_fold_metrics.csv", index=False)
    average.to_csv(OUTPUT_DIR / "loso_average_metrics.csv", index=False)
    (OUTPUT_DIR / "availability.json").write_text(json.dumps(availability, indent=2), encoding="utf-8")
    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps(
            {
                "systems": SYSTEMS,
                "target": "ac_power_W / (dc_capacity_kW * 1000)",
                "clipping_applied": False,
                "final_artifacts_modified": False,
                "cleaning_summary": cleaning_summary,
                "model_c_availability": availability["C_GHI_DNI_DHI"],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(result.to_string(index=False))
    print("\nAVERAGES")
    print(average.to_string(index=False))
    print(f"\nDiagnostic outputs written to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
