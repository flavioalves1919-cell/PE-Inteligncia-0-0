import json

from pathlib import Path

import pandas as pd
import pytest

from motor_dados.processamento.curar_mortalidade import (
    transformar,
    calcular_hash,
)


LANDING = Path(
    "lakehouse/landing/condepe/"
    "datasus_mortalidade_infantil"
)

CURADO = Path(
    "lakehouse/curado/saude/mortalidade_infantil"
)

NORONHA = "2605459"


@pytest.fixture(scope="module")
def dados_2022():
    arquivo = (
        LANDING / "ano=2022" / "observacoes.parquet"
    )

    return pd.read_parquet(arquivo)


def test_transformacao_retorna_185_registros(dados_2022):
    resultado = transformar(dados_2022, 2022)

    assert len(resultado) == 185


def test_classificacao_territorial(dados_2022):
    resultado = transformar(dados_2022, 2022)

    municipios = resultado[
        resultado["tipo_localidade"] == "MUNICIPIO"
    ]

    distritos = resultado[
        resultado["tipo_localidade"] == "DISTRITO_ESTADUAL"
    ]

    assert len(municipios) == 184
    assert len(distritos) == 1

    assert distritos.iloc[0]["cd_municipio_ibge"] == NORONHA


def test_chave_de_negocio_unica(dados_2022):
    resultado = transformar(dados_2022, 2022)

    assert resultado["chave_negocio"].is_unique


def test_periodicidade_anual_sem_mes(dados_2022):
    resultado = transformar(dados_2022, 2022)

    assert resultado["periodicidade"].eq("ANUAL").all()
    assert resultado["mes"].isna().all()


def test_valores_nao_negativos(dados_2022):
    resultado = transformar(dados_2022, 2022)

    assert resultado["valor"].notna().all()
    assert (resultado["valor"] >= 0).all()


def test_valor_zero_de_noronha_preservado(dados_2022):
    resultado = transformar(dados_2022, 2022)

    noronha = resultado[
        resultado["cd_municipio_ibge"] == NORONHA
    ]

    assert len(noronha) == 1
    assert noronha.iloc[0]["valor"] == 0.0


def test_rejeita_duplicidade(dados_2022):
    duplicado = pd.concat(
        [dados_2022, dados_2022.iloc[[0]]],
        ignore_index=True,
    )

    with pytest.raises(ValueError, match="Duplicidade"):
        transformar(duplicado, 2022)


def test_rejeita_cobertura_sem_noronha(dados_2022):
    sem_noronha = dados_2022[
        dados_2022["cd_municipio_ibge"] != NORONHA
    ].copy()

    with pytest.raises(ValueError, match="185 localidades"):
        transformar(sem_noronha, 2022)


@pytest.mark.parametrize("ano", [2022, 2023, 2024])
def test_arquivo_curado_e_manifesto(ano):
    diretorio = CURADO / f"ano={ano}"

    arquivo = diretorio / "observacoes.parquet"
    manifesto_arquivo = diretorio / "manifesto.json"

    assert arquivo.exists()
    assert manifesto_arquivo.exists()

    df = pd.read_parquet(arquivo)

    manifesto = json.loads(
        manifesto_arquivo.read_text(encoding="utf-8")
    )

    origem = (
        LANDING
        / f"ano={ano}"
        / "observacoes.parquet"
    )

    assert len(df) == 185
    assert manifesto["quantidade_registros"] == 185
    assert manifesto["municipios"] == 184
    assert manifesto["distritos_estaduais"] == 1

    # Confirma que o arquivo de origem continua íntegro.
    assert manifesto["hash_origem_sha256"] == calcular_hash(origem)

    # Confirma que o Parquet curado corresponde ao manifesto.
    assert manifesto["hash_curado_sha256"] == calcular_hash(arquivo)


def test_volume_historico_total():
    arquivos = sorted(
        CURADO.glob("ano=*/observacoes.parquet")
    )

    assert len(arquivos) == 3

    total = sum(
        len(pd.read_parquet(arquivo))
        for arquivo in arquivos
    )

    assert total == 555
