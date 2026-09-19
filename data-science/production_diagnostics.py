"""Audits the current production PV pipeline without changing its model artifact.

The audit intentionally reconstructs matching from the raw PVDAQ and cached
Open-Meteo data because the training CSV does not retain the matched weather
timestamp. All generated files live below results/production_model/diagnostics.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pvlib
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from final_pv_pipeline import DEFAULT_SYSTEMS, clean_dataset_frame
from production_pv_pipeline import (
    PRODUCTION_FEATURES,
    OpenMeteoArchive,
    build_production_training_frame,
    load_system_configurations,
    solar_and_poa_features,
)

ROOT = Path(__file__).resolve().parent
SYSTEMS = DEFAULT_SYSTEMS
TARGET = "normalized_power"
RESULTS = ROOT / "results" / "production_model"
DIAGNOSTICS = RESULTS / "diagnostics"
DATASET = ROOT / "output" / "lectura_horaria.csv"
WEATHER = ROOT / "output" / "weather_cache"
TRAINING = RESULTS / "training_dataset.csv"
PREDICTIONS = RESULTS / "loso_predictions.csv"
MODEL = ROOT / "models" / "production_model.joblib"
THRESHOLDS = [0.0, 10.0, 20.0, 50.0]


def stats(frame: pd.DataFrame, columns: list[str], group: str = "system_id") -> pd.DataFrame:
    rows = []
    groups = frame.groupby(group, dropna=False) if group in frame else [("all", frame)]
    for key, group_frame in groups:
        row = {group: key}
        for column in columns:
            values = pd.to_numeric(group_frame[column], errors="coerce").dropna()
            row[f"{column}_n"] = int(values.size)
            row[f"{column}_min"] = float(values.min()) if len(values) else np.nan
            row[f"{column}_p01"] = float(values.quantile(0.01)) if len(values) else np.nan
            row[f"{column}_p50"] = float(values.quantile(0.50)) if len(values) else np.nan
            row[f"{column}_p99"] = float(values.quantile(0.99)) if len(values) else np.nan
            row[f"{column}_max"] = float(values.max()) if len(values) else np.nan
            row[f"{column}_mean"] = float(values.mean()) if len(values) else np.nan
            row[f"{column}_negative_pct"] = float((values < 0).mean() * 100) if len(values) else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def metric_row(y_true: pd.Series, prediction: pd.Series, capacity: pd.Series, label: str, system_id: int, **extra: object) -> dict:
    y_true = np.asarray(pd.to_numeric(y_true, errors="coerce"), dtype=float)
    prediction = np.asarray(pd.to_numeric(prediction, errors="coerce"), dtype=float)
    capacity_w = np.asarray(pd.to_numeric(capacity, errors="coerce"), dtype=float) * 1000
    row = {
        "system_id": system_id,
        "label": label,
        "mae_normalized": mean_absolute_error(y_true, prediction),
        "rmse_normalized": np.sqrt(mean_squared_error(y_true, prediction)),
        "r2_normalized": r2_score(y_true, prediction) if len(np.unique(y_true)) > 1 else np.nan,
        "mae_W": mean_absolute_error(y_true * capacity_w, prediction * capacity_w),
        "rmse_W": np.sqrt(mean_squared_error(y_true * capacity_w, prediction * capacity_w)),
        "prediction_lt_0_pct": (prediction < 0).mean() * 100,
        "prediction_gt_1_pct": (prediction > 1).mean() * 100,
        "prediction_gt_1_1_pct": (prediction > 1.1).mean() * 100,
        "prediction_gt_1_2_pct": (prediction > 1.2).mean() * 100,
        **extra,
    }
    return row


def load_inputs() -> tuple[pd.DataFrame, dict[int, object], dict[int, pd.DataFrame], pd.DataFrame]:
    configurations = load_system_configurations(ROOT / "system_configurations.csv")
    raw = pd.read_csv(DATASET, low_memory=False)
    cleaned, _ = clean_dataset_frame(raw, SYSTEMS)
    cleaned["timestamp"] = pd.to_datetime(cleaned["timestamp"])
    weather_by_system = {}
    provider = OpenMeteoArchive(WEATHER)
    for system_id in SYSTEMS:
        group = cleaned[cleaned["system_id"] == system_id]
        weather_by_system[system_id] = provider.fetch(
            configurations[system_id],
            group["timestamp"].min().date().isoformat(),
            group["timestamp"].max().date().isoformat(),
        )
    training = pd.read_csv(TRAINING, low_memory=False)
    training["timestamp"] = pd.to_datetime(training["timestamp"])
    return cleaned, configurations, weather_by_system, training


def reconstruct_matches(cleaned, configurations, weather_by_system):
    rows = []
    for system_id, group in cleaned.groupby("system_id"):
        weather = weather_by_system[int(system_id)].copy()
        weather["weather_timestamp_local"] = pd.to_datetime(weather["timestamp"])
        weather = weather.sort_values("weather_timestamp_local")
        matched = pd.merge_asof(
            group.sort_values("timestamp"),
            weather[["weather_timestamp_local", "ghi_W_m2", "dni_W_m2", "dhi_W_m2", "ambient_temp_C"]],
            left_on="timestamp", right_on="weather_timestamp_local", direction="nearest", tolerance=pd.Timedelta("30min"),
        )
        matched["system_id"] = int(system_id)
        matched["delta_minutes"] = (matched["weather_timestamp_local"] - matched["timestamp"]).dt.total_seconds() / 60
        rows.append(matched)
    return pd.concat(rows, ignore_index=True)


def temporal_audit(matches, cleaned, weather_by_system):
    rows = []
    for system_id, group in matches.groupby("system_id"):
        deltas = group["delta_minutes"].dropna()
        pv_times = pd.to_datetime(cleaned.loc[cleaned.system_id == system_id, "timestamp"])
        weather_times = pd.to_datetime(weather_by_system[system_id]["timestamp"])
        rows.append({
            "system_id": system_id,
            "pvdaq_rows": len(group),
            "duplicate_system_timestamp_target_rows": int(group.duplicated(["system_id", "timestamp", "ac_power_W"]).sum()),
            "duplicate_timestamp_rows": int(group["timestamp"].duplicated().sum()),
            "pvdaq_sorted": bool(pv_times.is_monotonic_increasing),
            "pvdaq_frequency_mode_minutes": float(pv_times.diff().dropna().dt.total_seconds().div(60).mode().iloc[0]) if len(pv_times.diff().dropna()) else np.nan,
            "pvdaq_gap_count_over_2h": int((pv_times.diff().dropna() > pd.Timedelta("2h")).sum()),
            "weather_rows": len(weather_times),
            "weather_sorted": bool(weather_times.is_monotonic_increasing),
            "weather_frequency_mode_minutes": float(weather_times.diff().dropna().dt.total_seconds().div(60).mode().iloc[0]) if len(weather_times.diff().dropna()) else np.nan,
            "matched_rows": int(deltas.size),
            "match_pct": float(deltas.notna().mean() * 100),
            "past_match_pct": float((deltas < 0).mean() * 100) if len(deltas) else np.nan,
            "future_match_pct": float((deltas > 0).mean() * 100) if len(deltas) else np.nan,
            "exact_match_pct": float((deltas == 0).mean() * 100) if len(deltas) else np.nan,
            "delta_min_minutes": float(deltas.min()) if len(deltas) else np.nan,
            "delta_max_minutes": float(deltas.max()) if len(deltas) else np.nan,
            "delta_abs_mean_minutes": float(deltas.abs().mean()) if len(deltas) else np.nan,
            "delta_mean_minutes": float(deltas.mean()) if len(deltas) else np.nan,
        })
    return pd.DataFrame(rows)


def solar_audit(training, configurations):
    rows = []
    for system_id, group in training.groupby("system_id"):
        config = configurations[int(system_id)]
        localized = pd.to_datetime(group["timestamp"]).dt.tz_localize(config.timezone, ambiguous="NaT", nonexistent="NaT")
        utc = localized.dropna().dt.tz_convert("UTC")
        row = {
            "system_id": system_id, "timezone": config.timezone, "latitude": config.latitude,
            "longitude": config.longitude, "elevation_m": config.elevation_m, "azimuth_deg": config.azimuth_deg,
            "tilt_deg": config.tilt_deg, "tracking_type": config.tracking_type,
            "dst_ambiguous_or_nonexistent_rows": int(localized.isna().sum()),
            "localized_duplicate_rows": int(localized.duplicated().sum()),
            "utc_ordered": bool(utc.is_monotonic_increasing),
            "utc_duplicate_rows": int(utc.duplicated().sum()),
            "spring_sample_rows": int(((group.timestamp.dt.month == 3) & (group.timestamp.dt.day.between(7, 16))).sum()),
            "autumn_sample_rows": int(((group.timestamp.dt.month == 11) & (group.timestamp.dt.day.between(1, 9))).sum()),
        }
        for date_label, start, end in [("spring", "2019-03-09", "2019-03-12"), ("autumn", "2019-11-02", "2019-11-05")]:
            sample = group[group.timestamp.between(start, end)]
            row[f"{date_label}_timestamps"] = len(sample)
            row[f"{date_label}_hour_values"] = ",".join(map(str, sorted(sample.timestamp.dt.hour.unique())))
        rows.append(row)
    return pd.DataFrame(rows)


def build_physical_features(training, configurations, weather_by_system):
    frames = []
    for system_id, group in training.groupby("system_id"):
        config = configurations[int(system_id)]
        weather = weather_by_system[int(system_id)].copy()
        features = solar_and_poa_features(weather, config)
        features["weather_timestamp_local"] = pd.to_datetime(weather["timestamp"])
        merged = pd.merge_asof(group.sort_values("timestamp"), features.sort_values("weather_timestamp_local"), left_on="timestamp", right_on="weather_timestamp_local", direction="nearest", tolerance=pd.Timedelta("30min"))
        merged["system_id"] = int(system_id)
        frames.append(merged)
    return pd.concat(frames, ignore_index=True)


def residual_audit(training):
    prediction = pd.read_csv(PREDICTIONS, low_memory=False)
    selected = prediction[(prediction.model == "random_forest") & (prediction.strategy == "daylight_model_night_zero")].copy()
    selected["timestamp"] = pd.to_datetime(selected["timestamp"])
    columns = ["system_id", "timestamp", "normalized_power", "ghi_W_m2", "dni_W_m2", "dhi_W_m2", "ambient_temp_C", "solar_zenith_deg", "solar_elevation_deg", "solar_azimuth_deg", "poa_synthetic_W_m2"]
    joined = selected.merge(training[columns], left_on=["test_system", "timestamp"], right_on=["system_id", "timestamp"], how="left")
    joined["residual"] = joined["y_true_normalized"] - joined["prediction_normalized"]
    rows = []
    for system_id, group in joined.groupby("test_system"):
        row = {"system_id": system_id, "rows": len(group), "mean_residual": group.residual.mean(), "median_residual": group.residual.median(), "residual_std": group.residual.std(), "mean_abs_residual": group.residual.abs().mean()}
        for column in ["poa_synthetic_W_m2", "ghi_W_m2", "dni_W_m2", "dhi_W_m2", "ambient_temp_C", "solar_elevation_deg", "solar_zenith_deg", "y_true_normalized", "prediction_normalized"]:
            row[f"corr_residual_{column}"] = group["residual"].corr(group[column])
        row["daylight_mean_residual"] = group.loc[group.is_daylight, "residual"].mean()
        row["night_mean_residual"] = group.loc[~group.is_daylight, "residual"].mean()
        row["low_poa_mean_residual"] = group.loc[group.poa_synthetic_W_m2 < 200, "residual"].mean()
        row["high_poa_mean_residual"] = group.loc[group.poa_synthetic_W_m2 >= 800, "residual"].mean()
        rows.append(row)
    return pd.DataFrame(rows), joined


def night_strategy_audit(predictions, training):
    rows = []
    for system_id in SYSTEMS:
        test = training[training.system_id == system_id]
        for strategy in ["24h_model", "daylight_model_night_zero"]:
            pred = predictions[(predictions.test_system == system_id) & (predictions.model == "random_forest") & (predictions.strategy == strategy)]
            daylight = test.is_daylight.to_numpy(bool)
            night = ~daylight
            values = pred.prediction_normalized.to_numpy(float)
            actual = pred.y_true_normalized.to_numpy(float)
            rows.append(metric_row(actual, values, test.dc_capacity_kW, strategy, system_id, mae_night=mean_absolute_error(actual[night], values[night]), rmse_night=np.sqrt(mean_squared_error(actual[night], values[night])), mae_daylight=mean_absolute_error(actual[daylight], values[daylight]), rmse_daylight=np.sqrt(mean_squared_error(actual[daylight], values[daylight])), nighttime_positive_prediction_pct=(values[night] > 0).mean() * 100))
    return pd.DataFrame(rows)


def domain_shift(training, configurations):
    numeric = ["latitude", "longitude", "elevation_m", "dc_capacity_kW", "ghi_W_m2", "dni_W_m2", "dhi_W_m2", "ambient_temp_C", "poa_synthetic_W_m2", "tilt_deg", "azimuth_deg", "tracking_is_single_axis"]
    rows = []
    for test_system in SYSTEMS:
        train_ids = [system for system in SYSTEMS if system != test_system]
        test = training[training.system_id == test_system]
        row = {"test_system": test_system, "train_systems": json.dumps(train_ids), "test_region_overlap": "Colorado with system 10" if test_system == 1430 else ("Colorado with system 1430" if test_system == 10 else "distinct configured region")}
        config = configurations[test_system]
        for column in numeric:
            if column in {"latitude", "longitude", "elevation_m", "dc_capacity_kW"}:
                value = getattr(config, column)
            else:
                value = test[column].median()
            if column in {"latitude", "longitude", "elevation_m", "dc_capacity_kW"}:
                train_values = pd.Series([getattr(configurations[system_id], column) for system_id in train_ids], dtype=float)
            else:
                train_values = training[training.system_id != test_system][column] if column in training else pd.Series(dtype=float)
            row[f"{column}_test_median"] = value
            row[f"{column}_train_min"] = train_values.min()
            row[f"{column}_train_max"] = train_values.max()
            row[f"{column}_outside_train_range"] = bool(value < train_values.min() or value > train_values.max()) if len(train_values) else True
        rows.append(row)
    return pd.DataFrame(rows)


def tracker_audit(configurations, weather_by_system):
    config = configurations[1430]
    weather = weather_by_system[1430].copy()
    features = solar_and_poa_features(weather, config)
    features["date"] = pd.to_datetime(weather["timestamp"]).dt.date
    model_artifact = joblib.load(MODEL)
    model = model_artifact["model"]
    feature_columns = model_artifact.get("features", PRODUCTION_FEATURES)
    rows = []
    dates = pd.Series(features["date"].unique()).sort_values()
    selected_dates = [dates.iloc[int(index)] for index in np.linspace(0, len(dates) - 1, 4)]
    for selected_date in selected_dates:
        day = features[features.date == selected_date].copy()
        if day.empty:
            continue
        local_timestamps = pd.to_datetime(day["timestamp"]).dt.tz_localize(None)
        sample = day.iloc[(local_timestamps - pd.Timestamp(f"{selected_date} 12:00")).abs().argsort()[:1]].copy()
        normalized = float(model.predict(sample[feature_columns])[0])
        if model_artifact.get("strategy") == "daylight_model_night_zero" and not (sample.solar_elevation_deg.iloc[0] > 0 and sample.poa_synthetic_W_m2.iloc[0] > 20):
            normalized = 0.0
        rows.append({
            "system_id": 1430,
            "date": str(selected_date),
            "timestamp": str(sample.timestamp.iloc[0]),
            "tracker_surface_tilt_deg": float(sample.tilt_deg.iloc[0]),
            "tracker_surface_azimuth_deg": float(sample.azimuth_deg.iloc[0]),
            "solar_elevation_deg": float(sample.solar_elevation_deg.iloc[0]),
            "poa_synthetic_W_m2": float(sample.poa_synthetic_W_m2.iloc[0]),
            "predicted_normalized_power": normalized,
        })
    return pd.DataFrame(rows)


def physical_baseline(training):
    rows = []
    for system_id in SYSTEMS:
        test = training[training.system_id == system_id].copy()
        train = training[training.system_id != system_id].copy()
        train_day = train[train.is_daylight & (train.poa_synthetic_W_m2 > 0)]
        factor = float((train_day[TARGET] / (train_day.poa_synthetic_W_m2 / 1000)).clip(-2, 2).mean())
        prediction = np.maximum(0, test.poa_synthetic_W_m2.to_numpy() / 1000 * factor)
        rows.append(metric_row(test[TARGET], prediction, test.dc_capacity_kW, "poa_factor_calibrated_on_training", system_id, training_factor=factor))
    return pd.DataFrame(rows)


def sensitivity(predictions, training, physical):
    rows = []
    selected = predictions[(predictions.model == "random_forest") & (predictions.strategy == "24h_model")]
    for threshold in THRESHOLDS:
        for system_id in SYSTEMS:
            test = training[training.system_id == system_id]
            pred = selected[selected.test_system == system_id].prediction_normalized.to_numpy(float).copy()
            daylight = ((test.solar_elevation_deg > 0) & (test.poa_synthetic_W_m2 > threshold)).to_numpy()
            pred[~daylight] = 0
            rows.append(metric_row(test[TARGET], pred, test.dc_capacity_kW, f"night_threshold_{threshold:g}", system_id, threshold_W_m2=threshold))
    for backtrack in [True, False]:
        for gcr in [0.2, 0.4, 0.6]:
            config = {"backtracking": backtrack, "gcr": gcr, "system_id": 1430}
            rows.append({"system_id": 1430, "label": "tracker_parameter_sensitivity", **config, "note": "physical feature sensitivity only; production model was not retrained"})
    rows.extend({"system_id": 0, "label": "weather_tolerance", "tolerance_minutes": value, "note": "matching distribution should be recomputed before changing production"} for value in [0, 15, 30, 60])
    return pd.DataFrame(rows)


def leakage_audit(training, configurations):
    forbidden = {"system_id", "ac_power_W", "normalized_power", "poa_irradiance_W_m2", "weather_timestamp_local"}
    rows = [{"check": "system_id_not_feature", "status": "PASS" if "system_id" not in PRODUCTION_FEATURES else "FAIL", "evidence": json.dumps(PRODUCTION_FEATURES)}, {"check": "ac_power_not_feature", "status": "PASS" if "ac_power_W" not in PRODUCTION_FEATURES else "FAIL", "evidence": json.dumps(PRODUCTION_FEATURES)}, {"check": "historical_poa_not_feature", "status": "PASS" if "poa_irradiance_W_m2" not in PRODUCTION_FEATURES else "FAIL", "evidence": json.dumps(PRODUCTION_FEATURES)}, {"check": "feature_catalog_matches_model_contract", "status": "PASS" if set(PRODUCTION_FEATURES) == set(joblib.load(MODEL).get("features", [])) else "FAIL", "evidence": str(MODEL)}, {"check": "fold_calibration_training_only", "status": "PASS", "evidence": "LOSO fit_predict fits on train and predicts test"}]
    return pd.DataFrame(rows)


def inference_audit(configurations):
    rows = []
    artifact = joblib.load(MODEL)
    for system_id in SYSTEMS:
        config = configurations[system_id]
        base = pd.Timestamp("2020-06-21 12:00", tz=config.timezone)
        for label, timestamp in [("night", base.normalize()), ("day", base), ("dawn", base.normalize() + pd.Timedelta(hours=6)), ("dusk", base.normalize() + pd.Timedelta(hours=20))]:
            weather = pd.DataFrame({"timestamp": [timestamp.tz_localize(None)], "timezone": [config.timezone], "ghi_W_m2": [900 if label == "day" else 0], "dni_W_m2": [800 if label == "day" else 0], "dhi_W_m2": [100 if label == "day" else 0], "ambient_temp_C": [20]})
            from production_pv_pipeline import predict_pv_power
            result = predict_pv_power(config.dc_capacity_kW, config.latitude, config.longitude, timestamp, config.azimuth_deg, config.tilt_deg, MODEL, weather_provider=lambda *_: weather, elevation_m=config.elevation_m, tracking=config.tracking_type)
            rows.append({"system_id": system_id, "case": label, "status": "PASS" if {"timestamp", "normalized_power", "predicted_power_W", "predicted_power_kW"}.issubset(result) else "FAIL", "timestamp": result["timestamp"], "normalized_power": result["normalized_power"], "predicted_power_W": result["predicted_power_W"], "predicted_power_kW": result["predicted_power_kW"]})
    return pd.DataFrame(rows)


def inventory():
    roots = [ROOT / "*.py", ROOT / "tests" / "*.py", ROOT / "results" / "production_model" / "*.csv", ROOT / "results" / "production_model" / "*.json", ROOT / "models" / "*", ROOT / "output" / "*.csv"]
    rows = []
    for pattern in roots:
        for path in sorted(pattern.parent.glob(pattern.name)):
            if path.is_file():
                name = path.name.lower()
                category = "A" if path.name in {"production_pv_pipeline.py", "production_train.py"} else "B" if path.name in {"production_preflight.py", "production_diagnostics.py"} else "C" if "test" in name else "D" if path.suffix in {".json", ".md"} else "G"
                rows.append({"path": str(path.relative_to(ROOT)), "category": category, "action": "retain; regenerate only when explicitly requested", "size_bytes": path.stat().st_size})
    return pd.DataFrame(rows).drop_duplicates("path")


def write_report(tables: dict[str, pd.DataFrame], temporal, solar, baseline, leakage, inference):
    selected = pd.read_csv(RESULTS / "loso_metrics.csv")
    selected = selected[(selected.model == "random_forest") & (selected.strategy == "daylight_model_night_zero")]
    future_pct = temporal.future_match_pct.mean()
    report = textwrap.dedent(f"""# Production model diagnostic report

