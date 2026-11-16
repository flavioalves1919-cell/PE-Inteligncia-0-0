from datetime import datetime, timezone

from airflow.sdk import DAG
from airflow.providers.standard.operators.bash import BashOperator


PROJECT_ROOT = "/home/flavio/projects/pe-inteligencia"
PYTHON = f"{PROJECT_ROOT}/.venv/bin/python"


def comando(modulo: str, argumentos: str = "") -> str:
    return (
        "set -euo pipefail\n"
        f"cd {PROJECT_ROOT}\n"
        f"exec {PYTHON} -m {modulo} {argumentos}"
    )


with DAG(
    dag_id="pe_inteligencia_pipeline",
    description="Pipeline de Engenharia de Dados de Pernambuco",
    start_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
    schedule=None,
    catchup=False,
    max_active_runs=1,
    max_active_tasks=1,
    tags=["pe-inteligencia", "engenharia-de-dados"],
) as dag:

    ingestao_saude = BashOperator(
        task_id="ingestao_condepe",
        bash_command=comando(
            "fontes.condepe.conector",
            "--anos 2022 2023 2024",
        ),
    )

    ingestao_fiscal = BashOperator(
        task_id="ingestao_siconfi",
        bash_command=comando(
            "fontes.siconfi.conector",
            "--ano 2024 --municipio 2611606",
        ),
    )

    curadoria_saude = BashOperator(
        task_id="curadoria_saude",
        bash_command=comando(
            "motor_dados.processamento.curar_mortalidade",
            "--anos 2022 2023 2024",
        ),
    )

    curadoria_fiscal = BashOperator(
        task_id="curadoria_fiscal",
        bash_command=comando(
            "motor_dados.processamento.curar_despesas_fiscais",
            "--ano 2024 --municipio 2611606",
        ),
    )

    raw_vault_saude = BashOperator(
        task_id="carga_raw_vault_saude",
        bash_command=comando(
            "motor_dados.data_vault.carregar_raw_vault",
        ),
    )

    raw_vault_fiscal = BashOperator(
        task_id="carga_raw_vault_fiscal",
        bash_command=comando(
            "motor_dados.data_vault.carregar_raw_vault_fiscal",
        ),
    )

    ingestao_saude >> curadoria_saude >> raw_vault_saude
    ingestao_fiscal >> curadoria_fiscal

    [raw_vault_saude, curadoria_fiscal] >> raw_vault_fiscal
