CREATE OR REPLACE VIEW business_vault.vw_mortalidade_infantil AS

WITH ultima_localidade AS (
    SELECT DISTINCT ON (localidade_hk)
        localidade_hk,
        nome_localidade,
        tipo_localidade
    FROM raw_vault.sat_localidade
    ORDER BY localidade_hk, load_dts DESC, batch_id DESC
),

ultimo_indicador AS (
    SELECT DISTINCT ON (indicador_hk)
        indicador_hk,
        nome_indicador,
        periodicidade
    FROM raw_vault.sat_indicador
    ORDER BY indicador_hk, load_dts DESC, batch_id DESC
),

ultima_observacao AS (
    SELECT DISTINCT ON (observacao_hk)
        observacao_hk,
        valor,
        unidade,
        natureza,
        fonte_original,
        arquivo_origem,
        data_coleta_utc,
        url_origem,
        load_dts
    FROM raw_vault.sat_observacao
    ORDER BY observacao_hk, load_dts DESC, batch_id DESC
)

SELECT
    p.ano,
    h.codigo_ibge,
    l.nome_localidade,
    l.tipo_localidade,
    i.nome_indicador,
    i.periodicidade,
    o.valor,
    o.unidade,
    o.natureza,
    o.fonte_original,
    o.arquivo_origem,
    o.data_coleta_utc,
    o.url_origem,
    o.load_dts AS data_carga_raw_vault

FROM raw_vault.link_observacao link

JOIN raw_vault.hub_localidade h
    ON h.localidade_hk = link.localidade_hk

JOIN ultima_localidade l
    ON l.localidade_hk = link.localidade_hk

JOIN ultimo_indicador i
    ON i.indicador_hk = link.indicador_hk

JOIN raw_vault.hub_periodo p
    ON p.periodo_hk = link.periodo_hk

JOIN ultima_observacao o
    ON o.observacao_hk = link.observacao_hk;
