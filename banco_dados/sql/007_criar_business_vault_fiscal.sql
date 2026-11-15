BEGIN;

CREATE OR REPLACE VIEW business_vault.vw_despesas_fiscais_saude AS

WITH ultima_versao_despesa AS (
    SELECT DISTINCT ON (despesa_hk)
        despesa_hk,
        valor,
        cod_conta,
        conta,
        rotulo,
        instituicao,
        uf,
        populacao,
        data_coleta_utc,
        arquivo_origem,
        url_origem,
        load_dts
    FROM raw_vault.sat_despesa_fiscal
    ORDER BY despesa_hk, load_dts DESC, batch_id DESC
)

SELECT
    periodo.ano,
    localidade.codigo_ibge,
    classificacao.codigo_classificacao,
    estagio.codigo_estagio,
    anexo.codigo_anexo,

    despesa.valor,
    despesa.cod_conta,
    despesa.conta,
    despesa.rotulo,

    despesa.instituicao,
    despesa.uf,
    despesa.populacao,

    despesa.data_coleta_utc,
    despesa.arquivo_origem,
    despesa.url_origem,

    despesa.load_dts AS data_carga_raw_vault

FROM raw_vault.link_despesa_fiscal link

JOIN raw_vault.hub_localidade localidade
    ON localidade.localidade_hk = link.localidade_hk

JOIN raw_vault.hub_periodo periodo
    ON periodo.periodo_hk = link.periodo_hk

JOIN raw_vault.hub_classificacao_funcional classificacao
    ON classificacao.classificacao_hk = link.classificacao_hk

JOIN raw_vault.hub_estagio_despesa estagio
    ON estagio.estagio_hk = link.estagio_hk

JOIN raw_vault.hub_anexo anexo
    ON anexo.anexo_hk = link.anexo_hk

JOIN ultima_versao_despesa despesa
    ON despesa.despesa_hk = link.despesa_hk

WHERE
    classificacao.codigo_classificacao = '10'
    OR classificacao.codigo_classificacao LIKE '10.%'
    OR classificacao.codigo_classificacao = 'FU10';

COMMIT;
