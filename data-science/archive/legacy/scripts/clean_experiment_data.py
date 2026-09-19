"""Aplicación segura de la limpieza experimental para 1430 y 1239.

- crea backup del CSV local
- elimina registros fuera de las ventanas definidas en config.py
- sincroniza la tabla `lectura_horaria` en Supabase usando filtros por system_id + timestamp
- reporta conteos antes/después
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pandas as pd
import psycopg2
from dotenv import load_dotenv

from config import SYSTEM_CLEANUP_RULES

CSV_PATH = Path(__file__).resolve().parent / "output" / "lectura_horaria.csv"
BACKUP_PATH = Path(__file__).resolve().parent / "output" / "lectura_horaria_backup_pre_clean.csv"


def load_env() -> None:
    env_candidates = [
        Path(__file__).resolve().parent / ".env",
        Path(__file__).resolve().parent.parent / "backend" / ".env",
    ]
    for env_file in env_candidates:
        if env_file.exists():
            load_dotenv(env_file, override=False)


def snapshot_counts(df: pd.DataFrame) -> dict[int, dict[str, int | str]]:
    report = {}
    for sid, rule in SYSTEM_CLEANUP_RULES.items():
        s = df[df["system_id"] == sid].copy().sort_values("timestamp")
        report[sid] = {
            "before_rows": int(len(s)),
            "min_ts": str(s["timestamp"].min()) if not s.empty else None,
            "max_ts": str(s["timestamp"].max()) if not s.empty else None,
        }
    return report


def apply_local_cleanup(df: pd.DataFrame) -> pd.DataFrame:
    cleaned = df.copy()
    for sid, rule in SYSTEM_CLEANUP_RULES.items():
        if sid == 1430:
            cutoff = pd.Timestamp(rule["delete_from"])
            mask = ~((cleaned["system_id"] == sid) & (cleaned["timestamp"] >= cutoff))
            cleaned = cleaned.loc[mask].copy()
        elif sid == 1239:
            min_cutoff = pd.Timestamp(rule["min_timestamp"])
            max_cutoff = pd.Timestamp(rule["max_timestamp"])
            mask = ~((cleaned["system_id"] == sid) & ((cleaned["timestamp"] < min_cutoff) | (cleaned["timestamp"] > max_cutoff)))
            cleaned = cleaned.loc[mask].copy()
    return cleaned


def apply_supabase_cleanup() -> dict[int, dict[str, int | str]]:
    load_env()
    dsn = os.environ.get("DIRECT_URL") or os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError("No existe DIRECT_URL/DATABASE_URL en el entorno para Supabase.")

    conn = psycopg2.connect(dsn)
    cur = conn.cursor()
    report = {}
    try:
        for sid, rule in SYSTEM_CLEANUP_RULES.items():
            if sid == 1430:
                before = cur.execute("SELECT COUNT(*) FROM lectura_horaria WHERE system_id = %s", (sid,))
                delete_sql = "DELETE FROM lectura_horaria WHERE system_id = %s AND timestamp >= %s"
                cur.execute(delete_sql, (sid, rule["delete_from"]))
            elif sid == 1239:
                delete_sql = "DELETE FROM lectura_horaria WHERE system_id = %s AND (timestamp < %s OR timestamp > %s)"
                cur.execute(delete_sql, (sid, rule["min_timestamp"], rule["max_timestamp"]))
            conn.commit()
            cur.execute("SELECT COUNT(*) FROM lectura_horaria WHERE system_id = %s", (sid,))
            after = cur.fetchone()[0]
            report[sid] = {"deleted": "applied", "after_rows": int(after)}
    finally:
        conn.close()
    return report


def main() -> None:
    load_env()
    df = pd.read_csv(CSV_PATH, parse_dates=["timestamp"])
    before = snapshot_counts(df)
    if not BACKUP_PATH.exists():
        shutil.copy2(CSV_PATH, BACKUP_PATH)
        print(f"BACKUP_CREATED {BACKUP_PATH}")
    else:
        print(f"BACKUP_EXISTS {BACKUP_PATH}")

    cleaned = apply_local_cleanup(df)
    cleaned.to_csv(CSV_PATH, index=False)
    after = snapshot_counts(cleaned)
    print("LOCAL_CLEANUP_SUMMARY")
    for sid in sorted(SYSTEM_CLEANUP_RULES):
        print({
            "system_id": sid,
            "before": before[sid],
            "after": after[sid],
            "removed": before[sid]["before_rows"] - after[sid]["before_rows"],
        })

    supabase_report = apply_supabase_cleanup()
    print("SUPABASE_CLEANUP_SUMMARY")
    print(supabase_report)


if __name__ == "__main__":
    main()