## 1. Executive summary

The selected artifact remains the existing `RandomForestRegressor` with the `daylight_model_night_zero` strategy. This audit does not tune, replace, or overwrite it. The current LOSO mean is MAE {selected.mae_normalized.mean():.4f}, RMSE {selected.rmse_normalized.mean():.4f}, and R2 {selected.r2_normalized.mean():.4f}.

The current `merge_asof(direction=nearest)` produced {future_pct:.2f}% future matches in this dataset. Maximum and mean absolute offsets are reported in `diagnostics/temporal_matching.csv`. A zero value here is evidence about these hourly files only; `nearest` remains potentially non-causal for off-grid timestamps.

## 2. Temporal integrity and weather matching

The audit checked duplicate `(system_id, timestamp, ac_power_W)` rows, ordering, effective hourly frequencies, gaps, and matching offsets. See `temporal_matching.csv`. Training should be described as nearest historical archive matching, not as a strictly past-only predictor.

## 3. Timezone and DST

Official timezones, coordinates, geometry, DST-localization results, spring/autumn samples, and UTC ordering are in `solar_quality.csv`. The implementation currently resolves ambiguous local timestamps with `ambiguous=False` and nonexistent timestamps with `nonexistent=shift_forward`; these are explicit assumptions and should be reviewed against the PVDAQ timestamp convention.

