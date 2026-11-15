import argparse
import hashlib
import json
import logging

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


FONTE = "datasus_mortalidade_infantil"
INDICADOR = "Taxa de mortalidade infantil (por mil nascidos vivos)"

CODIGO_FERNANDO_DE_NORONHA = "2605459"

LANDING = Path(
    "lakehouse/landing/condepe"
)

CURADO = Path(
    "lakehouse/curado/saude/mortalidade_infantil"
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger("pe_inteligencia.curadoria")


def calcular_hash(caminho: Path) -> str:
    sha = hashlib.sha256()

    with caminho.open("rb") as arquivo:
        for bloco in iter(
            lambda: arquivo.read(1024 * 1024),
            b"",
        ):
            sha.update(bloco)

    return sha.hexdigest()


def classificar_localidade(codigo: str) -> str:
    if codigo == CODIGO_FERNANDO_DE_NORONHA:
        return "DISTRITO_ESTADUAL"

    return "MUNICIPIO"


def validar_cobertura(df: pd.DataFrame, ano: int) -> None:
    if len(df) != 185:
        raise ValueError(
            f"Ano {ano}: esperadas 185 localidades; "
            f"recebidas {len(df)}."
        )

    noronha = df[
        df["cd_municipio_ibge"]
        == CODIGO_FERNANDO_DE_NORONHA
    ]

    if len(noronha) != 1:
        raise ValueError(
            "Fernando de Noronha deve aparecer exatamente uma vez."
        )

    if noronha.iloc[0]["nm_municipio"] != "Fernando de Noronha":
        raise ValueError(
            "Código territorial de Fernando de Noronha "
            "associado a nome inesperado."
        )

    municipios = df[
        df["cd_municipio_ibge"]
        != CODIGO_FERNANDO_DE_NORONHA
    ]

    if municipios["cd_municipio_ibge"].nunique() != 184:
        raise ValueError(
            "A cobertura dos 184 municípios não foi confirmada."
        )


def transformar(df: pd.DataFrame, ano: int) -> pd.DataFrame:
    """Padroniza os dados recebidos da Landing."""

    if df.empty:
        raise ValueError("Não existem dados para transformar.")

    obrigatorias = [
        "cd_municipio_ibge",
        "nm_municipio",
        "ano",
        "valor",
        "unidade",
        "natureza",
        "fonte_original",
        "id_fonte",
        "data_coleta_utc",
        "url_origem",
    ]

    ausentes = [
        coluna for coluna in obrigatorias
        if coluna not in df.columns
    ]

    if ausentes:
        raise ValueError(
            f"Colunas obrigatórias ausentes: {ausentes}"
        )

    df = df.copy()

    # Padronização dos tipos.
    df["cd_municipio_ibge"] = (
        df["cd_municipio_ibge"].astype("string")
    )

    df["nm_municipio"] = (
        df["nm_municipio"].astype("string").str.strip()
    )

    df["ano"] = pd.to_numeric(
        df["ano"], errors="raise"
    ).astype("int64")

    df["valor"] = pd.to_numeric(
        df["valor"], errors="raise"
    ).astype("float64")

    if not df["ano"].eq(ano).all():
        raise ValueError("Existem registros de outro ano.")

    if df["cd_municipio_ibge"].isna().any():
        raise ValueError("Código IBGE ausente.")

    if not df["cd_municipio_ibge"].str.fullmatch(
        r"26\d{5}"
    ).all():
        raise ValueError("Código IBGE fora do padrão de Pernambuco.")

    if df["nm_municipio"].isna().any():
        raise ValueError("Nome da localidade ausente.")

    if df["valor"].isna().any() or (df["valor"] < 0).any():
        raise ValueError("Indicador nulo ou negativo.")

    if not df["natureza"].eq("estoque").all():
        raise ValueError("Natureza do indicador inesperada.")

    # O indicador é anual. O campo mes deve permanecer nulo.
    if "mes" in df.columns and df["mes"].notna().any():
        raise ValueError(
            "Indicador anual contém competência mensal inesperada."
        )

    # Verifica duplicidades antes da quantidade de localidades.
    if df.duplicated(
        subset=["cd_municipio_ibge", "ano"]
    ).any():
        raise ValueError("Duplicidade de município e ano.")

    validar_cobertura(df, ano)

    # Classificação territorial explícita.
    df["tipo_localidade"] = (
        df["cd_municipio_ibge"]
        .map(classificar_localidade)
    )

    df["periodicidade"] = "ANUAL"
    df["indicador"] = INDICADOR

    # Chave de negócio determinística.
    df["chave_negocio"] = (
        df["id_fonte"].astype(str)
        + "|"
        + df["cd_municipio_ibge"].astype(str)
        + "|"
        + df["ano"].astype(str)
    )

    if df["chave_negocio"].duplicated().any():
        raise ValueError("Chave de negócio duplicada.")

    colunas = [
        "chave_negocio",
        "id_fonte",
        "indicador",
        "cd_municipio_ibge",
        "nm_municipio",
        "tipo_localidade",
        "ano",
        "periodicidade",
        "mes",
        "valor",
        "unidade",
        "natureza",
        "fonte_original",
        "arquivo_origem",
        "data_coleta_utc",
        "url_origem",
    ]

    return df[colunas].sort_values(
        ["cd_municipio_ibge", "ano"]
    ).reset_index(drop=True)


def processar_ano(ano: int) -> Path:
    origem = (
        LANDING
        / FONTE
        / f"ano={ano}"
        / "observacoes.parquet"
    )

    if not origem.exists():
        raise FileNotFoundError(
            f"Arquivo de origem não encontrado: {origem}"
        )

    logger.info("Lendo Landing: %s", origem)

    bruto = pd.read_parquet(origem)

    curado = transformar(bruto, ano)

    destino = (
        CURADO
        / f"ano={ano}"
    )

    destino.mkdir(parents=True, exist_ok=True)

    arquivo_final = destino / "observacoes.parquet"
    arquivo_temporario = destino / "observacoes.parquet.tmp"

    curado.to_parquet(
        arquivo_temporario,
        engine="pyarrow",
        compression="zstd",
        index=False,
    )

    arquivo_temporario.replace(arquivo_final)

    manifesto = {
        "fonte": FONTE,
        "ano": ano,
        "camada": "CURATED",
        "quantidade_registros": len(curado),
        "municipios": int(
            (curado["tipo_localidade"] == "MUNICIPIO").sum()
        ),
        "distritos_estaduais": int(
            (curado["tipo_localidade"] == "DISTRITO_ESTADUAL").sum()
        ),
        "periodicidade": "ANUAL",
        "hash_origem_sha256": calcular_hash(origem),
        "hash_curado_sha256": calcular_hash(arquivo_final),
        "processado_em_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "arquivo": arquivo_final.name,
    }

    manifesto_path = destino / "manifesto.json"
    temporario = destino / "manifesto.json.tmp"

    temporario.write_text(
        json.dumps(
            manifesto,
            ensure_ascii=False,
            indent=4,
        ),
        encoding="utf-8",
    )

    temporario.replace(manifesto_path)

    logger.info(
        "Ano %s curado: %s registros",
        ano,
        len(curado),
    )

    return arquivo_final


def main():
    parser = argparse.ArgumentParser(
        description="Curadoria de mortalidade infantil de Pernambuco"
    )

    parser.add_argument(
        "--anos",
        nargs="+",
        type=int,
        default=[2022, 2023, 2024],
    )

    args = parser.parse_args()

    for ano in args.anos:
        if ano not in [2022, 2023, 2024]:
            raise ValueError(f"Ano não autorizado no MVP: {ano}")

        processar_ano(ano)


if __name__ == "__main__":
    main()
