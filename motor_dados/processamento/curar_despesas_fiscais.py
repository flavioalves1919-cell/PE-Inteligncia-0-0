import argparse
import hashlib
import json
import logging
import os
import re

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pandas as pd


FONTE = "siconfi_dca"
ANEXO_ESPERADO = "DCA-Anexo I-E"

LANDING = Path("lakehouse/landing/siconfi/dca_anexo_i_e")
CURADO = Path("lakehouse/curado/fiscal/despesas_saude")

ESTAGIOS_ESPERADOS = {
    "Despesas Empenhadas",
    "Despesas Liquidadas",
    "Despesas Pagas",
    "Inscrição de Restos a Pagar Processados",
}

PADRAO_CLASSIFICACAO = re.compile(
    r"^\s*(FU\d{2}|\d{2}(?:\.\d{3})?)\s*-\s*(.+?)\s*$",
    re.IGNORECASE,
)

CLASSIFICACAO_SAUDE = re.compile(
    r"^(FU10|\d{2}(?:\.\d{3})?)$",
    re.IGNORECASE,
)

CENTAVO = Decimal("0.01")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger("pe_inteligencia.curadoria_fiscal")


def calcular_hash(caminho: Path) -> str:
    """Calcula SHA-256 em blocos para evitar consumo excessivo de memória."""

    sha = hashlib.sha256()

    with caminho.open("rb") as arquivo:
        for bloco in iter(
            lambda: arquivo.read(1024 * 1024),
            b"",
        ):
            sha.update(bloco)

    return sha.hexdigest()


def localizar_ultima_coleta(
    ano: int,
    codigo_ibge: str,
) -> tuple[Path, Path, dict]:
    """Localiza a coleta versionada mais recente e valida seu manifesto."""

    pasta = (
        LANDING
        / f"ano={ano}"
        / f"municipio={codigo_ibge}"
    )

    arquivos = sorted(pasta.glob("observacoes_*.parquet"))

    if not arquivos:
        raise FileNotFoundError(
            f"Nenhum Parquet versionado encontrado em {pasta}"
        )

    origem = arquivos[-1]

    manifesto_path = pasta / origem.name.replace(
        "observacoes_", "manifesto_"
    ).replace(".parquet", ".json")

    if not manifesto_path.exists():
        raise FileNotFoundError(
            f"Manifesto correspondente não encontrado: {manifesto_path}"
        )

    manifesto = json.loads(
        manifesto_path.read_text(encoding="utf-8")
    )

    if manifesto.get("status") != "SUCESSO":
        raise ValueError("Manifesto da coleta não indica SUCESSO.")

    if manifesto.get("arquivo") != origem.name:
        raise ValueError("Arquivo indicado no manifesto não corresponde.")

    if manifesto.get("ano") != ano:
        raise ValueError("Ano do manifesto diferente do solicitado.")

    if str(manifesto.get("codigo_ibge")) != codigo_ibge:
        raise ValueError("Código IBGE do manifesto diferente do solicitado.")

    if manifesto.get("anexo") != ANEXO_ESPERADO:
        raise ValueError("Anexo do manifesto diferente do esperado.")

    hash_real = calcular_hash(origem)

    if hash_real != manifesto.get("sha256"):
        raise ValueError("Hash SHA-256 do Landing não confere.")

    logger.info("Landing validado: %s", origem)
    logger.info("SHA-256 da origem confirmado.")

    return origem, manifesto_path, manifesto


def extrair_classificacao(conta: str) -> tuple[str, str]:
    """Extrai o código e a descrição da classificação funcional."""

    resultado = PADRAO_CLASSIFICACAO.match(str(conta))

    if not resultado:
        raise ValueError(
            f"Classificação funcional fora do padrão: {conta!r}"
        )

    codigo = resultado.group(1).upper()
    descricao = resultado.group(2).strip()

    if not CLASSIFICACAO_SAUDE.fullmatch(codigo):
        raise ValueError(
            f"Código de classificação inesperado: {codigo}"
        )

    return codigo, descricao


