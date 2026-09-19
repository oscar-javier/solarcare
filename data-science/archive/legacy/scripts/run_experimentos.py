"""Ejecución centralizada de los experimentos de regresión."""

from __future__ import annotations

import argparse
from pathlib import Path

from experiment_pipeline import DEFAULT_PREDICTORS, DEFAULT_SYSTEMS, ExperimentConfig, run_experiment_suite
from experiment_visualization import generate_all_experiment_graphs, generate_metric_comparison_plots


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ejecuta experimentos de regresión para sistemas solares.")
    parser.add_argument("--dataset", type=Path, default=Path("output/lectura_horaria.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("output/experimentos"))
    parser.add_argument("--experiment", choices=["all", "joint_normalized", "individual_normalized", "individual_power"], default="all")
    parser.add_argument("--systems", nargs="*", type=int, default=None, help="Sistema(s) a incluir; si no se pasa, usa todos.")
    parser.add_argument("--degree", type=int, default=2)
    parser.add_argument("--test-fraction", type=float, default=0.2)
    parser.add_argument("--predictors", nargs="*", default=DEFAULT_PREDICTORS)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    experiments = None if args.experiment == "all" else [args.experiment]
    config = ExperimentConfig(
        dataset_path=args.dataset,
        systems=args.systems or DEFAULT_SYSTEMS,
        predictors=args.predictors,
        degree=args.degree,
        test_fraction=args.test_fraction,
        output_dir=args.output_dir,
        plot_dir=args.output_dir / "graficos",
    )

    results = run_experiment_suite(config=config, experiments=experiments)
    output_dir = Path(config.output_dir)
    all_plots = generate_all_experiment_graphs(results["outputs"], output_dir / "graficos")
    metric_plots = generate_metric_comparison_plots(results["all_results"], output_dir / "graficos")
    print(f"Dataset validado: {results['dataset_summary']}")
    print(f"Metricas globales:")
    print(results["global_summary"].to_string(index=False))
    print(f"Graficas generadas: {len(all_plots) + len(metric_plots)}")
    print(f"Resultados guardados en: {output_dir}")


if __name__ == "__main__":
    main()
