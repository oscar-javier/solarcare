"""Generate an auditable report for canonical PVDAQ units."""

from __future__ import annotations

import glob
import json
import os
import re
from pathlib import Path

import pandas as pd

from config import OUTPUT_DIR, SYSTEM_IDS
from pvdaq_units import load_metric_catalog
from transform_load import METRIC_CATALOG_PATH, resample_to_hourly, standardize_columns


CAPACITY_PATH = Path(__file__).with_name("capacidades_sistemas.csv")
REPORT_DIR = Path(OUTPUT_DIR) / "unit_audit"


def _raw_file_by_system() -> dict[int, str]:
    selected = {}
    for path in glob.glob(os.path.join(OUTPUT_DIR, "raw_*_????_????.csv")):
        match = re.fullmatch(r"raw_(\d+)_(\d{4})_(\d{4})\.csv", os.path.basename(path))
        if not match:
            continue
        system_id = int(match.group(1))
        span = int(match.group(3)) - int(match.group(2))
        current = selected.get(system_id)
        if current is None or span > current[0]:
            selected[system_id] = (span, path)
    return {system_id: value[1] for system_id, value in selected.items()}


def build_audit() -> tuple[pd.DataFrame, pd.DataFrame]:
    catalog = load_metric_catalog(METRIC_CATALOG_PATH)
    capacity_frame = pd.read_csv(CAPACITY_PATH).set_index("system_id")
    capacity_column = "dc_capacity_kW" if "dc_capacity_kW" in capacity_frame else "capacidad_instalada_kw"
    capacities = capacity_frame[capacity_column]
    rows = []
    feature_rows = []
    for system_id, path in sorted(_raw_file_by_system().items()):
        if system_id not in SYSTEM_IDS:
            continue
        raw = pd.read_csv(path)
        canonical = standardize_columns(raw, system_id, catalog)
        hourly = resample_to_hourly(canonical)
        ac = hourly["ac_power_W"].dropna()
        metric = catalog.loc[canonical["ac_power_W_metric_id"].iloc[0]]
        raw_column = next(column for column in raw.columns if column.endswith(f"__{int(metric['metric_id'])}"))
        max_raw = float(pd.to_numeric(raw[raw_column], errors="coerce").max())
        capacity_w = float(capacities.loc[system_id]) * 1000.0
        rows.append(
            {
                "system_id": system_id,
                "metric_id": int(metric["metric_id"]),
                "max_raw": max_raw,
                "raw_units": metric["raw_units"],
                "units": metric["units"],
                "calc_scale": metric["calc_scale"],
                "calc_offset": metric["calc_offset"],
                "records": int(ac.size),
                "ac_power_min_W": float(ac.min()),
                "ac_power_max_W": float(ac.max()),
                "ac_power_mean_W": float(ac.mean()),
                "ac_power_p01_W": float(ac.quantile(0.01)),
                "ac_power_p50_W": float(ac.quantile(0.50)),
                "ac_power_p99_W": float(ac.quantile(0.99)),
                "dc_capacity_kW": float(capacities.loc[system_id]),
                "max_ac_W_over_capacity_W": float(ac.max() / capacity_w),
            }
        )
        for column in ["poa_irradiance_W_m2", "ambient_temp_C"]:
            metric_id = int(canonical[f"{column}_metric_id"].iloc[0])
            feature = catalog.loc[metric_id]
            feature_rows.append(
                {
                    "system_id": system_id,
                    "feature": column,
                    "metric_id": metric_id,
                    "raw_units": feature["raw_units"],
                    "units": feature["units"],
                    "calc_scale": feature["calc_scale"],
                    "calc_offset": feature["calc_offset"],
                    "canonical_units": feature["canonical_units"],
                }
            )
    return pd.DataFrame(rows), pd.DataFrame(feature_rows)


def main() -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    audit, features = build_audit()
    audit.to_csv(REPORT_DIR / "ac_power_unit_audit.csv", index=False)
    features.to_csv(REPORT_DIR / "feature_unit_audit.csv", index=False)
    (REPORT_DIR / "summary.json").write_text(
        json.dumps(
            {
                "systems": audit["system_id"].tolist(),
                "power_canonical_units": "W",
                "feature_units": {"poa_irradiance_W_m2": "W/m^2", "ambient_temp_C": "C"},
                "source_catalog": str(METRIC_CATALOG_PATH),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(audit.to_string(index=False))
    print(f"Reports written to {REPORT_DIR}")


if __name__ == "__main__":
    main()