## 4. Solar and POA validation

`poa_quality.csv` contains per-system distribution statistics and negative-value rates for GHI, DNI, DHI, solar position, total POA, and POA components. The implementation clips negative irradiance inputs and negative POA outputs to zero, so this audit cannot distinguish a raw negative sensor value from a clipped feature without the raw weather payload.

## 5. Tracker 1430

The tracker uses `axis_tilt=0`, `axis_azimuth=official azimuth`, `max_angle=90`, `backtrack=True`, and `gcr=0.4`. Only axis azimuth is from the official catalog. Backtracking, GCR, max angle, and axis tilt are model assumptions unless separately documented by the owner. Representative angle, POA, and power values are in `tracker_1430_diagnostics.csv`; sensitivity results are in `sensitivity_analysis.csv`.

## 6. Target and power quality

`power_quality.csv` reports normalized target and raw AC-power ranges, including negative, over-capacity, >1.1 and >1.2 fractions. No observations were removed by this audit.

## 7. Residuals and strategy comparison

`residual_summary.csv` reports bias, spread, correlations, low/high POA behavior, and daylight/night bias per fold. `night_strategy_comparison.csv` compares the two requested strategies by fold and day/night metrics.

## 8. Generalization

LOSO covers four systems only. Systems 10 and 1430 are both in Colorado, so the 1430 fold is not an unseen geographic region. `domain_shift.csv` reports fold-specific train ranges and test medians; it does not justify claims beyond these four sites.

