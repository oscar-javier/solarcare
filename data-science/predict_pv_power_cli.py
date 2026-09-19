"""JSON stdin/stdout bridge for the production PV inference function."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from production_pv_pipeline import predict_pv_day, predict_pv_power


ROOT = Path(__file__).resolve().parent


def main() -> None:
    payload = json.load(sys.stdin)
    common = {
        "capacity_kW": float(payload["capacity_kW"]),
        "latitude": float(payload["latitude"]),
        "longitude": float(payload["longitude"]),
        "azimuth": float(payload["azimuth_deg"]),
        "tilt": float(payload["tilt_deg"]),
        "model_path": ROOT / "models" / "production_model.joblib",
        "elevation_m": float(payload.get("elevation_m", 0.0)),
        "tracking": str(payload["tracking_type"]),
    }
    if payload.get("date"):
        result = predict_pv_day(
            date_value=payload["date"],
            timezone=payload.get("timezone"),
            weather_scenario=payload.get("weather", "clear"),
            **common,
        )
    else:
        result = predict_pv_power(datetime_value=payload["datetime"], **common)
    json.dump(result, sys.stdout)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(str(error), file=sys.stderr)
        raise