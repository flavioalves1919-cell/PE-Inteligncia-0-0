import argparse
import hashlib
import json
import logging
import os
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


API_URL = "https://apidatalake.tesouro.gov.br/ords/siconfi/tt/dca"

ID_FONTE = "siconfi_dca"
ANEXO = "DCA-Anexo I-E"

LIMITE_PAGINA = 5000
INTERVALO_REQUISICOES = 1.0
CENTAVO = Decimal("0.01")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger("pe_inteligencia.siconfi")


def criar_sessao() -> requests.Session:
    """Cria sessão HTTP com tentativas automáticas."""

    retry = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=frozenset(["GET"]),
        respect_retry_after_header=True,
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


def converter_valor_decimal(valor) -> Decimal:
    """Converte valor monetário sem utilizar ponto flutuante."""

    if valor is None or pd.isna(valor):
        raise ValueError("Valor contábil ausente.")

    try:
        resultado = (
            valor
            if isinstance(valor, Decimal)
            else Decimal(str(valor))
        )
    except (InvalidOperation, ValueError, TypeError) as erro:
        raise ValueError(
            f"Valor contábil inválido: {valor!r}"
        ) from erro

    if not resultado.is_finite():
        raise ValueError(
            f"Valor contábil não finito: {valor!r}"
        )

    if resultado != resultado.quantize(CENTAVO):
        raise ValueError(
            f"Valor possui mais de duas casas decimais: {valor!r}"
        )

    return resultado.quantize(CENTAVO)


def coletar_dca(
    session: requests.Session,
    ano: int,
    codigo_ibge: str,
) -> tuple[pd.DataFrame, list[str]]:
    """Coleta todas as páginas do DCA para um município e exercício."""

    logger.info(
        "Iniciando coleta SICONFI: ano=%s, município=%s, anexo=%s",
        ano,
        codigo_ibge,
        ANEXO,
    )

    offset = 0
    registros = []
    urls_consultadas = []
    paginas = 0
    ultima_requisicao = 0.0

    while True:
        decorrido = time.monotonic() - ultima_requisicao
        espera = INTERVALO_REQUISICOES - decorrido

        if espera > 0:
            time.sleep(espera)

        parametros = {
            "an_exercicio": ano,
            "id_ente": codigo_ibge,
            "no_anexo": ANEXO,
            "limit": LIMITE_PAGINA,
            "offset": offset,
        }

        logger.info(
            "Consultando página %s | offset=%s",
            paginas + 1,
            offset,
        )

        resposta = session.get(
            API_URL,
            params=parametros,
            timeout=(5, 30),
        )

        ultima_requisicao = time.monotonic()
        resposta.raise_for_status()

        # parse_float mantém os números decimais como Decimal.
        dados = json.loads(
            resposta.text,
            parse_float=Decimal,
        )

        if not isinstance(dados, dict):
            raise ValueError("A API retornou uma estrutura inesperada.")

        itens = dados.get("items")

        if not isinstance(itens, list):
            raise ValueError("A resposta não contém uma lista válida de itens.")

        if not itens:
            if paginas == 0:
                raise ValueError("A API não retornou registros.")

            raise ValueError(
                "A API informou que existem mais páginas, "
                "mas retornou uma página vazia."
            )

        registros.extend(itens)
        urls_consultadas.append(resposta.url)
        paginas += 1

        logger.info(
            "Página %s coletada: %s registros",
            paginas,
            len(itens),
        )

        has_more = dados.get("hasMore", False)

        if not isinstance(has_more, bool):
            raise ValueError("Campo hasMore inválido na resposta da API.")

        if not has_more:
            break

        novo_offset = offset + len(itens)

        if novo_offset <= offset:
            raise ValueError("Offset não avançou. Paginação interrompida.")

        offset = novo_offset

    df = pd.DataFrame(registros)

    colunas_obrigatorias = {
        "exercicio",
        "instituicao",
        "cod_ibge",
        "uf",
        "anexo",
        "rotulo",
        "coluna",
        "conta",
        "valor",
    }

    ausentes = colunas_obrigatorias - set(df.columns)

    if ausentes:
        raise ValueError(
            f"Colunas obrigatórias ausentes: {sorted(ausentes)}"
        )

    df["exercicio"] = pd.to_numeric(
        df["exercicio"],
        errors="raise",
    ).astype("int64")

    df["cod_ibge"] = (
        df["cod_ibge"]
        .astype("string")
        .str.replace(r"\.0$", "", regex=True)
        .str.zfill(7)
    )

    if not (df["exercicio"] == ano).all():
        raise ValueError("A API retornou exercícios diferentes do solicitado.")

    if not (df["cod_ibge"] == codigo_ibge).all():
        raise ValueError("A API retornou municípios diferentes do solicitado.")

    if not (df["anexo"] == ANEXO).all():
        raise ValueError("A API retornou anexos diferentes do solicitado.")

    # Mantém os valores como Decimal até a gravação no Parquet.
    df["valor"] = df["valor"].map(converter_valor_decimal)

    if df.astype("string").duplicated().any():
        raise ValueError("A API retornou registros integralmente duplicados.")

    data_coleta = datetime.now(timezone.utc).isoformat()

    df["id_fonte"] = ID_FONTE
    df["data_coleta_utc"] = data_coleta
    df["url_origem"] = API_URL

    logger.info(
        "Coleta validada: %s registros em %s página(s)",
        len(df),
        paginas,
    )

    logger.info(
        "Tipo dos valores financeiros: %s",
        type(df["valor"].iloc[0]).__name__,
    )

    return df, urls_consultadas