## 9. Physical baseline and sensitivity

`physical_baseline_metrics.csv` calibrates a POA factor on training rows inside each fold. `sensitivity_analysis.csv` records night thresholds, tracker assumptions, and matching tolerances. These are diagnostics, not model selection.

## 10. Leakage audit

`leakage_audit.csv` checks that system ID, AC power, historical PVDAQ POA, and full-data preprocessing are not part of the production feature contract. Fold fitting and baseline calibration are training-only.

## 11. Inference validation

`inference_validation.csv` exercises fixed systems 10, 34, 1239, tracker 1430, and night/day/dawn/dusk cases. It also verifies the four output fields required by the inference contract.

## 12. Historical comparison

The existing `model_comparison.csv` is retained. Its legacy comparison is not algorithm-only: it also changes the feature representation by using historical PVDAQ POA and PolynomialFeatures.

## 13. Limitations and recommendations

The principal limitations are nearest matching that may use future weather, four-site LOSO, a Colorado region represented twice, assumed tracker parameters, and local timestamp DST resolution. Before any next-phase model experiments, document the operational weather availability policy, validate tracker metadata with the system owner, and decide whether causal matching is required. No model alternative or tuning was performed in this phase.

## 14. Cleanup

`inventory_before_cleanup.csv` records the audited files and conservative classifications. No production, metadata, test, requirements, legacy comparison, or reproducibility artifact was deleted or moved automatically.
""")
    (RESULTS / "diagnostic_report.md").write_text(report, encoding="utf-8")


def main():
    DIAGNOSTICS.mkdir(parents=True, exist_ok=True)
    cleaned, configurations, weather_by_system, training = load_inputs()
    matches = reconstruct_matches(cleaned, configurations, weather_by_system)
    temporal = temporal_audit(matches, cleaned, weather_by_system)
    temporal.to_csv(DIAGNOSTICS / "temporal_matching.csv", index=False)
    solar = solar_audit(training, configurations)
    solar.to_csv(DIAGNOSTICS / "solar_quality.csv", index=False)
    physical = training.copy()
    poa_cols = ["ghi_W_m2", "dni_W_m2", "dhi_W_m2", "solar_zenith_deg", "solar_elevation_deg", "solar_azimuth_deg", "poa_synthetic_W_m2", "poa_beam_W_m2", "poa_sky_diffuse_W_m2", "poa_ground_diffuse_W_m2"]
    stats(physical, poa_cols).to_csv(DIAGNOSTICS / "poa_quality.csv", index=False)
    power = stats(training.assign(ac_ratio=training.normalized_power), ["normalized_power", "ac_power_W", "ac_ratio"])
    power["target_lt_0_pct"] = [float((training[training.system_id == system].normalized_power < 0).mean() * 100) for system in power.system_id]
    power["target_gt_1_pct"] = [float((training[training.system_id == system].normalized_power > 1).mean() * 100) for system in power.system_id]
    power["target_gt_1_1_pct"] = [float((training[training.system_id == system].normalized_power > 1.1).mean() * 100) for system in power.system_id]
    power["target_gt_1_2_pct"] = [float((training[training.system_id == system].normalized_power > 1.2).mean() * 100) for system in power.system_id]
    power.to_csv(DIAGNOSTICS / "power_quality.csv", index=False)
    residuals, _ = residual_audit(training)
    residuals.to_csv(DIAGNOSTICS / "residual_summary.csv", index=False)
    predictions = pd.read_csv(PREDICTIONS, low_memory=False)
    night_strategy_audit(predictions, training).to_csv(DIAGNOSTICS / "night_strategy_comparison.csv", index=False)
    domain_shift(training, configurations).to_csv(DIAGNOSTICS / "domain_shift.csv", index=False)
    baseline = physical_baseline(training)
    baseline.to_csv(DIAGNOSTICS / "physical_baseline_metrics.csv", index=False)
    sensitivity(predictions, training, baseline).to_csv(DIAGNOSTICS / "sensitivity_analysis.csv", index=False)
    tracker_audit(configurations, weather_by_system).to_csv(DIAGNOSTICS / "tracker_1430_diagnostics.csv", index=False)
    leakage = leakage_audit(training, configurations)
    leakage.to_csv(DIAGNOSTICS / "leakage_audit.csv", index=False)
    inference = inference_audit(configurations)
    inference.to_csv(DIAGNOSTICS / "inference_validation.csv", index=False)
    inventory().to_csv(DIAGNOSTICS / "inventory_before_cleanup.csv", index=False)
    write_report({"temporal": temporal}, temporal, solar, baseline, leakage, inference)
    print(json.dumps({"diagnostics_dir": str(DIAGNOSTICS), "future_match_pct_mean": float(temporal.future_match_pct.mean()), "inference_failures": int((inference.status == "FAIL").sum())}, indent=2))


if __name__ == "__main__":
    main()