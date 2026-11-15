import hashlib
import json
import logging
import os

from pathlib import Path

import pandas as pd
import psycopg

from dotenv import load_dotenv


load_dotenv()

BASE_CURADO = Path(
    "lakehouse/curado/saude/mortalidade_infantil"
)

FONTE = "CONDEPE_FIDEM:datasus_mortalidade_infantil"

CODIGO_FERNANDO = "2605459"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger("pe_inteligencia.data_vault")


def conectar():
    return psycopg.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("PE_DB_NAME"),
        user=os.getenv("PE_DB_USER"),
        password=os.getenv("PE_DB_PASSWORD"),
        connect_timeout=5,
    )


def hash_texto(valor: str) -> str:
    return hashlib.sha256(
        valor.encode("utf-8")
    ).hexdigest()


def hash_atributos(atributos: dict) -> str:
    """
    Gera hashdiff determinístico dos atributos
    de um Satellite.
    """

    conteudo = json.dumps(
        atributos,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

    return hash_texto(conteudo)


def hash_arquivo(caminho: Path) -> str:
    sha = hashlib.sha256()

    with caminho.open("rb") as arquivo:
        for bloco in iter(
            lambda: arquivo.read(1024 * 1024),
            b"",
        ):
            sha.update(bloco)

    return sha.hexdigest()


def gerar_batch_id(arquivos: list[Path]) -> str:
    """
    Identifica o conjunto exato de arquivos curados.
    A mesma entrada física gera o mesmo batch_id.
    """

    partes = []

    for arquivo in sorted(arquivos):
        relativo = arquivo.relative_to(BASE_CURADO)

        partes.append(
            f"{relativo}:{hash_arquivo(arquivo)}"
        )

    return hash_texto("|".join(partes))


def normalizar(valor):
    if valor is None:
        return None

    if pd.isna(valor):
        return None

    if isinstance(valor, pd.Timestamp):
        return valor.isoformat()

    if hasattr(valor, "item"):
        return valor.item()

    return valor


def carregar_arquivos() -> tuple[pd.DataFrame, list[Path]]:
    arquivos = sorted(
        BASE_CURADO.glob("ano=*/observacoes.parquet")
    )

    if not arquivos:
        raise FileNotFoundError(
            "Nenhum arquivo curado encontrado."
        )

    dataframes = [
        pd.read_parquet(arquivo)
        for arquivo in arquivos
    ]

    df = pd.concat(
        dataframes,
        ignore_index=True,
    )

    obrigatorias = [
        "id_fonte",
        "indicador",
        "cd_municipio_ibge",
        "nm_municipio",
        "tipo_localidade",
        "ano",
        "periodicidade",
        "valor",
        "unidade",
        "natureza",
        "fonte_original",
        "arquivo_origem",
        "data_coleta_utc",
        "url_origem",
    ]

    ausentes = [
        coluna for coluna in obrigatorias
        if coluna not in df.columns
    ]

    if ausentes:
        raise ValueError(
            f"Colunas ausentes na Curated: {ausentes}"
        )

    if df.empty:
        raise ValueError("A Curated não possui registros.")

    if df.duplicated(
        subset=[
            "id_fonte",
            "indicador",
            "cd_municipio_ibge",
            "ano",
        ]
    ).any():
        raise ValueError(
            "Existem observações duplicadas na Curated."
        )

    logger.info(
        "Arquivos encontrados: %s",
        len(arquivos),
    )

    logger.info(
        "Observações carregadas: %s",
        len(df),
    )

    return df, arquivos


def inserir_hub_localidade(cursor, hk, codigo):
    cursor.execute(
        """
        INSERT INTO raw_vault.hub_localidade (
            localidade_hk,
            codigo_ibge,
            record_source
        )
        VALUES (%s, %s, %s)
        ON CONFLICT DO NOTHING
        """,
        (hk, codigo, FONTE),
    )

    return cursor.rowcount


def inserir_hub_indicador(cursor, hk, chave):
    cursor.execute(
        """
        INSERT INTO raw_vault.hub_indicador (
            indicador_hk,
            chave_negocio,
            record_source
        )
        VALUES (%s, %s, %s)
        ON CONFLICT DO NOTHING
        """,
        (hk, chave, FONTE),
    )

    return cursor.rowcount


def inserir_hub_periodo(cursor, hk, ano):
    cursor.execute(
        """
        INSERT INTO raw_vault.hub_periodo (
            periodo_hk,
            ano,
            record_source
        )
        VALUES (%s, %s, %s)
        ON CONFLICT DO NOTHING
        """,
        (hk, ano, FONTE),
    )

    return cursor.rowcount


def inserir_satellite(
    cursor,
    tabela,
    coluna_hk,
    hk,
    batch_id,
    hashdiff,
    atributos,
):
    """
    Insere uma nova versão somente quando os atributos
    diferem da versão mais recente.
    """

    cursor.execute(
        f"""
        SELECT hashdiff
        FROM raw_vault.{tabela}
        WHERE {coluna_hk} = %s
        ORDER BY load_dts DESC
        LIMIT 1
        """,
        (hk,),
    )

    ultima_versao = cursor.fetchone()

    if ultima_versao and ultima_versao[0] == hashdiff:
        return 0

    colunas = [
        coluna_hk,
        "batch_id",
        "hashdiff",
        *atributos.keys(),
        "record_source",
    ]

    valores = [
        hk,
        batch_id,
        hashdiff,
        *atributos.values(),
        FONTE,
    ]

    placeholders = ", ".join(
        ["%s"] * len(valores)
    )

    nomes_colunas = ", ".join(colunas)

    cursor.execute(
        f"""
        INSERT INTO raw_vault.{tabela} (
            {nomes_colunas}
        )
        VALUES ({placeholders})
        ON CONFLICT DO NOTHING
        """,
        valores,
    )

    return cursor.rowcount



def registrar_inicio(batch_id, arquivos, registros):
    """
    Registra o início de uma execução em uma transação independente.
    """

    with conectar() as conexao:
        with conexao.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO raw_vault.audit_batch (
                    batch_id,
                    pipeline_name,
                    source_name,
                    status,
                    files_count,
                    records_read,
                    metadata
                )
                VALUES (
                    %s, %s, %s, 'RUNNING',
                    %s, %s, %s::jsonb
                )
                RETURNING batch_run_id
                """,
                (
                    batch_id,
                    "pipeline_raw_vault_mortalidade_infantil",
                    FONTE,
                    len(arquivos),
                    registros,
                    json.dumps({
                        "arquivos": [
                            str(arquivo.relative_to(BASE_CURADO))
                            for arquivo in arquivos
                        ]
                    }, ensure_ascii=False),
                ),
            )

            batch_run_id = cursor.fetchone()[0]

    return batch_run_id


def registrar_sucesso(batch_run_id, totais):
    """
    Finaliza a execução como SUCCESS.
    """

    with conectar() as conexao:
        with conexao.cursor() as cursor:
            cursor.execute(
                """
                UPDATE raw_vault.audit_batch
                SET
                    status = 'SUCCESS',
                    finished_at = CURRENT_TIMESTAMP,
                    inserted_records = %s::jsonb
                WHERE batch_run_id = %s
                  AND status = 'RUNNING'
                """,
                (
                    json.dumps(totais),
                    batch_run_id,
                ),
            )

            if cursor.rowcount != 1:
                raise RuntimeError(
                    "Não foi possível atualizar a auditoria para SUCCESS."
                )


def registrar_falha(batch_run_id, erro):
    """
    Registra a falha sem depender da transação da carga.
    """

    with conectar() as conexao:
        with conexao.cursor() as cursor:
            cursor.execute(
                """
                UPDATE raw_vault.audit_batch
                SET
                    status = 'FAILED',
                    finished_at = CURRENT_TIMESTAMP,
                    error_message = %s
                WHERE batch_run_id = %s
                  AND status = 'RUNNING'
                """,
                (
                    str(erro)[:10000],
                    batch_run_id,
                ),
            )


def carregar():
    df, arquivos = carregar_arquivos()

    batch_id = gerar_batch_id(arquivos)

    logger.info("Batch ID: %s", batch_id)

    totais = {
        "hub_localidade": 0,
        "hub_indicador": 0,
        "hub_periodo": 0,
        "link_observacao": 0,
        "sat_localidade": 0,
        "sat_indicador": 0,
        "sat_observacao": 0,
    }

    # A auditoria é confirmada antes de iniciar a carga.
    batch_run_id = registrar_inicio(
        batch_id,
        arquivos,
        len(df),
    )

    logger.info(
        "Execução de auditoria iniciada. ID: %s",
        batch_run_id,
    )

    try:
        with conectar() as conexao:
            with conexao.cursor() as cursor:

                for _, linha in df.iterrows():

                    codigo = str(
                        linha["cd_municipio_ibge"]
                    )

                    indicador = str(
                        linha["indicador"]
                    )

                    id_fonte = str(
                        linha["id_fonte"]
                    )

                    ano = int(linha["ano"])

                    # ======================================
                    # CHAVES HASH DOS HUBS
                    # ======================================

                    localidade_hk = hash_texto(codigo)

                    chave_indicador = (
                        f"{id_fonte}|{indicador}"
                    )

                    indicador_hk = hash_texto(
                        chave_indicador
                    )

                    periodo_hk = hash_texto(
                        str(ano)
                    )

                    # ======================================
                    # HUBS
                    # ======================================

                    totais["hub_localidade"] += (
                        inserir_hub_localidade(
                            cursor,
                            localidade_hk,
                            codigo,
                        )
                    )

                    totais["hub_indicador"] += (
                        inserir_hub_indicador(
                            cursor,
                            indicador_hk,
                            chave_indicador,
                        )
                    )

                    totais["hub_periodo"] += (
                        inserir_hub_periodo(
                            cursor,
                            periodo_hk,
                            ano,
                        )
                    )

                    # ======================================
                    # LINK
                    # ======================================

                    observacao_hk = hash_texto(
                        "|".join([
                            localidade_hk,
                            indicador_hk,
                            periodo_hk,
                        ])
                    )

                    cursor.execute(
                        """
                        INSERT INTO raw_vault.link_observacao (
                            observacao_hk,
                            localidade_hk,
                            indicador_hk,
                            periodo_hk,
                            record_source
                        )
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT DO NOTHING
                        """,
                        (
                            observacao_hk,
                            localidade_hk,
                            indicador_hk,
                            periodo_hk,
                            FONTE,
                        ),
                    )

                    totais["link_observacao"] += cursor.rowcount

                    # ======================================
                    # SATELLITE LOCALIDADE
                    # ======================================

                    atributos_localidade = {
                        "nome_localidade": str(
                            linha["nm_municipio"]
                        ),
                        "tipo_localidade": str(
                            linha["tipo_localidade"]
                        ),
                    }

                    hashdiff_localidade = hash_atributos(
                        atributos_localidade
                    )

                    totais["sat_localidade"] += inserir_satellite(
                        cursor,
                        "sat_localidade",
                        "localidade_hk",
                        localidade_hk,
                        batch_id,
                        hashdiff_localidade,
                        atributos_localidade,
                    )

                    # ======================================
                    # SATELLITE INDICADOR
                    # ======================================

                    atributos_indicador = {
                        "nome_indicador": indicador,
                        "unidade": normalizar(linha["unidade"]),
                        "periodicidade": str(
                            linha["periodicidade"]
                        ),
                        "fonte_original": normalizar(
                            linha["fonte_original"]
                        ),
                    }

                    hashdiff_indicador = hash_atributos(
                        atributos_indicador
                    )

                    totais["sat_indicador"] += inserir_satellite(
                        cursor,
                        "sat_indicador",
                        "indicador_hk",
                        indicador_hk,
                        batch_id,
                        hashdiff_indicador,
                        atributos_indicador,
                    )

                    # ======================================
                    # SATELLITE OBSERVAÇÃO
                    # ======================================

                    atributos_observacao = {
                        "valor": float(linha["valor"]),
                        "unidade": normalizar(linha["unidade"]),
                        "natureza": normalizar(linha["natureza"]),
                        "fonte_original": normalizar(
                            linha["fonte_original"]
                        ),
                        "arquivo_origem": normalizar(
                            linha["arquivo_origem"]
                        ),
                        "data_coleta_utc": normalizar(
                            linha["data_coleta_utc"]
                        ),
                        "url_origem": normalizar(
                            linha["url_origem"]
                        ),
                    }

                    # A data da coleta não participa do hashdiff.
                    atributos_hash = {
                        chave: valor
                        for chave, valor in atributos_observacao.items()
                        if chave != "data_coleta_utc"
                    }

                    hashdiff_observacao = hash_atributos(
                        atributos_hash
                    )

                    totais["sat_observacao"] += inserir_satellite(
                        cursor,
                        "sat_observacao",
                        "observacao_hk",
                        observacao_hk,
                        batch_id,
                        hashdiff_observacao,
                        atributos_observacao,
                    )

    except Exception as erro:
        logger.exception(
            "Falha durante a carga do Raw Vault."
        )

        try:
            registrar_falha(batch_run_id, erro)

            logger.info(
                "Auditoria atualizada para FAILED. ID: %s",
                batch_run_id,
            )

        except Exception:
            logger.exception(
                "Não foi possível registrar a falha na auditoria."
            )

        raise

    # A transação dos dados já foi confirmada neste ponto.
    registrar_sucesso(batch_run_id, totais)

    logger.info("Carga concluída com sucesso.")

    logger.info(
        "Execução de auditoria finalizada. ID: %s",
        batch_run_id,
    )

    for tabela, quantidade in totais.items():
        logger.info(
            "%s: %s novos registros",
            tabela,
            quantidade,
        )


if __name__ == "__main__":
    carregar()
