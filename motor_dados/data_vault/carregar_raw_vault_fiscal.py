import hashlib
import json
import logging
import os

from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd
import psycopg

from dotenv import load_dotenv


load_dotenv()

BASE_CURADO = Path("lakehouse/curado/fiscal/despesas_saude")

FONTE = "SICONFI:DCA-Anexo I-E"
SOURCE_NAME = "siconfi_dca"
PIPELINE_NAME = "pipeline_raw_vault_despesas_fiscais"

ANEXO_ESPERADO = "DCA-Anexo I-E"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger("pe_inteligencia.data_vault_fiscal")


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
    partes = []

    for arquivo in sorted(arquivos):
        relativo = arquivo.relative_to(BASE_CURADO)

        partes.append(
            f"{relativo}:{hash_arquivo(arquivo)}"
        )

    return hash_texto("|".join(partes))


def normalizar_data(valor):
    if valor is None or pd.isna(valor):
        return None

    if isinstance(valor, datetime):
        return valor

    texto = str(valor).strip()

    if texto.endswith("Z"):
        texto = texto[:-1] + "+00:00"

    return datetime.fromisoformat(texto)


def localizar_arquivos_curados() -> list[Path]:
    """
    Seleciona somente a versão mais recente de cada
    partição ano/município.
    """

    encontrados = sorted(
        BASE_CURADO.glob(
            "ano=*/municipio=*/observacoes_*.parquet"
        )
    )

    if not encontrados:
        raise FileNotFoundError(
            "Nenhum arquivo fiscal Curado encontrado."
        )

    particoes = {}

    for arquivo in encontrados:
        particoes.setdefault(
            arquivo.parent,
            [],
        ).append(arquivo)

    selecionados = []

    for pasta, arquivos in sorted(particoes.items()):
        arquivo = sorted(arquivos)[-1]

        manifesto_path = pasta / arquivo.name.replace(
            "observacoes_", "manifesto_"
        ).replace(".parquet", ".json")

        if not manifesto_path.exists():
            raise FileNotFoundError(
                f"Manifesto não encontrado: {manifesto_path}"
            )

        manifesto = json.loads(
            manifesto_path.read_text(encoding="utf-8")
        )

        ano = int(pasta.parent.name.split("=")[1])
        municipio = pasta.name.split("=")[1]

        if manifesto.get("status") != "SUCESSO":
            raise ValueError(
                f"Manifesto sem status SUCESSO: {manifesto_path}"
            )

        if manifesto.get("arquivo") != arquivo.name:
            raise ValueError(
                f"Arquivo não corresponde ao manifesto: {arquivo}"
            )

        if manifesto.get("ano") != ano:
            raise ValueError("Ano divergente no manifesto.")

        if str(manifesto.get("codigo_ibge")) != municipio:
            raise ValueError("Município divergente no manifesto.")

        if manifesto.get("anexo") != ANEXO_ESPERADO:
            raise ValueError("Anexo divergente no manifesto.")

        if hash_arquivo(arquivo) != manifesto.get(
            "hash_curado_sha256"
        ):
            raise ValueError(
                f"SHA-256 Curado não confere: {arquivo}"
            )

        selecionados.append(arquivo)

        logger.info(
            "Curado validado: %s",
            arquivo,
        )

    return selecionados


