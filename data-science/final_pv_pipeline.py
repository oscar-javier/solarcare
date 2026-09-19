from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import urlopen

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression, Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import Pipeline, make_pipeline
from sklearn.preprocessing import PolynomialFeatures, StandardScaler


DEFAULT_SYSTEMS = [10, 34, 1239, 1430]
TARGET_MODE = "normalized_power"
FEATURE_COLUMNS = [
    "latitude",
    "longitude",
    "elevation",
    "poa_irradiance_W_m2",
    "ambient_temp_C",
    "sin_hour",
    "cos_hour",
    "sin_day_of_year",
    "cos_day_of_year",
]

SYSTEM_CAPACITY_FALLBACK = {
    10: 1.12,
    34: 146.64,
    1239: 20.16,
    1430: 720.72,
}

SYSTEM_LOCATION_METADATA = {
    10: {"latitude": 39.7404, "longitude": -105.1774, "elevation": 1792.8},
    34: {"latitude": 36.1952, "longitude": -115.0, "elevation": None},
    1239: {"latitude": 46.6704, "longitude": -68.0178, "elevation": 197.0},
    1430: {"latitude": 39.7438, "longitude": -105.1779, "elevation": 1831.0},
}

CLEANING_RULES = {
    1430: {"max_timestamp": "2010-08-29 23:59:59"},
    1239: {"min_timestamp": "2019-04-01 00:00:00", "max_timestamp": "2019-10-31 23:59:59"},
}


@dataclass
class FinalModelConfig:
    dataset_path: Path = Path("output/lectura_horaria.csv")
    capacity_path: Path = Path("capacidades_sistemas.csv")
    systems: list[int] = field(default_factory=lambda: DEFAULT_SYSTEMS.copy())
    capacity_source: str = "dc_capacity"
    target_mode: str = TARGET_MODE
    degree: int = 2
    feature_columns: list[str] = field(default_factory=lambda: FEATURE_COLUMNS.copy())
    output_dir: Path = Path("output/final_pipeline")
    model_output_dir: Path = Path("models")
    results_output_dir: Path = Path("results")
    weather_provider: str = "openmeteo"


def load_system_capacities(capacity_path: Path | str) -> dict[int, float]:
    p = Path(capacity_path)
    if not p.exists():
        return SYSTEM_CAPACITY_FALLBACK.copy()
    df = pd.read_csv(p)
    if {"system_id", "dc_capacity_kW"}.issubset(df.columns):
        return {int(row.system_id): float(row.dc_capacity_kW) for row in df.itertuples(index=False)}
    return SYSTEM_CAPACITY_FALLBACK.copy()


