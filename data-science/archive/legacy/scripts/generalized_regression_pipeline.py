"""Pipeline experimental para generalización entre sistemas fotovoltaicos.

Responsabilidades:
- data loading
- data cleaning
- feature engineering
- capacity normalization
- model training
- evaluation
- weather provider adapters (preparado para Open-Meteo)
- prediction interface
- visualization

En esta etapa se mantiene la aproximación actual de PVDAQ y se prepara la
arquitectura para comparar:
- capacidad provisional: max(ac_power)
- capacidad nominal: dc_capacity (si existe)

La evaluación principal es Leave-One-System-Out (LOSO), porque es la prueba
más apropiada para estimar generalización entre sistemas diferentes.
"""

from __future__ import annotations

import argparse
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import PolynomialFeatures, StandardScaler


@dataclass
class ExperimentConfig:
    dataset_path: Path = Path("output/lectura_horaria.csv")
    capacity_path: Path = Path("capacidades_sistemas.csv")
    output_dir: Path = Path("output/generalized_experiments")
    system_ids: list[int] | None = field(default_factory=lambda: [10, 34, 1239, 1430])
    capacity_source: str = "dc_capacity"
    target_mode: str = "normalized_power"
    polynomial_degree: int = 2
    feature_set: list[str] = field(default_factory=lambda: [
        "poa_irradiance",
        "ambient_temp",
        "sin_hour",
        "cos_hour",
        "sin_day_of_year",
        "cos_day_of_year",
    ])
    random_state: int = 42
    weather_provider: str = "pvdaq"


def validate_dataset(df: pd.DataFrame, predictors: list[str]) -> tuple[pd.DataFrame, dict[str, Any]]:
    required = {"system_id", "timestamp", "ac_power", *predictors}
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(f"Faltan columnas requeridas: {missing}")

    original_rows = len(df)
    df = df.copy()
    df["system_id"] = pd.to_numeric(df["system_id"], errors="coerce")
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df["ac_power"] = pd.to_numeric(df["ac_power"], errors="coerce")
    for c in predictors:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    df = df.dropna(subset=["system_id", "timestamp", "ac_power", *predictors]).copy()
    df = df[np.isfinite(df["ac_power"]).to_numpy()]
    for c in predictors:
        df = df[np.isfinite(df[c].to_numpy())]

    if df.empty:
        raise ValueError("No quedan filas válidas después de la validación.")

    summary = {
        "rows_input": int(original_rows),
        "rows_valid": int(len(df)),
        "rows_removed": int(original_rows - len(df)),
        "systems": sorted(int(x) for x in df["system_id"].unique()),
    }
    return df, summary


def build_time_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy().sort_values(["system_id", "timestamp"]).reset_index(drop=True)
    ts = pd.to_datetime(df["timestamp"])
    hour = ts.dt.hour + ts.dt.minute / 60.0
    day_of_year = ts.dt.dayofyear
    year_days = ts.dt.is_leap_year.astype(int) + 365

    df["hour"] = hour
    df["day_of_year"] = day_of_year
    df["sin_hour"] = np.sin(2 * np.pi * hour / 24.0)
    df["cos_hour"] = np.cos(2 * np.pi * hour / 24.0)
    df["sin_day_of_year"] = np.sin(2 * np.pi * day_of_year / year_days)
    df["cos_day_of_year"] = np.cos(2 * np.pi * day_of_year / year_days)
    return df


class WeatherProvider(ABC):
    @abstractmethod
    def get_weather(self, latitude: float, longitude: float, timestamp: pd.Timestamp) -> dict[str, float]:
        pass


class PVDAQWeatherProvider(WeatherProvider):
    """Adapter para usar los datos meteorológicos ya presentes en PVDAQ durante entrenamiento."""

    def get_weather(self, latitude: float, longitude: float, timestamp: pd.Timestamp) -> dict[str, float]:
        # Este provider sirve como contrato, pero para esta fase el entrenamiento usa
        # directamente las observaciones ya cargadas del dataset PVDAQ.
        return {
            "temperature": np.nan,
            "poa_irradiance": np.nan,
            "source": "pvdaq",
        }


