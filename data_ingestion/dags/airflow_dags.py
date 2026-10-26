"""Apache Airflow DAG — Sub-Task 1: Data Ingestion & Feature Store.

Schedules
---------
    Source          | Update frequency | Cron schedule
    --------------- | ---------------- | ----------------
    Ookla           | Quarterly        | 0 6 1 */3 *
    IBGE            | Static           | 0 6 1 1 *  (annual refresh)
    Anatel          | Monthly          | 0 6 1 * *
    OpenCelliD      | Daily            | 0 3 * * *
    M-Lab NDT       | Daily            | 0 4 * * *
    Cloudflare Radar| Near-real-time   | 0 * * * *  (hourly)

A master DAG (``telecom_feature_store_daily``) runs daily and chains all
ingestion tasks followed by a monthly Gold build step.

Place this file in your Airflow ``dags/`` directory.  Required environment
variables are documented in ``.env.example`` at the project root.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path

from airflow import DAG
from airflow.operators.python import PythonOperator

# ---------------------------------------------------------------------------
# Shared defaults
# ---------------------------------------------------------------------------
_DEFAULT_ARGS = {
    "owner": "data-engineering",
    "depends_on_past": False,
    "retries": 3,
    "retry_delay": timedelta(minutes=10),
    "retry_exponential_backoff": True,
    "email_on_failure": False,
}

_BRONZE_DIR = Path(os.getenv("BRONZE_DIR", "/data/bronze"))
_GOLD_DIR = Path(os.getenv("GOLD_DIR", "/data/gold"))


# ---------------------------------------------------------------------------
# Task callables
# ---------------------------------------------------------------------------

def _ingest_ookla(**ctx):
    from data_ingestion.connectors.ookla import OoklaConnector

    ds = ctx["ds"]
    year, quarter = _date_to_ookla_quarter(ds)
    for ctype in ["fixed", "mobile"]:
        conn = OoklaConnector(connection_type=ctype, year=year, quarter=quarter)
        conn.run(_BRONZE_DIR)


def _ingest_ibge(**ctx):
    from data_ingestion.connectors.ibge import IBGEConnector

    IBGEConnector().run(_BRONZE_DIR)


def _ingest_anatel(**ctx):
    from data_ingestion.connectors.anatel import AnatelConnector

    AnatelConnector().run(_BRONZE_DIR)


def _ingest_opencellid(**ctx):
    from data_ingestion.connectors.opencellid import OpenCelliDConnector

    OpenCelliDConnector().run(_BRONZE_DIR)


def _ingest_mlab(**ctx):
    from data_ingestion.connectors.mlab import MLABConnector

    MLABConnector().run(_BRONZE_DIR)


def _ingest_cloudflare(**ctx):
    from data_ingestion.connectors.cloudflare import CloudflareRadarConnector

    CloudflareRadarConnector().run(_BRONZE_DIR)


def _build_gold_layer(**ctx):
    """Assemble Silver → Gold after all ingestion tasks complete."""
    import pandas as pd
    from data_ingestion.processing.feature_store import build_silver, build_gold
    from data_ingestion.processing.quality import validate_gold

    ds = ctx["ds"]
    year, month = int(ds[:4]), int(ds[5:7])

    def _load(src_id: str, filename: str) -> pd.DataFrame:
        path = _BRONZE_DIR / src_id / filename
        if path.exists():
            return pd.read_parquet(path)
        return pd.DataFrame()

    ookla_df = pd.concat(
        [
            _load("ookla_speedtest_fixed", "data.parquet"),
            _load("ookla_speedtest_mobile", "data.parquet"),
        ],
        ignore_index=True,
    )

    ibge_df = _load("ibge_geodados", "data.parquet")
    anatel_muni = _load("anatel_dados", "municipality_metrics.parquet")
    anatel_erb = _load("anatel_dados", "erb_h3.parquet")
    opencellid_df = _load("opencellid", "data.parquet")
    mlab_df = _load("mlab_ndt", "data.parquet")

    for res in [8, 9]:
        silver = build_silver(
            ookla_df=ookla_df,
            ibge_df=ibge_df,
            anatel_muni_df=anatel_muni,
            anatel_erb_df=anatel_erb,
            opencellid_df=opencellid_df,
            mlab_df=mlab_df,
            h3_resolution=res,
        )
        gold = build_gold(
            silver=silver,
            h3_resolution=res,
            year=year,
            month=month,
            output_dir=_GOLD_DIR,
        )
        report = validate_gold(gold)
        if not report.passed:
            raise RuntimeError(
                f"[DAG] Gold quality check FAILED at res {res}:\n{report.summary()}"
            )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _date_to_ookla_quarter(ds: str) -> tuple[int, int]:
    """Convert YYYY-MM-DD execution date to (year, quarter) for Ookla."""
    month = int(ds[5:7])
    year = int(ds[:4])
    prev_month = month - 3
    if prev_month <= 0:
        prev_month += 12
        year -= 1
    return year, (prev_month - 1) // 3 + 1


# ---------------------------------------------------------------------------
# DAG: Ookla (quarterly)
# ---------------------------------------------------------------------------
with DAG(
    dag_id="ingest_ookla",
    description="Ingest Ookla Speedtest Open Data (quarterly)",
    schedule="0 6 1 */3 *",
    start_date=datetime(2024, 1, 1),
    catchup=False,
    default_args=_DEFAULT_ARGS,
    tags=["ingestion", "ookla", "sub-task-1"],
) as dag_ookla:
    PythonOperator(task_id="ingest_ookla", python_callable=_ingest_ookla)

# ---------------------------------------------------------------------------
# DAG: IBGE (annual)
# ---------------------------------------------------------------------------
with DAG(
    dag_id="ingest_ibge",
    description="Ingest IBGE CNEFE + SIDRA (annual)",
    schedule="0 6 1 1 *",
    start_date=datetime(2024, 1, 1),
    catchup=False,
    default_args=_DEFAULT_ARGS,
    tags=["ingestion", "ibge", "sub-task-1"],
) as dag_ibge:
    PythonOperator(task_id="ingest_ibge", python_callable=_ingest_ibge)

# ---------------------------------------------------------------------------
# DAG: Anatel (monthly)
# ---------------------------------------------------------------------------
with DAG(
    dag_id="ingest_anatel",
    description="Ingest Anatel open datasets (monthly)",
    schedule="0 6 1 * *",
    start_date=datetime(2024, 1, 1),
    catchup=False,
    default_args=_DEFAULT_ARGS,
    tags=["ingestion", "anatel", "sub-task-1"],
) as dag_anatel:
    PythonOperator(task_id="ingest_anatel", python_callable=_ingest_anatel)

# ---------------------------------------------------------------------------
# DAG: OpenCelliD (daily)
# ---------------------------------------------------------------------------
with DAG(
    dag_id="ingest_opencellid",
    description="Ingest OpenCelliD daily dump (daily)",
    schedule="0 3 * * *",
    start_date=datetime(2024, 1, 1),
    catchup=False,
    default_args=_DEFAULT_ARGS,
    tags=["ingestion", "opencellid", "sub-task-1"],
) as dag_opencellid:
    PythonOperator(task_id="ingest_opencellid", python_callable=_ingest_opencellid)

# ---------------------------------------------------------------------------
# DAG: M-Lab NDT (daily)
# ---------------------------------------------------------------------------
with DAG(
    dag_id="ingest_mlab",
    description="Ingest M-Lab NDT measurements from BigQuery (daily)",
    schedule="0 4 * * *",
    start_date=datetime(2024, 1, 1),
    catchup=False,
    default_args=_DEFAULT_ARGS,
    tags=["ingestion", "mlab", "sub-task-1"],
) as dag_mlab:
    PythonOperator(task_id="ingest_mlab", python_callable=_ingest_mlab)

# ---------------------------------------------------------------------------
# DAG: Cloudflare Radar (hourly)
# ---------------------------------------------------------------------------
with DAG(
    dag_id="ingest_cloudflare",
    description="Ingest Cloudflare Radar outage/anomaly events (hourly)",
    schedule="0 * * * *",
    start_date=datetime(2024, 1, 1),
    catchup=False,
    default_args=_DEFAULT_ARGS,
    tags=["ingestion", "cloudflare", "sub-task-1"],
) as dag_cloudflare:
    PythonOperator(task_id="ingest_cloudflare", python_callable=_ingest_cloudflare)

# ---------------------------------------------------------------------------
# Master DAG: daily orchestrator → Gold build
# ---------------------------------------------------------------------------
with DAG(
    dag_id="telecom_feature_store_daily",
    description="Master orchestrator: daily ingestion + monthly Gold build",
    schedule="0 5 * * *",
    start_date=datetime(2024, 1, 1),
    catchup=False,
    default_args=_DEFAULT_ARGS,
    tags=["orchestration", "feature-store", "sub-task-1"],
) as dag_master:
    t_ookla = PythonOperator(task_id="ingest_ookla", python_callable=_ingest_ookla)
    t_opencellid = PythonOperator(task_id="ingest_opencellid", python_callable=_ingest_opencellid)
    t_mlab = PythonOperator(task_id="ingest_mlab", python_callable=_ingest_mlab)
    t_cloudflare = PythonOperator(task_id="ingest_cloudflare", python_callable=_ingest_cloudflare)
    t_anatel = PythonOperator(task_id="ingest_anatel", python_callable=_ingest_anatel)
    t_ibge = PythonOperator(task_id="ingest_ibge", python_callable=_ingest_ibge)
    t_gold = PythonOperator(task_id="build_gold", python_callable=_build_gold_layer)

    [t_ookla, t_opencellid, t_mlab, t_cloudflare, t_anatel, t_ibge] >> t_gold