def carregar_arquivos() -> tuple[pd.DataFrame, list[Path]]:
    arquivos = localizar_arquivos_curados()

    dataframes = [
        pd.read_parquet(arquivo)
        for arquivo in arquivos
    ]

    df = pd.concat(
        dataframes,
        ignore_index=True,
    )

    obrigatorias = [
        "chave_negocio",
        "id_fonte",
        "cod_ibge",
        "uf",
        "instituicao",
        "ano",
        "codigo_anexo",
        "rotulo",
        "cod_conta",
        "conta",
        "codigo_classificacao",
        "codigo_estagio",
        "valor",
        "populacao",
        "data_coleta_utc",
        "arquivo_origem",
        "url_origem",
    ]

    ausentes = [
        coluna
        for coluna in obrigatorias
        if coluna not in df.columns
    ]

    if ausentes:
        raise ValueError(
            f"Colunas ausentes na Curated: {ausentes}"
        )

    if df.empty:
        raise ValueError("A Curated fiscal está vazia.")

    if not df["id_fonte"].eq(SOURCE_NAME).all():
        raise ValueError("Fonte fiscal inesperada.")

    if not df["codigo_anexo"].eq(ANEXO_ESPERADO).all():
        raise ValueError("Anexo fiscal inesperado.")

    if not df["valor"].map(
        lambda valor: isinstance(valor, Decimal)
    ).all():
        raise TypeError(
            "Valores financeiros devem permanecer em Decimal."
        )

    if not df["valor"].map(
        lambda valor: valor.is_finite()
    ).all():
        raise ValueError("Existem valores financeiros não finitos.")

    if not df["valor"].map(
        lambda valor: valor == valor.quantize(Decimal("0.01"))
    ).all():
        raise ValueError(
            "Existem valores financeiros com precisão inválida."
        )

    if df["valor"].map(
        lambda valor: valor < Decimal("0.00")
    ).any():
        raise ValueError("Existem despesas negativas.")

    dimensoes = [
        "cod_ibge",
        "ano",
        "codigo_classificacao",
        "codigo_estagio",
        "codigo_anexo",
    ]

    if df.duplicated(subset=dimensoes).any():
        raise ValueError(
            "Existem despesas duplicadas na Curated."
        )

    if df["chave_negocio"].duplicated().any():
        raise ValueError("Chave de negócio duplicada.")

    logger.info("Arquivos Curados selecionados: %s", len(arquivos))
    logger.info("Registros fiscais validados: %s", len(df))

    return df, arquivos