class OpenMeteoWeatherProvider(WeatherProvider):
    """Proveedor preparado para integración futura con Open-Meteo."""

    def __init__(self, base_url: str = "https://api.open-meteo.com/v1/forecast"):
        self.base_url = base_url

    def get_weather(self, latitude: float, longitude: float, timestamp: pd.Timestamp) -> dict[str, float]:
        raise NotImplementedError("La integración real con Open-Meteo queda preparada para una etapa posterior.")


class CapacityManager:
    """Abstracción para la capacidad: max_ac es provisional y dc_capacity es el modo nominal."""

    @staticmethod
    def load_dc_capacity(path: Path) -> dict[int, float]:
        if not path.exists():
            return {}
        cap = pd.read_csv(path)
        required = {"system_id", "dc_capacity_kW"}
        missing = required - set(cap.columns)
        if missing:
            raise ValueError(f"Faltan columnas en {path}: {sorted(missing)}")
        return {int(row.system_id): float(row.dc_capacity_kW) for row in cap.itertuples(index=False)}

    @staticmethod
    def resolve_capacity_map(df: pd.DataFrame, source: str, dc_capacity_path: Path | None = None) -> dict[int, float]:
        if source == "max_ac":
            return {int(sid): float(group["ac_power"].max()) for sid, group in df.groupby("system_id")}
        if source == "dc_capacity":
            dc_map = CapacityManager.load_dc_capacity(dc_capacity_path or Path("capacidades_sistemas.csv"))
            missing = sorted(set(df["system_id"].unique()) - set(dc_map.keys()))
            if missing:
                raise ValueError(f"No existe dc_capacity para los sistemas: {missing}")
            return {int(sid): float(dc_map[int(sid)]) for sid in sorted(df["system_id"].unique())}
        raise ValueError(f"source de capacidad no soportada: {source}")


def compute_capacity_and_target(
    df: pd.DataFrame,
    capacity_source: str,
    dc_capacity_path: Path,
    target_mode: str,
) -> pd.DataFrame:
    allowed_modes = {"normalized_power", "raw_power"}
    if target_mode not in allowed_modes:
        raise ValueError(f"target_mode no soportado: {target_mode}")

    capacity_map = CapacityManager.resolve_capacity_map(df, source=capacity_source, dc_capacity_path=dc_capacity_path)
    df = df.copy()
    df["capacity_used"] = df["system_id"].map(capacity_map)
    df["capacity_source"] = capacity_source
    if (df["capacity_used"] <= 0).any():
        offenders = df[df["capacity_used"] <= 0]["system_id"].unique().tolist()
        raise ValueError(f"Hay sistemas con capacidad <= 0: {offenders}")

    df["target_original"] = df["ac_power"]
    df["target_normalized"] = df["ac_power"] / df["capacity_used"]
    if target_mode == "normalized_power":
        df["target"] = df["target_normalized"]
    else:
        df["target"] = df["target_original"]
    return df


def make_model(predictors: list[str], degree: int = 2, with_scaler: bool = True):
    steps = []
    if with_scaler:
        steps.append(("scaler", StandardScaler()))
    steps.append(("poly", PolynomialFeatures(degree=degree, include_bias=False)))
    steps.append(("reg", LinearRegression()))
    return make_pipeline(*steps)


def fit_linear_baseline(train_df: pd.DataFrame, predictors: list[str], target_col: str) -> Any:
    model = LinearRegression()
    model.fit(train_df[predictors], train_df[target_col])
    return model


def fit_baseline_mean(train_df: pd.DataFrame, target_col: str) -> float:
    return float(train_df[target_col].mean())


def evaluate_predictions(y_true: pd.Series, y_pred: np.ndarray) -> dict[str, float]:
    y_true = pd.Series(y_true).astype(float)
    y_pred = pd.Series(y_pred).astype(float)
    return {
        "mae": float(mean_absolute_error(y_true, y_pred)),
        "rmse": float(np.sqrt(mean_squared_error(y_true, y_pred))),
        "r2": float(r2_score(y_true, y_pred)),
    }


