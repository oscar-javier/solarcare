"""PVDAQ metric metadata and canonical-unit transformations."""

from __future__ import annotations

from pathlib import Path
import re
import warnings

import pandas as pd


METADATA_COLUMNS = [
    "metric_id",
    "raw_units",
    "units",
    "calc_scale",
    "calc_offset",
    "sensor_name",
    "common_name",
    "calc_details",
]


class UnitConversionError(ValueError):
    """Raised when a PVDAQ metric cannot be converted without guessing."""


def load_metric_catalog(path: str | Path) -> pd.DataFrame:
    catalog = pd.read_csv(path)
    required = set(METADATA_COLUMNS + ["calc_applies_to_exported_value", "quantity", "canonical_units"])
    missing = sorted(required - set(catalog.columns))
    if missing:
        raise ValueError(f"Metric catalog is missing columns: {missing}")
    catalog["metric_id"] = pd.to_numeric(catalog["metric_id"], errors="raise").astype(int)
    for column in ["calc_scale", "calc_offset"]:
        catalog[column] = pd.to_numeric(catalog[column], errors="raise")
    catalog["calc_applies_to_exported_value"] = (
        catalog["calc_applies_to_exported_value"].astype(str).str.strip().str.lower().eq("true")
    )
    return catalog.set_index("metric_id", drop=False)


def _unit_factor_to_canonical(raw_units: str, units: str, canonical_units: str) -> float:
    raw = str(raw_units).strip().replace("²", "^2")
    canonical = str(canonical_units).strip().replace("²", "^2")
    factors = {
        ("W", "W"): 1.0,
        ("hW", "W"): 100.0,
        ("W/m^2", "W/m^2"): 1.0,
        ("C", "C"): 1.0,
        ("F", "C"): None,
        ("kW", "W"): 1000.0,
    }
    factor = factors.get((raw, canonical))
    if factor is None and raw == "F" and canonical == "C":
        return 5.0 / 9.0
    if factor is None:
        raise UnitConversionError(
            f"Unsupported conversion raw_units={raw_units!r}, units={units!r}, "
            f"canonical_units={canonical_units!r}"
        )
    return factor


def _validate_raw_units(raw_units: str) -> None:
    supported = {"W", "hW", "kW", "W/m^2", "C", "F"}
    normalized = str(raw_units).strip().replace("²", "^2")
    if normalized not in supported:
        raise UnitConversionError(f"Unsupported raw_units={raw_units!r}")


def transform_metric_values(values: pd.Series, metadata: pd.Series) -> pd.Series:
    """Transform exported PVDAQ values to the catalog's canonical units.

    PVDAQ exports may already contain the calculated value. In that case the
    catalog records that calc_scale/calc_offset belong to the upstream raw
    sensor conversion and must not be applied a second time.
    """
    raw_units = str(metadata["raw_units"]).strip()
    canonical_units = str(metadata["canonical_units"]).strip()
    scale = float(metadata["calc_scale"])
    offset = float(metadata["calc_offset"])
    _validate_raw_units(raw_units)

    transformed = pd.to_numeric(values, errors="coerce")
    if bool(metadata["calc_applies_to_exported_value"]):
        transformed = transformed * scale + offset
    elif not str(metadata["calc_details"]).strip():
        raise UnitConversionError(
            f"metric_id={metadata['metric_id']} has calc_scale/calc_offset but no "
            "documented export semantics"
        )

    source_units = str(metadata["units"]).strip() if bool(metadata["calc_applies_to_exported_value"]) else raw_units
    factor = _unit_factor_to_canonical(source_units, str(metadata["units"]), canonical_units)
    if source_units == "F" and canonical_units == "C":
        transformed = (transformed - 32.0) * factor
    else:
        transformed = transformed * factor
    return transformed


def transform_frame_with_metadata(
    df: pd.DataFrame,
    metric_catalog: pd.DataFrame,
    system_id: int,
) -> pd.DataFrame:
    """Convert metric columns identified by ``__<metric_id>`` before resampling."""
    result = df.copy()
    metadata_by_column = {}
    for column in df.columns:
        match = re.search(r"__(\d+)$", column)
        if not match:
            continue
        metric_id = int(match.group(1))
        if metric_id not in metric_catalog.index:
            warnings.warn(
                f"No metric metadata for metric_id={metric_id}, system_id={system_id}; "
                "leaving the metric out of the canonical dataset.",
                RuntimeWarning,
            )
            continue
        metadata = metric_catalog.loc[metric_id]
        canonical = str(metadata["canonical_units"])
        quantity = str(metadata["quantity"])
        result[column] = transform_metric_values(result[column], metadata)
        result[f"{column}_canonical"] = canonical
        metadata_by_column[column] = metadata

    return result


def metric_metadata_for_column(column: str, metric_catalog: pd.DataFrame) -> pd.Series:
    match = re.search(r"__(\d+)$", column)
    if not match or int(match.group(1)) not in metric_catalog.index:
        raise UnitConversionError(f"No pvdaq_metrics metadata for column {column!r}")
    return metric_catalog.loc[int(match.group(1))]
