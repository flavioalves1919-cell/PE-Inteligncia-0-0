from datetime import date, datetime
from decimal import Decimal

import psycopg
from fastapi import FastAPI, HTTPException, Query
from psycopg.rows import dict_row

from api.database import conectar

app = FastAPI(
    title="PE Inteligência API",
    description="Plataforma de inteligência fiscal e saúde pública de Pernambuco.",
    version="1.0.0",
)


def executar_consulta(sql, parametros=()):
    try:
        with conectar() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(sql, parametros)
                registros = cursor.fetchall()

        resultado = []

        for registro in registros:
            linha = {}

            for chave, valor in registro.items():
                if isinstance(valor, Decimal):
                    linha[chave] = str(valor)
                elif isinstance(valor, (date, datetime)):
                    linha[chave] = valor.isoformat()
                else:
                    linha[chave] = valor

            resultado.append(linha)

        return resultado

    except (psycopg.Error, RuntimeError):
        raise HTTPException(
            status_code=503,
            detail="Não foi possível consultar o banco de dados.",
        )


@app.get("/")
def inicio():
    return {
        "plataforma": "PE Inteligência",
        "versao": "1.0.0",
        "status": "online",
    }


@app.get("/health")
def health():
    resultado = executar_consulta(
        "SELECT current_database() AS banco, current_user AS usuario"
    )
    return {
        "status": "healthy",
        "database": resultado[0]["banco"],
    }


@app.get("/saude/mortalidade-infantil")
def mortalidade_infantil(
    ano: int | None = Query(default=None, ge=1900, le=2100),
    codigo_ibge: str | None = Query(default=None, min_length=7, max_length=7),
):
    return executar_consulta(
        """
        SELECT *
        FROM business_vault.vw_mortalidade_infantil
        WHERE (%s::integer IS NULL OR ano = %s)
          AND (%s::text IS NULL OR codigo_ibge = %s)
        ORDER BY ano, codigo_ibge
        """,
        (ano, ano, codigo_ibge, codigo_ibge),
    )


@app.get("/fiscal/despesas")
def despesas_fiscais(
    ano: int | None = Query(default=None, ge=1900, le=2100),
    codigo_ibge: str | None = Query(default=None, min_length=7, max_length=7),
):
    return executar_consulta(
        """
        SELECT *
        FROM data_marts.vw_resumo_fiscal_saude
        WHERE (%s::integer IS NULL OR ano = %s)
          AND (%s::text IS NULL OR codigo_ibge = %s)
        ORDER BY ano, codigo_ibge, codigo_estagio
        """,
        (ano, ano, codigo_ibge, codigo_ibge),
    )


@app.get("/fiscal/execucao-orcamentaria")
def execucao_orcamentaria(
    ano: int | None = Query(default=None, ge=1900, le=2100),
    codigo_ibge: str | None = Query(default=None, min_length=7, max_length=7),
):
    return executar_consulta(
        """
        SELECT *
        FROM data_marts.vw_execucao_orcamentaria_saude
        WHERE (%s::integer IS NULL OR ano = %s)
          AND (%s::text IS NULL OR codigo_ibge = %s)
        ORDER BY ano, codigo_ibge
        """,
        (ano, ano, codigo_ibge, codigo_ibge),
    )


@app.get("/fiscal/detalhamento")
def detalhamento_fiscal(
    ano: int | None = Query(default=None, ge=1900, le=2100),
    codigo_ibge: str | None = Query(default=None, min_length=7, max_length=7),
):
    return executar_consulta(
        """
        SELECT *
        FROM data_marts.vw_detalhamento_fiscal_saude
        WHERE (%s::integer IS NULL OR ano = %s)
          AND (%s::text IS NULL OR codigo_ibge = %s)
        ORDER BY ano, codigo_ibge, codigo_classificacao, codigo_estagio
        """,
        (ano, ano, codigo_ibge, codigo_ibge),
    )
