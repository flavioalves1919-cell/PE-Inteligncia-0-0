import pandas as pd
import pandera.pandas as pa


def validar_observacoes(df: pd.DataFrame, ano: int) -> pd.DataFrame:
    """
    Valida os registros de mortalidade infantil recebidos
    da API do Observatório de Pernambuco.
    """

    campos_obrigatorios = [
        "cd_municipio_ibge",
        "nm_municipio",
        "ano",
        "valor",
        "unidade",
        "fonte_original",
    ]

    ausentes = [
        campo for campo in campos_obrigatorios
        if campo not in df.columns
    ]

    if ausentes:
        raise ValueError(
            f"Campos obrigatórios ausentes: {ausentes}"
        )

    if df.empty:
        raise ValueError("A API retornou zero observações.")

    schema = pa.DataFrameSchema(
        {
            "cd_municipio_ibge": pa.Column(
                str,
                checks=pa.Check.str_matches(r"^26\d{5}$"),
                nullable=False,
            ),
            "nm_municipio": pa.Column(
                str,
                nullable=False,
            ),
            "ano": pa.Column(
                int,
                checks=pa.Check.equal_to(ano),
                nullable=False,
            ),
            "valor": pa.Column(
                float,
                checks=pa.Check.ge(0),
                nullable=False,
            ),
            "unidade": pa.Column(
                str,
                nullable=False,
            ),
            "fonte_original": pa.Column(
                str,
                nullable=False,
            ),
        },
        checks=pa.Check(
            lambda frame: not frame.duplicated(
                subset=["cd_municipio_ibge", "ano"]
            ).any(),
            error="Existem municípios duplicados para o mesmo ano.",
        ),
        strict=False,
    )

    return schema.validate(df)
