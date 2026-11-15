import json
from decimal import Decimal

import pandas as pd
import pytest

from motor_dados.processamento import curar_despesas_fiscais as fiscal


ANO = 2024
MUNICIPIO = "2611606"

ESTAGIOS = sorted(fiscal.ESTAGIOS_ESPERADOS)

CLASSIFICACOES = [
    ("10", "Saúde", Decimal("1000.00")),
    ("10.122", "Administração Geral", Decimal("100.00")),
    ("10.301", "Atenção Básica", Decimal("200.00")),
    ("10.302", "Assistência Hospitalar e Ambulatorial", Decimal("150.00")),
    ("10.303", "Suporte Profilático e Terapêutico", Decimal("100.00")),
    ("10.304", "Vigilância Sanitária", Decimal("100.00")),
    ("10.305", "Vigilância Epidemiológica", Decimal("150.00")),
    ("FU10", "Demais Subfunções", Decimal("200.00")),
]


@pytest.fixture
def landing_valido():
    registros = []

    for estagio in ESTAGIOS:
        for codigo, descricao, valor in CLASSIFICACOES:
            registros.append({
                "exercicio": ANO,
                "instituicao": "Prefeitura Municipal de Recife",
                "cod_ibge": MUNICIPIO,
                "uf": "PE",
                "anexo": fiscal.ANEXO_ESPERADO,
                "rotulo": "Despesas por Função",
                "coluna": estagio,
                "cod_conta": "TotalDespesas",
                "conta": f"{codigo} - {descricao}",
                "valor": valor,
                "populacao": 1587707,
                "id_fonte": fiscal.FONTE,
                "data_coleta_utc": "2026-11-15T00:00:00Z",
                "url_origem": "https://apidatalake.tesouro.gov.br/ords/siconfi/tt/dca",
            })

    return pd.DataFrame(registros)


def transformar(df):
    return fiscal.transformar(
        bruto=df,
        ano=ANO,
        codigo_ibge=MUNICIPIO,
        arquivo_origem="teste.parquet",
    )


def test_curadoria_valida_gera_32_registros(landing_valido):
    resultado = transformar(landing_valido)

    assert len(resultado) == 32
    assert resultado["valor"].map(
        lambda valor: isinstance(valor, Decimal)
    ).all()
    assert resultado["chave_negocio"].is_unique
    assert resultado["codigo_classificacao"].eq("10").sum() == 4
    assert resultado["tipo_classificacao"].eq("SUBFUNCAO").sum() == 28


def test_classificacao_funcional_valida():
    assert fiscal.extrair_classificacao(
        "10.301 - Atenção Básica"
    ) == ("10.301", "Atenção Básica")


def test_classificacao_fu10_valida():
    assert fiscal.extrair_classificacao(
        "FU10 - Demais Subfunções"
    ) == ("FU10", "Demais Subfunções")


@pytest.mark.parametrize(
    "conta",
    [
        "FU11 - Classificação inválida",
        "abc",
        "10.30 - Código inválido",
        "",
    ],
)
def test_classificacao_invalida(conta):
    with pytest.raises(ValueError):
        fiscal.extrair_classificacao(conta)


def test_landing_vazio(landing_valido):
    with pytest.raises(ValueError, match="Landing vazio"):
        transformar(landing_valido.iloc[0:0])


def test_coluna_obrigatoria_ausente(landing_valido):
    landing_valido = landing_valido.drop(columns=["instituicao"])

    with pytest.raises(ValueError, match="Colunas obrigatórias ausentes"):
        transformar(landing_valido)


@pytest.mark.parametrize(
    ("coluna", "valor", "mensagem"),
    [
        ("exercicio", 2023, "outro exercício"),
        ("cod_ibge", "2600000", "outro município"),
        ("anexo", "Anexo inválido", "outro anexo"),
        ("id_fonte", "fonte_invalida", "Identificador de fonte"),
    ],
)
def test_metadados_invalidos(
    landing_valido,
    coluna,
    valor,
    mensagem,
):
    landing_valido.loc[0, coluna] = valor

    with pytest.raises(ValueError, match=mensagem):
        transformar(landing_valido)


def test_nenhum_registro_de_saude(landing_valido):
    landing_valido["conta"] = "12 - Educação"

    with pytest.raises(ValueError, match="Nenhum registro"):
        transformar(landing_valido)


def test_valor_float_rejeitado(landing_valido):
    landing_valido["valor"] = landing_valido["valor"].astype(float)

    with pytest.raises(TypeError, match="não estão em Decimal"):
        transformar(landing_valido)


def test_valor_negativo_rejeitado(landing_valido):
    landing_valido.loc[1, "valor"] = Decimal("-10.00")

    with pytest.raises(ValueError, match="valores negativos"):
        transformar(landing_valido)


