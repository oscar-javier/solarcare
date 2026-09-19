"""Train and evaluate the reproducible physical-feature production candidates."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import LinearRegression, Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from final_pv_pipeline import clean_dataset_frame
from production_pv_pipeline import (
    PRODUCTION_FEATURES,
    SYSTEMS,
    OpenMeteoArchive,
    build_production_training_frame,
    load_system_configurations,
    production_estimators,
)

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "results" / "production_model"
MODEL_DIR = ROOT / "models"
TARGET = "normalized_power"
DAYLIGHT_THRESHOLD_W_M2 = 20.0


def load_training_frame() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    configurations = load_system_configurations(ROOT / "system_configurations.csv")
    pvdaq = pd.read_csv(ROOT / "output" / "lectura_horaria.csv", low_memory=False)
    cleaned, _ = clean_dataset_frame(pvdaq, SYSTEMS)
    weather_by_system = {}
    provider = OpenMeteoArchive(ROOT / "output" / "weather_cache")
    for system_id in SYSTEMS:
        group = cleaned[cleaned["system_id"] == system_id]
        config = configurations[system_id]
        weather_by_system[system_id] = provider.fetch(
            config,
            pd.to_datetime(group["timestamp"]).min().date().isoformat(),
            pd.to_datetime(group["timestamp"]).max().date().isoformat(),
        )
    frame, coverage = build_production_training_frame(cleaned, weather_by_system, configurations)
    frame["tracking_is_single_axis"] = (frame["tracking_type"] == "single_axis").astype(float)
    frame["is_daylight"] = (
        (frame["solar_elevation_deg"] > 0) &
        (frame["poa_synthetic_W_m2"] > DAYLIGHT_THRESHOLD_W_M2)
    )
    frame = frame.dropna(subset=PRODUCTION_FEATURES + [TARGET]).copy()
    return frame, coverage, pd.DataFrame([config.__dict__ for config in configurations.values()])


def metrics(y_true: np.ndarray, prediction: np.ndarray, capacity_kW: np.ndarray, daylight: np.ndarray) -> dict[str, float]:
    y_true = np.asarray(y_true, dtype=float)
    prediction = np.asarray(prediction, dtype=float)
    capacity_w = np.asarray(capacity_kW, dtype=float) * 1000.0
    y_true_w = y_true * capacity_w
    prediction_w = prediction * capacity_w
    result = {
        "mae_normalized": float(mean_absolute_error(y_true, prediction)),
        "rmse_normalized": float(np.sqrt(mean_squared_error(y_true, prediction))),
        "r2_normalized": float(r2_score(y_true, prediction)),
        "mae_W": float(mean_absolute_error(y_true_w, prediction_w)),
        "rmse_W": float(np.sqrt(mean_squared_error(y_true_w, prediction_w))),
        "pct_prediction_lt_0": float(np.mean(prediction < 0) * 100),
        "pct_prediction_gt_1": float(np.mean(prediction > 1) * 100),
    }
    if daylight.any():
        result.update({
            "daylight_mae_normalized": float(mean_absolute_error(y_true[daylight], prediction[daylight])),
            "daylight_rmse_normalized": float(np.sqrt(mean_squared_error(y_true[daylight], prediction[daylight]))),
            "daylight_r2_normalized": float(r2_score(y_true[daylight], prediction[daylight])),
            "daylight_mae_W": float(mean_absolute_error(y_true_w[daylight], prediction_w[daylight])),
            "daylight_rmse_W": float(np.sqrt(mean_squared_error(y_true_w[daylight], prediction_w[daylight]))),
        })
    else:
        result.update({key: np.nan for key in [
            "daylight_mae_normalized", "daylight_rmse_normalized", "daylight_r2_normalized",
            "daylight_mae_W", "daylight_rmse_W",
        ]})
    return result


def fit_predict(name: str, train: pd.DataFrame, test: pd.DataFrame, features: list[str], daylight_model: bool) -> np.ndarray:
    train_fit = train[train["is_daylight"]].copy() if daylight_model else train
    estimators = production_estimators()
    if name == "mean_global":
        prediction = np.full(len(test), train_fit[TARGET].mean())
    else:
        estimator = estimators[name]
        estimator.fit(train_fit[features], train_fit[TARGET])
        prediction = estimator.predict(test[features])
    if daylight_model:
        prediction = np.asarray(prediction, dtype=float)
        prediction[~test["is_daylight"].to_numpy()] = 0.0
    return np.asarray(prediction, dtype=float)


def main() -> None:
    frame, coverage, configurations = load_training_frame()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    coverage.to_csv(OUTPUT_DIR / "weather_coverage.csv", index=False)
    configurations.to_csv(OUTPUT_DIR / "system_configurations.csv", index=False)
    frame.to_csv(OUTPUT_DIR / "training_dataset.csv", index=False)
    pd.DataFrame({"feature": PRODUCTION_FEATURES, "source": [
        "Open-Meteo", "Open-Meteo", "Open-Meteo", "Open-Meteo",
        "pvlib solarposition", "pvlib solarposition", "pvlib solarposition",
        "official systems_2025 metadata", "official systems_2025 metadata", "official systems_2025 metadata",
        "pvlib get_total_irradiance", "pvlib get_total_irradiance", "pvlib get_total_irradiance",
        "pvlib get_total_irradiance", "timestamp", "timestamp", "timestamp", "timestamp",
    ]}).to_csv(OUTPUT_DIR / "feature_catalog.csv", index=False)

    rows, prediction_rows = [], []
    model_names = ["mean_global", "linear_ridge", "linear", "random_forest", "hist_gradient_boosting"]
    for test_system in SYSTEMS:
        train = frame[frame.system_id != test_system]
        test = frame[frame.system_id == test_system]
        for strategy in ["24h_model", "daylight_model_night_zero"]:
            for model_name in model_names:
                prediction = fit_predict(model_name, train, test, PRODUCTION_FEATURES, strategy != "24h_model")
                fold_metrics = metrics(
                    test[TARGET].to_numpy(), prediction,
                    test["dc_capacity_kW"].to_numpy(), test["is_daylight"].to_numpy(),
                )
                rows.append({
                    "test_system": test_system,
                    "train_systems": json.dumps([s for s in SYSTEMS if s != test_system]),
                    "model": model_name,
                    "strategy": strategy,
                    "n_train": len(train),
                    "n_test": len(test),
                    "daylight_rows_test": int(test["is_daylight"].sum()),
                    **fold_metrics,
                })
                for timestamp, actual, predicted, daylight in zip(
                    test["timestamp"], test[TARGET], prediction, test["is_daylight"]
                ):
                    prediction_rows.append({
                        "test_system": test_system,
                        "model": model_name,
                        "strategy": strategy,
                        "timestamp": timestamp,
                        "y_true_normalized": actual,
                        "prediction_normalized": predicted,
                        "residual_normalized": actual - predicted,
                        "is_daylight": daylight,
                    })

    fold_metrics = pd.DataFrame(rows)
    predictions = pd.DataFrame(prediction_rows)
    fold_metrics.to_csv(OUTPUT_DIR / "loso_metrics.csv", index=False)
    predictions.to_csv(OUTPUT_DIR / "loso_predictions.csv", index=False)
    average = fold_metrics.groupby(["model", "strategy"], as_index=False).mean(numeric_only=True)
    comparison_rows = average.copy()
    legacy_path = ROOT / "results" / "loso_metrics.csv"
    if legacy_path.exists():
        legacy = pd.read_csv(legacy_path)
        legacy["test_system"] = legacy["test_systems"].map(lambda value: ast.literal_eval(value)[0])
        comparison_rows = pd.concat(
            [comparison_rows, pd.DataFrame([{
                "model": "legacy_historical_poa_polynomial",
                "strategy": "legacy_24h",
                "mae_normalized": legacy["model_mae"].mean(),
                "rmse_normalized": legacy["model_rmse"].mean(),
                "r2_normalized": legacy["model_r2"].mean(),
                "mae_W": legacy["mae_w"].mean(),
                "rmse_W": legacy["rmse_w"].mean(),
                "pct_prediction_lt_0": np.nan,
                "pct_prediction_gt_1": np.nan,
            }])], ignore_index=True, sort=False
        )
    comparison_rows.to_csv(OUTPUT_DIR / "model_comparison.csv", index=False)

    # Conservative selection: first minimize worst-fold daylight RMSE, then normalized MAE,
    # while rejecting candidates with catastrophic out-of-range predictions.
    aggregate = fold_metrics.groupby(["model", "strategy"], as_index=False).agg(
        mean_daylight_rmse=("daylight_rmse_normalized", "mean"),
        worst_daylight_rmse=("daylight_rmse_normalized", "max"),
        mean_mae=("mae_normalized", "mean"),
        max_outside=("pct_prediction_lt_0", "sum"),
        max_above=("pct_prediction_gt_1", "sum"),
    )
    acceptable = aggregate[(aggregate["max_outside"] < 150) & (aggregate["max_above"] < 150)].copy()
    if acceptable.empty:
        acceptable = aggregate.copy()
    selected = acceptable.sort_values(["worst_daylight_rmse", "mean_daylight_rmse", "mean_mae"]).iloc[0]
    selected_model = str(selected["model"])
    selected_strategy = str(selected["strategy"])

    full_train = frame[frame["is_daylight"]].copy() if selected_strategy != "24h_model" else frame
    estimators = production_estimators()
    if selected_model == "mean_global":
        final_model = {"kind": "mean_global", "value": float(full_train[TARGET].mean())}
    else:
        final_model = estimators[selected_model]
        final_model.fit(full_train[PRODUCTION_FEATURES], full_train[TARGET])
    joblib.dump({"model": final_model, "features": PRODUCTION_FEATURES, "strategy": selected_strategy}, MODEL_DIR / "production_model.joblib")
    metadata = {
        "metadata_source": "systems_2025...",
        "features": PRODUCTION_FEATURES,
        "target": "ac_power_W / (dc_capacity_kW * 1000)",
        "model": selected_model,
        "strategy": selected_strategy,
        "daylight_definition": f"solar_elevation_deg > 0 and poa_synthetic_W_m2 > {DAYLIGHT_THRESHOLD_W_M2}",
        "systems": SYSTEMS,
        "system_configurations": configurations.to_dict(orient="records"),
        "weather_source": "Open-Meteo archive cached locally",
        "timezone_matching": "PVDAQ local timestamp matched to Open-Meteo local hourly timestamp with merge_asof tolerance 30min",
        "tracking": "pvlib.tracking.singleaxis(axis_tilt=0, axis_azimuth=official azimuth, backtrack=True, gcr=0.4)",
    }
    (MODEL_DIR / "production_model_metadata.json").write_text(json.dumps(metadata, indent=2, default=str), encoding="utf-8")
    final_summary = {
        "status": "completed",
        "metadata_source": "systems_2025...",
        "selected_model": selected_model,
        "selected_strategy": selected_strategy,
        "target": "ac_power_W / (dc_capacity_kW * 1000)",
        "comparison": comparison_rows.to_dict(orient="records"),
        "loso_folds": SYSTEMS,
        "training_rows": int(len(frame)),
    }
    (OUTPUT_DIR / "final_training_summary.json").write_text(json.dumps(final_summary, indent=2, default=str), encoding="utf-8")
    (OUTPUT_DIR / "summary.json").write_text(json.dumps(final_summary, indent=2, default=str), encoding="utf-8")
    (OUTPUT_DIR / "limitations.md").write_text(
        "# Production model limitations\n\n"
        "The model uses four PVDAQ systems and LOSO is therefore a small-sample generalization test. "
        "System 1430 is in Colorado, as is system 10, so that fold is not a fully unseen geography. "
        "Negative power, above-capacity power, and suspicious historical observations are retained in the audit; "
        "no clipping is applied to predictions or metrics.\n",
        encoding="utf-8",
    )
    print(json.dumps({"selected_model": selected_model, "selected_strategy": selected_strategy, "loso_rows": len(fold_metrics), "training_rows": len(frame)}, indent=2))


if __name__ == "__main__":
    main()
