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
import os

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

from config import (
    COLUMN_MAP,
    RAW_TIMESTAMP_COL,
    OUTPUT_DIR,
    DB_CONFIG,
    ANALYTICS_TABLE,
    YEAR,
    MONTH,
)

STANDARD_COLUMNS = ["ac_power", "poa_irradiance", "ambient_temp"]


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
    return hourly


def load_to_postgres(df: pd.DataFrame):
    if df.empty:
        print("Nada que cargar (dataframe vacío).")
        return

    conn = psycopg2.connect(**DB_CONFIG)
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS {ANALYTICS_TABLE} (
                    system_id INTEGER NOT NULL,
                    timestamp TIMESTAMP NOT NULL,
                    ac_power DOUBLE PRECISION,
                    poa_irradiance DOUBLE PRECISION,
                    ambient_temp DOUBLE PRECISION,
                    PRIMARY KEY (system_id, timestamp)
                );
            """)

            # Idempotencia: igual que simular-dia, borramos antes de insertar
            # para poder re-correr el ETL sin duplicar filas.
            system_ids = df["system_id"].unique().tolist()
            cur.execute(
                f"""
                DELETE FROM {ANALYTICS_TABLE}
                WHERE system_id = ANY(%s)
                  AND EXTRACT(YEAR FROM timestamp) = %s
                  AND EXTRACT(MONTH FROM timestamp) = %s
                """,
                (system_ids, YEAR, MONTH),
            )

            rows = [
                (
                    int(r.system_id),
                    r.timestamp,
                    r.ac_power if "ac_power" in df.columns else None,
                    r.poa_irradiance if "poa_irradiance" in df.columns else None,
                    r.ambient_temp if "ambient_temp" in df.columns else None,
                )
                for r in df.itertuples(index=False)
            ]

            execute_values(
                cur,
                f"""
                INSERT INTO {ANALYTICS_TABLE}
                    (system_id, timestamp, ac_power, poa_irradiance, ambient_temp)
                VALUES %s
                """,
                rows,
            )
        conn.commit()
        print(f"Cargadas {len(rows)} filas horarias en '{ANALYTICS_TABLE}'.")
    finally:
        conn.close()


def main():
    raw_files = sorted(glob.glob(os.path.join(OUTPUT_DIR, "raw_*.csv")))
    if not raw_files:
        print("No hay archivos raw_*.csv. Corre extract.py primero.")
        return

    all_hourly = []
    for path in raw_files:
        system_id = int(os.path.basename(path).replace("raw_", "").replace(".csv", ""))
        df = pd.read_csv(path)

        df = standardize_columns(df, system_id)
        hourly = resample_to_hourly(df)
        all_hourly.append(hourly)
        print(f"[system {system_id}] {len(hourly)} filas horarias listas para cargar")

    final_df = pd.concat(all_hourly, ignore_index=True)
    load_to_postgres(final_df)


if __name__ == "__main__":
    main()