def inserir_hub_validado(cursor, tipo, hk, codigo):
    """
    Insere um Hub e valida a correspondência entre Hash Key e código.
    Os identificadores SQL são definidos exclusivamente nesta lista.
    """

    configuracoes = {
        "localidade": (
            """
            INSERT INTO raw_vault.hub_localidade
                (localidade_hk, codigo_ibge, record_source)
            VALUES (%s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            """
            SELECT localidade_hk, codigo_ibge
            FROM raw_vault.hub_localidade
            WHERE localidade_hk = %s OR codigo_ibge = %s
            """,
        ),
        "periodo": (
            """
            INSERT INTO raw_vault.hub_periodo
                (periodo_hk, ano, record_source)
            VALUES (%s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            """
            SELECT periodo_hk, ano
            FROM raw_vault.hub_periodo
            WHERE periodo_hk = %s OR ano = %s
            """,
        ),
        "classificacao": (
            """
            INSERT INTO raw_vault.hub_classificacao_funcional
                (classificacao_hk, codigo_classificacao, record_source)
            VALUES (%s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            """
            SELECT classificacao_hk, codigo_classificacao
            FROM raw_vault.hub_classificacao_funcional
            WHERE classificacao_hk = %s OR codigo_classificacao = %s
            """,
        ),
        "estagio": (
            """
            INSERT INTO raw_vault.hub_estagio_despesa
                (estagio_hk, codigo_estagio, record_source)
            VALUES (%s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            """
            SELECT estagio_hk, codigo_estagio
            FROM raw_vault.hub_estagio_despesa
            WHERE estagio_hk = %s OR codigo_estagio = %s
            """,
        ),
        "anexo": (
            """
            INSERT INTO raw_vault.hub_anexo
                (anexo_hk, codigo_anexo, record_source)
            VALUES (%s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            """
            SELECT anexo_hk, codigo_anexo
            FROM raw_vault.hub_anexo
            WHERE anexo_hk = %s OR codigo_anexo = %s
            """,
        ),
    }

    if tipo not in configuracoes:
        raise ValueError(f"Tipo de Hub não permitido: {tipo}")

    sql_insert, sql_validacao = configuracoes[tipo]

    cursor.execute(sql_insert, (hk, codigo, FONTE))
    inseridos = cursor.rowcount

    cursor.execute(sql_validacao, (hk, codigo))
    encontrados = cursor.fetchall()

    if len(encontrados) != 1 or encontrados[0] != (hk, codigo):
        raise RuntimeError(
            f"Inconsistência no Hub {tipo}: "
            f"Hash Key e código não correspondem. "
            f"Esperado=({hk}, {codigo}); encontrado={encontrados}"
        )

    return inseridos


def inserir_hub_localidade(cursor, hk, codigo):
    return inserir_hub_validado(cursor, "localidade", hk, codigo)


def inserir_hub_periodo(cursor, hk, ano):
    return inserir_hub_validado(cursor, "periodo", hk, ano)


def inserir_hub_classificacao(cursor, hk, codigo):
    return inserir_hub_validado(cursor, "classificacao", hk, codigo)


def inserir_hub_estagio(cursor, hk, codigo):
    return inserir_hub_validado(cursor, "estagio", hk, codigo)


def inserir_hub_anexo(cursor, hk, codigo):
    return inserir_hub_validado(cursor, "anexo", hk, codigo)


def inserir_link(cursor, chaves):
    """
    Insere o Link fiscal e valida sua Hash Key e suas cinco relações.
    """

    if len(chaves) != 6:
        raise ValueError(
            "O Link fiscal precisa de seis chaves: "
            "despesa_hk e cinco Hash Keys de referência."
        )

    despesa_hk, localidade_hk, periodo_hk, classificacao_hk, estagio_hk, anexo_hk = chaves

    componentes = (
        localidade_hk,
        periodo_hk,
        classificacao_hk,
        estagio_hk,
        anexo_hk,
    )

    hash_esperada = hash_texto("|".join(componentes))

    if despesa_hk != hash_esperada:
        raise RuntimeError(
            "Hash Key do Link fiscal inválida. "
            "A despesa_hk não corresponde às cinco chaves relacionadas."
        )

    cursor.execute(
        """
        INSERT INTO raw_vault.link_despesa_fiscal (
            despesa_hk,
            localidade_hk,
            periodo_hk,
            classificacao_hk,
            estagio_hk,
            anexo_hk,
            record_source
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT DO NOTHING
        """,
        (*chaves, FONTE),
    )

    inseridos = cursor.rowcount

    cursor.execute(
        """
        SELECT
            despesa_hk,
            localidade_hk,
            periodo_hk,
            classificacao_hk,
            estagio_hk,
            anexo_hk
        FROM raw_vault.link_despesa_fiscal
        WHERE despesa_hk = %s
           OR (
                localidade_hk = %s
                AND periodo_hk = %s
                AND classificacao_hk = %s
                AND estagio_hk = %s
                AND anexo_hk = %s
           )
        """,
        (despesa_hk, *componentes),
    )

    encontrados = cursor.fetchall()

    if len(encontrados) != 1 or tuple(encontrados[0]) != tuple(chaves):
        raise RuntimeError(
            "Inconsistência no Link fiscal. "
            f"Esperado={chaves}; encontrado={encontrados}"
        )

    return inseridos


def inserir_satellite(
    cursor,
    despesa_hk,
    batch_id,
    hashdiff,
    atributos,
):
    """
    Insere nova versão do Satellite com proteção contra concorrência.

    Serializa operações por despesa_hk, evita versões idênticas
    e detecta conflitos de batch com hashdiff divergente.
    """

    # Bloqueio transacional exclusivo para esta despesa.
    cursor.execute(
        """
        SELECT pg_advisory_xact_lock(
            hashtextextended(%s, 0)
        )
        """,
        (despesa_hk,),
    )

    # Consulta a última versão após obter o bloqueio.
    cursor.execute(
        """
        SELECT hashdiff
        FROM raw_vault.sat_despesa_fiscal
        WHERE despesa_hk = %s
        ORDER BY load_dts DESC
        LIMIT 1
        """,
        (despesa_hk,),
    )

    ultima_versao = cursor.fetchone()

    if ultima_versao and ultima_versao[0].strip() == hashdiff:
        return 0

    cursor.execute(
        """
        INSERT INTO raw_vault.sat_despesa_fiscal (
            despesa_hk,
            batch_id,
            hashdiff,
            valor,
            cod_conta,
            conta,
            rotulo,
            instituicao,
            uf,
            populacao,
            data_coleta_utc,
            arquivo_origem,
            url_origem,
            record_source,
            load_dts
        )
        VALUES (
            %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s,
            clock_timestamp()
        )
        ON CONFLICT (despesa_hk, batch_id) DO NOTHING
        """,
        (
            despesa_hk,
            batch_id,
            hashdiff,
            atributos["valor"],
            atributos["cod_conta"],
            atributos["conta"],
            atributos["rotulo"],
            atributos["instituicao"],
            atributos["uf"],
            atributos["populacao"],
            atributos["data_coleta_utc"],
            atributos["arquivo_origem"],
            atributos["url_origem"],
            FONTE,
        ),
    )

    inseridos = cursor.rowcount

    if inseridos == 0:
        cursor.execute(
            """
            SELECT hashdiff
            FROM raw_vault.sat_despesa_fiscal
            WHERE despesa_hk = %s
              AND batch_id = %s
            """,
            (despesa_hk, batch_id),
        )

        existente = cursor.fetchone()

        if not existente or existente[0].strip() != hashdiff:
            raise RuntimeError(
                "Conflito no Satellite: o mesmo batch_id já existe "
                "com hashdiff diferente."
            )

    return inseridos


def registrar_inicio(batch_id, arquivos, registros):
    """
    Registra o início de uma execução.

    SUCCESS: não permite repetir o batch.
    RUNNING: impede execução concorrente do mesmo batch.
    FAILED: permite uma nova tentativa.
    """

    try:
        with conectar() as conexao:
            with conexao.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT status
                    FROM raw_vault.audit_batch
                    WHERE batch_id = %s
                      AND pipeline_name = %s
                      AND status IN ('RUNNING', 'SUCCESS')
                    ORDER BY started_at DESC
                    LIMIT 1
                    """,
                    (batch_id, PIPELINE_NAME),
                )

                existente = cursor.fetchone()

                if existente:
                    status = existente[0]

                    if status == "SUCCESS":
                        logger.info(
                            "Batch já concluído anteriormente: %s",
                            batch_id,
                        )
                        return None

                    raise RuntimeError(
                        "Já existe uma execução RUNNING para este batch."
                    )

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
                        PIPELINE_NAME,
                        SOURCE_NAME,
                        len(arquivos),
                        registros,
                        json.dumps(
                            {
                                "arquivos": [
                                    str(
                                        arquivo.relative_to(BASE_CURADO)
                                    )
                                    for arquivo in arquivos
                                ]
                            },
                            ensure_ascii=False,
                        ),
                    ),
                )

                return cursor.fetchone()[0]

    except psycopg.errors.UniqueViolation as erro:
        raise RuntimeError(
            "Outra execução já iniciou ou concluiu este batch."
        ) from erro


def registrar_sucesso(batch_run_id, totais):
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



def registrar_sucesso_na_transacao(cursor, batch_run_id, totais):
    """
    Atualiza a auditoria SUCCESS na mesma transação dos dados fiscais.
    """

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
        "hub_periodo": 0,
        "hub_classificacao_funcional": 0,
        "hub_estagio_despesa": 0,
        "hub_anexo": 0,
        "link_despesa_fiscal": 0,
        "sat_despesa_fiscal": 0,
    }

    batch_run_id = registrar_inicio(
        batch_id,
        arquivos,
        len(df),
    )

    if batch_run_id is None:
        logger.info(
            "Batch já processado. Nenhuma inserção será realizada."
        )
        return

    logger.info(
        "Auditoria iniciada. ID: %s",
        batch_run_id,
    )

    try:
        with conectar() as conexao:
            with conexao.cursor() as cursor:

                for _, linha in df.iterrows():
                    codigo = str(linha["cod_ibge"]).strip()
                    ano = int(linha["ano"])

                    classificacao = str(
                        linha["codigo_classificacao"]
                    ).strip()

                    estagio = str(
                        linha["codigo_estagio"]
                    ).strip()

                    anexo = str(
                        linha["codigo_anexo"]
                    ).strip()

                    # Hubs compartilhados.
                    localidade_hk = hash_texto(codigo)
                    periodo_hk = hash_texto(str(ano))

                    totais["hub_localidade"] += (
                        inserir_hub_localidade(
                            cursor,
                            localidade_hk,
                            codigo,
                        )
                    )

                    totais["hub_periodo"] += (
                        inserir_hub_periodo(
                            cursor,
                            periodo_hk,
                            ano,
                        )
                    )

                    # Hubs fiscais.
                    classificacao_hk = hash_texto(classificacao)
                    estagio_hk = hash_texto(estagio)
                    anexo_hk = hash_texto(anexo)

                    totais["hub_classificacao_funcional"] += (
                        inserir_hub_classificacao(
                            cursor,
                            classificacao_hk,
                            classificacao,
                        )
                    )

                    totais["hub_estagio_despesa"] += (
                        inserir_hub_estagio(
                            cursor,
                            estagio_hk,
                            estagio,
                        )
                    )

                    totais["hub_anexo"] += inserir_hub_anexo(
                        cursor,
                        anexo_hk,
                        anexo,
                    )

                    # Link fiscal.
                    despesa_hk = hash_texto(
                        "|".join(
                            [
                                localidade_hk,
                                periodo_hk,
                                classificacao_hk,
                                estagio_hk,
                                anexo_hk,
                            ]
                        )
                    )

                    totais["link_despesa_fiscal"] += inserir_link(
                        cursor,
                        (
                            despesa_hk,
                            localidade_hk,
                            periodo_hk,
                            classificacao_hk,
                            estagio_hk,
                            anexo_hk,
                        ),
                    )

                    # Atributos do Satellite.
                    atributos = {
                        "valor": linha["valor"],
                        "cod_conta": linha["cod_conta"],
                        "conta": linha["conta"],
                        "rotulo": linha["rotulo"],
                        "instituicao": linha["instituicao"],
                        "uf": linha["uf"],
                        "populacao": (
                            int(linha["populacao"])
                            if pd.notna(linha["populacao"])
                            else None
                        ),
                        "data_coleta_utc": normalizar_data(
                            linha["data_coleta_utc"]
                        ),
                        "arquivo_origem": linha["arquivo_origem"],
                        "url_origem": linha["url_origem"],
                    }

                    # Metadados operacionais não provocam
                    # uma nova versão financeira.
                    atributos_hash = {
                        "valor": str(atributos["valor"]),
                        "cod_conta": atributos["cod_conta"],
                        "conta": atributos["conta"],
                        "rotulo": atributos["rotulo"],
                        "instituicao": atributos["instituicao"],
                        "uf": atributos["uf"],
                        "populacao": atributos["populacao"],
                    }

                    hashdiff = hash_atributos(atributos_hash)

                    totais["sat_despesa_fiscal"] += (
                        inserir_satellite(
                            cursor,
                            despesa_hk,
                            batch_id,
                            hashdiff,
                            atributos,
                        )
                    )

                # Auditoria SUCCESS na mesma transação dos dados.
                registrar_sucesso_na_transacao(
                    cursor,
                    batch_run_id,
                    totais,
                )

        logger.info("Carga fiscal concluída com sucesso.")

        for tabela, quantidade in totais.items():
            logger.info(
                "%s: %s novos registros",
                tabela,
                quantidade,
            )

    except Exception as erro:
        try:
            registrar_falha(batch_run_id, erro)
        except Exception:
            logger.exception(
                "Falha ao registrar o erro na auditoria."
            )

        logger.exception("Carga fiscal interrompida.")
        raise


if __name__ == "__main__":
    carregar()
