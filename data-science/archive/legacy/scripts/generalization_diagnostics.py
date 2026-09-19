"""Diagnostic-only audit of LOSO distribution shift and polynomial extrapolation."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from final_pv_pipeline import (
    FEATURE_COLUMNS,
    build_model_pipeline,
    build_time_features,
    attach_system_metadata,
    clean_dataset_frame,
    load_system_capacities,
)

SYSTEMS = [10, 34, 1239, 1430]
AUDIT_FEATURES = [
    "poa_irradiance_W_m2",
    "ambient_temp_C",
    "sin_hour",
    "cos_hour",
    "sin_day_of_year",
    "cos_day_of_year",
    "dc_capacity_kW",
]
OUTPUT_DIR = Path("results/diagnostics")


def distribution_rows(train: pd.DataFrame, test: pd.DataFrame, test_system: int) -> list[dict]:
    rows = []
    for feature in AUDIT_FEATURES:
        train_values = train[feature].dropna().astype(float)
        test_values = test[feature].dropna().astype(float)
        quantiles = train_values.quantile([0.01, 0.25, 0.50, 0.75, 0.99])
        test_quantiles = test_values.quantile([0.01, 0.25, 0.50, 0.75, 0.99])
        outside = ((test_values < train_values.min()) | (test_values > train_values.max())).mean() * 100
        for split, values, q in [
            ("train", train_values, quantiles),
            ("test", test_values, test_quantiles),
        ]:
            rows.append(
                {
                    "test_system": test_system,
                    "feature": feature,
                    "split": split,
                    "min": values.min(),
                    "p01": q[0.01],
                    "p25": q[0.25],
                    "median": q[0.50],
                    "p75": q[0.75],
                    "p99": q[0.99],
                    "max": values.max(),
                    "mean": values.mean(),
                    "std": values.std(),
                    "test_outside_train_range_pct": outside if split == "test" else np.nan,
                }
            )
    return rows


def metrics(y_true: pd.Series, prediction: np.ndarray) -> dict[str, float]:
    return {
        "mae": mean_absolute_error(y_true, prediction),
        "rmse": np.sqrt(mean_squared_error(y_true, prediction)),
        "r2": r2_score(y_true, prediction),
    }


def main() -> None:
    data = pd.read_csv("output/lectura_horaria.csv", low_memory=False)
    data, _ = clean_dataset_frame(data, SYSTEMS)
    data = attach_system_metadata(build_time_features(data))
    capacities = load_system_capacities("capacidades_sistemas.csv")
    data["dc_capacity_kW"] = data["system_id"].map(capacities)
    data["normalized_power"] = data["ac_power_W"] / (data["dc_capacity_kW"] * 1000.0)

    distribution = []
    fold_metrics = []
    coefficient_rows = []
    for test_system in SYSTEMS:
        train = data[data.system_id != test_system].copy()
        test = data[data.system_id == test_system].copy()
        distribution.extend(distribution_rows(train, test, test_system))
        X_train, X_test = train[FEATURE_COLUMNS], test[FEATURE_COLUMNS]
        y_train, y_test = train["normalized_power"], test["normalized_power"]

        polynomial = build_model_pipeline(degree=2, ridge=False)
        polynomial.fit(X_train, y_train)
        polynomial_prediction = polynomial.predict(X_test)
        linear = make_pipeline(StandardScaler(), LinearRegression())
        linear.fit(X_train, y_train)
        linear_prediction = linear.predict(X_test)
        baseline_prediction = np.full(len(test), y_train.mean())

        row = {"test_system": test_system, "n_train": len(train), "n_test": len(test)}
        for name, prediction in [
            ("baseline_mean", baseline_prediction),
            ("linear_scaled", linear_prediction),
            ("polynomial_degree_2", polynomial_prediction),
        ]:
            values = metrics(y_test, prediction)
            row.update({f"{name}_{key}": value for key, value in values.items()})
            if name != "baseline_mean":
                row[f"{name}_pct_pred_lt_0"] = np.mean(prediction < 0) * 100
                row[f"{name}_pct_pred_gt_1"] = np.mean(prediction > 1) * 100
                row[f"{name}_pct_pred_outside_0_1"] = np.mean((prediction < 0) | (prediction > 1)) * 100
        any_domain_shift = np.zeros(len(test), dtype=bool)
        for feature in AUDIT_FEATURES:
            any_domain_shift |= (test[feature] < train[feature].min()) | (test[feature] > train[feature].max())
        row["pct_test_rows_any_feature_outside"] = np.mean(any_domain_shift) * 100
        extreme = np.abs(polynomial_prediction) > 1
        row["pct_extreme_predictions_with_domain_shift"] = np.mean(any_domain_shift[extreme]) * 100 if extreme.any() else 0.0

        scaler = polynomial.named_steps["standardscaler"]
        poly_features = polynomial.named_steps["polynomialfeatures"]
        regression = polynomial.named_steps["linearregression"]
        names = poly_features.get_feature_names_out(FEATURE_COLUMNS)
        powers = poly_features.powers_
        transformed = poly_features.transform(scaler.transform(X_test))
        contributions = transformed * regression.coef_
        degrees = powers.sum(axis=1)
        row.update({f"mean_abs_contribution_degree_{int(degree)}": np.abs(contributions[:, degrees == degree]).sum(axis=1).mean() for degree in sorted(set(degrees))})
        fold_metrics.append(row)
        top = np.argsort(np.abs(regression.coef_))[::-1][:12]
        coefficient_rows.extend(
            {
                "test_system": test_system,
                "term": names[index],
                "coefficient": regression.coef_[index],
                "abs_coefficient": abs(regression.coef_[index]),
                "degree": int(powers[index].sum()),
            }
            for index in top
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(distribution).to_csv(OUTPUT_DIR / "feature_distribution_shift.csv", index=False)
    pd.DataFrame(fold_metrics).to_csv(OUTPUT_DIR / "fold_model_diagnostics.csv", index=False)
    pd.DataFrame(coefficient_rows).to_csv(OUTPUT_DIR / "top_polynomial_coefficients.csv", index=False)
    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps(
            {
                "model_features": FEATURE_COLUMNS,
                "audit_features": AUDIT_FEATURES,
                "clipping_applied": False,
                "artifacts_modified": False,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Diagnostic reports written to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
