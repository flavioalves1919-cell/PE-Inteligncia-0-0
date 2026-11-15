import hashlib
import uuid

import pytest

from motor_dados.data_vault.carregar_raw_vault import (
    conectar,
    registrar_inicio,
    registrar_sucesso,
    registrar_falha,
)


@pytest.fixture
def execucao_auditoria():
    batch_id = hashlib.sha256(
        uuid.uuid4().bytes
    ).hexdigest()

    batch_run_id = registrar_inicio(
        batch_id=batch_id,
        arquivos=[],
        registros=555,
    )

    yield batch_run_id

    # Remove somente o registro temporário deste teste.
    with conectar() as conexao:
        with conexao.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM raw_vault.audit_batch
                WHERE batch_run_id = %s
                """,
                (batch_run_id,),
            )


def consultar_execucao(batch_run_id):
    with conectar() as conexao:
        with conexao.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    status,
                    files_count,
                    records_read,
                    inserted_records,
                    error_message,
                    finished_at
                FROM raw_vault.audit_batch
                WHERE batch_run_id = %s
                """,
                (batch_run_id,),
            )

            return cursor.fetchone()


def test_registrar_inicio(execucao_auditoria):
    resultado = consultar_execucao(
        execucao_auditoria
    )

    assert resultado is not None
    assert resultado[0] == "RUNNING"
    assert resultado[1] == 0
    assert resultado[2] == 555
    assert resultado[5] is None


def test_registrar_sucesso(execucao_auditoria):
    totais = {
        "hub_localidade": 10,
        "hub_indicador": 1,
        "hub_periodo": 2,
    }

    registrar_sucesso(
        execucao_auditoria,
        totais,
    )

    resultado = consultar_execucao(
        execucao_auditoria
    )

    assert resultado[0] == "SUCCESS"
    assert resultado[3] == totais
    assert resultado[5] is not None
    assert resultado[4] is None


def test_registrar_falha(execucao_auditoria):
    registrar_falha(
        execucao_auditoria,
        RuntimeError("Erro simulado pelo Pytest"),
    )

    resultado = consultar_execucao(
        execucao_auditoria
    )

    assert resultado[0] == "FAILED"
    assert "Erro simulado pelo Pytest" in resultado[4]
    assert resultado[5] is not None


def test_nao_permite_finalizar_execucao_duas_vezes(
    execucao_auditoria,
):
    registrar_sucesso(
        execucao_auditoria,
        {},
    )

    with pytest.raises(RuntimeError):
        registrar_sucesso(
            execucao_auditoria,
            {},
        )


def test_nao_permite_sucesso_apos_falha(
    execucao_auditoria,
):
    registrar_falha(
        execucao_auditoria,
        RuntimeError("Falha simulada"),
    )

    with pytest.raises(RuntimeError):
        registrar_sucesso(
            execucao_auditoria,
            {},
        )
