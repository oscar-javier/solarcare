import json
from pathlib import Path

import pandas as pd

from final_pv_pipeline import build_feature_frame, create_final_model, load_system_capacities


def test_build_feature_frame_has_required_columns():
    row = build_feature_frame(
        timestamp="2024-01-15 13:00:00",
        latitude=39.74,
        longitude=-105.18,
        elevation=1792.8,
        temperature_c=22.5,
        irradiance_wm2=850.0,
        capacity_kW=1.12,
    )

    expected = {
        "latitude",
        "longitude",
        "elevation",
        "poa_irradiance_W_m2",
        "ambient_temp_C",
        "sin_hour",
        "cos_hour",
        "sin_day_of_year",
        "cos_day_of_year",
    }
    expected.issubset(set(row.columns))
    assert row["poa_irradiance_W_m2"].iloc[0] == 850.0


def test_load_system_capacities_reads_project_capacity_file():
    capacities = load_system_capacities(Path("capacidades_sistemas.csv"))
    assert 10 in capacities
    assert 34 in capacities
    assert 1239 in capacities
    assert 1430 in capacities
    assert capacities == {10: 1.12, 34: 146.64, 1239: 20.16, 1430: 720.72}


def test_create_final_model_writes_metadata(tmp_path):
    model_path = tmp_path / "final_model.joblib"
    meta_path = tmp_path / "final_model_metadata.json"
    model = create_final_model(
        dataset_path=Path("output/lectura_horaria.csv"),
        capacity_path=Path("capacidades_sistemas.csv"),
        model_path=model_path,
        metadata_path=meta_path,
        systems=[10, 34],
    )

    assert model_path.exists()
    assert meta_path.exists()
    payload = json.loads(meta_path.read_text(encoding="utf-8"))
    assert payload["target"] == "normalized_power"
    assert payload["capacity_source"] == "dc_capacity"
