from motor_dados.data_vault.carregar_raw_vault import conectar


def consultar(sql, parametros=None):
    with conectar() as conexao:
        with conexao.cursor() as cursor:
            cursor.execute(sql, parametros)
            return cursor.fetchall()


def test_dimensoes_possuem_volume_esperado():
    resultado = consultar("""
        SELECT
            (SELECT COUNT(*) FROM data_marts.dim_localidade),
            (SELECT COUNT(*) FROM data_marts.dim_tempo),
            (SELECT COUNT(*) FROM data_marts.dim_indicador)
    """)

    assert resultado[0] == (185, 3, 1)


def test_tabela_fato_possui_555_observacoes():
    resultado = consultar("""
        SELECT COUNT(*)
        FROM data_marts.fact_mortalidade_infantil
    """)

    assert resultado[0][0] == 555


def test_distribuicao_anual_das_observacoes():
    resultado = consultar("""
        SELECT ano, COUNT(*), COUNT(DISTINCT codigo_ibge)
        FROM data_marts.fact_mortalidade_infantil
        GROUP BY ano
        ORDER BY ano
    """)

    assert resultado == [
        (2022, 185, 185),
        (2023, 185, 185),
        (2024, 185, 185),
    ]


def test_nao_existam_fatos_sem_dimensoes():
    resultado = consultar("""
        SELECT COUNT(*)
        FROM data_marts.fact_mortalidade_infantil f
        LEFT JOIN data_marts.dim_localidade l
            ON l.codigo_ibge = f.codigo_ibge
        LEFT JOIN data_marts.dim_tempo t
            ON t.ano = f.ano
        LEFT JOIN data_marts.dim_indicador i
            ON i.indicador_id = f.indicador_id
        WHERE l.codigo_ibge IS NULL
           OR t.ano IS NULL
           OR i.indicador_id IS NULL
    """)

    assert resultado[0][0] == 0


def test_nao_existam_fatos_duplicados():
    resultado = consultar("""
        SELECT COUNT(*)
        FROM (
            SELECT codigo_ibge, ano, indicador_id
            FROM data_marts.fact_mortalidade_infantil
            GROUP BY codigo_ibge, ano, indicador_id
            HAVING COUNT(*) > 1
        ) duplicados
    """)

    assert resultado[0][0] == 0


def test_views_analiticas_existam():
    resultado = consultar("""
        SELECT
            to_regclass('data_marts.vw_resumo_mortalidade_anual'),
            to_regclass('data_marts.vw_ranking_mortalidade_anual'),
            to_regclass('data_marts.vw_evolucao_mortalidade_municipal')
    """)

    assert all(valor is not None for valor in resultado[0])


def test_resumo_anual_contem_tres_anos():
    resultado = consultar("""
        SELECT ano, localidades_analisadas
        FROM data_marts.vw_resumo_mortalidade_anual
        ORDER BY ano
    """)

    assert resultado == [
        (2022, 184),
        (2023, 184),
        (2024, 184),
    ]


def test_evolucao_2024_possui_184_municipios():
    resultado = consultar("""
        SELECT
            COUNT(*),
            COUNT(taxa_ano_anterior)
        FROM data_marts.vw_evolucao_mortalidade_municipal
        WHERE ano = 2024
    """)

    assert resultado[0] == (184, 184)
