"""Visualización para experimentos de regresión.  

Genera gráficos scatter, serie temporal y residuales por experimento/sistema,
además de comparativas de métricas por sistema.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def plot_real_vs_predicted_scatter(
    df: pd.DataFrame,
    real_col: str,
    pred_col: str,
    output_path: Path,
    title: str,
    xlabel: str,
    ylabel: str,
) -> None:
    _ensure_dir(output_path.parent)
    fig, ax = plt.subplots(figsize=(7, 7), constrained_layout=True)
    ax.scatter(df[real_col], df[pred_col], alpha=0.6, s=18)
    min_val = min(df[real_col].min(), df[pred_col].min())
    max_val = max(df[real_col].max(), df[pred_col].max())
    if pd.notna(min_val) and pd.notna(max_val):
        ax.plot([min_val, max_val], [min_val, max_val], "r--", label="y = x")
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.grid(alpha=0.25)
    ax.legend()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def plot_time_series(
    df: pd.DataFrame,
    real_col: str,
    pred_col: str,
    output_path: Path,
    title: str,
    xlabel: str,
    ylabel: str,
) -> None:
    _ensure_dir(output_path.parent)
    fig, ax = plt.subplots(figsize=(14, 5), constrained_layout=True)
    ax.plot(df["timestamp"], df[real_col], label="Real", linewidth=1.4)
    ax.plot(df["timestamp"], df[pred_col], label="Predicha", linewidth=1.2)
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.grid(alpha=0.25)
    ax.legend()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def plot_residuals(
    df: pd.DataFrame,
    residual_col: str,
    output_path: Path,
    title: str,
) -> None:
    _ensure_dir(output_path.parent)
    fig, ax = plt.subplots(figsize=(14, 4), constrained_layout=True)
    ax.scatter(df["timestamp"], df[residual_col], s=12, alpha=0.6)
    ax.axhline(0, color="red", linestyle="--")
    ax.set_title(title)
    ax.set_xlabel("timestamp")
    ax.set_ylabel("Residual")
    ax.grid(alpha=0.25)
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def generate_experiment_plots_for_predictions(
    predictions_df: pd.DataFrame,
    output_dir: Path,
    experiment_name: str,
) -> list[Path]:
    if predictions_df.empty:
        return []

    output_dir = Path(output_dir) / experiment_name
    _ensure_dir(output_dir)
    created: list[Path] = []

    for system_id in sorted(predictions_df["system_id"].dropna().unique()):
        system_df = predictions_df[predictions_df["system_id"] == system_id].sort_values("timestamp")
        if system_df.empty:
            continue

        if {"ac_power_norm", "predicted_ac_power_norm"}.issubset(system_df.columns):
            scatter_norm = output_dir / f"sistema_{int(system_id)}_scatter_normalizado.png"
            plot_real_vs_predicted_scatter(
                system_df,
                "ac_power_norm",
                "predicted_ac_power_norm",
                scatter_norm,
                f"{experiment_name} · Sistema {int(system_id)} · Normalizado",
                "Valor real (normalizado)",
                "Valor predicho (normalizado)",
            )
            created.append(scatter_norm)

            series_norm = output_dir / f"sistema_{int(system_id)}_serie_normalizada.png"
            plot_time_series(
                system_df,
                "ac_power_norm",
                "predicted_ac_power_norm",
                series_norm,
                f"{experiment_name} · Sistema {int(system_id)} · Serie temporal normalizada",
                "timestamp",
                "ac_power_norm",
            )
            created.append(series_norm)

            residual_norm = output_dir / f"sistema_{int(system_id)}_residual_normalizado.png"
            plot_residuals(system_df, "residual_ac_power_norm", residual_norm, f"Residual normalizado · Sistema {int(system_id)}")
            created.append(residual_norm)

        if {"ac_power", "predicted_ac_power"}.issubset(system_df.columns):
            scatter_watts = output_dir / f"sistema_{int(system_id)}_scatter_watts.png"
            plot_real_vs_predicted_scatter(
                system_df,
                "ac_power",
                "predicted_ac_power",
                scatter_watts,
                f"{experiment_name} · Sistema {int(system_id)} · Watts",
                "AC power real (W)",
                "AC power predicha (W)",
            )
            created.append(scatter_watts)

            series_watts = output_dir / f"sistema_{int(system_id)}_serie_watts.png"
            plot_time_series(
                system_df,
                "ac_power",
                "predicted_ac_power",
                series_watts,
                f"{experiment_name} · Sistema {int(system_id)} · Serie temporal en watts",
                "timestamp",
                "ac_power (W)",
            )
            created.append(series_watts)

            residual_watts = output_dir / f"sistema_{int(system_id)}_residual_watts.png"
            plot_residuals(system_df, "residual_ac_power", residual_watts, f"Residual en watts · Sistema {int(system_id)}")
            created.append(residual_watts)

    return created


def generate_metric_comparison_plots(results_df: pd.DataFrame, output_dir: Path) -> list[Path]:
    output_dir = Path(output_dir)
    _ensure_dir(output_dir)
    created: list[Path] = []

    if results_df.empty:
        return created

    watts_df = results_df[results_df["scale"] == "watts"].copy()
    if not watts_df.empty:
        fig, axes = plt.subplots(3, 1, figsize=(14, 12), constrained_layout=True)
        for ax, metric in zip(axes, ["mae", "rmse", "r2"]):
            pivot = watts_df.pivot_table(index="system_id", columns="experiment", values=metric, aggfunc="mean")
            pivot.plot(kind="bar", ax=ax, legend=True)
            ax.set_title(f"Comparación de {metric.upper()} por sistema (watts)")
            ax.set_ylabel(metric.upper())
            ax.grid(alpha=0.25)
        fig.savefig(output_dir / "comparacion_metricas_watts.png", dpi=150)
        plt.close(fig)
        created.append(output_dir / "comparacion_metricas_watts.png")

    normalized_df = results_df[results_df["scale"] == "normalized"].copy()
    if not normalized_df.empty:
        fig, axes = plt.subplots(3, 1, figsize=(14, 12), constrained_layout=True)
        for ax, metric in zip(axes, ["mae", "rmse", "r2"]):
            pivot = normalized_df.pivot_table(index="system_id", columns="experiment", values=metric, aggfunc="mean")
            pivot.plot(kind="bar", ax=ax, legend=True)
            ax.set_title(f"Comparación de {metric.upper()} por sistema (normalizado)")
            ax.set_ylabel(metric.upper())
            ax.grid(alpha=0.25)
        fig.savefig(output_dir / "comparacion_metricas_normalizadas.png", dpi=150)
        plt.close(fig)
        created.append(output_dir / "comparacion_metricas_normalizadas.png")

    return created


def generate_all_experiment_graphs(
    outputs: dict[str, dict[str, pd.DataFrame]],
    output_dir: Path,
) -> list[Path]:
    output_dir = Path(output_dir)
    _ensure_dir(output_dir)
    created: list[Path] = []
    for experiment_name, payload in outputs.items():
        predictions = payload.get("predictions")
        if predictions is None or predictions.empty:
            continue
        created.extend(generate_experiment_plots_for_predictions(predictions, output_dir, experiment_name))
    return created
