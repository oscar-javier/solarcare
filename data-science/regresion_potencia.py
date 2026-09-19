"""Entrena una regresion polinomica global para potencia normalizada.

Objetivo:
    eficiencia = ac_power / capacidad_instalada

Predictores:
    irradiancia POA, temperatura ambiente y funciones ciclicas del tiempo.

El CSV horario no contiene la capacidad instalada, por lo que se recibe desde
un CSV separado con columnas ``system_id,capacidad_instalada_kw``.
"""

import argparse
import json
from pathlib import Path

import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_squared_error, r2_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import PolynomialFeatures, StandardScaler


PREDICTORS = [
    "poa_irradiance",
    "ambient_temp",
    "sin_hora",
    "cos_hora",
    "sin_dia_anual",
    "cos_dia_anual",
]
TARGET = "eficiencia"


def cargar_capacidades(path: Path) -> dict[int, float]:
    capacidades = pd.read_csv(path)
    required = {"system_id", "capacidad_instalada_kw"}
    missing = required - set(capacidades.columns)
    if missing:
        raise ValueError(f"Faltan columnas en {path}: {sorted(missing)}")
    return {
        int(row.system_id): float(row.capacidad_instalada_kw)
        for row in capacidades.itertuples(index=False)
    }


def preparar_datos(csv_path: Path, capacidades_path: Path) -> pd.DataFrame:
    datos = pd.read_csv(csv_path, parse_dates=["timestamp"])
    capacidades = cargar_capacidades(capacidades_path)
    datos["capacidad_instalada_kw"] = datos["system_id"].map(capacidades)

    required = {"system_id", "timestamp", "ac_power", *PREDICTORS}
    missing = required - set(datos.columns)
    if missing:
        raise ValueError(f"Faltan columnas en {csv_path}: {sorted(missing)}")

    datos = datos.dropna(subset=["ac_power", *PREDICTORS, "capacidad_instalada_kw"])
    datos = datos[datos["capacidad_instalada_kw"] > 0].copy()
    datos[TARGET] = datos["ac_power"] / datos["capacidad_instalada_kw"]
    return datos


def separar_temporalmente(datos: pd.DataFrame, proporcion_prueba: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    entrenamiento = []
    prueba = []
    for _, sistema in datos.sort_values("timestamp").groupby("system_id"):
        indice_prueba = int(len(sistema) * (1 - proporcion_prueba))
        if indice_prueba <= 0 or indice_prueba >= len(sistema):
            raise ValueError("La proporcion de prueba deja un conjunto vacio")
        entrenamiento.append(sistema.iloc[:indice_prueba])
        prueba.append(sistema.iloc[indice_prueba:])
    return (
        pd.concat(entrenamiento, ignore_index=True),
        pd.concat(prueba, ignore_index=True),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=Path("output/lectura_horaria.csv"))
    parser.add_argument("--capacidades", type=Path, required=True)
    parser.add_argument("--salida", type=Path, default=Path("output"))
    parser.add_argument("--prueba", type=float, default=0.2)
    args = parser.parse_args()

    datos = preparar_datos(args.csv, args.capacidades)
    entrenamiento, prueba = separar_temporalmente(datos, args.prueba)

    modelo = make_pipeline(
        StandardScaler(),
        PolynomialFeatures(degree=2, include_bias=False),
        LinearRegression(),
    )
    modelo.fit(entrenamiento[PREDICTORS], entrenamiento[TARGET])

    eficiencia_predicha = modelo.predict(prueba[PREDICTORS])
    prueba = prueba.copy()
    prueba["eficiencia_predicha"] = eficiencia_predicha
    prueba["ac_power_predicha"] = (
        eficiencia_predicha * prueba["capacidad_instalada_kw"]
    )

    metricas = {
        "modelo": "regresion_lineal_multivariante_grado_2",
        "objetivo": TARGET,
        "predictores": PREDICTORS,
        "registros": int(len(datos)),
        "entrenamiento": int(len(entrenamiento)),
        "prueba": int(len(prueba)),
        "r2": float(r2_score(prueba[TARGET], eficiencia_predicha)),
        "rmse_eficiencia": float(mean_squared_error(prueba[TARGET], eficiencia_predicha) ** 0.5),
        "rmse_ac_power": float(
            mean_squared_error(prueba["ac_power"], prueba["ac_power_predicha"]) ** 0.5
        ),
    }

    args.salida.mkdir(parents=True, exist_ok=True)
    prueba.to_csv(args.salida / "predicciones_regresion.csv", index=False)
    (args.salida / "metricas_regresion.json").write_text(
        json.dumps(metricas, indent=2), encoding="utf-8"
    )
    print(json.dumps(metricas, indent=2))


if __name__ == "__main__":
    main()