def test_valor_nao_finito_rejeitado(landing_valido):
    landing_valido.loc[1, "valor"] = Decimal("NaN")

    with pytest.raises(ValueError, match="não finitos"):
        transformar(landing_valido)


def test_valor_com_mais_de_duas_casas_rejeitado(landing_valido):
    landing_valido.loc[1, "valor"] = Decimal("100.001")

    with pytest.raises(
        ValueError,
        match="mais de duas casas decimais",
    ):
        transformar(landing_valido)


def test_estagio_invalido_rejeitado(landing_valido):
    landing_valido.loc[0, "coluna"] = "Estágio inexistente"

    with pytest.raises(ValueError, match="Estágio de despesa inesperado"):
        transformar(landing_valido)


def test_estagio_ausente_rejeitado(landing_valido):
    landing_valido = landing_valido[
        landing_valido["coluna"] != ESTAGIOS[0]
    ]

    with pytest.raises(ValueError, match="Estágios esperados ausentes"):
        transformar(landing_valido)


def test_registro_duplicado_rejeitado(landing_valido):
    duplicado = landing_valido.iloc[[0]]
    landing_valido = pd.concat(
        [landing_valido, duplicado],
        ignore_index=True,
    )

    with pytest.raises(ValueError, match="despesas duplicadas"):
        transformar(landing_valido)


def test_reconciliacao_com_diferenca_rejeitada(landing_valido):
    resultado = transformar(landing_valido)

    indice = resultado[
        resultado["codigo_classificacao"] == "10.301"
    ].index[0]

    resultado.loc[indice, "valor"] += Decimal("0.01")

    with pytest.raises(ValueError, match="Falha na reconciliação"):
        fiscal.validar_reconciliacao(resultado)


def test_reconciliacao_valida(landing_valido):
    resultado = transformar(landing_valido)

    assert fiscal.validar_reconciliacao(resultado) is None


def test_processamento_completo_e_manifesto(
    tmp_path,
    monkeypatch,
    landing_valido,
):
    landing_dir = (
        tmp_path
        / "landing"
        / "ano=2024"
        / "municipio=2611606"
    )

    landing_dir.mkdir(parents=True)

    arquivo_landing = landing_dir / "observacoes_teste.parquet"
    landing_valido.to_parquet(
        arquivo_landing,
        engine="pyarrow",
        index=False,
    )

    manifesto_landing = {
        "status": "SUCESSO",
        "arquivo": arquivo_landing.name,
        "ano": ANO,
        "codigo_ibge": MUNICIPIO,
        "anexo": fiscal.ANEXO_ESPERADO,
        "quantidade_registros": len(landing_valido),
        "sha256": fiscal.calcular_hash(arquivo_landing),
    }

    (landing_dir / "manifesto_teste.json").write_text(
        json.dumps(manifesto_landing),
        encoding="utf-8",
    )

    diretorio_curado = tmp_path / "curado"

    monkeypatch.setattr(fiscal, "LANDING", tmp_path / "landing")
    monkeypatch.setattr(fiscal, "CURADO", diretorio_curado)

    arquivo_curado = fiscal.processar(ANO, MUNICIPIO)

    assert arquivo_curado.exists()

    manifesto_curado_path = arquivo_curado.parent / (
        arquivo_curado.name.replace(
            "observacoes_", "manifesto_"
        ).replace(".parquet", ".json")
    )

    assert manifesto_curado_path.exists()

    manifesto_curado = json.loads(
        manifesto_curado_path.read_text(encoding="utf-8")
    )

    resultado = pd.read_parquet(arquivo_curado)

    assert len(resultado) == 32
    assert manifesto_curado["status"] == "SUCESSO"
    assert manifesto_curado["quantidade_registros"] == 32
    assert manifesto_curado["arquivo"] == arquivo_curado.name
    assert manifesto_curado["hash_curado_sha256"] == (
        fiscal.calcular_hash(arquivo_curado)
    )


def test_landing_com_hash_invalido_rejeitado(
    tmp_path,
    monkeypatch,
    landing_valido,
):
    landing_dir = (
        tmp_path
        / "landing"
        / "ano=2024"
        / "municipio=2611606"
    )

    landing_dir.mkdir(parents=True)

    arquivo = landing_dir / "observacoes_teste.parquet"
    landing_valido.to_parquet(arquivo, index=False)

    manifesto = {
        "status": "SUCESSO",
        "arquivo": arquivo.name,
        "ano": ANO,
        "codigo_ibge": MUNICIPIO,
        "anexo": fiscal.ANEXO_ESPERADO,
        "sha256": "hash_incorreto",
    }

    (landing_dir / "manifesto_teste.json").write_text(
        json.dumps(manifesto),
        encoding="utf-8",
    )

    monkeypatch.setattr(fiscal, "LANDING", tmp_path / "landing")

    with pytest.raises(ValueError, match="SHA-256"):
        fiscal.localizar_ultima_coleta(ANO, MUNICIPIO)
