import pandas as pd
import pytest

from pandera.errors import SchemaError

from motor_dados.validacao.contrato_saude import (
    validar_observacoes,
)


@pytest.fixture
def dados_validos():
    return pd.DataFrame(
        {
            "cd_municipio_ibge": ["2600054", "2600104"],
            "nm_municipio": [
                "Abreu e Lima",
                "Afogados da Ingazeira",
            ],
            "ano": [2022, 2022],
            "valor": [10.51, 12.99],
            "unidade": [
                "Por mil nascidos vivos",
                "Por mil nascidos vivos",
            ],
            "fonte_original": [
                "Ministério da Saúde (SIM / SINASC)",
                "Ministério da Saúde (SIM / SINASC)",
            ],
        }
    )


def test_aceita_dados_validos(dados_validos):
    resultado = validar_observacoes(
        dados_validos,
        2022,
    )

    assert len(resultado) == 2


def test_rejeita_codigo_ibge_invalido(dados_validos):
    dados_validos.loc[0, "cd_municipio_ibge"] = "123"

    with pytest.raises(SchemaError):
        validar_observacoes(dados_validos, 2022)


def test_rejeita_valor_negativo(dados_validos):
    dados_validos.loc[0, "valor"] = -5

    with pytest.raises(SchemaError):
        validar_observacoes(dados_validos, 2022)


def test_rejeita_registros_duplicados(dados_validos):
    duplicado = pd.concat(
        [dados_validos, dados_validos.iloc[[0]]],
        ignore_index=True,
    )

    with pytest.raises(SchemaError):
        validar_observacoes(duplicado, 2022)


def test_rejeita_ano_incorreto(dados_validos):
    dados_validos.loc[0, "ano"] = 2023

    with pytest.raises(SchemaError):
        validar_observacoes(dados_validos, 2022)


def test_rejeita_dataframe_vazio():
    vazio = pd.DataFrame(
        columns=[
            "cd_municipio_ibge",
            "nm_municipio",
            "ano",
            "valor",
            "unidade",
            "fonte_original",
        ]
    )

    with pytest.raises(ValueError):
        validar_observacoes(vazio, 2022)
