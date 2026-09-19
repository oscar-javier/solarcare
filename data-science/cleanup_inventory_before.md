# Cleanup inventory before archiving

## Retain: production and retraining

- `production_pv_pipeline.py`
- `production_train.py`
- `production_preflight.py`
- `production_diagnostics.py`
- `predict_pv_power_cli.py`
- `final_pv_pipeline.py`
- `system_configurations.csv` and `system_configurations.template.csv`
- `extract.py`, `transform_load.py`, `config.py`, `pvdaq_units.py`, `pvdaq_metrics.csv`
- `capacidades_sistemas.csv`, `requirements.txt`, `models/production_model.joblib`, and its metadata
- `output/lectura_horaria.csv`, raw PVDAQ inputs, and `output/weather_cache/`

## Retain: tests and traceability

- `tests/`
- `experiment_pipeline.py` (imported by `tests/test_experiment_pipeline.py`)
- `results/production_model/`
- legacy metrics, reports, model artifacts, and `backup.dump` needed for comparison or recovery

The active `models/` directory now contains only `production_model.joblib` and
`production_model_metadata.json`. The former `final_model.joblib` and metadata were moved to
`archive/legacy/models/`; they are not loaded by the application.

## Archive: experiment-only scripts

These scripts are not imported by the production or test paths and implement superseded model families
or exploratory diagnostics: `audit_units.py`, `clean_experiment_data.py`,
`experiment_visualization.py`, `feature_ablation_diagnostics.py`, `generalization_diagnostics.py`,
`generalized_regression_pipeline.py`, `graficar_predicciones.py`, `regresion_potencia.py`, and
`run_experimentos.py`.

## Archive: regenerable experiment outputs

- `output/experimentos/`
- `output/final_pipeline/`
- `output/generalized_model/`
- `output/predicciones_por_sistema/`
- `output/weather_cache_test/`
- `results/baseline_dc_capacity_before_official_capacities/`
- `results/diagnostics/`
- `results/final_model/`
- `results/generalized_model/`
- `results/predicciones_por_sistema/`
- `output/unit_audit/`

No production model, official metadata, required input dataset, test, dependency file, or historical
comparison artifact is deleted.