def salvar_landing(
    df: pd.DataFrame,
    ano: int,
    codigo_ibge: str,
    urls_consultadas: list[str],
    diretorio_saida: Path,
) -> Path:
    """Salva uma versão imutável dos dados e seu manifesto."""

    pasta = (
        diretorio_saida
        / "dca_anexo_i_e"
        / f"ano={ano}"
        / f"municipio={codigo_ibge}"
    )

    pasta.mkdir(parents=True, exist_ok=True)

    identificador = datetime.now(timezone.utc).strftime(
        "%Y%m%dT%H%M%S%fZ"
    )

    nome_arquivo = f"observacoes_{identificador}.parquet"
    arquivo_final = pasta / nome_arquivo
    arquivo_temporario = pasta / f".{nome_arquivo}.tmp"

    if arquivo_final.exists():
        raise FileExistsError(
            f"Arquivo de coleta já existe: {arquivo_final}"
        )

    try:
        df.to_parquet(
            arquivo_temporario,
            engine="pyarrow",
            compression="zstd",
            index=False,
        )

        os.replace(arquivo_temporario, arquivo_final)

    finally:
        if arquivo_temporario.exists():
            arquivo_temporario.unlink()

    hash_arquivo = calcular_sha256(arquivo_final)

    manifesto = {
        "id_fonte": ID_FONTE,
        "sistema": "SICONFI - Tesouro Nacional",
        "tipo_declaracao": "DCA",
        "anexo": ANEXO,
        "ano": ano,
        "codigo_ibge": codigo_ibge,
        "quantidade_registros": len(df),
        "quantidade_paginas": len(urls_consultadas),
        "data_coleta_utc": df["data_coleta_utc"].iloc[0],
        "endpoint": API_URL,
        "urls_consultadas": urls_consultadas,
        "arquivo": nome_arquivo,
        "formato": "parquet",
        "compressao": "zstd",
        "sha256": hash_arquivo,
        "status": "SUCESSO",
    }

    arquivo_manifesto = pasta / f"manifesto_{identificador}.json"
    temporario_manifesto = pasta / f".manifesto_{identificador}.json.tmp"

    try:
        temporario_manifesto.write_text(
            json.dumps(
                manifesto,
                ensure_ascii=False,
                indent=4,
            ),
            encoding="utf-8",
        )

        os.replace(temporario_manifesto, arquivo_manifesto)

    finally:
        if temporario_manifesto.exists():
            temporario_manifesto.unlink()

    logger.info("Parquet salvo: %s", arquivo_final)
    logger.info("SHA-256: %s", hash_arquivo)
    logger.info("Manifesto salvo: %s", arquivo_manifesto)

    return arquivo_final

def executar(
    ano: int,
    codigo_ibge: str,
    diretorio_saida: Path,
) -> None:
    """Executa a coleta e persistência do município solicitado."""

    if ano < 2013 or ano > datetime.now().year:
        raise ValueError(f"Exercício inválido: {ano}")

    if not codigo_ibge.isdigit() or len(codigo_ibge) != 7:
        raise ValueError("O código IBGE deve conter exatamente 7 dígitos.")

    with criar_sessao() as session:
        df, urls = coletar_dca(
            session=session,
            ano=ano,
            codigo_ibge=codigo_ibge,
        )

        caminho = salvar_landing(
            df=df,
            ano=ano,
            codigo_ibge=codigo_ibge,
            urls_consultadas=urls,
            diretorio_saida=diretorio_saida,
        )

        logger.info(
            "Coleta concluída. Registros: %s | Arquivo: %s",
            len(df),
            caminho,
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Conector de dados fiscais do SICONFI"
    )

    parser.add_argument(
        "--ano",
        type=int,
        default=2024,
        help="Exercício da declaração.",
    )

    parser.add_argument(
        "--municipio",
        type=str,
        default="2611606",
        help="Código IBGE do município.",
    )

    parser.add_argument(
        "--saida",
        type=Path,
        default=Path("lakehouse/landing/siconfi"),
        help="Diretório de saída dos arquivos Parquet.",
    )

    args = parser.parse_args()

    executar(
        ano=args.ano,
        codigo_ibge=args.municipio,
        diretorio_saida=args.saida,
    )


if __name__ == "__main__":
    main()