def leave_one_system_out(
    df: pd.DataFrame,
    config: ExperimentConfig,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    records = []
    for test_system in config.system_ids or sorted(df["system_id"].unique().tolist()):
        if test_system not in df["system_id"].unique():
            continue
        train_systems = [s for s in sorted(df["system_id"].unique()) if s != test_system]
        train_df = df[df["system_id"].isin(train_systems)].copy()
        test_df = df[df["system_id"] == test_system].copy()

        if train_df.empty or test_df.empty:
            continue

        capacity_map_train = CapacityManager.resolve_capacity_map(train_df, source=config.capacity_source, dc_capacity_path=config.capacity_path)
        if config.capacity_source == "dc_capacity":
            if test_system not in capacity_map_train:
                # no se usa capacidad del test, por lo que el experimento se marca como no válido
                records.append({
                    "experiment": "leave_one_system_out",
                    "test_system": int(test_system),
                    "train_systems": train_systems,
                    "capacity_source": config.capacity_source,
                    "status": "invalid_no_dc_capacity",
                    "mae_w": np.nan,
                    "rmse_w": np.nan,
                    "r2": np.nan,
                    "nmae": np.nan,
                    "nrmse": np.nan,
                    "n_samples": int(len(test_df)),
                })
                continue

        train_df = compute_capacity_and_target(train_df, config.capacity_source, config.capacity_path, config.target_mode)
        test_df = compute_capacity_and_target(test_df, config.capacity_source, config.capacity_path, config.target_mode)

        if config.target_mode == "normalized_power":
            target_col = "target_normalized"
        else:
            target_col = "target_original"

        X_train = train_df[config.feature_set]
        y_train = train_df[target_col]
        X_test = test_df[config.feature_set]
        y_test = test_df[target_col]

        # Baseline media
        mean_pred = np.full(len(test_df), fit_baseline_mean(train_df, target_col))
        baseline_metrics = evaluate_predictions(y_test, mean_pred)

        # Lineal
        model_linear = fit_linear_baseline(train_df, config.feature_set, target_col)
        pred_linear = model_linear.predict(X_test)
        linear_metrics = evaluate_predictions(y_test, pred_linear)

        # Polinomio grado 2
        model_poly = make_pipeline(StandardScaler(), PolynomialFeatures(degree=config.polynomial_degree, include_bias=False), LinearRegression())
        model_poly.fit(X_train, y_train)
        pred_poly = model_poly.predict(X_test)
        poly_metrics = evaluate_predictions(y_test, pred_poly)

        # Reconstrucción a potencia si el target es normalizado
        if config.target_mode == "normalized_power":
            pred_poly_watts = pred_poly * test_df["capacity_used"].to_numpy()
            y_test_watts = test_df["target_original"].to_numpy()
            metrics_watts = evaluate_predictions(y_test_watts, pred_poly_watts)
        else:
            pred_poly_watts = pred_poly
            metrics_watts = evaluate_predictions(y_test, pred_poly)

        nmae = metrics_watts["mae"] / float(test_df["capacity_used"].mean()) if float(test_df["capacity_used"].mean()) > 0 else np.nan
        nrmse = metrics_watts["rmse"] / float(test_df["capacity_used"].mean()) if float(test_df["capacity_used"].mean()) > 0 else np.nan

        records.append({
            "experiment": "leave_one_system_out",
            "test_system": int(test_system),
            "train_systems": train_systems,
            "capacity_source": config.capacity_source,
            "target_mode": config.target_mode,
            "baseline_media_mae": baseline_metrics["mae"],
            "baseline_media_rmse": baseline_metrics["rmse"],
            "baseline_media_r2": baseline_metrics["r2"],
            "linear_mae": linear_metrics["mae"],
            "linear_rmse": linear_metrics["rmse"],
            "linear_r2": linear_metrics["r2"],
            "poly_mae": poly_metrics["mae"],
            "poly_rmse": poly_metrics["rmse"],
            "poly_r2": poly_metrics["r2"],
            "mae_w": metrics_watts["mae"],
            "rmse_w": metrics_watts["rmse"],
            "r2": metrics_watts["r2"],
            "nmae": nmae,
            "nrmse": nrmse,
            "n_samples": int(len(test_df)),
            "train_n": int(len(train_df)),
            "test_n": int(len(test_df)),
            "status": "ok",
        })

        pred_frame = test_df.copy()
        pred_frame["predicted_target"] = pred_poly
        pred_frame["predicted_ac_power"] = pred_poly_watts
        pred_frame["residual"] = pred_frame["target_original"] - pred_frame["predicted_ac_power"]
        pred_frame["experiment"] = "leave_one_system_out"
        pred_frame.to_csv(config.output_dir / f"pred_{test_system}.csv", index=False)

        fig, axes = plt.subplots(2, 2, figsize=(12, 10), constrained_layout=True)
        axes[0, 0].scatter(pred_frame["target_original"], pred_frame["predicted_ac_power"], alpha=0.5)
        minv = min(pred_frame["target_original"].min(), pred_frame["predicted_ac_power"].min())
        maxv = max(pred_frame["target_original"].max(), pred_frame["predicted_ac_power"].max())
        axes[0, 0].plot([minv, maxv], [minv, maxv], "r--", label="y=x")
        axes[0, 0].set_title(f"Sistema {test_system}: real vs predicha")
        axes[0, 0].set_xlabel("AC real (W)")
        axes[0, 0].set_ylabel("AC predicha (W)")
        axes[0, 0].legend()

        axes[0, 1].plot(pred_frame["timestamp"], pred_frame["target_original"], label="Real", linewidth=1.2)
        axes[0, 1].plot(pred_frame["timestamp"], pred_frame["predicted_ac_power"], label="Predicha", linewidth=1.2)
        axes[0, 1].set_title(f"Sistema {test_system}: serie temporal")
        axes[0, 1].legend()

        axes[1, 0].scatter(pred_frame["target_original"], pred_frame["residual"], alpha=0.5)
        axes[1, 0].axhline(0, color="red", linestyle="--")
        axes[1, 0].set_title("Residual vs real")
        axes[1, 0].set_xlabel("AC real")
        axes[1, 0].set_ylabel("Residual")

        axes[1, 1].scatter(pred_frame["poa_irradiance"], pred_frame["residual"], alpha=0.5)
        axes[1, 1].axhline(0, color="red", linestyle="--")
        axes[1, 1].set_title("Residual vs irradiancia")
        axes[1, 1].set_xlabel("POA irradiance")
        axes[1, 1].set_ylabel("Residual")

        fig.savefig(config.output_dir / f"plot_{test_system}.png", dpi=150)
        plt.close(fig)

    summary = pd.DataFrame(records)
    return summary, {"n_experiments": int(len(summary)), "systems": config.system_ids}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=Path("output/lectura_horaria.csv"))
    parser.add_argument("--capacity-path", type=Path, default=Path("capacidades_sistemas.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("output/generalized_experiments"))
    parser.add_argument("--capacity-source", choices=["max_ac", "dc_capacity"], default="dc_capacity")
    parser.add_argument("--target-mode", choices=["normalized_power", "raw_power"], default="normalized_power")
    parser.add_argument("--degree", type=int, default=2)
    parser.add_argument("--systems", nargs="*", type=int, default=[10, 34, 1239, 1430])
    parser.add_argument("--weather-provider", choices=["pvdaq", "openmeteo"], default="pvdaq")
    args = parser.parse_args()

    config = ExperimentConfig(
        dataset_path=args.dataset,
        capacity_path=args.capacity_path,
        output_dir=args.output_dir,
        system_ids=args.systems,
        capacity_source=args.capacity_source,
        target_mode=args.target_mode,
        polynomial_degree=args.degree,
        weather_provider=args.weather_provider,
    )

    if not config.dataset_path.exists():
        raise FileNotFoundError(f"No existe dataset: {config.dataset_path}")

    config.output_dir.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(config.dataset_path, parse_dates=["timestamp"])
    df, summary = validate_dataset(df, [
        "poa_irradiance",
        "ambient_temp",
        "sin_hora",
        "cos_hora",
        "sin_dia_anual",
        "cos_dia_anual",
    ])
    df = build_time_features(df)
    already_present = {col for col in ["sin_hour", "cos_hour", "sin_day_of_year", "cos_day_of_year"] if col in df.columns}
    if not already_present:
        df = df.rename(columns={
            "sin_hora": "sin_hour",
            "cos_hora": "cos_hour",
            "sin_dia_anual": "sin_day_of_year",
            "cos_dia_anual": "cos_day_of_year",
        })
    config.feature_set = [
        "poa_irradiance",
        "ambient_temp",
        "sin_hour",
        "cos_hour",
        "sin_day_of_year",
        "cos_day_of_year",
    ]

    results, metadata = leave_one_system_out(df, config)
    results.to_csv(config.output_dir / "leave_one_system_out_summary.csv", index=False)
    (config.output_dir / "dataset_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (config.output_dir / "experiment_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(results.to_string(index=False))
    print(f"Resultados guardados en: {config.output_dir}")


if __name__ == "__main__":
    main()
