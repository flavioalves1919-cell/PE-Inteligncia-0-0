import argparse
import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from motor_dados.validacao.contrato_saude import (
    validar_observacoes,
)


API_URL = "https://www.cf.pe.gov.br/api/observatorio/serie"

ID_FONTE = "datasus_mortalidade_infantil"

INDICADOR = (
    "Taxa de mortalidade infantil "
    "(por mil nascidos vivos)"
)

FONTE_ORIGINAL = "Ministério da Saúde (SIM / SINASC)"


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger("pe_inteligencia.condepe")


def criar_sessao() -> requests.Session:
    """Cria sessão HTTP com tentativas automáticas."""

    retry = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=frozenset(["GET"]),
    )

    adapter = HTTPAdapter(max_retries=retry)

    session = requests.Session()
    session.mount("https://", adapter)

    session.headers.update(
        {
            "User-Agent": "PE-Inteligencia/1.0",
            "Accept": "application/json",
        }
    )

    return session


def coletar_ano(
    session: requests.Session,
    ano: int,
) -> tuple[pd.DataFrame, str]:
    """Consulta a API e valida os registros de um ano."""

    logger.info("Iniciando coleta do ano %s", ano)

    parametros = {
        "fonte": ID_FONTE,
        "indicador": INDICADOR,
        "ano": ano,
    }

    resposta = session.get(
        API_URL,
        params=parametros,
        timeout=(10, 40),
    )

    resposta.raise_for_status()

    dados = resposta.json()

    if dados.get("fonte") != ID_FONTE:
        raise ValueError("A API retornou uma fonte inesperada.")

    if dados.get("ano") != ano:
        raise ValueError("A API retornou um ano inesperado.")

    if dados.get("truncado") is True:
        raise ValueError("A resposta da API está truncada.")

    observacoes = dados.get("observacoes")

    if not isinstance(observacoes, list) or not observacoes:
        raise ValueError("A API não retornou observações válidas.")

    df = pd.DataFrame(observacoes)

    # Garantir os tipos numéricos.
    df["ano"] = pd.to_numeric(
        df["ano"],
        errors="raise",
    ).astype("int64")

    df["valor"] = pd.to_numeric(
        df["valor"],
        errors="coerce",
    )

    # Validar antes de adicionar metadados.
    df = validar_observacoes(df, ano)

    # Metadados de rastreabilidade.
    df["id_fonte"] = ID_FONTE
    df["data_coleta_utc"] = datetime.now(
        timezone.utc
    ).isoformat()

    df["url_origem"] = resposta.url

    logger.info(
        "Validação aprovada: %s registros para %s",
        len(df),
        ano,
    )

    return df, resposta.url


def calcular_sha256(caminho: Path) -> str:
    """Calcula o hash SHA-256 de um arquivo."""

    sha256 = hashlib.sha256()

    with caminho.open("rb") as arquivo:
        for bloco in iter(
            lambda: arquivo.read(1024 * 1024),
            b"",
        ):
            sha256.update(bloco)

    return sha256.hexdigest()


def salvar_parquet(
    df: pd.DataFrame,
    ano: int,
    url_consultada: str,
    diretorio_saida: Path,
) -> Path:
    """Salva Parquet e manifesto de auditoria."""

    pasta = (
        diretorio_saida
        / ID_FONTE
        / f"ano={ano}"
    )

    pasta.mkdir(parents=True, exist_ok=True)

    arquivo_final = pasta / "observacoes.parquet"
    arquivo_temporario = pasta / "observacoes.parquet.tmp"

    df.to_parquet(
        arquivo_temporario,
        engine="pyarrow",
        compression="zstd",
        index=False,
    )

    os.replace(arquivo_temporario, arquivo_final)

    hash_arquivo = calcular_sha256(arquivo_final)

    manifesto = {
        "id_fonte": ID_FONTE,
        "indicador": INDICADOR,
        "ano": ano,
        "quantidade_registros": len(df),
        "quantidade_municipios_distintos": int(
            df["cd_municipio_ibge"].nunique()
        ),
        "data_coleta_utc": df["data_coleta_utc"].iloc[0],
        "url_consultada": url_consultada,
        "arquivo": arquivo_final.name,
        "formato": "parquet",
        "compressao": "zstd",
        "sha256": hash_arquivo,
    }

    arquivo_manifesto = pasta / "manifesto.json"
    temporario_manifesto = pasta / "manifesto.json.tmp"

    temporario_manifesto.write_text(
        json.dumps(
            manifesto,
            ensure_ascii=False,
            indent=4,
        ),
        encoding="utf-8",
    )

    os.replace(temporario_manifesto, arquivo_manifesto)

    logger.info("Parquet salvo: %s", arquivo_final)
    logger.info("SHA-256: %s", hash_arquivo)

    return arquivo_final


def executar(anos: list[int], diretorio_saida: Path) -> None:
    """Executa a coleta e persistência dos anos solicitados."""

    with criar_sessao() as session:
        for ano in anos:
            if ano < 2017 or ano > 2024:
                raise ValueError(
                    f"Ano fora do período disponível: {ano}"
                )

            df, url = coletar_ano(session, ano)

            caminho = salvar_parquet(
                df=df,
                ano=ano,
                url_consultada=url,
                diretorio_saida=diretorio_saida,
            )

            logger.info(
                "Ano %s concluído. Arquivo: %s",
                ano,
                caminho,
            )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Conector de dados do PE Inteligência"
    )

    parser.add_argument(
        "--anos",
        nargs="+",
        type=int,
        default=[2022],
        help="Anos que serão coletados.",
    )

    parser.add_argument(
        "--saida",
        type=Path,
        default=Path("lakehouse/landing/condepe"),
        help="Diretório de saída dos arquivos Parquet.",
    )

    args = parser.parse_args()

    executar(
        anos=args.anos,
        diretorio_saida=args.saida,
    )


if __name__ == "__main__":
    main()
