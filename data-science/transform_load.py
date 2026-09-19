"""
transform_load.py
Paso 2 del nuevo ETL horario para SolarCare.

Qué hace:
  1. Lee los CSV crudos filtrados (output/raw_<system_id>.csv) generados
     por extract.py.
  2. Renombra las columnas propias de cada sistema a un esquema estándar,
     usando COLUMN_MAP de config.py.
  3. Resamplea de la resolución cruda (~15 min) a EXACTAMENTE 1 fila por
     hora, promediando las lecturas dentro de cada hora. Esto reduce el
     volumen ~4x adicional sobre el filtro de horario ya aplicado.
  4. Carga el resultado a la tabla analítica en Postgres (idempotente:
     borra el rango year/month/system_id antes de insertar, igual que
     hace simular-dia con las lecturas simuladas).
"""

import glob
import math
import os
import re

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

from config import (
    COLUMN_MAP,
    RAW_TIMESTAMP_COL,
    OUTPUT_DIR,
    DB_CONFIG,
    ANALYTICS_TABLE,
    YEAR_START,
    YEAR_END,
    DATABASE_URL,
)

STANDARD_COLUMNS = ["ac_power", "poa_irradiance", "ambient_temp"]
TIME_FEATURE_COLUMNS = ["sin_hora", "cos_hora", "sin_dia_anual", "cos_dia_anual"]


def standardize_columns(df: pd.DataFrame, system_id: int) -> pd.DataFrame:
    mapping = COLUMN_MAP.get(system_id)
    if mapping is None:
        raise KeyError(
            f"No hay COLUMN_MAP definido para system_id={system_id} en config.py"
        )

    missing = [raw_col for raw_col in mapping.values() if raw_col not in df.columns]
    if missing:
        raise KeyError(
            f"[system {system_id}] columnas esperadas no encontradas: {missing}. "
            f"Vuelve a correr inspect_columns.py, los nombres pudieron cambiar."
        )

    rename_map = {raw_col: std_col for std_col, raw_col in mapping.items()}
    df = df.rename(columns=rename_map)

    keep_cols = [RAW_TIMESTAMP_COL, "system_id"] + [
        c for c in STANDARD_COLUMNS if c in df.columns
    ]
    return df[keep_cols]


def resample_to_hourly(df: pd.DataFrame) -> pd.DataFrame:
    """Colapsa lecturas de ~15 min a 1 fila por hora (promedio)."""
    df[RAW_TIMESTAMP_COL] = pd.to_datetime(df[RAW_TIMESTAMP_COL])
    df = df.set_index(RAW_TIMESTAMP_COL)

    numeric_cols = [c for c in STANDARD_COLUMNS if c in df.columns]

    hourly = (
        df.groupby("system_id")[numeric_cols]
        .resample("1h")
        .mean()
        .dropna(how="all")
        .reset_index()
    )
    hourly = hourly.rename(columns={RAW_TIMESTAMP_COL: "timestamp"})

    timestamps = pd.to_datetime(hourly["timestamp"])
    hora_decimal = timestamps.dt.hour + timestamps.dt.minute / 60
    dia_del_año = timestamps.dt.dayofyear
    dias_del_año = timestamps.dt.is_leap_year.astype(int) + 365
    hourly["sin_hora"] = (hora_decimal * 2 * math.pi / 24).map(math.sin)
    hourly["cos_hora"] = (hora_decimal * 2 * math.pi / 24).map(math.cos)
    hourly["sin_dia_anual"] = (dia_del_año * 2 * math.pi / dias_del_año).map(math.sin)
    hourly["cos_dia_anual"] = (dia_del_año * 2 * math.pi / dias_del_año).map(math.cos)
    return hourly


