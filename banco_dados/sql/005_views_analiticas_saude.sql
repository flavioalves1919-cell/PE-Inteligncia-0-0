-- ============================================
-- VIEWS ANALITICAS - SAUDE DE PERNAMBUCO
-- ============================================

-- 1. RESUMO ANUAL
CREATE OR REPLACE VIEW data_marts.vw_resumo_mortalidade_anual AS
SELECT
    t.ano,
    COUNT(*) AS localidades_analisadas,
    ROUND(AVG(f.valor), 2) AS media_simples_municipal,
    ROUND(MIN(f.valor), 2) AS menor_taxa,
    ROUND(MAX(f.valor), 2) AS maior_taxa,
    ROUND(STDDEV_POP(f.valor), 2) AS desvio_padrao
FROM data_marts.fact_mortalidade_infantil f
JOIN data_marts.dim_tempo t
    ON t.ano = f.ano
JOIN data_marts.dim_localidade l
    ON l.codigo_ibge = f.codigo_ibge
WHERE l.tipo_localidade = 'MUNICIPIO'
GROUP BY t.ano;

-- 2. RANKING ANUAL POR LOCALIDADE
CREATE OR REPLACE VIEW data_marts.vw_ranking_mortalidade_anual AS
SELECT
    t.ano,
    l.codigo_ibge,
    l.nome_localidade,
    l.tipo_localidade,
    f.valor AS taxa_mortalidade,
    RANK() OVER (
        PARTITION BY t.ano
        ORDER BY f.valor DESC
    ) AS ranking_maior_taxa
FROM data_marts.fact_mortalidade_infantil f
JOIN data_marts.dim_localidade l
    ON l.codigo_ibge = f.codigo_ibge
JOIN data_marts.dim_tempo t
    ON t.ano = f.ano;

-- 3. EVOLUCAO ANUAL POR MUNICIPIO
CREATE OR REPLACE VIEW data_marts.vw_evolucao_mortalidade_municipal AS
WITH evolucao AS (
    SELECT
        l.codigo_ibge,
        l.nome_localidade,
        t.ano,
        f.valor AS taxa_atual,
        LAG(f.valor) OVER (
            PARTITION BY l.codigo_ibge
            ORDER BY t.ano
        ) AS taxa_ano_anterior
    FROM data_marts.fact_mortalidade_infantil f
    JOIN data_marts.dim_localidade l
        ON l.codigo_ibge = f.codigo_ibge
    JOIN data_marts.dim_tempo t
        ON t.ano = f.ano
    WHERE l.tipo_localidade = 'MUNICIPIO'
)
SELECT
    codigo_ibge,
    nome_localidade,
    ano,
    taxa_atual,
    taxa_ano_anterior,
    ROUND(
        (taxa_atual - taxa_ano_anterior)::NUMERIC,
        2
    ) AS variacao_absoluta,
    ROUND(
        100.0 * (taxa_atual - taxa_ano_anterior)
        / NULLIF(taxa_ano_anterior, 0),
        2
    ) AS variacao_percentual
FROM evolucao;
