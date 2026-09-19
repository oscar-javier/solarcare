"""Infraestructura modular para experimentos de regresión.  

Arquitectura:
- Carga y validación de datos
- División temporal por sistema
- Normalización por sistema usando solo el máximo del conjunto de entrenamiento
- Modelos polinomiales de grado 2 con LinearRegression
- Evaluación por escala (normalizada y watts)
- Resultados por sistema y comparativa global
- Generación de artefactos por experimento

NOTA IMPORTANTE SOBRE NORMALIZACIÓN:
Se calcula max_ac_power_system a partir del conjunto de entrenamiento de cada sistema
para evitar leakage. El máximo global del sistema solo se conserva como referencia
analítica, no se usa para escalar ni para entrenar.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import PolynomialFeatures

DEFAULT_PREDICTORS = [
    "poa_irradiance",
    "ambient_temp",
    "sin_hora",
    "cos_hora",
    "sin_dia_anual",
    "cos_dia_anual",
]
DEFAULT_DEGREE = 2
DEFAULT_TEST_FRACTION = 0.2
DEFAULT_RANDOM_SEED = 42
DEFAULT_SYSTEMS = [10, 34, 1239, 1430]


@dataclass
class ExperimentConfig:
    dataset_path: str | Path = "output/lectura_horaria.csv"
    systems: list[int] | None = None
    predictors: list[str] = field(default_factory=lambda: DEFAULT_PREDICTORS.copy())
    degree: int = DEFAULT_DEGREE
    test_fraction: float = DEFAULT_TEST_FRACTION
    random_seed: int = DEFAULT_RANDOM_SEED
    output_dir: str | Path = "output/experimentos"
    plot_dir: str | Path = "output/experimentos/graficos"
    min_train_rows: int = 5
    min_test_rows: int = 2

    def resolved_systems(self) -> list[int] | None:
        return list(self.systems) if self.systems is not None else None


def validate_dataset(df: pd.DataFrame, predictors: list[str] | None = None) -> dict[str, Any]:
    predictors = predictors or DEFAULT_PREDICTORS
    required = {
        "system_id",
        "timestamp",
        "ac_power",
        *predictors,
    }
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(f"Faltan columnas requeridas: {missing}")

    if df.empty:
        raise ValueError("El dataset está vacío después del preprocessing.")

    original_rows = len(df)
    df = df.copy()
    df["system_id"] = pd.to_numeric(df["system_id"], errors="coerce")
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    for col in ["ac_power", *predictors]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    before_null = len(df)
    df = df.dropna(subset=["system_id", "timestamp", "ac_power", *predictors])
    null_rows = before_null - len(df)

    # Evita columnas no finitas.
    numeric_cols = ["ac_power", *predictors]
    finite_before = len(df)
    for col in numeric_cols:
        df = df[np.isfinite(df[col].to_numpy())]
    finite_rows = finite_before - len(df)

    bad_systems = df["system_id"].isna()
    if bad_systems.any():
        raise ValueError(f"Hay system_id nulos o no numéricos: {bad_systems.sum()} registros")

    if len(df) == 0:
        raise ValueError("No quedan filas válidas después de validar tipos, nulos y valores finitos.")

    summary = {
        "rows_input": int(original_rows),
        "rows_valid": int(len(df)),
        "rows_removed_nulls": int(null_rows),
        "rows_removed_non_finite": int(finite_rows),
        "systems": sorted(int(s) for s in df["system_id"].unique()),
    }
    return summary, df


def build_temporal_split(
    df: pd.DataFrame,
    test_fraction: float = DEFAULT_TEST_FRACTION,
    min_train_rows: int = 5,
    min_test_rows: int = 2,
    seed: int | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Divide temporalmente por sistema manteniendo orden cronológico.

    Los datos más antiguos quedan en entrenamiento y los más recientes en prueba.
    El parámetro seed se acepta por compatibilidad con la API de experimentación,
    pero la estrategia es temporal y determinista, no aleatoria.
    """
    if not 0 < test_fraction < 1:
        raise ValueError(f"test_fraction debe estar entre 0 y 1, recibido: {test_fraction}")

    train_parts: list[pd.DataFrame] = []
    test_parts: list[pd.DataFrame] = []

    for _, system_df in df.sort_values(["system_id", "timestamp"]).groupby("system_id", sort=True):
        system_df = system_df.sort_values("timestamp").reset_index(drop=True)
        n_rows = len(system_df)

        effective_min_train = min(min_train_rows, max(1, n_rows - min_test_rows))
        effective_min_test = min(min_test_rows, max(1, n_rows - effective_min_train))

        if n_rows < effective_min_train + effective_min_test:
            effective_min_train = max(1, n_rows // 2)
            effective_min_test = max(1, n_rows - effective_min_train)

        cut_idx = max(effective_min_train, int(round(n_rows * (1 - test_fraction))))
        cut_idx = min(cut_idx, n_rows - effective_min_test)
        if cut_idx <= 0 or cut_idx >= n_rows:
            cut_idx = max(1, min(n_rows - 1, n_rows // 2))

        train_parts.append(system_df.iloc[:cut_idx].copy())
        test_parts.append(system_df.iloc[cut_idx:].copy())

    train_df = pd.concat(train_parts, ignore_index=True)
    test_df = pd.concat(test_parts, ignore_index=True)
    return train_df, test_df


class NormalizationResult(dict):
    """Resultado compatible con unpacking y acceso por clave."""

    def __iter__(self):
        return iter((self["train_df"], self["test_df"], self["train_max_by_system"]))


def compute_train_max_normalization(
    train_df: pd.DataFrame,
    test_df: pd.DataFrame,
    target_column: str = "ac_power",
) -> NormalizationResult:
    """Normaliza con el máximo calculado en entrenamiento por sistema.

    Se conserva el max global del sistema únicamente como metadata descriptiva y
    no se usa para la normalización del modelo.
    """
    train_max = train_df.groupby("system_id")[target_column].max()
    global_max = pd.concat([
        train_df.groupby("system_id")[target_column].max(),
        test_df.groupby("system_id")[target_column].max(),
    ], axis=1).max(axis=1)

    zero_max = train_max[train_max <= 0]
    if not zero_max.empty:
        raise ValueError(
            "No se puede normalizar porque existe un max_ac_power_system <= 0 en entrenamiento para: "
            f"{zero_max.to_dict()}"
        )

    train_df = train_df.copy()
    test_df = test_df.copy()
    train_df["max_ac_power_system"] = train_df["system_id"].map(train_max)
    test_df["max_ac_power_system"] = test_df["system_id"].map(train_max)
    train_df["global_max_ac_power_system"] = train_df["system_id"].map(global_max)
    test_df["global_max_ac_power_system"] = test_df["system_id"].map(global_max)

    train_df["ac_power_norm"] = train_df[target_column] / train_df["max_ac_power_system"]
    test_df["ac_power_norm"] = test_df[target_column] / test_df["max_ac_power_system"]

    result = NormalizationResult()
    result["train_df"] = train_df
    result["test_df"] = test_df
    result["train_max_by_system"] = train_max.to_dict()
    result["train"] = train_df
    result["test"] = test_df
    return result


def train_polynomial_model(
    train_df: pd.DataFrame,
    predictors: list[str],
    target: str,
    degree: int = DEFAULT_DEGREE,
) -> Any:
    model = make_pipeline(
        PolynomialFeatures(degree=degree, include_bias=False),
        LinearRegression(),
    )
    model.fit(train_df[predictors], train_df[target])
    return model


def evaluate_predictions(y_true: pd.Series, y_pred: np.ndarray) -> dict[str, float]:
    y_true = pd.Series(y_true).astype(float)
    y_pred = pd.Series(y_pred).astype(float)
    return {
        "mae": float(mean_absolute_error(y_true, y_pred)),
        "rmse": float(np.sqrt(mean_squared_error(y_true, y_pred))),
        "r2": float(r2_score(y_true, y_pred)),
    }


def _safe_series(values: pd.Series) -> pd.Series:
    values = pd.to_numeric(values, errors="coerce")
    return values.replace([np.inf, -np.inf], np.nan)


def _make_prediction_frame(
    system_id: int,
    train_df: pd.DataFrame,
    test_df: pd.DataFrame,
    predictor_cols: list[str],
    predicted_norm: np.ndarray,
    predicted_watts: np.ndarray,
    target_name: str,
    experiment_name: str,
) -> pd.DataFrame:
    test_frame = test_df.copy()
    test_frame["experiment"] = experiment_name
    test_frame["system_id"] = int(system_id)
    test_frame["predicted_ac_power_norm"] = pd.to_numeric(predicted_norm, errors="coerce")
    test_frame["predicted_ac_power"] = pd.to_numeric(predicted_watts, errors="coerce")
    test_frame["residual_ac_power_norm"] = test_frame["ac_power_norm"] - test_frame["predicted_ac_power_norm"]
    test_frame["residual_ac_power"] = test_frame["ac_power"] - test_frame["predicted_ac_power"]
    test_frame["n_train"] = int(len(train_df))
    test_frame["n_test"] = int(len(test_df))
    test_frame["max_ac_power"] = float(test_frame["max_ac_power_system"].iloc[0])
    test_frame["target"] = target_name
    return test_frame


def run_joint_normalized_experiment(
    df: pd.DataFrame,
    config: ExperimentConfig,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Modelo único sobre toda la muestra, normalizando por sistema con max de entrenamiento."""
    train_df, test_df = build_temporal_split(
        df,
        test_fraction=config.test_fraction,
        min_train_rows=config.min_train_rows,
        min_test_rows=config.min_test_rows,
    )
    train_df, test_df, train_max = compute_train_max_normalization(train_df, test_df, target_column="ac_power")

    model = train_polynomial_model(train_df, config.predictors, "ac_power_norm", degree=config.degree)

    pred_norm = model.predict(test_df[config.predictors])
    pred_watts = pred_norm * test_df["max_ac_power_system"].to_numpy()
    test_df = test_df.copy()
    test_df["predicted_ac_power_norm"] = pd.to_numeric(pred_norm, errors="coerce")
    test_df["predicted_ac_power"] = pd.to_numeric(pred_watts, errors="coerce")
    test_df["residual_ac_power_norm"] = test_df["ac_power_norm"] - test_df["predicted_ac_power_norm"]
    test_df["residual_ac_power"] = test_df["ac_power"] - test_df["predicted_ac_power"]
    test_df["experiment"] = "regresion_conjunta_normalizada"
    test_df["target"] = "ac_power_norm"

    result_rows = []
    for system_id in sorted(test_df["system_id"].unique()):
        system_df = test_df[test_df["system_id"] == system_id].copy()
        metric_norm = evaluate_predictions(system_df["ac_power_norm"], system_df["predicted_ac_power_norm"])
        metric_watts = evaluate_predictions(system_df["ac_power"], system_df["predicted_ac_power"])
        system_max = float(train_max.get(int(system_id), system_df["max_ac_power_system"].iloc[0]))
        result_rows.append(
            {
                "experiment": "regresion_conjunta_normalizada",
                "system_id": int(system_id),
                "target": "ac_power_norm",
                "scale": "normalized",
                "n_train": int(len(train_df[train_df["system_id"] == system_id])),
                "n_test": int(len(system_df)),
                "mae": metric_norm["mae"],
                "rmse": metric_norm["rmse"],
                "r2": metric_norm["r2"],
                "max_ac_power": system_max,
            }
        )
        result_rows.append(
            {
                "experiment": "regresion_conjunta_normalizada",
                "system_id": int(system_id),
                "target": "ac_power",
                "scale": "watts",
                "n_train": int(len(train_df[train_df["system_id"] == system_id])),
                "n_test": int(len(system_df)),
                "mae": metric_watts["mae"],
                "rmse": metric_watts["rmse"],
                "r2": metric_watts["r2"],
                "max_ac_power": system_max,
            }
        )

    summary_df = pd.DataFrame(result_rows)
    metadata = {
        "experiment": "regresion_conjunta_normalizada",
        "degree": config.degree,
        "predictors": config.predictors,
        "test_fraction": config.test_fraction,
        "train_max_used_for_normalization": train_max,
        "system_count": int(test_df["system_id"].nunique()),
        "n_train": int(len(train_df)),
        "n_test": int(len(test_df)),
    }
    return test_df, summary_df, metadata


def run_individual_normalized_experiment(
    df: pd.DataFrame,
    config: ExperimentConfig,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    predictions = []
    summary_rows = []
    metadata_rows = []

    for system_id in sorted(df["system_id"].unique()):
        if config.systems is not None and int(system_id) not in config.systems:
            continue
        system_df = df[df["system_id"] == system_id].copy().sort_values("timestamp")
        train_df, test_df = build_temporal_split(
            system_df,
            test_fraction=config.test_fraction,
            min_train_rows=config.min_train_rows,
            min_test_rows=config.min_test_rows,
        )
        train_df, test_df, train_max = compute_train_max_normalization(train_df, test_df, target_column="ac_power")

        model = train_polynomial_model(train_df, config.predictors, "ac_power_norm", degree=config.degree)
        pred_norm = model.predict(test_df[config.predictors])
        pred_watts = pred_norm * test_df["max_ac_power_system"].to_numpy()

        test_df = test_df.copy()
        test_df["experiment"] = "regresion_individual_normalizada"
        test_df["system_id"] = int(system_id)
        test_df["predicted_ac_power_norm"] = pd.to_numeric(pred_norm, errors="coerce")
        test_df["predicted_ac_power"] = pd.to_numeric(pred_watts, errors="coerce")
        test_df["residual_ac_power_norm"] = test_df["ac_power_norm"] - test_df["predicted_ac_power_norm"]
        test_df["residual_ac_power"] = test_df["ac_power"] - test_df["predicted_ac_power"]
        test_df["target"] = "ac_power_norm"
        predictions.append(test_df)

        norm_metrics = evaluate_predictions(test_df["ac_power_norm"], test_df["predicted_ac_power_norm"])
        watts_metrics = evaluate_predictions(test_df["ac_power"], test_df["predicted_ac_power"])
        system_max = float(train_max.get(int(system_id), test_df["max_ac_power_system"].iloc[0]))

        summary_rows.extend([
            {
                "experiment": "regresion_individual_normalizada",
                "system_id": int(system_id),
                "target": "ac_power_norm",
                "scale": "normalized",
                "n_train": int(len(train_df)),
                "n_test": int(len(test_df)),
                "mae": norm_metrics["mae"],
                "rmse": norm_metrics["rmse"],
                "r2": norm_metrics["r2"],
                "max_ac_power": system_max,
            },
            {
                "experiment": "regresion_individual_normalizada",
                "system_id": int(system_id),
                "target": "ac_power",
                "scale": "watts",
                "n_train": int(len(train_df)),
                "n_test": int(len(test_df)),
                "mae": watts_metrics["mae"],
                "rmse": watts_metrics["rmse"],
                "r2": watts_metrics["r2"],
                "max_ac_power": system_max,
            },
        ])
        metadata_rows.append(
            {
                "experiment": "regresion_individual_normalizada",
                "system_id": int(system_id),
                "degree": config.degree,
                "predictors": config.predictors,
                "train_max_ac_power": system_max,
                "n_train": int(len(train_df)),
                "n_test": int(len(test_df)),
            }
        )

    pred_all = pd.concat(predictions, ignore_index=True) if predictions else pd.DataFrame()
    summary_df = pd.DataFrame(summary_rows)
    metadata = {"experiment": "regresion_individual_normalizada", "models": metadata_rows}
    return pred_all, summary_df, metadata


def run_individual_power_experiment(
    df: pd.DataFrame,
    config: ExperimentConfig,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    predictions = []
    summary_rows = []
    metadata_rows = []

    for system_id in sorted(df["system_id"].unique()):
        if config.systems is not None and int(system_id) not in config.systems:
            continue
        system_df = df[df["system_id"] == system_id].copy().sort_values("timestamp")
        train_df, test_df = build_temporal_split(
            system_df,
            test_fraction=config.test_fraction,
            min_train_rows=config.min_train_rows,
            min_test_rows=config.min_test_rows,
        )
        model = train_polynomial_model(train_df, config.predictors, "ac_power", degree=config.degree)
        pred_watts = model.predict(test_df[config.predictors])

        test_df = test_df.copy()
        test_df["experiment"] = "regresion_individual_ac_power"
        test_df["system_id"] = int(system_id)
        test_df["predicted_ac_power"] = pd.to_numeric(pred_watts, errors="coerce")
        test_df["residual_ac_power"] = test_df["ac_power"] - test_df["predicted_ac_power"]
        test_df["target"] = "ac_power"
        predictions.append(test_df)

        metrics = evaluate_predictions(test_df["ac_power"], test_df["predicted_ac_power"])
        summary_rows.append(
            {
                "experiment": "regresion_individual_ac_power",
                "system_id": int(system_id),
                "target": "ac_power",
                "scale": "watts",
                "n_train": int(len(train_df)),
                "n_test": int(len(test_df)),
                "mae": metrics["mae"],
                "rmse": metrics["rmse"],
                "r2": metrics["r2"],
                "max_ac_power": float(test_df["ac_power"].max()),
            }
        )
        metadata_rows.append(
            {
                "experiment": "regresion_individual_ac_power",
                "system_id": int(system_id),
                "degree": config.degree,
                "predictors": config.predictors,
                "n_train": int(len(train_df)),
                "n_test": int(len(test_df)),
            }
        )

    pred_all = pd.concat(predictions, ignore_index=True) if predictions else pd.DataFrame()
    summary_df = pd.DataFrame(summary_rows)
    metadata = {"experiment": "regresion_individual_ac_power", "models": metadata_rows}
    return pred_all, summary_df, metadata


def run_experiment_name(
    experiment_name: str,
    df: pd.DataFrame,
    config: ExperimentConfig,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    if experiment_name == "joint_normalized":
        return run_joint_normalized_experiment(df, config)
    if experiment_name == "individual_normalized":
        return run_individual_normalized_experiment(df, config)
    if experiment_name == "individual_power":
        return run_individual_power_experiment(df, config)
    raise ValueError(f"Experimento no soportado: {experiment_name}")


def compare_experiments(summary_frames: list[pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame]:
    merged = pd.concat(summary_frames, ignore_index=True)
    if merged.empty:
        return pd.DataFrame(), pd.DataFrame()

    global_summary = (
        merged.groupby(["experiment", "scale"], as_index=False)
        .agg(
            mae=("mae", "mean"),
            rmse=("rmse", "mean"),
            r2=("r2", "mean"),
            systems=("system_id", "nunique"),
        )
        .sort_values(["experiment", "scale"])
        .reset_index(drop=True)
    )
    per_system = merged[["system_id", "experiment", "scale", "mae", "rmse", "r2"]].copy()
    per_system = per_system.sort_values(["system_id", "experiment", "scale"]).reset_index(drop=True)
    return global_summary, per_system


def save_results_csv(path: Path, df: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def save_metadata_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def run_experiment_suite(
    config: ExperimentConfig,
    experiments: list[str] | None = None,
    dataset_path: str | Path | None = None,
) -> dict[str, Any]:
    dataset_path = Path(dataset_path) if dataset_path is not None else Path(config.dataset_path)
    df = pd.read_csv(dataset_path, parse_dates=["timestamp"])
    summary, df_valid = validate_dataset(df, predictors=config.predictors)
    if config.systems is not None:
        df_valid = df_valid[df_valid["system_id"].isin(config.systems)].copy()
        summary = {
            **summary,
            "systems": sorted(int(s) for s in df_valid["system_id"].unique()),
            "rows_valid": int(len(df_valid)),
            "rows_input": int(len(df)),
        }
    results = []
    metrics_by_experiment = []
    outputs = {}

    selected = experiments or ["joint_normalized", "individual_normalized", "individual_power"]
    for experiment_name in selected:
        predictions_df, summary_df, metadata = run_experiment_name(experiment_name, df_valid, config)
        outputs[experiment_name] = {"predictions": predictions_df, "summary": summary_df, "metadata": metadata}
        metrics_by_experiment.append(summary_df)
        results.append(summary_df)

    all_summary = pd.concat(results, ignore_index=True) if results else pd.DataFrame()
    global_summary, per_system_summary = compare_experiments(metrics_by_experiment)

    output_dir = Path(config.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    save_results_csv(output_dir / "resultados_por_sistema.csv", all_summary)
    save_results_csv(output_dir / "comparacion_global.csv", global_summary)
    save_results_csv(output_dir / "comparacion_por_sistema.csv", per_system_summary)
    save_metadata_json(output_dir / "metadata_ejecucion.json", {
        "summary": summary,
        "config": {
            "predictors": config.predictors,
            "degree": config.degree,
            "test_fraction": config.test_fraction,
            "systems": config.systems,
            "dataset_path": str(dataset_path),
            "output_dir": str(output_dir),
        },
        "experiments": {
            name: {
                key: value
                for key, value in meta.get("metadata", {}).items()
                if isinstance(value, (dict, list, str, int, float, bool, type(None)))
            }
            for name, meta in outputs.items()
            if meta.get("metadata")
        },
    })

    for experiment_name, payload in outputs.items():
        experiment_dir = output_dir / experiment_name
        experiment_dir.mkdir(parents=True, exist_ok=True)
        if not payload["predictions"].empty:
            save_results_csv(experiment_dir / "predicciones.csv", payload["predictions"])
        if not payload["summary"].empty:
            save_results_csv(experiment_dir / "metricas.csv", payload["summary"])
        save_metadata_json(experiment_dir / "metadata.json", payload["metadata"])

    return {
        "dataset_summary": summary,
        "all_results": all_summary,
        "global_summary": global_summary,
        "per_system_summary": per_system_summary,
        "outputs": outputs,
    }
