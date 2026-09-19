"""Production preflight and coverage report; does not train or overwrite models."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from final_pv_pipeline import SYSTEM_LOCATION_METADATA
from production_pv_pipeline import PRODUCTION_FEATURES, SYSTEMS, OpenMeteoArchive, SystemConfiguration, load_system_configurations

OUTPUT_DIR = Path("results/production_model")
CAPACITIES = {10: 1.12, 34: 146.64, 1239: 20.16, 1430: 720.72}


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    pvdaq = pd.read_csv("output/lectura_horaria.csv", low_memory=False)
    pvdaq["timestamp"] = pd.to_datetime(pvdaq["timestamp"])
    weather_rows = []
    quality_rows = []
    provider = OpenMeteoArchive("output/weather_cache")
    for system_id in SYSTEMS:
        group = pvdaq[pvdaq["system_id"] == system_id].sort_values("timestamp")
        location = SYSTEM_LOCATION_METADATA[system_id]
        dates = group["timestamp"]
        config = SystemConfiguration(
            system_id=system_id,
            latitude=location["latitude"],
            longitude=location["longitude"],
            elevation_m=float(location.get("elevation") or 0),
            dc_capacity_kW=CAPACITIES[system_id],
            azimuth_deg=float("nan"),
            tilt_deg=float("nan"),
            tracking_type="unavailable",
        )
        weather = provider.fetch(config, dates.min().date().isoformat(), dates.max().date().isoformat())
        matched = pd.merge_asof(
            group[["timestamp"]].sort_values("timestamp"),
            weather[["timestamp", "ghi_W_m2", "dni_W_m2", "dhi_W_m2", "ambient_temp_C"]].sort_values("timestamp"),
            on="timestamp",
            direction="nearest",
            tolerance=pd.Timedelta("30min"),
        )
        weather_rows.append(
            {
                "system_id": system_id,
                "pvdaq_rows": len(group),
                "weather_rows": len(weather),
                "matched_rows": int(matched["ghi_W_m2"].notna().sum()),
                "match_pct": float(matched["ghi_W_m2"].notna().mean() * 100),
                "discarded_rows": int(matched["ghi_W_m2"].isna().sum()),
                "timezone": weather["timezone"].dropna().iloc[0],
                "matching_method": "merge_asof nearest, tolerance=30min",
                "pvdaq_start": dates.min().isoformat(),
                "pvdaq_end": dates.max().isoformat(),
            }
        )
        quality_rows.append(
            {
                "system_id": system_id,
                "rows": len(group),
                "duplicate_timestamps": int(group["timestamp"].duplicated().sum()),
                "negative_ac_power_rows": int((group["ac_power_W"] < 0).sum()),
                "ac_power_above_capacity_rows": int((group["ac_power_W"] > CAPACITIES[system_id] * 1000).sum()),
                "negative_poa_rows": int((group["poa_irradiance_W_m2"] < 0).sum()),
                "missing_poa_rows": int(group["poa_irradiance_W_m2"].isna().sum()),
                "missing_temperature_rows": int(group["ambient_temp_C"].isna().sum()),
                "nighttime_power_rows": int(((group["poa_irradiance_W_m2"] <= 1) & (group["ac_power_W"] > 0)).sum()),
                "timestamp_start": group["timestamp"].min().isoformat(),
                "timestamp_end": group["timestamp"].max().isoformat(),
            }
        )

    pd.DataFrame(weather_rows).to_csv(OUTPUT_DIR / "weather_coverage.csv", index=False)
    pd.DataFrame(quality_rows).to_csv(OUTPUT_DIR / "data_quality.csv", index=False)
    pd.DataFrame({"feature": PRODUCTION_FEATURES, "source": [
        "Open-Meteo archive", "Open-Meteo archive", "Open-Meteo archive", "Open-Meteo archive",
        "pvlib solarposition", "pvlib solarposition", "pvlib solarposition", "system catalog",
        "system catalog", "system catalog", "pvlib irradiance.get_total_irradiance",
        "pvlib irradiance.get_total_irradiance", "pvlib irradiance.get_total_irradiance",
        "pvlib irradiance.get_total_irradiance", "timestamp", "timestamp", "timestamp", "timestamp",
    ]}).to_csv(OUTPUT_DIR / "feature_catalog.csv", index=False)

    config_path = Path("system_configurations.csv")
    geometry_available = config_path.exists()
    if geometry_available:
        try:
            load_system_configurations(config_path)
        except Exception as exc:
            geometry_available = False
            geometry_error = str(exc)
        else:
            geometry_error = None
    else:
        geometry_error = "system_configurations.csv is absent; official azimuth/tilt/tracking values are unavailable"

    summary = {
        "weather_provider": "Open-Meteo archive",
        "weather_cache": "output/weather_cache",
        "systems": SYSTEMS,
        "production_features": PRODUCTION_FEATURES,
        "official_geometry_catalog_available": geometry_available,
        "geometry_error": geometry_error,
        "training_status": "blocked_until_official_geometry_catalog_is_available",
        "final_artifacts_modified": False,
    }
    (OUTPUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (OUTPUT_DIR / "limitations.md").write_text(
        "# Production preflight limitations\n\n"
        "Open-Meteo historical irradiance and temperature were cached for all four systems. "
        "The local project and reachable S3 paths do not contain official azimuth, tilt, or tracking metadata. "
        "The NREL PVDAQ API was not resolvable from this environment.\n\n"
        "Training is intentionally blocked. No geometry defaults were invented, no historical POA was reused, "
        "and no final model artifacts were overwritten. Provide an official system_configurations.csv before training.\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
