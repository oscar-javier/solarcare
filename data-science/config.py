"""
config.py
Configuración compartida para el ETL horario (6am-6pm) de SolarCare.

IMPORTANTE:
Los archivos CSV de PVDAQ NO tienen el mismo esquema de columnas entre
sistemas: cada inversor mete su propio ID en el nombre de columna
(ej. "inv_01_ac_power_inv_149583"). Por eso este ETL usa un mapeo de
columnas POR SISTEMA en vez de asumir nombres fijos.

Antes de correr extract.py por primera vez para un sistema nuevo, corre:
    python inspect_columns.py <system_id>
y llena COLUMN_MAP con los nombres reales que aparezcan.
"""

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None

# Carga .env si existe (útil para ejecutar localmente sin repetir variables en cada terminal)
_env_path = Path(__file__).resolve().parent / ".env"
if load_dotenv is not None and _env_path.exists():
    load_dotenv(dotenv_path=_env_path, override=False)

# --- Sistemas seleccionados (mismos 6 del pipeline original) ---
SYSTEM_IDS = [10, 34, 1430, 2107, 9069, 1239]

# --- Bucket público de NREL PVDAQ (acceso anónimo, sin credenciales) ---
S3_BUCKET = "oedi-data-lake"
S3_PREFIX_TEMPLATE = "pvdaq/csv/pvdata/system_id={system_id}/"

# --- Ventana temporal a extraer ---
# El bucket de PVDAQ no tiene el mismo periodo para todos los sistemas.
# Para validar el ETL usamos un mes con datos reales para al menos un sistema.
YEAR = 2010
MONTH = 10

# --- Ventana horaria de interés: 6am a 6pm inclusive ---
HOUR_START = 6   # 06:00
HOUR_END = 18    # 18:00 (inclusive)

# --- Nombre de la columna de timestamp en los CSV crudos de PVDAQ ---
# Casi siempre es "measured_on", pero verifícalo con inspect_columns.py
RAW_TIMESTAMP_COL = "measured_on"

# --- Mapeo columna real -> nombre estándar por sistema ---
# Los nombres reales fueron inspeccionados desde PVDAQ. Para los sistemas que
# no tienen archivos disponibles, se dejan vacíos para que el ETL no falle.
COLUMN_MAP = {
    10: {
        "ac_power": "ac_power__423",
        "poa_irradiance": "poa_irradiance__421",
        "ambient_temp": "ambient_temp__428",
    },
    34: {
        "ac_power": "ac_power_hw__2695",
        "poa_irradiance": "poa_irradiance__2679",
        "ambient_temp": "ambient_temp_f__2688",
    },
    1430: {
        "poa_irradiance": "poa_irradiance__5041",
        "ambient_temp": "ambient_temp__5042",
    },
    2107: {},
    9069: {},
    1239: {
        "ac_power": "ac_power_metered_kw__3015",
        "poa_irradiance": "poa_irradiance__3018",
        "ambient_temp": "ambient_temp_f__3016",
    },
}

# --- Salida intermedia (antes de cargar a Postgres) ---
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# --- Conexión a Postgres (reusa tus variables de entorno actuales) ---
DB_CONFIG = {
    "host": os.environ.get("PGHOST") or "localhost",
    "port": os.environ.get("PGPORT") or "5432",
    "dbname": os.environ.get("PGDATABASE") or "solarcare",
    "user": os.environ.get("PGUSER") or "postgres",
    "password": os.environ.get("PGPASSWORD") or "",
}

ANALYTICS_TABLE = "lectura_horaria"