def validar_reconciliacao(df: pd.DataFrame) -> None:
    """Confere se as subfunções fecham com o total da função Saúde."""

    estagios_encontrados = set(df["codigo_estagio"].unique())

    ausentes = ESTAGIOS_ESPERADOS - estagios_encontrados

    if ausentes:
        raise ValueError(
            f"Estágios esperados ausentes: {sorted(ausentes)}"
        )

    for estagio in sorted(ESTAGIOS_ESPERADOS):
        grupo = df[df["codigo_estagio"] == estagio]

        total_funcao = grupo[
            grupo["codigo_classificacao"] == "10"
        ]

        subfuncoes = grupo[
            grupo["codigo_classificacao"] != "10"
        ]

        if len(total_funcao) != 1:
            raise ValueError(
                f"{estagio}: esperado exatamente um total da função Saúde; "
                f"encontrados {len(total_funcao)}."
            )

        if subfuncoes.empty:
            raise ValueError(
                f"{estagio}: nenhuma subfunção encontrada."
            )

        valor_total = total_funcao["valor"].iloc[0]
        soma_subfuncoes = sum(
            subfuncoes["valor"],
            Decimal("0.00"),
        )

        diferenca = valor_total - soma_subfuncoes

        logger.info(
            "%s | total=%s | subfunções=%s | diferença=%s",
            estagio,
            valor_total,
            soma_subfuncoes,
            diferenca,
        )

        if diferenca != Decimal("0.00"):
            raise ValueError(
                f"Falha na reconciliação do estágio {estagio}: "
                f"diferença de {diferenca}."
            )


