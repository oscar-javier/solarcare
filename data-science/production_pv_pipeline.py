"""Production-oriented PV features, weather cache, training, and inference.

The system configuration catalog is intentionally mandatory: azimuth, tilt, and
tracking are not inferred from PV output or filled with defaults.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode
from urllib.request import urlopen

import joblib
import numpy as np
import pandas as pd
import pvlib
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import LinearRegression, Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from final_pv_pipeline import build_time_features, clean_dataset_frame, load_system_capacities

SYSTEMS = [10, 34, 1239, 1430]
TARGET = "normalized_power"
WEATHER_SCENARIOS = {
    "clear": {"ghi_factor": 1.00, "dni_factor": 1.00, "dhi_factor": 1.00},
    "partial_clouds": {"ghi_factor": 0.75, "dni_factor": 0.55, "dhi_factor": 0.90},
    "cloudy": {"ghi_factor": 0.45, "dni_factor": 0.15, "dhi_factor": 0.65},
    "rain": {"ghi_factor": 0.20, "dni_factor": 0.03, "dhi_factor": 0.40},
}
PRODUCTION_FEATURES = [
    "ghi_W_m2",
    "dni_W_m2",
    "dhi_W_m2",
    "ambient_temp_C",
    "solar_zenith_deg",
    "solar_elevation_deg",
    "solar_azimuth_deg",
    "tilt_deg",
    "azimuth_deg",
    "tracking_is_single_axis",
    "poa_synthetic_W_m2",
    "poa_beam_W_m2",
    "poa_sky_diffuse_W_m2",
    "poa_ground_diffuse_W_m2",
    "sin_hour",
    "cos_hour",
    "sin_day_of_year",
    "cos_day_of_year",
]


@dataclass(frozen=True)
class SystemConfiguration:
    system_id: int
    latitude: float
    longitude: float
    elevation_m: float
    dc_capacity_kW: float
    azimuth_deg: float
    tilt_deg: float
    tracking_type: str = "fixed"
    timezone: str = "UTC"
    metadata_source: str = "systems_2025..."

    def validate(self) -> None:
        if not -90 <= self.latitude <= 90:
            raise ValueError(f"Invalid latitude for system {self.system_id}")
        if not -180 <= self.longitude <= 180:
            raise ValueError(f"Invalid longitude for system {self.system_id}")
        if not 0 <= self.tilt_deg <= 180:
            raise ValueError(f"Invalid tilt for system {self.system_id}")
        if not 0 <= self.azimuth_deg <= 360:
            raise ValueError(f"Invalid azimuth for system {self.system_id}")
        if self.dc_capacity_kW <= 0:
            raise ValueError(f"Invalid capacity for system {self.system_id}")
        if self.tracking_type not in {"fixed", "single_axis"}:
            raise ValueError(f"Unsupported tracking_type={self.tracking_type!r}")


def load_system_configurations(path: str | Path) -> dict[int, SystemConfiguration]:
    frame = pd.read_csv(path)
    required = {
        "system_id", "latitude", "longitude", "elevation_m", "dc_capacity_kW",
        "azimuth_deg", "tilt_deg", "tracking_type",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"System configuration catalog missing columns: {missing}")
    if frame[list(required)].isna().any().any():
        raise ValueError("System configuration contains missing official geometry values")
    configurations = {}
    for row in frame.itertuples(index=False):
        config = SystemConfiguration(
            system_id=int(row.system_id),
            latitude=float(row.latitude),
            longitude=float(row.longitude),
            elevation_m=float(row.elevation_m),
            dc_capacity_kW=float(row.dc_capacity_kW),
            azimuth_deg=float(row.azimuth_deg),
            tilt_deg=float(row.tilt_deg),
            tracking_type=str(row.tracking_type),
            timezone=str(getattr(row, "timezone", "UTC")),
            metadata_source=str(getattr(row, "metadata_source", "systems_2025...")),
        )
        config.validate()
        configurations[config.system_id] = config
    return configurations


class OpenMeteoArchive:
    """Open-Meteo historical archive client with deterministic local caching."""

    def __init__(self, cache_dir: str | Path = "output/weather_cache", base_url: str = "https://archive-api.open-meteo.com/v1/archive"):
        self.cache_dir = Path(cache_dir)
        self.base_url = base_url

    def _cache_path(self, config: SystemConfiguration, start: str, end: str) -> Path:
        return self.cache_dir / f"system_{config.system_id}_{start}_{end}.json"

    def fetch(self, config: SystemConfiguration, start: str | date, end: str | date) -> pd.DataFrame:
        start_text, end_text = str(start), str(end)
        cache_path = self._cache_path(config, start_text, end_text)
        if cache_path.exists():
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
        else:
            params = {
                "latitude": config.latitude,
                "longitude": config.longitude,
                "start_date": start_text,
                "end_date": end_text,
                "hourly": "shortwave_radiation,direct_normal_irradiance,diffuse_radiation,temperature_2m",
                "timezone": "auto",
            }
            url = f"{self.base_url}?{urlencode(params)}"
            with urlopen(url, timeout=60) as response:
                payload = json.loads(response.read().decode("utf-8"))
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(payload), encoding="utf-8")
        hourly = payload.get("hourly") or {}
        if not hourly.get("time"):
            raise ValueError(f"Open-Meteo returned no hourly data for system {config.system_id}")
        return pd.DataFrame(
            {
                "timestamp": pd.to_datetime(hourly["time"]),
                "ghi_W_m2": hourly["shortwave_radiation"],
                "dni_W_m2": hourly["direct_normal_irradiance"],
                "dhi_W_m2": hourly["diffuse_radiation"],
                "ambient_temp_C": hourly["temperature_2m"],
            }
        ).assign(timezone=payload.get("timezone"), utc_offset_seconds=payload.get("utc_offset_seconds"))


def solar_and_poa_features(weather: pd.DataFrame, config: SystemConfiguration) -> pd.DataFrame:
    required = {"timestamp", "ghi_W_m2", "dni_W_m2", "dhi_W_m2", "ambient_temp_C"}
    missing = sorted(required - set(weather.columns))
    if missing:
        raise ValueError(f"Weather frame missing columns: {missing}")
    out = weather.copy()
    scenario = out.attrs.get("weather_scenario")
    if scenario is not None and scenario not in WEATHER_SCENARIOS:
        raise ValueError(f"Unsupported weather scenario: {scenario}")
    timestamps = pd.DatetimeIndex(pd.to_datetime(out["timestamp"]))
    if timestamps.tz is None:
        timezones = out.get("timezone")
        timezone = timezones.dropna().iloc[0] if timezones is not None and timezones.notna().any() else None
        if not timezone:
            raise ValueError("Weather timestamps must carry an explicit timezone")
        timestamps = timestamps.tz_localize(
            str(timezone), ambiguous=False, nonexistent="shift_forward"
        )
        out["timestamp"] = timestamps
    solar = pvlib.solarposition.get_solarposition(timestamps, config.latitude, config.longitude)
    out["solar_zenith_deg"] = solar["zenith"].to_numpy()
    out["solar_elevation_deg"] = solar["elevation"].to_numpy()
    out["solar_azimuth_deg"] = solar["azimuth"].to_numpy()

    if scenario is not None:
        factors = WEATHER_SCENARIOS[scenario]
        dni = pd.to_numeric(out["dni_W_m2"], errors="coerce").clip(lower=0).to_numpy() * factors["dni_factor"]
        dhi = pd.to_numeric(out["dhi_W_m2"], errors="coerce").clip(lower=0).to_numpy() * factors["dhi_factor"]
        ghi_base = pd.to_numeric(out["ghi_W_m2"], errors="coerce").clip(lower=0).to_numpy() * factors["ghi_factor"]
        apparent_zenith = np.clip(solar["apparent_zenith"].to_numpy(), 0, 90)
        cosine_zenith = np.cos(np.deg2rad(apparent_zenith))
        physically_consistent_ghi = dni * cosine_zenith + dhi
        out["dni_W_m2"] = dni
        out["dhi_W_m2"] = dhi
        out["ghi_W_m2"] = np.maximum(ghi_base, physically_consistent_ghi)

    surface_tilt = np.full(len(out), config.tilt_deg)
    surface_azimuth = np.full(len(out), config.azimuth_deg)
    if config.tracking_type == "single_axis":
        tracking = pvlib.tracking.singleaxis(
            apparent_zenith=solar["apparent_zenith"],
            solar_azimuth=solar["azimuth"],
            axis_tilt=0,
            axis_azimuth=config.azimuth_deg,
            max_angle=90,
            backtrack=True,
            gcr=0.4,
        )
        surface_tilt = tracking["surface_tilt"].fillna(0).to_numpy()
        surface_azimuth = tracking["surface_azimuth"].fillna(config.azimuth_deg).to_numpy()
    out["tilt_deg"] = surface_tilt
    out["azimuth_deg"] = surface_azimuth
    poa = pvlib.irradiance.get_total_irradiance(
        surface_tilt=surface_tilt,
        surface_azimuth=surface_azimuth,
        solar_zenith=solar["apparent_zenith"].to_numpy(),
        solar_azimuth=solar["azimuth"].to_numpy(),
        dni=out["dni_W_m2"],
        ghi=out["ghi_W_m2"],
        dhi=out["dhi_W_m2"],
        albedo=0.2,
    )
    out["poa_synthetic_W_m2"] = poa["poa_global"].clip(lower=0).to_numpy()
    out["poa_beam_W_m2"] = poa["poa_direct"].clip(lower=0).to_numpy()
    out["poa_sky_diffuse_W_m2"] = poa["poa_diffuse"].clip(lower=0).to_numpy()
    out["poa_ground_diffuse_W_m2"] = poa["poa_ground_diffuse"].clip(lower=0).to_numpy()
    out["tracking_is_single_axis"] = float(config.tracking_type == "single_axis")
    hour = timestamps.hour + timestamps.minute / 60
    day = timestamps.dayofyear
    year_days = timestamps.is_leap_year.astype(int) + 365
    out["sin_hour"] = np.sin(2 * np.pi * hour / 24)
    out["cos_hour"] = np.cos(2 * np.pi * hour / 24)
    out["sin_day_of_year"] = np.sin(2 * np.pi * day / year_days)
    out["cos_day_of_year"] = np.cos(2 * np.pi * day / year_days)
    return out


def build_production_training_frame(
    pvdaq: pd.DataFrame,
    weather_by_system: dict[int, pd.DataFrame],
    configurations: dict[int, SystemConfiguration],
    tolerance: str = "30min",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    coverage = []
    source = pvdaq.copy()
    source["timestamp"] = pd.to_datetime(source["timestamp"])
    for system_id, group in source.groupby("system_id"):
        if int(system_id) not in configurations:
            raise ValueError(f"Missing official configuration for system {system_id}")
        weather_source = weather_by_system[int(system_id)].copy()
        weather = solar_and_poa_features(weather_source, configurations[int(system_id)])
        weather["ambient_temp_C_weather"] = weather["ambient_temp_C"]
        weather["weather_timestamp_local"] = pd.to_datetime(weather_source["timestamp"])
        weather = weather.sort_values("weather_timestamp_local")
        weather_columns = [
            "weather_timestamp_local", "ghi_W_m2", "dni_W_m2", "dhi_W_m2", "ambient_temp_C_weather",
            "solar_zenith_deg", "solar_elevation_deg", "solar_azimuth_deg", "tilt_deg", "azimuth_deg",
            "tracking_is_single_axis", "poa_synthetic_W_m2", "poa_beam_W_m2", "poa_sky_diffuse_W_m2",
            "poa_ground_diffuse_W_m2", "sin_hour", "cos_hour", "sin_day_of_year", "cos_day_of_year", "timezone",
        ]
        matched = pd.merge_asof(
            group.sort_values("timestamp"),
            weather[weather_columns].sort_values("weather_timestamp_local"),
            left_on="timestamp",
            right_on="weather_timestamp_local",
            direction="nearest",
            tolerance=pd.Timedelta(tolerance),
        )
        matched = matched.drop(columns=["weather_timestamp_local"])
        matched["ambient_temp_C"] = matched["ambient_temp_C_weather"]
        matched = matched.drop(columns=["ambient_temp_C_weather"])
        matched["dc_capacity_kW"] = configurations[int(system_id)].dc_capacity_kW
        matched["tracking_type"] = configurations[int(system_id)].tracking_type
        matched[TARGET] = matched["ac_power_W"] / (matched["dc_capacity_kW"] * 1000.0)
        rows.append(matched)
        coverage.append(
            {
                "system_id": int(system_id),
                "pvdaq_rows": len(group),
                "matched_rows": int(matched["ghi_W_m2"].notna().sum()),
                "match_pct": float(matched["ghi_W_m2"].notna().mean() * 100),
                "discarded_rows": int(matched["ghi_W_m2"].isna().sum()),
                "timezone": weather["timezone"].dropna().iloc[0] if weather["timezone"].notna().any() else None,
                "matching_tolerance": tolerance,
            }
        )
    return pd.concat(rows, ignore_index=True), pd.DataFrame(coverage)


def production_estimators(random_state: int = 42) -> dict[str, Any]:
    return {
        "mean_global": None,
        "linear_ridge": make_pipeline(StandardScaler(), Ridge(alpha=1.0)),
        "linear": make_pipeline(StandardScaler(), LinearRegression()),
        "random_forest": RandomForestRegressor(n_estimators=300, min_samples_leaf=5, random_state=random_state, n_jobs=-1),
        "hist_gradient_boosting": HistGradientBoostingRegressor(max_iter=300, learning_rate=0.05, max_leaf_nodes=15, l2_regularization=1.0, random_state=random_state),
    }


def predict_pv_power(
    capacity_kW: float,
    latitude: float,
    longitude: float,
    datetime_value: str | pd.Timestamp,
    azimuth: float,
    tilt: float,
    model_path: str | Path,
    weather_provider: Callable[[float, float, pd.Timestamp], pd.DataFrame] | None = None,
    elevation_m: float = 0.0,
    tracking: str = "fixed",
) -> dict[str, Any]:
    config = SystemConfiguration(-1, latitude, longitude, elevation_m, capacity_kW, azimuth, tilt, tracking)
    config.validate()
    timestamp = pd.Timestamp(datetime_value)
    if weather_provider is None:
        archive = OpenMeteoArchive()
        start_date = (timestamp.date() - timedelta(days=1)).isoformat()
        end_date = (timestamp.date() + timedelta(days=1)).isoformat()
        weather = archive.fetch(config, start_date, end_date)
        weather_timestamps = pd.to_datetime(weather["timestamp"])
        comparison_timestamp = timestamp
        if weather_timestamps.dt.tz is None and timestamp.tzinfo is not None:
            weather_timezone = weather["timezone"].dropna().iloc[0] if weather["timezone"].notna().any() else None
            if weather_timezone:
                comparison_timestamp = timestamp.tz_convert(str(weather_timezone)).tz_localize(None)
            else:
                comparison_timestamp = timestamp.tz_localize(None)
        weather = weather.iloc[(weather_timestamps - comparison_timestamp).abs().argsort()[:1]].copy()
    else:
        weather = weather_provider(latitude, longitude, timestamp)
    features = solar_and_poa_features(weather, config)
    artifact = joblib.load(model_path)
    model = artifact["model"] if isinstance(artifact, dict) and "model" in artifact else artifact
    feature_columns = artifact.get("features", PRODUCTION_FEATURES) if isinstance(artifact, dict) else PRODUCTION_FEATURES
    strategy = artifact.get("strategy", "24h_model") if isinstance(artifact, dict) else "24h_model"
    normalized = float(model.predict(features[feature_columns])[0])
    if strategy == "daylight_model_night_zero":
        daylight = bool(
            features["solar_elevation_deg"].iloc[0] > 0
            and features["poa_synthetic_W_m2"].iloc[0] > 20
        )
        if not daylight:
            normalized = 0.0
    power_w = normalized * capacity_kW * 1000.0
    return {
        "predicted_power_W": power_w,
        "predicted_power_kW": power_w / 1000.0,
        "normalized_power": normalized,
        "timestamp": timestamp.isoformat(),
        "features_used": features[PRODUCTION_FEATURES].iloc[0].to_dict(),
    }


def predict_pv_day(
    capacity_kW: float,
    latitude: float,
    longitude: float,
    date_value: str,
    azimuth: float,
    tilt: float,
    model_path: str | Path,
    elevation_m: float = 0.0,
    tracking: str = "fixed",
    timezone: str | None = None,
    interval_minutes: int = 15,
    weather_scenario: str = "clear",
) -> dict[str, Any]:
    """Predict a complete local calendar day with the production feature path."""
    if interval_minutes <= 0 or 1440 % interval_minutes:
        raise ValueError("interval_minutes must divide 1440")
    if weather_scenario not in WEATHER_SCENARIOS:
        raise ValueError(f"Unsupported weather scenario: {weather_scenario}")
    config = SystemConfiguration(-1, latitude, longitude, elevation_m, capacity_kW, azimuth, tilt, tracking, timezone or "UTC")
    config.validate()
    day = pd.Timestamp(date_value).date()
    archive = OpenMeteoArchive()
    weather = archive.fetch(config, day.isoformat(), day.isoformat())
    weather.attrs["weather_scenario"] = weather_scenario
    resolved_timezone = str(weather["timezone"].dropna().iloc[0]) if weather["timezone"].notna().any() else (timezone or "UTC")
    local_points = pd.date_range(
        start=f"{day.isoformat()} 06:00",
        periods=((18 - 6) * 60 // interval_minutes) + 1,
        freq=f"{interval_minutes}min",
    )
    weather_features = solar_and_poa_features(weather, config)
    weather_features["weather_timestamp_local"] = pd.to_datetime(weather["timestamp"])
    weather_features = weather_features.drop(columns=["timestamp"])
    points = pd.DataFrame({"timestamp": local_points})
    features = pd.merge_asof(
        points.sort_values("timestamp"),
        weather_features.sort_values("weather_timestamp_local"),
        left_on="timestamp",
        right_on="weather_timestamp_local",
        direction="nearest",
        tolerance=pd.Timedelta("30min"),
    )
    artifact = joblib.load(model_path)
    model = artifact["model"] if isinstance(artifact, dict) and "model" in artifact else artifact
    feature_columns = artifact.get("features", PRODUCTION_FEATURES) if isinstance(artifact, dict) else PRODUCTION_FEATURES
    strategy = artifact.get("strategy", "24h_model") if isinstance(artifact, dict) else "24h_model"
    valid = features[feature_columns].notna().all(axis=1)
    normalized = np.full(len(features), np.nan, dtype=float)
    normalized[valid.to_numpy()] = model.predict(features.loc[valid, feature_columns])
    if strategy == "daylight_model_night_zero":
        daylight = (features["solar_elevation_deg"] > 0) & (features["poa_synthetic_W_m2"] > 20)
        normalized[~daylight.fillna(False).to_numpy()] = 0.0
    power_w = normalized * capacity_kW * 1000.0
    points_out = []
    for timestamp, normalized_value, watts in zip(features["timestamp"], normalized, power_w):
        timestamp_localized = pd.Timestamp(timestamp).tz_localize(resolved_timezone)
        points_out.append({
            "timestamp": timestamp_localized.isoformat(),
            "normalized_power": None if not np.isfinite(normalized_value) else float(normalized_value),
            "predicted_power_W": None if not np.isfinite(watts) else float(watts),
            "predicted_power_kW": None if not np.isfinite(watts) else float(watts / 1000.0),
        })
    return {"date": day.isoformat(), "timezone": resolved_timezone, "weather": weather_scenario, "interval_minutes": interval_minutes, "points": points_out}