def clean_dataset_frame(df: pd.DataFrame, system_ids: list[int] | None = None) -> tuple[pd.DataFrame, dict[str, Any]]:
    original = df.copy()
    if system_ids is not None:
        df = df[df["system_id"].isin(system_ids)].copy()

    df["system_id"] = pd.to_numeric(df["system_id"], errors="coerce")
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df["ac_power_W"] = pd.to_numeric(df["ac_power_W"], errors="coerce")
    for col in ["poa_irradiance_W_m2", "ambient_temp_C", "sin_hora", "cos_hora", "sin_dia_anual", "cos_dia_anual"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    for system_id, rule in CLEANING_RULES.items():
        if system_id in set(df["system_id"].dropna().astype(int).unique()):
            system_mask = df["system_id"] == system_id
            if "max_timestamp" in rule:
                max_ts = pd.Timestamp(rule["max_timestamp"])
                df.loc[system_mask & (df["timestamp"] > max_ts), "ac_power_W"] = np.nan
            if "min_timestamp" in rule:
                min_ts = pd.Timestamp(rule["min_timestamp"])
                df.loc[system_mask & (df["timestamp"] < min_ts), "ac_power_W"] = np.nan
            if "max_timestamp" in rule and "min_timestamp" in rule:
                min_ts = pd.Timestamp(rule["min_timestamp"])
                max_ts = pd.Timestamp(rule["max_timestamp"])
                df.loc[system_mask & ~((df["timestamp"] >= min_ts) & (df["timestamp"] <= max_ts)), "ac_power_W"] = np.nan

    df = df.dropna(subset=["system_id", "timestamp", "ac_power_W"]).copy()
    df = df[np.isfinite(df["ac_power_W"]).to_numpy()]
    if "poa_irradiance_W_m2" in df.columns:
        df = df[np.isfinite(df["poa_irradiance_W_m2"]).to_numpy()]
    if "ambient_temp_C" in df.columns:
        df = df[np.isfinite(df["ambient_temp_C"]).to_numpy()]

    summary = {
        "original_rows": int(len(original)),
        "filtered_rows": int(len(df)),
        "removed_rows": int(len(original) - len(df)),
        "systems": sorted(int(s) for s in df["system_id"].unique()),
        "time_range": {
            "start": df["timestamp"].min().isoformat() if not df.empty else None,
            "end": df["timestamp"].max().isoformat() if not df.empty else None,
        },
    }
    return df.reset_index(drop=True), summary


def build_time_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy().sort_values(["system_id", "timestamp"]).reset_index(drop=True)
    ts = pd.to_datetime(out["timestamp"])
    hour = ts.dt.hour + ts.dt.minute / 60.0 + ts.dt.second / 3600.0
    day_of_year = ts.dt.dayofyear
    year_days = ts.dt.is_leap_year.astype(int) + 365
    out["hour"] = hour
    out["day_of_year"] = day_of_year
    out["sin_hour"] = np.sin(2 * np.pi * hour / 24.0)
    out["cos_hour"] = np.cos(2 * np.pi * hour / 24.0)
    out["sin_day_of_year"] = np.sin(2 * np.pi * day_of_year / year_days)
    out["cos_day_of_year"] = np.cos(2 * np.pi * day_of_year / year_days)
    return out


def attach_system_metadata(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for field_name in ["latitude", "longitude", "elevation"]:
        values = []
        for system_id in out["system_id"].astype(int):
            meta = SYSTEM_LOCATION_METADATA.get(int(system_id), {})
            value = meta.get(field_name)
            values.append(float(value) if value is not None else np.nan)
        out[field_name] = values
    out["latitude"] = pd.to_numeric(out["latitude"], errors="coerce")
    out["longitude"] = pd.to_numeric(out["longitude"], errors="coerce")
    out["elevation"] = pd.to_numeric(out["elevation"], errors="coerce").fillna(0.0)
    return out


def build_feature_frame(
    timestamp: str | pd.Timestamp,
    latitude: float,
    longitude: float,
    elevation: float | None = None,
    temperature_c: float | None = None,
    irradiance_wm2: float | None = None,
    capacity_kW: float | None = None,
) -> pd.DataFrame:
    ts = pd.Timestamp(timestamp)
    hour = ts.hour + ts.minute / 60.0 + ts.second / 3600.0
    day_of_year = ts.dayofyear
    row = {
        "latitude": float(latitude),
        "longitude": float(longitude),
        "elevation": float(elevation) if elevation is not None else np.nan,
        "poa_irradiance_W_m2": float(irradiance_wm2) if irradiance_wm2 is not None else np.nan,
        "ambient_temp_C": float(temperature_c) if temperature_c is not None else np.nan,
        "sin_hour": float(np.sin(2 * np.pi * hour / 24.0)),
        "cos_hour": float(np.cos(2 * np.pi * hour / 24.0)),
        "sin_day_of_year": float(np.sin(2 * np.pi * day_of_year / (365 + int(ts.is_leap_year)))),
        "cos_day_of_year": float(np.cos(2 * np.pi * day_of_year / (365 + int(ts.is_leap_year)))),
    }
    if capacity_kW is not None:
        row["capacity_kW"] = float(capacity_kW)
    return pd.DataFrame([row])


class WeatherProvider:
    def get_weather(self, latitude: float, longitude: float, timestamp: pd.Timestamp) -> dict[str, float]:
        raise NotImplementedError


class OpenMeteoWeatherProvider(WeatherProvider):
    def __init__(self, api_base: str = "https://api.open-meteo.com/v1/forecast"):
        self.api_base = api_base

    def _fetch(self, latitude: float, longitude: float, timestamp: pd.Timestamp) -> dict[str, Any]:
        start = timestamp.strftime("%Y-%m-%d")
        end = timestamp.strftime("%Y-%m-%d")
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "hourly": "temperature_2m,shortwave_radiation,cloud_cover,wind_speed_10m",
            "timezone": "auto",
            "start_date": start,
            "end_date": end,
        }
        url = f"{self.api_base}?{urlencode(params)}"
        try:
            with urlopen(url, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
            return payload
        except Exception:
            return {}

    def get_weather(self, latitude: float, longitude: float, timestamp: pd.Timestamp) -> dict[str, float]:
        payload = self._fetch(latitude, longitude, timestamp)
        hourly = payload.get("hourly") or {}
        times = hourly.get("time") or []
        if not times:
            return {"temperature_c": 20.0, "poa_irradiance_W_m2": 0.0, "cloud_cover": 0.0, "wind_speed_ms": 0.0}
        dt_values = [pd.Timestamp(t) for t in times]
        idx = min(range(len(dt_values)), key=lambda i: abs((dt_values[i] - timestamp).total_seconds()))
        return {
            "temperature_c": float((hourly.get("temperature_2m") or [20.0])[idx]),
            "poa_irradiance_W_m2": float((hourly.get("shortwave_radiation") or [0.0])[idx]),
            "cloud_cover": float((hourly.get("cloud_cover") or [0.0])[idx]),
            "wind_speed_ms": float((hourly.get("wind_speed_10m") or [0.0])[idx]),
        }


def resolve_capacity_map(df: pd.DataFrame, capacity_source: str, capacities: dict[int, float]) -> dict[int, float]:
    if capacity_source == "max_ac":
        return {int(system_id): float(group["ac_power_W"].max()) for system_id, group in df.groupby("system_id")}
    if capacity_source == "dc_capacity":
        missing = sorted(set(df["system_id"].unique()) - set(capacities.keys()))
        if missing:
            raise ValueError(f"Falta dc_capacity para sistemas: {missing}")
        return {int(system_id): float(capacities[int(system_id)]) for system_id in sorted(df["system_id"].unique())}
    raise ValueError(f"capacidad no soportada: {capacity_source}")


def build_target_from_capacity(df: pd.DataFrame, capacity_source: str, capacities: dict[int, float], target_mode: str = TARGET_MODE) -> pd.DataFrame:
    out = df.copy()
    mm = resolve_capacity_map(out, capacity_source, capacities)
    out["capacity_used"] = out["system_id"].map(mm)
    out["target_original"] = out["ac_power_W"].astype(float)
    out["normalized_power"] = out["target_original"] / (out["capacity_used"] * 1000.0)
    out["target"] = out["normalized_power"] if target_mode == "normalized_power" else out["target_original"]
    out["capacity_source"] = capacity_source
    return out


def build_model_pipeline(degree: int = 2, ridge: bool = False) -> Pipeline:
    if ridge:
        return make_pipeline(
            StandardScaler(),
            PolynomialFeatures(degree=degree, include_bias=False),
            Ridge(alpha=1.0),
        )
    return make_pipeline(
        StandardScaler(),
        PolynomialFeatures(degree=degree, include_bias=False),
        LinearRegression(),
    )


def evaluate_metrics(y_true: pd.Series, y_pred: np.ndarray) -> dict[str, float]:
    y_true = pd.Series(y_true).astype(float)
    y_pred = pd.Series(y_pred).astype(float)
    return {
        "mae": float(mean_absolute_error(y_true, y_pred)),
        "rmse": float(np.sqrt(mean_squared_error(y_true, y_pred))),
        "r2": float(r2_score(y_true, y_pred)),
    }


def train_and_evaluate_fold(
    train_df: pd.DataFrame,
    test_df: pd.DataFrame,
    feature_columns: list[str],
    capacity_source: str,
    capacities: dict[int, float],
    target_mode: str = TARGET_MODE,
    degree: int = 2,
    ridge: bool = False,
) -> dict[str, Any]:
    train_df = build_target_from_capacity(train_df, capacity_source, capacities, target_mode=target_mode)
    test_df = build_target_from_capacity(test_df, capacity_source, capacities, target_mode=target_mode)

    X_train = train_df[feature_columns]
    y_train = train_df["target"]
    X_test = test_df[feature_columns]
    y_test = test_df["target"]

    baseline_mean = float(y_train.mean())
    baseline_pred = np.full(len(test_df), baseline_mean)
    baseline_metrics = evaluate_metrics(y_test, baseline_pred)

    model = build_model_pipeline(degree=degree, ridge=ridge)
    model.fit(X_train, y_train)
    pred_norm = model.predict(X_test)
    pred_norm = pd.Series(pred_norm).astype(float)

    norm_metrics = evaluate_metrics(y_test, pred_norm)
    pred_watts = pred_norm.to_numpy() * test_df["capacity_used"].to_numpy() * 1000.0
    true_watts = test_df["target_original"].to_numpy()
    watt_metrics = evaluate_metrics(pd.Series(true_watts), pred_watts)

    result = {
        "baseline_mae": baseline_metrics["mae"],
        "baseline_rmse": baseline_metrics["rmse"],
        "baseline_r2": baseline_metrics["r2"],
        "y_test_min": float(y_test.min()),
        "y_test_max": float(y_test.max()),
        "y_test_mean": float(y_test.mean()),
        "prediction_min": float(pred_norm.min()),
        "prediction_max": float(pred_norm.max()),
        "prediction_mean": float(pred_norm.mean()),
        "model_mae": norm_metrics["mae"],
        "model_rmse": norm_metrics["rmse"],
        "model_r2": norm_metrics["r2"],
        "mae_w": watt_metrics["mae"],
        "rmse_w": watt_metrics["rmse"],
        "r2_w": watt_metrics["r2"],
        "n_train": int(len(train_df)),
        "n_test": int(len(test_df)),
        "capacity_source": capacity_source,
        "target_mode": target_mode,
        "model_kind": "ridge_polynomial" if ridge else "polynomial_linear",
    }
    return {"model": model, "metrics": result, "predictions": pred_watts, "normalized_predictions": pred_norm, "test_df": test_df, "train_df": train_df}


def make_loso_experiment(df: pd.DataFrame, systems: list[int], feature_columns: list[str], capacity_source: str, capacities: dict[int, float], degree: int = 2, ridge: bool = False) -> pd.DataFrame:
    rows = []
    for test_system in systems:
        train_systems = [s for s in systems if s != test_system]
        train_df = df[df["system_id"].isin(train_systems)].copy()
        test_df = df[df["system_id"] == test_system].copy()
        if train_df.empty or test_df.empty:
            continue
        fold = train_and_evaluate_fold(train_df, test_df, feature_columns, capacity_source, capacities, target_mode="normalized_power", degree=degree, ridge=ridge)
        result = fold["metrics"].copy()
        result["experiment"] = "leave_one_system_out"
        result["train_systems"] = train_systems
        result["test_systems"] = [test_system]
        result["model_kind"] = "ridge_polynomial" if ridge else "polynomial_linear"
        rows.append(result)

    return pd.DataFrame(rows)


def make_grouped_holdout_experiment(df: pd.DataFrame, train_systems: list[int], test_systems: list[int], feature_columns: list[str], capacity_source: str, capacities: dict[int, float], degree: int = 2, ridge: bool = False) -> pd.DataFrame:
    train_df = df[df["system_id"].isin(train_systems)].copy()
    test_df = df[df["system_id"].isin(test_systems)].copy()
    fold = train_and_evaluate_fold(train_df, test_df, feature_columns, capacity_source, capacities, target_mode="normalized_power", degree=degree, ridge=ridge)
    result = fold["metrics"].copy()
    result["experiment"] = "grouped_system_holdout"
    result["train_systems"] = train_systems
    result["test_systems"] = test_systems
    result["model_kind"] = "ridge_polynomial" if ridge else "polynomial_linear"
    return pd.DataFrame([result])


def train_final_model(
    df: pd.DataFrame,
    feature_columns: list[str],
    capacity_source: str,
    capacities: dict[int, float],
    model_path: Path,
    metadata_path: Path,
    degree: int = 2,
    weather_source_training: str = "PVDAQ",
    weather_source_inference: str = "Open-Meteo",
) -> tuple[Any, dict[str, Any]]:
    train_df = build_target_from_capacity(df, capacity_source, capacities, target_mode="normalized_power")
    train_df = attach_system_metadata(train_df)
    model = build_model_pipeline(degree=degree, ridge=False)
    model.fit(train_df[feature_columns], train_df["target"])

    model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, model_path)

    metadata = {
        "model_type": "PolynomialFeatures+StandardScaler+LinearRegression",
        "degree": degree,
        "target": "normalized_power",
        "capacity_source": capacity_source,
        "features": feature_columns,
        "training_systems": sorted(int(s) for s in train_df["system_id"].unique()),
        "weather_source_training": weather_source_training,
        "weather_source_inference": weather_source_inference,
        "created_at": pd.Timestamp.now("UTC").isoformat(),
        "version": "final_pv_v1",
        "capacity_used_per_system": {str(int(k)): float(v) for k, v in resolve_capacity_map(train_df, capacity_source, capacities).items()},
    }
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return model, metadata


def create_final_model(
    dataset_path: Path | str,
    capacity_path: Path | str,
    model_path: Path | str,
    metadata_path: Path | str,
    systems: list[int] | None = None,
    capacity_source: str = "dc_capacity",
    degree: int = 2,
):
    dataset = pd.read_csv(dataset_path, low_memory=False)
    cleaned_df, _ = clean_dataset_frame(dataset, systems)
    cleaned_df = build_time_features(cleaned_df)
    cleaned_df = attach_system_metadata(cleaned_df)
    capacities = load_system_capacities(capacity_path)
    model, metadata = train_final_model(
        cleaned_df,
        feature_columns=FEATURE_COLUMNS,
        capacity_source=capacity_source,
        capacities=capacities,
        model_path=Path(model_path),
        metadata_path=Path(metadata_path),
        degree=degree,
    )
    return model


def load_final_model(model_path: Path | str) -> Any:
    return joblib.load(model_path)


def predict_new_system(
    capacity_kW: float,
    latitude: float,
    longitude: float,
    datetime_value: str | pd.Timestamp,
    duration_hours: float = 1.0,
    model_path: str | Path = "models/final_model.joblib",
    weather_provider: WeatherProvider | None = None,
    elevation: float | None = None,
) -> dict[str, Any]:
    if capacity_kW <= 0:
        raise ValueError("capacity_kW debe ser > 0")

    timestamp = pd.Timestamp(datetime_value)
    provider = weather_provider or OpenMeteoWeatherProvider()
    weather = provider.get_weather(latitude, longitude, timestamp)
    feature_frame = build_feature_frame(
        timestamp=timestamp,
        latitude=latitude,
        longitude=longitude,
        elevation=elevation,
        temperature_c=weather.get("temperature_c"),
        irradiance_wm2=weather.get("poa_irradiance_W_m2"),
        capacity_kW=capacity_kW,
    )

    model = load_final_model(model_path)
    normalized = float(model.predict(feature_frame[FEATURE_COLUMNS])[0])
    power_w = normalized * capacity_kW * 1000.0
    power_kW = power_w / 1000.0
    energy_kWh = power_kW * float(duration_hours)
    return {
        "predicted_normalized_power": normalized,
        "predicted_power_W": power_w,
        "predicted_power_kW": power_kW,
        "predicted_energy_kWh": energy_kWh,
        "features": feature_frame[FEATURE_COLUMNS].iloc[0].to_dict(),
        "weather": weather,
        "timestamp": timestamp.isoformat(),
    }


def run_final_pipeline(config: FinalModelConfig) -> dict[str, Any]:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    config.model_output_dir.mkdir(parents=True, exist_ok=True)
    config.results_output_dir.mkdir(parents=True, exist_ok=True)

    dataset = pd.read_csv(config.dataset_path, low_memory=False)
    cleaned_df, summary = clean_dataset_frame(dataset, config.systems)
    cleaned_df = build_time_features(cleaned_df)
    cleaned_df = attach_system_metadata(cleaned_df)
    if "poa_irradiance_W_m2" not in cleaned_df.columns:
        raise ValueError("El dataset no incluye poa_irradiance_W_m2: la feature meteorológica principal no está disponible.")

    capacities = load_system_capacities(config.capacity_path)

    loso = make_loso_experiment(cleaned_df, config.systems, FEATURE_COLUMNS, config.capacity_source, capacities, degree=config.degree)
    grouped = make_grouped_holdout_experiment(cleaned_df, [10, 34, 1430], [1239], FEATURE_COLUMNS, config.capacity_source, capacities, degree=config.degree)

    model_path = config.model_output_dir / "final_model.joblib"
    metadata_path = config.model_output_dir / "final_model_metadata.json"
    final_model, metadata = train_final_model(cleaned_df, FEATURE_COLUMNS, config.capacity_source, capacities, model_path, metadata_path, degree=config.degree)

    results_dir = config.results_output_dir
    results_dir.mkdir(parents=True, exist_ok=True)
    loso.to_csv(results_dir / "loso_metrics.csv", index=False)
    grouped.to_csv(results_dir / "grouped_holdout_metrics.csv", index=False)

    metrics_summary = {
        "data_quality": summary,
        "capacity_source": config.capacity_source,
        "capacity_map": {str(int(k)): float(v) for k, v in capacities.items()},
        "loso": loso.to_dict(orient="records"),
        "grouped_holdout": grouped.to_dict(orient="records"),
        "final_model": metadata,
    }
    (results_dir / "summary.json").write_text(json.dumps(metrics_summary, indent=2), encoding="utf-8")
    return {
        "model": final_model,
        "metadata": metadata,
        "summary": summary,
        "loso": loso,
        "grouped_holdout": grouped,
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Pipeline final de predicción fotovoltaica")
    parser.add_argument("--dataset", type=Path, default=Path("output/lectura_horaria.csv"))
    parser.add_argument("--capacity-path", type=Path, default=Path("capacidades_sistemas.csv"))
    parser.add_argument("--systems", nargs="*", type=int, default=DEFAULT_SYSTEMS)
    parser.add_argument("--capacity-source", choices=["max_ac", "dc_capacity"], default="dc_capacity")
    parser.add_argument("--degree", type=int, default=2)
    parser.add_argument("--model-dir", type=Path, default=Path("models"))
    parser.add_argument("--results-dir", type=Path, default=Path("results"))
    args = parser.parse_args()

    config = FinalModelConfig(
        dataset_path=args.dataset,
        capacity_path=args.capacity_path,
        systems=args.systems,
        capacity_source=args.capacity_source,
        degree=args.degree,
        model_output_dir=args.model_dir,
        results_output_dir=args.results_dir,
    )
    outcome = run_final_pipeline(config)
    print(json.dumps({
        "systems": sorted(args.systems),
        "capacity_source": args.capacity_source,
        "loso_rows": len(outcome["loso"]),
        "grouped_rows": len(outcome["grouped_holdout"]),
        "final_model_path": str(config.model_output_dir / "final_model.joblib"),
        "final_metadata_path": str(config.model_output_dir / "final_model_metadata.json"),
    }, indent=2))