def load_to_postgres(df: pd.DataFrame):
    if df.empty:
        print("Nada que cargar (dataframe vacío).")
        return

    conn = psycopg2.connect(DATABASE_URL) if DATABASE_URL else psycopg2.connect(**DB_CONFIG)
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS {ANALYTICS_TABLE} (
                    system_id INTEGER NOT NULL,
                    timestamp TIMESTAMP NOT NULL,
                    ac_power DOUBLE PRECISION,
                    poa_irradiance DOUBLE PRECISION,
                    ambient_temp DOUBLE PRECISION,
                    sin_hora DOUBLE PRECISION,
                    cos_hora DOUBLE PRECISION,
                    sin_dia_anual DOUBLE PRECISION,
                    cos_dia_anual DOUBLE PRECISION,
                    PRIMARY KEY (system_id, timestamp)
                );
            """)

            for column in TIME_FEATURE_COLUMNS:
                cur.execute(
                    f"ALTER TABLE {ANALYTICS_TABLE} "
                    f"ADD COLUMN IF NOT EXISTS {column} DOUBLE PRECISION"
                )

            # Idempotencia: reemplaza el rango temporal de cada sistema.
            for system_id, system_df in df.groupby("system_id"):
                cur.execute(
                    f"""
                    DELETE FROM {ANALYTICS_TABLE}
                    WHERE system_id = %s
                      AND timestamp BETWEEN %s AND %s
                    """,
                    (
                        int(system_id),
                        system_df["timestamp"].min(),
                        system_df["timestamp"].max(),
                    ),
                )

            rows = [
                (
                    int(r.system_id),
                    r.timestamp,
                    r.ac_power if "ac_power" in df.columns else None,
                    r.poa_irradiance if "poa_irradiance" in df.columns else None,
                    r.ambient_temp if "ambient_temp" in df.columns else None,
                    r.sin_hora,
                    r.cos_hora,
                    r.sin_dia_anual,
                    r.cos_dia_anual,
                )
                for r in df.itertuples(index=False)
            ]

            execute_values(
                cur,
                f"""
                INSERT INTO {ANALYTICS_TABLE}
                    (system_id, timestamp, ac_power, poa_irradiance, ambient_temp,
                     sin_hora, cos_hora, sin_dia_anual, cos_dia_anual)
                VALUES %s
                """,
                rows,
            )
        conn.commit()
        print(f"Cargadas {len(rows)} filas horarias en '{ANALYTICS_TABLE}'.")
    finally:
        conn.close()


def main():
    raw_pattern = os.path.join(OUTPUT_DIR, "raw_*_????_????.csv")
    raw_files = sorted(glob.glob(raw_pattern))
    if not raw_files:
        print("No hay archivos raw_*.csv. Corre extract.py primero.")
        return

    # Usa el archivo de rango más amplio cuando hay extracciones parciales
    # antiguas del mismo sistema.
    files_by_system = {}
    for path in raw_files:
        match = re.fullmatch(r"raw_(\d+)_(\d{4})_(\d{4})\.csv", os.path.basename(path))
        if not match:
            print(f"Ignorando archivo con nombre no reconocido: {path}")
            continue
        system_id = int(match.group(1))
        span = int(match.group(3)) - int(match.group(2))
        current = files_by_system.get(system_id)
        if current is None or span > current[0]:
            files_by_system[system_id] = (span, path)

    all_hourly = []
    for system_id, (_, path) in sorted(files_by_system.items()):
        df = pd.read_csv(path)

        df = standardize_columns(df, system_id)
        hourly = resample_to_hourly(df)
        all_hourly.append(hourly)
        print(f"[system {system_id}] {len(hourly)} filas horarias listas para cargar")

    final_df = pd.concat(all_hourly, ignore_index=True)
    hourly_path = os.path.join(OUTPUT_DIR, "lectura_horaria.csv")
    final_df.to_csv(hourly_path, index=False)
    print(f"CSV horario guardado -> {hourly_path}")
    load_to_postgres(final_df)


if __name__ == "__main__":
    main()
