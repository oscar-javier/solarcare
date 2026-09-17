"""
inspect_columns.py
Utilidad de una sola corrida: lista las columnas reales que trae un
system_id de PVDAQ, para poder llenar COLUMN_MAP en config.py.

Uso:
    python inspect_columns.py 2107
"""

import sys
import io
import boto3
from botocore import UNSIGNED
from botocore.config import Config

from config import S3_BUCKET, S3_PREFIX_TEMPLATE

import pandas as pd


def get_first_csv_key(s3_client, system_id: int) -> str | None:
    prefix = S3_PREFIX_TEMPLATE.format(system_id=system_id)
    paginator = s3_client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []):
            if obj["Key"].endswith(".csv"):
                return obj["Key"]
    return None


def main(system_id: int):
    s3 = boto3.client("s3", config=Config(signature_version=UNSIGNED))

    key = get_first_csv_key(s3, system_id)
    if key is None:
        print(f"No se encontraron archivos CSV para system_id={system_id}")
        return

    print(f"Leyendo muestra: s3://{S3_BUCKET}/{key}\n")
    obj = s3.get_object(Bucket=S3_BUCKET, Key=key)
    df = pd.read_csv(io.BytesIO(obj["Body"].read()), nrows=5)

    print("Columnas encontradas:")
    for col in df.columns:
        print(f"  - {col}")

    print("\nPrimeras filas:")
    print(df.head())


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Uso: python inspect_columns.py <system_id>")
        sys.exit(1)
    main(int(sys.argv[1]))