def transformar(
    bruto: pd.DataFrame,
    ano: int,
    codigo_ibge: str,
    arquivo_origem: str,
) -> pd.DataFrame:
    """Filtra, padroniza e valida as despesas da função Saúde."""

    if bruto.empty:
        raise ValueError("Landing vazio.")

    obrigatorias = [
        "exercicio",
        "instituicao",
        "cod_ibge",
        "uf",
        "anexo",
        "rotulo",
        "coluna",
        "cod_conta",
        "conta",
        "valor",
        "populacao",
        "id_fonte",
        "data_coleta_utc",
        "url_origem",
    ]

    ausentes = [
        coluna
        for coluna in obrigatorias
        if coluna not in bruto.columns
    ]

    if ausentes:
        raise ValueError(
            f"Colunas obrigatórias ausentes: {ausentes}"
        )

    df = bruto.copy()

    df["cod_ibge"] = (
        df["cod_ibge"]
        .astype("string")
        .str.strip()
    )

    df["exercicio"] = pd.to_numeric(
        df["exercicio"],
        errors="raise",
    ).astype("int64")

    if not df["exercicio"].eq(ano).all():
        raise ValueError("Existem registros de outro exercício.")

    if not df["cod_ibge"].eq(codigo_ibge).all():
        raise ValueError("Existem registros de outro município.")

    if not df["anexo"].eq(ANEXO_ESPERADO).all():
        raise ValueError("Existem registros de outro anexo.")

    if not df["id_fonte"].eq(FONTE).all():
        raise ValueError("Identificador de fonte inesperado.")

    # Filtra a função Saúde e suas subfunções.
    mascara_saude = df["conta"].astype("string").str.match(
        r"^\s*(10\s*-\s*Saúde|10\.\d{3}\s*-|FU10\b)",
        case=False,
        na=False,
    )

    df = df.loc[mascara_saude].copy()

    if df.empty:
        raise ValueError("Nenhum registro da função Saúde encontrado.")

    classificacoes = df["conta"].map(extrair_classificacao)

    df["codigo_classificacao"] = classificacoes.map(
        lambda item: item[0]
    )

    df["descricao_classificacao"] = classificacoes.map(
        lambda item: item[1]
    )

    df["tipo_classificacao"] = df["codigo_classificacao"].map(
        lambda codigo: (
            "FUNCAO" if codigo == "10" else "SUBFUNCAO"
        )
    )

    df["nivel_agregacao"] = df["tipo_classificacao"].map(
        {
            "FUNCAO": "TOTAL_FUNCAO",
            "SUBFUNCAO": "DETALHE_SUBFUNCAO",
        }
    )

    # Não permite que valores financeiros passem por float.
    if not df["valor"].map(
        lambda valor: isinstance(valor, Decimal)
    ).all():
        raise TypeError(
            "Valores financeiros não estão em Decimal. "
            "Verifique a coleta e o Parquet de origem."
        )

    if not df["valor"].map(
        lambda valor: valor.is_finite()
    ).all():
        raise ValueError("Existem valores financeiros não finitos.")

    if not df["valor"].map(
        lambda valor: valor == valor.quantize(CENTAVO)
    ).all():
        raise ValueError(
            "Existem valores financeiros com mais de duas casas decimais."
        )

    if df["valor"].map(
        lambda valor: valor < Decimal("0.00")
    ).any():
        raise ValueError("Existem despesas com valores negativos.")

    df["codigo_estagio"] = (
        df["coluna"].astype("string").str.strip()
    )

    if not df["codigo_estagio"].isin(
        ESTAGIOS_ESPERADOS
    ).all():
        raise ValueError("Estágio de despesa inesperado.")

    if df["codigo_classificacao"].eq("10").sum() == 0:
        raise ValueError("Total da função Saúde não encontrado.")

    df["ano"] = df["exercicio"]
    df["codigo_anexo"] = df["anexo"]
    df["periodicidade"] = "ANUAL"
    df["arquivo_origem"] = arquivo_origem

    # Chave de negócio no grão fiscal.
    df["chave_negocio"] = (
        df["id_fonte"].astype(str)
        + "|"
        + df["cod_ibge"].astype(str)
        + "|"
        + df["ano"].astype(str)
        + "|"
        + df["codigo_classificacao"].astype(str)
        + "|"
        + df["codigo_estagio"].astype(str)
        + "|"
        + df["codigo_anexo"].astype(str)
    )

    dimensoes = [
        "cod_ibge",
        "ano",
        "codigo_classificacao",
        "codigo_estagio",
        "codigo_anexo",
    ]

    if df.duplicated(subset=dimensoes).any():
        raise ValueError(
            "Existem despesas duplicadas no grão fiscal definido."
        )

    if df["chave_negocio"].duplicated().any():
        raise ValueError("Chave de negócio fiscal duplicada.")

    validar_reconciliacao(df)

    colunas_saida = [
        "chave_negocio",
        "id_fonte",
        "cod_ibge",
        "uf",
        "instituicao",
        "ano",
        "periodicidade",
        "codigo_anexo",
        "rotulo",
        "cod_conta",
        "conta",
        "codigo_classificacao",
        "descricao_classificacao",
        "tipo_classificacao",
        "nivel_agregacao",
        "codigo_estagio",
        "valor",
        "populacao",
        "data_coleta_utc",
        "url_origem",
        "arquivo_origem",
    ]

    resultado = df[colunas_saida].sort_values(
        [
            "cod_ibge",
            "ano",
            "codigo_estagio",
            "codigo_classificacao",
        ]
    ).reset_index(drop=True)

    logger.info(
        "Curadoria validada: %s registros de Saúde.",
        len(resultado),
    )

    logger.info(
        "Funções: %s | Subfunções: %s",
        int((resultado["tipo_classificacao"] == "FUNCAO").sum()),
        int((resultado["tipo_classificacao"] == "SUBFUNCAO").sum()),
    )

    return resultado


