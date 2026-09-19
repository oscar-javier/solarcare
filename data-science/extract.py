"""
extract.py
Paso 1 del nuevo ETL horario para SolarCare.

Qué hace distinto respecto al pipeline anterior:
  - Antes: se traía la resolución cruda de PVDAQ (~15 min) completa.
  - Ahora: se filtra ANTES de guardar nada, quedándonos solo con lecturas
    cuya hora local esté entre HOUR_START y HOUR_END (6am-6pm), porque
    fuera de ese rango un panel solar no genera nada relevante y esos
    datos solo ocupan espacio sin aportar señal al modelo de regresión.

Salida: un CSV crudo filtrado por sistema en output/raw_<system_id>.csv
(este archivo YA viene filtrado por hora, pero todavía a la resolución
original de PVDAQ; el resampleo a 1 fila/hora ocurre en transform_load.py)
"""

import io
import boto3
from botocore import UNSIGNED
from botocore.config import Config
import pandas as pd

from config import (
    S3_BUCKET,
    S3_PREFIX_TEMPLATE,
    SYSTEM_IDS,
    YEAR_START,
    YEAR_END,
    HOUR_START,
    HOUR_END,
    RAW_TIMESTAMP_COL,
    OUTPUT_DIR,
    SYSTEM_YEAR_RANGES,
)


def make_s3_client():
    # PVDAQ es un bucket público: acceso anónimo, sin credenciales de AWS.
    return boto3.client("s3", config=Config(signature_version=UNSIGNED))


def list_month_keys(s3_client, system_id: int, year: int, month: int) -> list[str]:
    """Lista las keys .csv de un sistema para un año/mes dado.

    La partición real en el bucket es system_id/year/month/day, así que
    filtramos por prefijo hasta el nivel de mes y dejamos que boto3 pagine.
    """
    prefix = S3_PREFIX_TEMPLATE.format(system_id=system_id)
    keys = []
    paginator = s3_client.get_paginator("list_objects_v2")
    month_prefixes = {
        f"{prefix}year={year}/month={month:02d}/",
        f"{prefix}year={year}/month={month}/",
    }
    for month_prefix in month_prefixes:
        for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=month_prefix):
            for obj in page.get("Contents", []):
                if obj["Key"].endswith(".csv") and obj["Key"] not in keys:
                    keys.append(obj["Key"])

    if not keys:
        print(
            f"  [system {system_id}] sin datos en year={year}/month={month:02d} "
            f"(prueba con otro mes: no todos los sistemas cubren el mismo periodo)"
        )
    return keys


def read_csv_from_s3(s3_client, key: str) -> pd.DataFrame:
    obj = s3_client.get_object(Bucket=S3_BUCKET, Key=key)
    return pd.read_csv(io.BytesIO(obj["Body"].read()))


def filter_daylight_window(df: pd.DataFrame) -> pd.DataFrame:
    """Se queda solo con filas cuya hora local esté en [HOUR_START, HOUR_END]."""
    if RAW_TIMESTAMP_COL not in df.columns:
        raise KeyError(
            f"No se encontró la columna de timestamp '{RAW_TIMESTAMP_COL}'. "
            f"Corre inspect_columns.py para este sistema y actualiza "
            f"RAW_TIMESTAMP_COL en config.py si el nombre es distinto."
        )

    df[RAW_TIMESTAMP_COL] = pd.to_datetime(df[RAW_TIMESTAMP_COL], errors="coerce")
    df = df.dropna(subset=[RAW_TIMESTAMP_COL])

    mask = (df[RAW_TIMESTAMP_COL].dt.hour >= HOUR_START) & (
        df[RAW_TIMESTAMP_COL].dt.hour <= HOUR_END
    )
    return df.loc[mask].copy()


def extract_system(s3_client, system_id: int) -> pd.DataFrame:
    frames = []
    year_start, year_end = SYSTEM_YEAR_RANGES.get(system_id, (YEAR_START, YEAR_END))
    for year in range(year_start, year_end + 1):
        for month in range(1, 13):
            print(f"[system {system_id}] listando archivos de {year}-{month:02d}...")
            keys = list_month_keys(s3_client, system_id, year, month)
            for key in keys:
                try:
                    df = read_csv_from_s3(s3_client, key)
                    df_filtered = filter_daylight_window(df)
                    if not df_filtered.empty:
                        frames.append(df_filtered)
                except Exception as exc:
                    print(f"  [system {system_id}] error leyendo {key}: {exc}")

    if not frames:
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)
    combined["system_id"] = system_id
    print(
        f"  [system {system_id}] {len(combined)} filas dentro de "
        f"{HOUR_START}:00-{HOUR_END}:00 (de {sum(len(f) for f in frames)} leídas)"
    )
    return combined


def main():
    s3 = make_s3_client()

    for system_id in SYSTEM_IDS:
        df = extract_system(s3, system_id)
        if df.empty:
            continue

        year_start, year_end = SYSTEM_YEAR_RANGES.get(system_id, (YEAR_START, YEAR_END))
        out_path = f"{OUTPUT_DIR}/raw_{system_id}_{year_start}_{year_end}.csv"
        df.to_csv(out_path, index=False)
        print(f"  [system {system_id}] guardado -> {out_path}\n")


if __name__ == "__main__":
    main()
