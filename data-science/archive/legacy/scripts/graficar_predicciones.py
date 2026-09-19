"""Grafica predicciones de regresion contra valores reales."""

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


REQUIRED_COLUMNS = {
    "system_id",
    "timestamp",
    "ac_power",
    "ac_power_predicha",
    "eficiencia",
    "eficiencia_predicha",
}


def validar_columnas(datos):
    faltantes = REQUIRED_COLUMNS - set(datos.columns)
    if faltantes:
        raise ValueError(f"Faltan columnas: {sorted(faltantes)}")


def graficar_general(datos, salida):
    figura, ejes = plt.subplots(3, 1, figsize=(15, 13), constrained_layout=True)
    ejes[0].plot(datos["timestamp"], datos["ac_power"], label="Real", linewidth=1)
    ejes[0].plot(datos["timestamp"], datos["ac_power_predicha"], label="Predicha", linewidth=1)
    ejes[0].set_title("Potencia AC real contra predicha")
    ejes[0].set_ylabel("AC power")
    ejes[0].legend()
    ejes[0].grid(alpha=0.3)

    ejes[1].scatter(datos["ac_power"], datos["ac_power_predicha"], s=8, alpha=0.35)
    limites = [
        min(datos["ac_power"].min(), datos["ac_power_predicha"].min()),
        max(datos["ac_power"].max(), datos["ac_power_predicha"].max()),
    ]
    ejes[1].plot(limites, limites, "r--", label="Prediccion perfecta")
    ejes[1].set_title("Real contra predicha")
    ejes[1].set_xlabel("AC power real")
    ejes[1].set_ylabel("AC power predicha")
    ejes[1].legend()
    ejes[1].grid(alpha=0.3)

    residuos = datos["ac_power"] - datos["ac_power_predicha"]
    ejes[2].scatter(datos["timestamp"], residuos, s=8, alpha=0.35)
    ejes[2].axhline(0, color="red", linestyle="--")
    ejes[2].set_title("Residuos")
    ejes[2].set_xlabel("Tiempo")
    ejes[2].set_ylabel("Real - predicha")
    ejes[2].grid(alpha=0.3)
    figura.savefig(salida, dpi=150)
    plt.close(figura)


def graficar_por_sistema(datos, salida):
    sistemas = sorted(datos["system_id"].unique())
    figura, ejes = plt.subplots(len(sistemas), 1, figsize=(15, max(4, 4 * len(sistemas))), squeeze=False, constrained_layout=True)
    for indice, system_id in enumerate(sistemas):
        eje = ejes[indice, 0]
        sistema = datos[datos["system_id"] == system_id]
        eje.plot(sistema["timestamp"], sistema["ac_power"], label="Real", linewidth=1)
        eje.plot(sistema["timestamp"], sistema["ac_power_predicha"], label="Predicha", linewidth=1)
        eje.set_title(f"Sistema {system_id}")
        eje.set_ylabel("AC power")
        eje.legend()
        eje.grid(alpha=0.3)
    ejes[-1, 0].set_xlabel("Tiempo")
    figura.savefig(salida, dpi=150)
    plt.close(figura)


def graficar_archivos_individuales(datos, directorio):
    directorio.mkdir(parents=True, exist_ok=True)
    for system_id in sorted(datos["system_id"].unique()):
        sistema = datos[datos["system_id"] == system_id]
        figura, eje = plt.subplots(figsize=(15, 5), constrained_layout=True)
        eje.plot(sistema["timestamp"], sistema["ac_power"], label="Real", linewidth=1)
        eje.plot(
            sistema["timestamp"],
            sistema["ac_power_predicha"],
            label="Predicha",
            linewidth=1,
        )
        eje.set_title(f"Sistema {system_id}: potencia AC real contra predicha")
        eje.set_xlabel("Tiempo")
        eje.set_ylabel("AC power")
        eje.legend()
        eje.grid(alpha=0.3)
        figura.savefig(directorio / f"sistema_{system_id}_real_vs_predicha.png", dpi=150)
        plt.close(figura)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entrada", type=Path, default=Path("output/predicciones_regresion.csv"))
    parser.add_argument("--salida", type=Path, default=Path("output"))
    args = parser.parse_args()
    datos = pd.read_csv(args.entrada, parse_dates=["timestamp"])
    validar_columnas(datos)
    datos = datos.sort_values(["system_id", "timestamp"])
    args.salida.mkdir(parents=True, exist_ok=True)
    graficar_general(datos, args.salida / "grafica_predicciones.png")
    graficar_por_sistema(datos, args.salida / "graficas_predicciones_por_sistema.png")
    graficar_archivos_individuales(datos, args.salida / "predicciones_por_sistema")
    print(f"Grafica general -> {args.salida / 'grafica_predicciones.png'}")
    print(f"Graficas por sistema -> {args.salida / 'graficas_predicciones_por_sistema.png'}")
    print(f"Graficas individuales -> {args.salida / 'predicciones_por_sistema'}")


if __name__ == "__main__":
    main()