def processar(
    ano: int,
    codigo_ibge: str,
) -> Path:
    """Executa a curadoria de um município e exercício."""

    origem, manifesto_origem_path, manifesto_origem = (
        localizar_ultima_coleta(ano, codigo_ibge)
    )

    logger.info("Lendo Landing: %s", origem)

    bruto = pd.read_parquet(origem)

    if len(bruto) != manifesto_origem["quantidade_registros"]:
        raise ValueError(
            "Quantidade de registros diferente do manifesto de origem."
        )

    curado = transformar(
        bruto=bruto,
        ano=ano,
        codigo_ibge=codigo_ibge,
        arquivo_origem=origem.name,
    )

    destino = (
        CURADO
        / f"ano={ano}"
        / f"municipio={codigo_ibge}"
    )

    destino.mkdir(parents=True, exist_ok=True)

    identificador = datetime.now(timezone.utc).strftime(
        "%Y%m%dT%H%M%S%fZ"
    )

    nome_arquivo = f"observacoes_{identificador}.parquet"
    arquivo_final = destino / nome_arquivo
    arquivo_temporario = destino / f".{nome_arquivo}.tmp"

    try:
        curado.to_parquet(
            arquivo_temporario,
            engine="pyarrow",
            compression="zstd",
            index=False,
        )

        os.replace(arquivo_temporario, arquivo_final)

    finally:
        if arquivo_temporario.exists():
            arquivo_temporario.unlink()

    manifesto = {
        "fonte": FONTE,
        "camada": "CURATED",
        "ano": ano,
        "codigo_ibge": codigo_ibge,
        "anexo": ANEXO_ESPERADO,
        "quantidade_registros": len(curado),
        "quantidade_funcoes": int(
            (curado["tipo_classificacao"] == "FUNCAO").sum()
        ),
        "quantidade_subfuncoes": int(
            (curado["tipo_classificacao"] == "SUBFUNCAO").sum()
        ),
        "estagios": sorted(
            curado["codigo_estagio"].unique().tolist()
        ),
        "tipo_valor": "decimal",
        "periodicidade": "ANUAL",
        "arquivo_origem": origem.name,
        "manifesto_origem": manifesto_origem_path.name,
        "hash_origem_sha256": calcular_hash(origem),
        "hash_manifesto_origem_sha256": calcular_hash(
            manifesto_origem_path
        ),
        "hash_curado_sha256": calcular_hash(arquivo_final),
        "processado_em_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "arquivo": arquivo_final.name,
        "status": "SUCESSO",
    }

    manifesto_final = destino / (
        f"manifesto_{identificador}.json"
    )

    manifesto_temporario = destino / (
        f".manifesto_{identificador}.json.tmp"
    )

    try:
        manifesto_temporario.write_text(
            json.dumps(
                manifesto,
                ensure_ascii=False,
                indent=4,
            ),
            encoding="utf-8",
        )

        os.replace(manifesto_temporario, manifesto_final)

    finally:
        if manifesto_temporario.exists():
            manifesto_temporario.unlink()

    logger.info("Curado salvo: %s", arquivo_final)
    logger.info("Manifesto salvo: %s", manifesto_final)
    logger.info("SHA-256 Curado: %s", manifesto["hash_curado_sha256"])

    return arquivo_final


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Curadoria fiscal das despesas públicas em Saúde."
    )

    parser.add_argument(
        "--ano",
        type=int,
        default=2024,
        help="Exercício fiscal.",
    )

    parser.add_argument(
        "--municipio",
        type=str,
        default="2611606",
        help="Código IBGE do município.",
    )

    args = parser.parse_args()

    if args.ano < 2013:
        raise ValueError("Exercício inválido.")

    if not args.municipio.isdigit() or len(args.municipio) != 7:
        raise ValueError("Código IBGE deve conter sete dígitos.")

    processar(
        ano=args.ano,
        codigo_ibge=args.municipio,
    )


if __name__ == "__main__":
    main()
